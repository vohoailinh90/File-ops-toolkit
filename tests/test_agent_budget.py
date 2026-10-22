"""The agent-budget hook turns `max_agent_invocations` from prose into a refusal.

Everything here is accounting, so everything here is asserted: which slot a
spawn is charged to, when the ceiling refuses, what a reserve may pay for, and
that the hook fails open on its own errors but never on a full ledger.
"""

from __future__ import annotations

import contextlib
import errno
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = ROOT / "scripts" / "hooks" / "agent_budget.py"
ROUTE_PATH = ROOT / "scripts" / "route.py"
SETTINGS_PATH = ROOT / ".claude" / "settings.example.json"


def load_module(name: str, path: Path):
    """Load from source, never from the bytecode cache (see test_session_budget)."""
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


def route_result(tier: str) -> dict:
    """What scripts/route.py emits for a representative case of each tier."""
    route = load_module("route", ROUTE_PATH)
    policy = route.load_policy()
    scores = {
        "T0": (0, 0, 0, 0, 0, 0),
        "T1": (0, 1, 0, 1, 1, 1),
        "T2": (1, 1, 1, 1, 2, 2),
        "T3": (1, 2, 2, 2, 2, 2),
        "T3-ambiguous": (2, 2, 2, 2, 2, 2),
    }[tier]
    names = policy["scoring"]["dimensions"]
    return route.resolve(policy, dict(zip(names, scores)), [])


def spawn(agent: str | None = "code-reviewer", tool: str = "Agent") -> dict:
    tool_input = {"prompt": "x"}
    if agent is not None:
        tool_input["subagent_type"] = agent
    return {"tool_name": tool, "tool_input": tool_input}


class LedgerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.hook = load_module("agent_budget", HOOK_PATH)
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)

    def record(self, tier: str, requirement: str = "REQ-X") -> dict:
        self.hook.record(route_result(tier), requirement, root=self.root)
        return self.hook.load_ledger(self.root)

    def decide(self, payload: dict, env: dict | None = None):
        with mock.patch.dict(os.environ, env or {}, clear=False):
            return self.hook.decide(self.root, payload["tool_name"], payload["tool_input"])


class LedgerBuildTests(LedgerCase):
    def test_a_recorded_route_becomes_a_ledger_with_no_invocations(self) -> None:
        ledger = self.record("T2", "REQ-007")
        self.assertEqual(ledger["requirement"], "REQ-007")
        self.assertEqual(ledger["tier"], "T2")
        self.assertEqual(ledger["base"], 2)
        self.assertEqual(ledger["reserves"], [])
        self.assertEqual([r["reserve"] for r in ledger["runtime_reserves"]], ["escalation_reserve"])
        self.assertEqual(ledger["invocations"], [])
        self.assertEqual(self.hook.ceiling(ledger), 2)

    def test_a_classification_time_reserve_is_granted_up_front(self) -> None:
        ledger = self.record("T3-ambiguous")
        self.assertEqual(ledger["base"], 3)
        self.assertEqual(len(ledger["reserves"]), 1)
        self.assertEqual(ledger["reserves"][0]["reserve"], "analyst_reserve")
        self.assertEqual(ledger["reserves"][0]["grantable_agents"], ["requirement-analyst"])
        self.assertEqual(self.hook.ceiling(ledger), 4)

    def test_recording_again_replaces_the_previous_requirement(self) -> None:
        self.record("T3")
        ledger = self.hook.load_ledger(self.root)
        self.hook.charge(ledger, "architecture-critic", "hook")
        self.hook.write_ledger(self.root, ledger)
        fresh = self.record("T1", "REQ-Y")
        self.assertEqual(fresh["invocations"], [])
        self.assertEqual(fresh["tier"], "T1")

    def test_a_corrupt_or_foreign_ledger_is_an_error_not_a_budget(self) -> None:
        path = self.hook.ledger_path(self.root)
        path.parent.mkdir(parents=True)
        for body in ("{not json",
                     json.dumps({"version": 99, "base": 1, "reserves": [], "runtime_reserves": [], "invocations": []}),
                     json.dumps({"version": 1, "base": -1, "reserves": [], "runtime_reserves": [], "invocations": []}),
                     json.dumps({"version": 1, "base": True, "reserves": [], "runtime_reserves": [], "invocations": []}),
                     json.dumps([1, 2])):
            with self.subTest(body=body[:20]):
                path.write_text(body, encoding="utf-8")
                with self.assertRaises(self.hook.LedgerError):
                    self.hook.load_ledger(self.root)

    def test_no_ledger_reads_as_none(self) -> None:
        self.assertIsNone(self.hook.load_ledger(self.root))


