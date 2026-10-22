"""scripts/route.py is the policy's deterministic half, so the policy is asserted through it.

The golden test is the important one: for every oracle case, the resolver
must reproduce the oracle's route from the oracle's own scores and signals.
That makes the oracle a machine-checked consequence of policy.yaml rather
than a hand-maintained parallel copy of it, and it means an eval failure on
tier or roster can be attributed: either the model scored differently from
the oracle, or it applied the policy differently from this script.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROUTE_PATH = ROOT / "scripts" / "route.py"
POLICY_PATH = ROOT / "agent-routing" / "policy.yaml"


def load_module(name: str, path: Path):
    """Load from source, never from the bytecode cache (see test_session_budget)."""
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


def dims(a: int = 0, s: int = 0, ar: int = 0, d: int = 0, r: int = 0, v: int = 0) -> dict[str, int]:
    return {"ambiguity": a, "scope": s, "architecture": ar, "dependencies": d, "risk": r, "verification": v}


class ResolverBase(unittest.TestCase):
    def setUp(self) -> None:
        self.route = load_module("route", ROUTE_PATH)
        self.policy = self.route.load_policy(POLICY_PATH)

    def resolve(self, dimensions, signals=()):
        return self.route.resolve(self.policy, dimensions, list(signals) if isinstance(signals, tuple) else signals)


class ScoreAndOverrideTests(ResolverBase):
    def test_raw_score_bands_map_to_tiers(self) -> None:
        for scores, tier in ((dims(), "T0"), (dims(1, 1), "T0"), (dims(1, 1, 1), "T1"),
                             (dims(1, 1, 1, 1, 1), "T1"), (dims(1, 1, 1, 1, 1, 1), "T2"),
                             (dims(2, 2, 2, 2), "T2"), (dims(2, 2, 2, 2, 1), "T3"), (dims(2, 2, 2, 2, 2, 2), "T3")):
            with self.subTest(score=sum(scores.values())):
                result = self.resolve(scores)
                self.assertEqual(result["score_tier"], tier)
                self.assertEqual(result["final_tier"], tier)

    def test_an_override_raises_the_tier_and_is_named(self) -> None:
        result = self.resolve(dims(0, 1, 0, 0, 2, 1), ["exposes-secret"])
        self.assertEqual(result["score_tier"], "T1")
        self.assertEqual(result["final_tier"], "T2")
        self.assertEqual(result["overrides_applied"], ["security-sensitive"])

    def test_an_override_never_lowers_a_tier(self) -> None:
        result = self.resolve(dims(2, 2, 2, 2, 2, 2), ["changes-schema"])
        self.assertEqual(result["final_tier"], "T3")
        self.assertEqual(result["overrides_applied"], ["database-or-data-migration"])

    def test_match_all_needs_every_signal(self) -> None:
        partial = self.resolve(dims(), ["moves-money", "coordinates-distributed-work"])
        self.assertNotIn("critical-payment-distributed-consistency", partial["overrides_applied"])
        self.assertEqual(partial["final_tier"], "T2")  # payment-or-money-movement alone
        full = self.resolve(dims(), ["moves-money", "coordinates-distributed-work", "requires-idempotency"])
        self.assertIn("critical-payment-distributed-consistency", full["overrides_applied"])
        self.assertEqual(full["final_tier"], "T3")

    def test_read_only_signals_are_dropped_before_matching(self) -> None:
        result = self.resolve(dims(0, 1, 0, 1, 1, 1), ["reads-payment-record", "reads-authorization-rule"])
        self.assertEqual(result["signals"], [])
        self.assertEqual(result["dropped_read_only_signals"], ["reads-payment-record", "reads-authorization-rule"])
        self.assertEqual(result["overrides_applied"], [])
        self.assertEqual(result["final_tier"], "T1")

    def test_an_action_beside_an_exempt_read_still_escalates(self) -> None:
        result = self.resolve(dims(0, 1, 0, 0, 2, 1), ["reads-secret-config", "exposes-secret"])
        self.assertEqual(result["signals"], ["exposes-secret"])
        self.assertEqual(result["final_tier"], "T2")

    def test_unknown_signals_are_reported_and_match_nothing(self) -> None:
        result = self.resolve(dims(), ["security", "payment"])
        self.assertEqual(result["unknown_signals"], ["security", "payment"])
        self.assertEqual(result["overrides_applied"], [])
        self.assertEqual(result["final_tier"], "T0")

    def test_duplicate_signals_collapse(self) -> None:
        result = self.resolve(dims(), ["changes-schema", "changes-schema"])
        self.assertEqual(result["signals"], ["changes-schema"])


class RosterAndBudgetTests(ResolverBase):
    def test_each_tier_has_its_profile_floor_and_base_ceiling(self) -> None:
        for scores, tier, agents, budget in (
            (dims(), "T0", [], 0),
            (dims(1, 1, 1), "T1", ["code-reviewer"], 1),
            (dims(1, 1, 1, 1, 1, 1), "T2", ["code-reviewer"], 2),
            (dims(1, 2, 2, 2, 2), "T3", ["architecture-critic", "code-reviewer-t3"], 3),
        ):
            with self.subTest(tier=tier):
                result = self.resolve(scores)
                self.assertEqual(result["final_tier"], tier)
                self.assertEqual(result["required_agents"], agents)
                self.assertEqual(result["max_agent_invocations"], budget)
                self.assertEqual(result["budget"]["base"], budget)

    def test_t2_architect_fires_on_the_dimension_arm_alone(self) -> None:
        result = self.resolve(dims(1, 1, 2, 1, 1, 1))
        self.assertEqual(result["final_tier"], "T2")
        self.assertEqual(result["required_agents"], ["architect", "code-reviewer"])
        self.assertEqual(result["conditional_agents_fired"], [{"agent": "architect", "because": "architecture 2 >= 2"}])

    def test_t2_architect_fires_on_the_signal_arm_alone(self) -> None:
        result = self.resolve(dims(0, 1, 1, 1, 1, 1), ["changes-canonical-model"])
        self.assertEqual(result["final_tier"], "T2")
        self.assertIn("architect", result["required_agents"])
        self.assertEqual(result["conditional_agents_fired"][0]["because"], "signal changes-canonical-model")

    def test_both_arms_at_once_fire_the_architect_exactly_once(self) -> None:
        result = self.resolve(dims(1, 2, 2, 1, 1, 1), ["changes-service-contract"])
        self.assertEqual(result["required_agents"].count("architect"), 1)
        self.assertEqual(result["max_agent_invocations"], 2)

    def test_t2_architect_does_not_fire_without_either_arm(self) -> None:
        result = self.resolve(dims(1, 1, 1, 1, 2, 2), ["changes-schema", "migrates-data", "runs-backfill"])
        self.assertEqual(result["final_tier"], "T2")
        self.assertEqual(result["required_agents"], ["code-reviewer"])

    def test_ambiguity_2_at_t3_fires_the_analyst_and_grants_its_reserve(self) -> None:
        result = self.resolve(dims(2, 2, 2, 2, 2, 2))
        self.assertEqual(result["required_agents"], ["requirement-analyst", "architecture-critic", "code-reviewer-t3"])
        self.assertEqual(result["max_agent_invocations"], 4)
        self.assertEqual(result["budget"]["base"], 3)
        granted = result["budget"]["reserves_granted"]
        self.assertEqual([item["reserve"] for item in granted], ["analyst_reserve"])
        self.assertEqual(granted[0]["agent"], "requirement-analyst")

    def test_ambiguity_2_below_t3_grants_nothing(self) -> None:
        result = self.resolve(dims(2, 1, 1, 1, 1, 1))
        self.assertEqual(result["final_tier"], "T2")
        self.assertNotIn("requirement-analyst", result["required_agents"])
        self.assertEqual(result["max_agent_invocations"], 2)

    def test_escalation_reserve_is_never_added_at_classification_time(self) -> None:
        for scores, expected_ceiling in ((dims(1, 1, 1, 1, 1, 1), 2), (dims(2, 2, 2, 2, 2, 2), 4)):
            result = self.resolve(scores)
            with self.subTest(tier=result["final_tier"]):
                granted = [item["reserve"] for item in result["budget"]["reserves_granted"]]
                self.assertNotIn("escalation_reserve", granted)
                runtime = [item["reserve"] for item in result["budget"]["runtime_reserves"]]
                self.assertEqual(runtime, ["escalation_reserve"])
                self.assertEqual(result["max_agent_invocations"], expected_ceiling)

    def test_no_reserve_exists_at_t0_or_t1(self) -> None:
        for scores in (dims(), dims(1, 1, 1)):
            result = self.resolve(scores)
            self.assertEqual(result["budget"]["reserves_granted"], [])
            self.assertEqual(result["budget"]["runtime_reserves"], [])

    def test_human_gate_follows_override_flags_only(self) -> None:
        result = self.resolve(dims(1, 1, 1, 1, 2, 2), ["executes-irreversible-operation"])
        self.assertEqual(result["final_tier"], "T3")
        self.assertEqual(result["human_gate"], {"required": False, "reason": None})

        gated = copy.deepcopy(self.policy)
        gated["overrides"][0]["human_gate"] = True
        gated["overrides"][0]["human_gate_reason"] = "credential exposure"
        result = self.route.resolve(gated, dims(), ["exposes-secret"])
        self.assertEqual(result["human_gate"], {"required": True, "reason": "credential exposure"})


    def test_an_override_may_require_an_agent_of_its_own(self) -> None:
        """No override carries require_agents today (policy.yaml says why); the path still has to work."""
        policy = copy.deepcopy(self.policy)
        policy["overrides"][0]["require_agents"] = ["test-engineer", "code-reviewer"]
        result = self.route.resolve(policy, dims(0, 1, 0, 0, 2, 1), ["exposes-secret"])
        self.assertEqual(result["required_agents"], ["code-reviewer", "test-engineer"])
        self.assertEqual(result["max_agent_invocations"], 2)
        policy["overrides"][0]["require_agents"] = ["test-engineer", "architect"]
        with self.assertRaisesRegex(self.route.RoutingError, "inconsistent"):
            self.route.resolve(policy, dims(0, 1, 0, 0, 2, 1), ["exposes-secret"])


class ValidationTests(ResolverBase):
    def test_rejects_scores_outside_the_allowed_values(self) -> None:
        for bad in (dims(3), dims(-1), {**dims(), "risk": True}, {**dims(), "risk": "1"}):
            with self.subTest(bad=bad):
                with self.assertRaises(self.route.RoutingError):
                    self.resolve(bad)

    def test_rejects_missing_or_unknown_dimensions(self) -> None:
        missing = dims()
        del missing["verification"]
        with self.assertRaisesRegex(self.route.RoutingError, "missing"):
            self.resolve(missing)
        with self.assertRaisesRegex(self.route.RoutingError, "unknown"):
            self.resolve({**dims(), "novelty": 1})

    def test_rejects_non_string_signals_and_accepts_a_bare_string_as_one(self) -> None:
        for bad in ([None], [""], [3], {"changes-schema": 1}):
            with self.subTest(bad=bad):
                with self.assertRaises(self.route.RoutingError):
                    self.resolve(dims(), bad)
        self.assertEqual(self.resolve(dims(), "changes-schema")["signals"], ["changes-schema"])

    def test_rejects_a_conditional_entry_that_combines_conditions(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["profiles"]["T2"]["conditional_agents"] = [
            {"agent": "architect", "when_architecture_dimension_at_least": 2, "when_any_signal": ["changes-schema"]}
        ]
        with self.assertRaisesRegex(self.route.RoutingError, "several conditions"):
            self.route.resolve(policy, dims(1, 1, 2, 1, 1, 1), ["changes-schema"])

    def test_rejects_a_reserve_condition_it_cannot_classify(self) -> None:
        """A misspelt threshold must not quietly become a runtime reserve."""
        policy = copy.deepcopy(self.policy)
        policy["budget"]["analyst_reserve"]["grant_condition"] = "ambiguity_at_least_2"
        with self.assertRaisesRegex(self.route.RoutingError, "neither a dimension threshold"):
            self.route.resolve(policy, dims(2, 2, 2, 2, 2, 2), [])

    def test_rejects_a_roster_larger_than_its_ceiling(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["budget"]["max_agent_invocations"]["T3"] = 1
        with self.assertRaisesRegex(self.route.RoutingError, "inconsistent"):
            self.route.resolve(policy, dims(2, 2, 2, 2, 1), [])


class CheckTests(ResolverBase):
    def emitted(self, **overrides):
        base = {
            "classification": dims(0, 1, 0, 0, 2, 1),
            "signals": ["exposes-secret"],
            "raw_score": 4,
            "score_tier": "T1",
            "overrides_applied": ["security-sensitive"],
            "final_tier": "T2",
            "strategy": "main_with_architect_and_reviewer",
            "required_agents": ["code-reviewer"],
            "max_agent_invocations": 2,
            "human_gate": {"required": False, "reason": None},
        }
        base.update(overrides)
        return base

    def test_a_correctly_applied_policy_has_no_mismatches(self) -> None:
        outcome = self.route.check(self.policy, self.emitted())
        self.assertEqual(outcome["mismatches"], {})
        self.assertEqual(outcome["warnings"], [])

    def test_a_misapplied_override_is_a_mismatch_on_the_route_fields_only(self) -> None:
        outcome = self.route.check(
            self.policy,
            self.emitted(overrides_applied=[], final_tier="T1", strategy="main_with_reviewer", max_agent_invocations=1),
        )
        self.assertEqual(
            set(outcome["mismatches"]), {"overrides_applied", "final_tier", "strategy", "max_agent_invocations"}
        )
        self.assertEqual(outcome["mismatches"]["final_tier"], {"emitted": "T1", "resolved": "T2"})

    def test_emitted_read_only_and_unknown_signals_are_warnings_not_mismatches(self) -> None:
        outcome = self.route.check(self.policy, self.emitted(signals=["exposes-secret", "reads-secret-config", "secrets"]))
        self.assertEqual(outcome["mismatches"], {})
        self.assertEqual(len(outcome["warnings"]), 2)

    def test_eval_runner_field_names_are_accepted(self) -> None:
        document = self.emitted()
        document["tier"] = document.pop("final_tier")
        document["dimensions"] = document.pop("classification")
        document["human_gate"] = False
        self.assertEqual(self.route.check(self.policy, document)["mismatches"], {})


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROUTE_PATH), *args],
            cwd=cwd or ROOT, capture_output=True, text=True, encoding="utf-8",
        )

    def test_positional_dimensions_and_comma_signals(self) -> None:
        done = self.run_cli("--dimensions", "1,1,1,1,2,2", "--signals", "changes-schema,runs-backfill", "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        result = json.loads(done.stdout)
        self.assertEqual(result["final_tier"], "T2")
        self.assertEqual(result["overrides_applied"], ["database-or-data-migration"])

    def test_named_dimensions_and_repeated_signal_flags(self) -> None:
        done = self.run_cli("-d", "ambiguity=2,scope=2", "-d", "architecture=2", "-d", "dependencies=2,risk=2,verification=2",
                            "-s", "changes-authentication-flow", "-s", "migrates-data", "--signal", "rolls-out-across-clients")
        self.assertEqual(done.returncode, 0, done.stderr)
        result = yaml.safe_load(done.stdout)
        self.assertIn("identity-model-migration", result["overrides_applied"])
        self.assertEqual(result["max_agent_invocations"], 4)

    def test_bad_input_exits_2_with_the_dimension_named(self) -> None:
        done = self.run_cli("--dimensions", "1,1,x,1,1,1")
        self.assertEqual(done.returncode, 2)
        self.assertIn("architecture", done.stderr)
        self.assertEqual(self.run_cli("--dimensions", "1,1,1").returncode, 2)
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertEqual(self.run_cli("--check").returncode, 2)

    def test_check_reads_a_classification_file_and_exits_1_on_a_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "classification.yaml"
            path.write_text(yaml.safe_dump({
                "classification": dims(0, 1, 0, 0, 2, 1),
                "signals": ["exposes-secret"],
                "raw_score": 4, "score_tier": "T1", "overrides_applied": [], "final_tier": "T1",
                "strategy": "main_with_reviewer", "required_agents": ["code-reviewer"],
                "max_agent_invocations": 1, "human_gate": {"required": False, "reason": None},
            }), encoding="utf-8")
            done = self.run_cli("--from", str(path), "--check", "--json")
            self.assertEqual(done.returncode, 1)
            self.assertIn("final_tier", json.loads(done.stdout)["mismatches"])

            path.write_text(path.read_text(encoding="utf-8").replace("final_tier: T1", "final_tier: T2")
                            .replace("overrides_applied: []", "overrides_applied: [security-sensitive]")
                            .replace("strategy: main_with_reviewer", "strategy: main_with_architect_and_reviewer")
                            .replace("max_agent_invocations: 1", "max_agent_invocations: 2"), encoding="utf-8")
            done = self.run_cli("--from", str(path), "--check")
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_record_writes_the_ledger_the_hook_enforces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_root = Path(directory)
            done = subprocess.run(
                [sys.executable, str(ROUTE_PATH), "-d", "1,1,1,1,2,2", "-s", "changes-schema",
                 "--record", "--requirement", "REQ-007"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                env={**dict(__import__("os").environ), "CLAUDE_PROJECT_DIR": str(env_root)},
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            ledger = json.loads((env_root / "artifacts" / "handoff" / "agent-budget.json").read_text(encoding="utf-8"))
            self.assertEqual(ledger["requirement"], "REQ-007")
            self.assertEqual(ledger["tier"], "T2")
            self.assertEqual(ledger["base"], 2)
            self.assertEqual(ledger["invocations"], [])


class ModuleEntryTests(unittest.TestCase):
    def test_main_reports_policy_errors_on_stderr_with_exit_2(self) -> None:
        route = load_module("route", ROUTE_PATH)
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / "policy.yaml"
            broken.write_text("scoring: {}\n", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = route.main(["--policy", str(broken), "-d", "0,0,0,0,0,0"])
        self.assertEqual(code, 2)
        self.assertIn("missing", err.getvalue())


if __name__ == "__main__":
    unittest.main()