class ChargingTests(LedgerCase):
    def test_base_is_charged_until_it_is_full_then_refused(self) -> None:
        ledger = self.record("T2")
        self.assertEqual(self.hook.charge(ledger, "code-reviewer", "hook"), "base")
        self.assertEqual(self.hook.charge(ledger, "Explore", "hook"), "base")
        with self.assertRaises(self.hook.BudgetExceeded):
            self.hook.charge(ledger, "architect", "hook")
        self.assertEqual([i["agent"] for i in ledger["invocations"]], ["code-reviewer", "Explore"])

    def test_t0_refuses_the_first_spawn(self) -> None:
        ledger = self.record("T0")
        with self.assertRaisesRegex(self.hook.BudgetExceeded, "main-session only"):
            self.hook.charge(ledger, "Explore", "hook")

    def test_a_reserve_pays_only_for_its_grantable_agent_and_only_once(self) -> None:
        ledger = self.record("T3-ambiguous")
        # the analyst takes its reserve whatever the spawn order
        self.assertEqual(self.hook.charge(ledger, "architecture-critic", "hook"), "base")
        self.assertEqual(self.hook.charge(ledger, "requirement-analyst", "hook"), "analyst_reserve")
        self.assertEqual(self.hook.charge(ledger, "code-reviewer-t3", "hook"), "base")
        self.assertEqual(self.hook.charge(ledger, "architecture-critic", "manual", "round 2"), "base")
        with self.assertRaises(self.hook.BudgetExceeded):
            self.hook.charge(ledger, "requirement-analyst", "hook")  # reserve spent, base full

    def test_the_analyst_spawned_first_leaves_the_base_to_the_roster(self) -> None:
        ledger = self.record("T3-ambiguous")
        self.assertEqual(self.hook.charge(ledger, "requirement-analyst", "hook"), "analyst_reserve")
        for agent in ("architecture-critic", "code-reviewer-t3", "architecture-critic"):
            self.assertEqual(self.hook.charge(ledger, agent, "hook"), "base")
        self.assertEqual(self.hook.base_used(ledger), 3)

    def test_a_non_grantable_agent_cannot_take_a_reserve_slot(self) -> None:
        ledger = self.record("T3-ambiguous")
        for agent in ("architecture-critic", "code-reviewer-t3", "Explore"):
            self.hook.charge(ledger, agent, "hook")
        with self.assertRaises(self.hook.BudgetExceeded):
            self.hook.charge(ledger, "test-engineer", "hook")
        self.assertIsNone(ledger["reserves"][0]["spent_by"])


class ReRecordTests(LedgerCase):
    """Re-recording the same requirement must not reopen its budget."""

    def spend(self, *agents: str) -> None:
        ledger = self.hook.load_ledger(self.root)
        for agent in agents:
            self.hook.charge(ledger, agent, "hook")
        self.hook.write_ledger(self.root, ledger)

    def test_same_label_carries_every_charge_into_the_new_ceiling(self) -> None:
        self.record("T2", "REQ-7")
        self.spend("code-reviewer", "architect")
        ledger = self.record("T3", "REQ-7")  # the requirement grew, as the refusal advises
        self.assertEqual([i["agent"] for i in ledger["invocations"]], ["code-reviewer", "architect"])
        self.assertTrue(all(i.get("carried") for i in ledger["invocations"]))
        self.assertEqual(self.hook.base_used(ledger), 2)
        self.hook.charge(ledger, "architecture-critic", "hook")
        with self.assertRaises(self.hook.BudgetExceeded):
            self.hook.charge(ledger, "code-reviewer-t3", "hook")

    def test_an_unlabelled_re_record_carries_over_and_keeps_the_label(self) -> None:
        self.record("T2", "REQ-7")
        self.spend("code-reviewer")
        ledger = self.record("T2", "")
        self.assertEqual(ledger["requirement"], "REQ-7")
        self.assertEqual(len(ledger["invocations"]), 1)

    def test_charges_beyond_the_new_ceiling_stay_on_record(self) -> None:
        self.record("T3", "REQ-7")
        self.spend("architecture-critic", "code-reviewer-t3", "Explore")
        ledger = self.record("T1", "REQ-7")  # re-recorded lower: nothing further may spawn
        self.assertEqual(len(ledger["invocations"]), 3)
        with self.assertRaises(self.hook.BudgetExceeded):
            self.hook.charge(ledger, "code-reviewer", "hook")

    def test_a_runtime_grant_and_its_spend_carry_over(self) -> None:
        self.record("T2", "REQ-7")
        ledger = self.hook.load_ledger(self.root)
        self.hook.charge(ledger, "code-reviewer", "hook")
        self.hook.charge(ledger, "architect", "hook")
        self.hook.grant(ledger, "escalation_reserve", "test-engineer", "escalated")
        self.hook.charge(ledger, "test-engineer", "hook")
        self.hook.write_ledger(self.root, ledger)
        ledger = self.record("T3", "REQ-7")
        self.assertEqual([i["charged_to"] for i in ledger["invocations"]], ["base", "base", "escalation_reserve"])
        self.assertEqual(self.hook.base_used(ledger), 2)

    def test_an_overdrawn_ledger_refuses_reserves_too(self) -> None:
        """A carried overflow must block every spawn, not only base-charged ones."""
        self.record("T3-ambiguous", "REQ-7")
        ledger = self.hook.load_ledger(self.root)
        for agent in ("requirement-analyst", "architecture-critic", "code-reviewer-t3", "architecture-critic"):
            self.hook.charge(ledger, agent, "hook")
        self.hook.grant(ledger, "escalation_reserve", "test-engineer", "escalated")  # granted, unspent
        self.hook.write_ledger(self.root, ledger)
        ledger = self.record("T2", "REQ-7")  # 4 carried invocations against base 2 + 1 carried reserve
        self.assertEqual(len(ledger["invocations"]), 4)
        self.assertGreater(len(ledger["invocations"]), self.hook.ceiling(ledger))
        with self.assertRaisesRegex(self.hook.BudgetExceeded, "overdrawn"):
            self.hook.charge(ledger, "test-engineer", "hook")
        self.assertEqual(len(ledger["invocations"]), 4)

    def test_recording_holds_the_ledger_lock_across_load_carry_and_write(self) -> None:
        """A hook charging between record()'s load and write must not be overwritten."""
        self.record("T2", "REQ-7")
        inside = {"locked": False}
        real_lock = self.hook.ledger_lock

        class SpyLock(real_lock):
            def __enter__(spy):
                inside["locked"] = True
                return super().__enter__()

            def __exit__(spy, *args):
                inside["locked"] = False
                return super().__exit__(*args)

        seen: list[tuple[str, bool]] = []
        real_load, real_write = self.hook.load_ledger, self.hook.write_ledger

        def spy_load(root):
            seen.append(("load", inside["locked"]))
            return real_load(root)

        def spy_write(root, ledger):
            seen.append(("write", inside["locked"]))
            return real_write(root, ledger)

        with mock.patch.object(self.hook, "ledger_lock", SpyLock), \
                mock.patch.object(self.hook, "load_ledger", spy_load), \
                mock.patch.object(self.hook, "write_ledger", spy_write):
            self.hook.record(route_result("T3"), "REQ-7", root=self.root)
            self.hook.record(route_result("T3"), "REQ-7", root=self.root, fresh=True)
        self.assertEqual(seen, [("load", True), ("write", True), ("write", True)])

    def test_a_different_label_or_fresh_starts_from_zero(self) -> None:
        self.record("T2", "REQ-7")
        self.spend("code-reviewer")
        self.assertEqual(self.record("T2", "REQ-8")["invocations"], [])
        self.spend("code-reviewer")
        self.hook.record(route_result("T2"), "REQ-8", root=self.root, fresh=True)
        self.assertEqual(self.hook.load_ledger(self.root)["invocations"], [])


class GrantTests(LedgerCase):
    def test_escalation_reserve_is_granted_once_and_only_for_its_agent(self) -> None:
        ledger = self.record("T2")
        entry = self.hook.grant(ledger, "escalation_reserve", "test-engineer", "reviewer escalated")
        self.assertEqual(entry["grantable_agents"], ["test-engineer"])
        self.assertEqual(self.hook.ceiling(ledger), 3)
        with self.assertRaisesRegex(self.hook.LedgerError, "fully granted"):
            self.hook.grant(ledger, "escalation_reserve", None, "")
        with self.assertRaisesRegex(self.hook.LedgerError, "may only pay for"):
            self.hook.grant(self.record("T3"), "escalation_reserve", "architecture-critic", "")

    def test_a_reserve_the_tier_does_not_have_cannot_be_granted(self) -> None:
        for tier in ("T0", "T1"):
            ledger = self.record(tier)
            with self.assertRaisesRegex(self.hook.LedgerError, "not a runtime reserve"):
                self.hook.grant(ledger, "escalation_reserve", None, "")

    def test_a_granted_reserve_is_spent_by_the_agent_it_was_granted_for(self) -> None:
        ledger = self.record("T2")
        self.hook.charge(ledger, "code-reviewer", "hook")
        self.hook.charge(ledger, "architect", "hook")
        self.hook.grant(ledger, "escalation_reserve", "test-engineer", "")
        with self.assertRaises(self.hook.BudgetExceeded):
            self.hook.charge(ledger, "code-reviewer", "hook")
        self.assertEqual(self.hook.charge(ledger, "test-engineer", "hook"), "escalation_reserve")


class DecisionTests(LedgerCase):
    def test_non_spawn_tools_are_ignored(self) -> None:
        self.record("T0")
        self.assertIsNone(self.decide(spawn(tool="Read")))
        self.assertIsNone(self.decide(spawn(tool="Bash")))

    def test_spawns_are_charged_and_persisted_then_denied_past_the_ceiling(self) -> None:
        self.record("T1")
        decision, message = self.decide(spawn("code-reviewer"))
        self.assertIsNone(decision)
        self.assertIn("Charged `code-reviewer` to base", message)
        self.assertEqual(len(self.hook.load_ledger(self.root)["invocations"]), 1)

        decision, message = self.decide(spawn("Explore"))
        self.assertEqual(decision, "deny")
        self.assertIn("exhausted", message)
        self.assertIn("escalation signal", message)
        self.assertEqual(len(self.hook.load_ledger(self.root)["invocations"]), 1, "a denied spawn is not charged")

    def test_the_legacy_task_tool_name_counts_as_a_spawn(self) -> None:
        self.record("T1")
        decision, _ = self.decide(spawn("code-reviewer", tool="Task"))
        self.assertIsNone(decision)
        self.assertEqual(self.decide(spawn("Explore", tool="Task"))[0], "deny")

    def test_a_spawn_without_a_subagent_type_still_counts(self) -> None:
        self.record("T1")
        self.assertIsNone(self.decide(spawn(None))[0])
        self.assertEqual(self.hook.load_ledger(self.root)["invocations"][0]["agent"], "unspecified")

    def test_the_refusal_names_the_grant_command_when_a_reserve_could_pay(self) -> None:
        self.record("T2")
        self.decide(spawn("code-reviewer"))
        self.decide(spawn("architect"))
        _, message = self.decide(spawn("test-engineer"))
        self.assertIn("grant escalation_reserve --agent test-engineer", message)
        _, message = self.decide(spawn("Explore"))
        self.assertNotIn("grant escalation_reserve", message)

    def test_unrouted_spawns_are_allowed_with_a_nudge_by_default(self) -> None:
        decision, message = self.decide(spawn("Explore"))
        self.assertIsNone(decision)
        self.assertIn("No agent budget is recorded", message)
        self.assertIsNone(self.hook.load_ledger(self.root), "an unrouted spawn must not invent a ledger")

    def test_unrouted_spawns_are_denied_when_asked(self) -> None:
        decision, message = self.decide(spawn("Explore"), env={"CLAUDE_AGENT_BUDGET_UNROUTED": "deny"})
        self.assertEqual(decision, "deny")
        self.assertIn("CLAUDE_AGENT_BUDGET_UNROUTED=deny", message)

    def test_a_corrupt_ledger_fails_open_as_unrouted_and_says_so(self) -> None:
        path = self.hook.ledger_path(self.root)
        path.parent.mkdir(parents=True)
        path.write_text("{oops", encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            decision, message = self.decide(spawn("Explore"))
        self.assertIsNone(decision)
        self.assertIn("No agent budget is recorded", message)
        self.assertIn("unrouted", err.getvalue())
        self.assertEqual(path.read_text(encoding="utf-8"), "{oops", "a corrupt ledger is not overwritten")

    def test_the_lock_is_released_after_a_decision_and_the_file_stays(self) -> None:
        self.record("T1")
        self.decide(spawn("code-reviewer"))
        lock_file = self.hook.ledger_path(self.root).with_name("agent-budget.lock")
        self.assertTrue(lock_file.exists(), "the lock file is never unlinked; unlinking a locked file reopens the race")
        with self.hook.ledger_lock(self.root) as lock:
            self.assertTrue(lock.held)

    def test_a_lock_file_left_by_a_dead_process_does_not_block(self) -> None:
        """An OS lock dies with its holder, so a leftover file needs no age-based reclaim."""
        self.record("T1")
        lock = self.hook.ledger_path(self.root).with_name("agent-budget.lock")
        lock.write_text("", encoding="utf-8")
        old = 1_000_000_000
        os.utime(lock, (old, old))
        decision, _ = self.decide(spawn("code-reviewer"))
        self.assertIsNone(decision)
        self.assertEqual(len(self.hook.load_ledger(self.root)["invocations"]), 1)

    def test_eacces_from_flock_is_contention_not_a_broken_lock(self) -> None:
        if self.hook.fcntl is None:
            self.skipTest("POSIX flock only")
        self.record("T1")
        busy = PermissionError(errno.EACCES, "Permission denied")
        with mock.patch.object(self.hook.fcntl, "flock", side_effect=busy), \
                mock.patch.object(self.hook, "LOCK_WAIT_SECONDS", 0.2):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                with self.hook.ledger_lock(self.root) as lock:
                    self.assertFalse(lock.held)
        self.assertIn("could not take the ledger lock", err.getvalue(), "EACCES must poll like EAGAIN")
        self.assertNotIn("lock unavailable", err.getvalue())

        broken = OSError(errno.ENOLCK, "No locks available")
        with mock.patch.object(self.hook.fcntl, "flock", side_effect=broken):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                with self.hook.ledger_lock(self.root) as lock:
                    self.assertFalse(lock.held)
        self.assertIn("lock unavailable", err.getvalue())

    def test_the_lock_excludes_another_process_while_held(self) -> None:
        """The mutation that makes _try_lock a no-op must fail here, deterministically."""
        self.record("T1")
        probe = (
            "import sys, types, pathlib\n"
            f"path = pathlib.Path({str(HOOK_PATH)!r})\n"
            "m = types.ModuleType('agent_budget'); m.__file__ = str(path)\n"
            "exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), m.__dict__)\n"
            "m.LOCK_WAIT_SECONDS = 0.3\n"
            f"with m.ledger_lock(pathlib.Path({str(self.root)!r})) as lock:\n"
            "    print(lock.held)\n"
        )

        def probe_held() -> str:
            done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8")
            return done.stdout.strip()

        with self.hook.ledger_lock(self.root) as lock:
            self.assertTrue(lock.held)
            self.assertEqual(probe_held(), "False", "a second process took a lock this one holds")
        self.assertEqual(probe_held(), "True")


class ProcessTests(unittest.TestCase):
    """The script as Claude Code runs it: stdin payload in, JSON decision out."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        self.env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.root)}

    def run_hook(self, *args: str, payload: dict | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HOOK_PATH), *args],
            input=json.dumps(payload) if payload is not None else "",
            capture_output=True, text=True, encoding="utf-8", env=env or self.env,
        )

    def run_route(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROUTE_PATH), *args],
            capture_output=True, text=True, encoding="utf-8", env=self.env, cwd=ROOT,
        )

    def test_end_to_end_record_charge_deny_grant_replay(self) -> None:
        recorded = self.run_route("-d", "1,1,1,1,2,2", "-s", "changes-schema", "--record", "--requirement", "REQ-007")
        self.assertEqual(recorded.returncode, 0, recorded.stderr)

        allowed = self.run_hook("pre-tool-use", payload=spawn("code-reviewer"))
        self.assertEqual(allowed.returncode, 0)
        output = json.loads(allowed.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertNotIn("permissionDecision", output)
        self.assertIn("base 1/2", output["additionalContext"])

        self.run_hook("pre-tool-use", payload=spawn("architect"))
        denied = self.run_hook("pre-tool-use", payload=spawn("test-engineer"))
        self.assertEqual(denied.returncode, 0, "a refusal is a decision, not a hook failure")
        output = json.loads(denied.stdout)["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("exhausted", output["permissionDecisionReason"])

        granted = self.run_hook("grant", "escalation_reserve", "--agent", "test-engineer", "--reason", "designed verification")
        self.assertEqual(granted.returncode, 0, granted.stderr)
        allowed = self.run_hook("pre-tool-use", payload=spawn("test-engineer"))
        self.assertIn("escalation_reserve", json.loads(allowed.stdout)["hookSpecificOutput"]["additionalContext"])

        replay = self.run_hook("session-start", payload={"source": "startup"})
        self.assertIn("REQ-007", replay.stdout)
        self.assertIn("base 2/2 used", replay.stdout)
        self.assertIn("reserves 1/1 spent", replay.stdout)

        status = self.run_hook("status", "--json")
        self.assertEqual(status.returncode, 0)
        self.assertEqual(len(json.loads(status.stdout)["invocations"]), 3)

        self.assertEqual(self.run_hook("charge", "--agent", "code-reviewer", "--reason", "resume").returncode, 1)

        re_recorded = self.run_route("-d", "1,2,2,2,2,2", "--record", "--requirement", "REQ-007")
        self.assertIn("carried 3 invocation", re_recorded.stderr)
        self.assertIn("base 2/3", self.run_hook("status").stdout)
        fresh = self.run_route("-d", "1,2,2,2,2,2", "--record", "--requirement", "REQ-007", "--fresh")
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        self.assertIn("base 0/3", self.run_hook("status").stdout)
        self.assertEqual(self.run_hook("reset").returncode, 0)
        self.assertEqual(self.run_hook("status").returncode, 1)
        self.assertEqual(self.run_hook("session-start", payload={}).stdout, "")

    def test_manual_charge_counts_a_resumed_agent(self) -> None:
        self.run_route("-d", "1,2,2,2,2,2", "--record")
        for agent in ("architecture-critic", "code-reviewer-t3"):
            self.run_hook("pre-tool-use", payload=spawn(agent))
        charged = self.run_hook("charge", "--agent", "architecture-critic", "--reason", "critique round 2, resumed")
        self.assertEqual(charged.returncode, 0, charged.stderr)
        self.assertIn("base 3/3", charged.stdout)
        denied = self.run_hook("pre-tool-use", payload=spawn("Explore"))
        self.assertEqual(json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_hook_subcommands_fail_open_on_an_unexpected_error(self) -> None:
        # A directory squats on the ledger's temp-file name, so the write after
        # a successful charge raises — an error the hook does not anticipate.
        self.run_route("-d", "1,1,1,1,2,2", "--record")
        (self.root / "artifacts" / "handoff" / "agent-budget.json.tmp").mkdir()
        done = self.run_hook("pre-tool-use", payload=spawn("Explore"))
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout, "", "no decision is emitted when the hook itself broke")
        self.assertIn("failed, continuing", done.stderr)

    def test_an_empty_payload_is_not_a_spawn(self) -> None:
        done = self.run_hook("pre-tool-use", payload=None)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout, "")

    def test_concurrent_hooks_never_over_charge_the_ceiling(self) -> None:
        """Two spawns in one turn fire two hooks at once; the lock must serialise them.

        Six hook processes race a T3 ledger (base 3). Exactly three may be
        allowed, exactly three denied, and the ledger must hold exactly three
        invocations — a lost update would allow a fourth.
        """
        self.run_route("-d", "1,2,2,2,2,2", "--record")
        processes = [
            subprocess.Popen(
                [sys.executable, str(HOOK_PATH), "pre-tool-use"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", env=self.env,
            )
            for _ in range(6)
        ]
        outputs = [process.communicate(json.dumps(spawn(f"agent-{index}")), timeout=60)[0]
                   for index, process in enumerate(processes)]
        decisions = [json.loads(out)["hookSpecificOutput"].get("permissionDecision") for out in outputs]
        self.assertEqual(decisions.count("deny"), 3, decisions)
        self.assertEqual(decisions.count(None), 3, decisions)
        ledger = json.loads((self.root / "artifacts" / "handoff" / "agent-budget.json").read_text(encoding="utf-8"))
        self.assertEqual(len(ledger["invocations"]), 3)

    def test_manual_subcommands_report_a_missing_ledger(self) -> None:
        done = self.run_hook("grant", "escalation_reserve")
        self.assertEqual(done.returncode, 1)
        self.assertIn("no ledger", done.stderr)


class SettingsWiringTests(unittest.TestCase):
    def test_the_example_settings_run_the_hook_on_agent_spawns_and_session_start(self) -> None:
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        spawn_groups = [
            group for group in settings["hooks"]["PreToolUse"]
            if any("agent_budget.py" in entry["command"] for entry in group["hooks"])
        ]
        self.assertEqual(len(spawn_groups), 1)
        self.assertTrue(spawn_groups[0]["hooks"][0]["command"].endswith("pre-tool-use"))

        # Claude Code matches a `|`-joined list of plain names exactly (each name,
        # no regex), so the matcher must be exactly the names the hook itself
        # treats as a spawn — one drifting from the other silently disables the
        # ceiling while every other test stays green.
        matcher = spawn_groups[0]["matcher"]
        self.assertRegex(matcher, r"^[A-Za-z0-9_|]+$", "a regex matcher would also match TaskCreate etc.")
        hook = load_module("agent_budget", HOOK_PATH)
        self.assertEqual(set(matcher.split("|")), hook.SPAWN_TOOLS)
        self.assertIn("Task", hook.SPAWN_TOOLS, "the spawn tool is named Task in some Claude Code releases")
        self.assertIn("Agent", hook.SPAWN_TOOLS, "and Agent in others")

        start_commands = [
            entry["command"]
            for group in settings["hooks"]["SessionStart"]
            for entry in group["hooks"]
            if "agent_budget.py" in entry["command"]
        ]
        self.assertEqual(len(start_commands), 1)
        self.assertTrue(start_commands[0].endswith("session-start"))

    def test_the_hook_script_is_executable(self) -> None:
        self.assertTrue(os.access(HOOK_PATH, os.X_OK))


if __name__ == "__main__":
    unittest.main()
