from __future__ import annotations

import contextlib
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
HOOK_PATH = ROOT / "scripts" / "hooks" / "session_budget.py"
AGENT_BUDGET_PATH = ROOT / "scripts" / "hooks" / "agent_budget.py"
OFFICE_EVENTS_PATH = ROOT / "scripts" / "hooks" / "office_events.py"
STATUSLINE_PATH = ROOT / "scripts" / "hooks" / "statusline.py"
SETTINGS_PATH = ROOT / ".claude" / "settings.example.json"


def load_module(name: str, path: Path):
    """Load a hook script from source, never from the bytecode cache.

    `spec_from_file_location` goes through the normal import machinery, which
    validates cached bytecode on `(mtime, size)` at one-second granularity. A
    test that rewrites a hook and reloads it within the same second, without
    changing its length — which is exactly what a mutation check does — would
    otherwise get the *previous* version back and report a false result. A test
    that can silently lie about what it loaded is worse than no test.
    """
    if not path.is_file():
        raise RuntimeError(f"Unable to load {path}")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


def usage_line(**fields: int) -> str:
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "usage": fields}})


class ContextEstimateTests(unittest.TestCase):
    def test_sums_every_billed_field_of_the_newest_usage_block(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        lines = [
            usage_line(input_tokens=10, output_tokens=10),
            usage_line(
                input_tokens=1_000,
                cache_read_input_tokens=90_000,
                cache_creation_input_tokens=5_000,
                output_tokens=2_000,
            ),
        ]

        self.assertEqual(hook.estimate_context_tokens(lines), 98_000)

    def test_reads_usage_at_the_top_level_as_well_as_under_message(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        lines = [json.dumps({"usage": {"input_tokens": 40, "output_tokens": 2}})]

        self.assertEqual(hook.estimate_context_tokens(lines), 42)

    def test_returns_none_rather_than_zero_when_no_usage_is_present(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        lines = [json.dumps({"type": "user"}), "{ not json", ""]

        self.assertIsNone(hook.estimate_context_tokens(lines))

    def test_tail_read_discards_the_partial_line_the_seek_lands_in(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "transcript.jsonl"
            filler = json.dumps({"pad": "x" * 4_000})
            wanted = usage_line(input_tokens=7)
            transcript.write_text(
                "\n".join([filler] * 100 + [wanted]) + "\n", encoding="utf-8"
            )

            with mock.patch.object(hook, "TRANSCRIPT_TAIL_BYTES", 6_000):
                lines = hook.transcript_tail(transcript)

            self.assertLess(len(lines), 100)
            for line in lines:
                json.loads(line)  # every returned line must parse whole
            self.assertEqual(hook.estimate_context_tokens(lines), 7)

    def test_a_seek_landing_on_a_record_boundary_keeps_that_whole_record(self) -> None:
        """The boundary case: nothing was split, so nothing should be discarded."""
        hook = load_module("session_budget", HOOK_PATH)

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "transcript.jsonl"
            wanted = usage_line(input_tokens=11)
            head = json.dumps({"pad": "x" * 200})
            body = head + "\n" + wanted + "\n"
            transcript.write_text(body, encoding="utf-8")

            # Tail length chosen so the seek lands exactly on the wanted record's first byte.
            tail = len(wanted.encode()) + 1
            with mock.patch.object(hook, "TRANSCRIPT_TAIL_BYTES", tail):
                lines = hook.transcript_tail(transcript)

            self.assertEqual(hook.estimate_context_tokens(lines), 11)

    def test_missing_transcript_is_not_an_error(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        self.assertEqual(hook.transcript_tail(Path("/nonexistent/transcript.jsonl")), [])


class SidechainTests(unittest.TestCase):
    """Subagent entries must not stand in for the main session's context."""

    def test_a_small_sidechain_usage_block_cannot_mask_a_full_main_context(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        lines = [
            json.dumps({"isSidechain": False, "message": {"usage": {"input_tokens": 180_000}}}),
            json.dumps({"isSidechain": True, "message": {"usage": {"input_tokens": 900}}}),
        ]

        self.assertEqual(hook.estimate_context_tokens(lines), 180_000)

    def test_a_sidechain_prompt_is_not_this_session_s_last_request(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        lines = [
            json.dumps({"isSidechain": False, "message": {"role": "user", "content": "the real request"}}),
            json.dumps({"isSidechain": True, "message": {"role": "user", "content": "subagent prompt"}}),
        ]

        self.assertEqual(hook.last_user_prompt(lines), "the real request")


class GitBudgetTests(unittest.TestCase):
    def test_git_calls_share_one_deadline_instead_of_each_taking_the_full_timeout(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)
        timeouts: list[float] = []

        def record(*args, **kwargs):
            timeouts.append(kwargs["timeout"])
            return mock.Mock(returncode=0, stdout="")

        deadline = hook.time.monotonic() + 2.0
        with mock.patch.object(hook.subprocess, "run", side_effect=record):
            for _ in range(4):
                hook.git(Path("."), "status", deadline=deadline)

        self.assertTrue(all(t <= 2.0 for t in timeouts), timeouts)
        self.assertLess(sum(timeouts), 4 * hook.GIT_TOTAL_BUDGET_SECONDS)

    def test_an_expired_deadline_skips_the_call_rather_than_running_it(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        with mock.patch.object(hook.subprocess, "run") as run:
            self.assertEqual(hook.git(Path("."), "status", deadline=hook.time.monotonic() - 1), "")

        run.assert_not_called()


class AtomicWriteTests(unittest.TestCase):
    def test_a_completed_write_replaces_the_target_and_leaves_no_temp_file(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "SESSION-HANDOFF.md"
            path.write_text("old", encoding="utf-8")

            hook.write_atomically(path, "new content")

            self.assertEqual(path.read_text(encoding="utf-8"), "new content")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_a_write_that_fails_before_the_rename_leaves_the_old_notes_intact(self) -> None:
        """The target must hold either the old handoff or the new one — never a fragment.

        Failing the rename is how a direct `write_text` implementation is caught: it has
        no rename to fail, so it would truncate the target and raise nothing.
        """
        hook = load_module("session_budget", HOOK_PATH)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "SESSION-HANDOFF.md"
            path.write_text("irreplaceable notes", encoding="utf-8")

            with mock.patch.object(hook.os, "replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    hook.write_atomically(path, "replacement")

            self.assertEqual(path.read_text(encoding="utf-8"), "irreplaceable notes")
            self.assertEqual(list(Path(directory).iterdir()), [path])  # no .tmp left behind


class LastUserPromptTests(unittest.TestCase):
    def test_skips_envelopes_and_truncates_long_prompts(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        lines = [
            json.dumps({"message": {"role": "user", "content": "a" * 900}}),
            json.dumps({"message": {"role": "assistant", "content": "ignored"}}),
            json.dumps({"message": {"role": "user", "content": "<system-reminder>x"}}),
        ]

        prompt = hook.last_user_prompt(lines)

        self.assertTrue(prompt.startswith("a"))
        self.assertTrue(prompt.endswith("[…]"))
        self.assertLessEqual(len(prompt), hook.PROMPT_EXCERPT_CHARS + 8)

    def test_reads_text_blocks_out_of_structured_content(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        lines = [
            json.dumps(
                {
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "content": "noise"},
                            {"type": "text", "text": "ship the guardrails"},
                        ],
                    }
                }
            )
        ]

        self.assertEqual(hook.last_user_prompt(lines), "ship the guardrails")


class HandoffMergeTests(unittest.TestCase):
    def test_model_notes_survive_a_regenerated_auto_state_block(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        authored = f"{hook.NOTES_START}\n## Model notes\n\n- Goal: finish the migration\n{hook.NOTES_END}"
        existing = f"# Session handoff\n\n{authored}\n\n{hook.STATE_START}\nstale\n{hook.STATE_END}\n"

        merged = hook.merge_handoff(existing, f"{hook.STATE_START}\nfresh\n{hook.STATE_END}")

        self.assertIn("- Goal: finish the migration", merged)
        self.assertIn("fresh", merged)
        self.assertNotIn("stale", merged)

    def test_notes_are_salvaged_when_the_markers_are_damaged(self) -> None:
        """The notes block is the part no script can rewrite, so it is never dropped."""
        hook = load_module("session_budget", HOOK_PATH)
        auto = f"{hook.STATE_START}\nfresh\n{hook.STATE_END}"

        damaged = {
            "markers reversed": f"# Session handoff\n\n{hook.NOTES_END}\nkeep me\n{hook.NOTES_START}\n\n{auto}",
            "closing marker lost": f"# Session handoff\n\n{hook.NOTES_START}\nkeep me\n\n{auto}",
            "no markers at all": "# Session handoff\n\nkeep me\n",
        }

        for label, existing in damaged.items():
            with self.subTest(shape=label):
                merged = hook.merge_handoff(existing, auto)
                self.assertIn("keep me", merged)
                self.assertIn("Recovered", merged)
                self.assertIn("fresh", merged)

    def test_every_block_survives_duplicated_or_nested_markers(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)
        auto = f"{hook.STATE_START}\nfresh\n{hook.STATE_END}"

        shapes = {
            "two blocks": (
                f"{hook.NOTES_START}\nfirst block\n{hook.NOTES_END}\n"
                f"{hook.NOTES_START}\nsecond block\n{hook.NOTES_END}\n\n{auto}"
            ),
            "nested markers": (
                f"{hook.NOTES_START}\nfirst block\n{hook.NOTES_START}\ninner\n"
                f"{hook.NOTES_END}\ntrailing text\n{hook.NOTES_END}\n\n{auto}"
            ),
        }

        for label, existing in shapes.items():
            with self.subTest(shape=label):
                merged = hook.merge_handoff(existing, auto)
                for fragment in ("first block", "second block", "inner", "trailing text"):
                    if fragment in existing:
                        self.assertIn(fragment, merged, f"{label} dropped {fragment!r}")

    def test_salvage_does_not_absorb_a_stale_auto_state_block(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)
        existing = f"# Session handoff\n\nkeep me\n\n{hook.STATE_START}\nstale\n{hook.STATE_END}\n"

        merged = hook.merge_handoff(existing, f"{hook.STATE_START}\nfresh\n{hook.STATE_END}")

        self.assertIn("keep me", merged)
        self.assertNotIn("stale", merged)

    def test_a_new_handoff_gets_the_notes_template_to_fill_in(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        merged = hook.merge_handoff("", f"{hook.STATE_START}\nfresh\n{hook.STATE_END}")

        self.assertIn(hook.NOTES_START, merged)
        self.assertIn("**Next command:**", merged)

    def test_capture_writes_the_handoff_and_preserves_notes_on_recapture(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": directory}):
                path = hook.capture({"session_id": "s1"}, "manual")
                path.write_text(
                    path.read_text(encoding="utf-8").replace(
                        "- **Goal:** _(not recorded)_", "- **Goal:** wire up the hooks"
                    ),
                    encoding="utf-8",
                )
                hook.capture({"session_id": "s1"}, "pre-compact")

            body = path.read_text(encoding="utf-8")

        self.assertIn("- **Goal:** wire up the hooks", body)
        self.assertIn("`pre-compact`", body)
        self.assertNotIn("`manual`", body)


class GitReadTests(unittest.TestCase):
    def test_leading_whitespace_survives_because_porcelain_status_encodes_it(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        completed = mock.Mock(returncode=0, stdout=" M path/one\n?? path/two\n")
        with mock.patch.object(hook.subprocess, "run", return_value=completed):
            output = hook.git(Path("."), "status", "--porcelain=v1")

        self.assertEqual(output.splitlines()[0], " M path/one")

    def test_a_failed_or_missing_git_reads_as_empty(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        with mock.patch.object(hook.subprocess, "run", side_effect=OSError("no git")):
            self.assertEqual(hook.git(Path("."), "status"), "")

        completed = mock.Mock(returncode=128, stdout="fatal: not a repository\n")
        with mock.patch.object(hook.subprocess, "run", return_value=completed):
            self.assertEqual(hook.git(Path("."), "status"), "")


class PreToolUseNudgeTests(unittest.TestCase):
    def _run(self, hook, directory: str, used: int, session_id: str = "s1") -> str:
        transcript = Path(directory) / "transcript.jsonl"
        transcript.write_text(usage_line(input_tokens=used) + "\n", encoding="utf-8")
        payload = {"session_id": session_id, "transcript_path": str(transcript)}
        buffer = io.StringIO()
        with mock.patch.dict(
            os.environ,
            {
                "CLAUDE_PROJECT_DIR": directory,
                "CLAUDE_SESSION_BUDGET_CONTEXT_WINDOW": "100000",
            },
        ), contextlib.redirect_stdout(buffer):
            self.assertEqual(hook.cmd_pre_tool_use(payload), 0)
        return buffer.getvalue()

    def test_stays_silent_below_the_handoff_threshold(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self._run(hook, directory, 50_000), "")

    def test_asks_for_a_handoff_once_per_level_not_once_per_tool_call(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        with tempfile.TemporaryDirectory() as directory:
            first = self._run(hook, directory, 72_000)
            repeat = self._run(hook, directory, 73_000)

            context = json.loads(first)["hookSpecificOutput"]
            self.assertEqual(context["hookEventName"], "PreToolUse")
            self.assertIn("SESSION-HANDOFF.md", context["additionalContext"])
            self.assertEqual(repeat, "")

    def test_escalates_to_wrap_up_at_the_higher_threshold(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        with tempfile.TemporaryDirectory() as directory:
            self._run(hook, directory, 72_000)
            escalated = self._run(hook, directory, 90_000)

        message = json.loads(escalated)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("stop cleanly", message)

    def test_a_new_session_is_nudged_again(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        with tempfile.TemporaryDirectory() as directory:
            self._run(hook, directory, 72_000, session_id="s1")
            self.assertNotEqual(self._run(hook, directory, 72_000, session_id="s2"), "")


class SessionStartTests(unittest.TestCase):
    def test_replays_an_existing_handoff_into_the_new_session(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": directory}):
                hook.capture({"session_id": "s1"}, "pre-compact")
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    self.assertEqual(hook.cmd_session_start({"source": "resume"}), 0)

        self.assertIn("handoff from an earlier session", buffer.getvalue())
        self.assertIn("Auto-captured state", buffer.getvalue())

    def test_emits_nothing_when_there_is_no_handoff(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        with tempfile.TemporaryDirectory() as directory:
            buffer = io.StringIO()
            with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": directory}), \
                    contextlib.redirect_stdout(buffer):
                self.assertEqual(hook.cmd_session_start({}), 0)

        self.assertEqual(buffer.getvalue(), "")


class FailOpenTests(unittest.TestCase):
    def test_a_raising_handler_never_breaks_the_session_it_protects(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        with mock.patch.dict(hook.HANDLERS, {"capture": mock.Mock(side_effect=RuntimeError("boom"))}), \
                mock.patch.object(hook, "read_payload", return_value={}):
            self.assertEqual(hook.main(["session_budget.py", "capture"]), 0)

    def test_an_unknown_subcommand_is_a_usage_error(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        self.assertEqual(hook.main(["session_budget.py", "not-a-subcommand"]), 2)

    def test_a_malformed_payload_reads_as_empty(self) -> None:
        hook = load_module("session_budget", HOOK_PATH)

        with mock.patch.object(hook.sys, "stdin", io.StringIO("not json")):
            self.assertEqual(hook.read_payload(), {})


class SettingsConformanceTests(unittest.TestCase):
    """The wiring is a contract a validator can assert, so a validator asserts it.

    See `deterministic_work` in agent-routing/policy.yaml: a drifted subcommand
    name here fails silently at runtime, and no reviewer should be the check.
    """

    HOOK_SCRIPTS = {
        "scripts/hooks/session_budget.py": ("session_budget", HOOK_PATH, "HANDLERS"),
        "scripts/hooks/agent_budget.py": ("agent_budget", AGENT_BUDGET_PATH, "HOOK_HANDLERS"),
        "scripts/hooks/office_events.py": ("office_events", OFFICE_EVENTS_PATH, "EVENT_BUILDERS"),
    }

    def test_every_configured_hook_command_resolves_to_a_real_subcommand(self) -> None:
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        handlers = {
            script: set(getattr(load_module(name, path), table))
            for script, (name, path, table) in self.HOOK_SCRIPTS.items()
        }

        configured: list[tuple[str, str]] = []
        for event, groups in settings["hooks"].items():
            for group in groups:
                for entry in group["hooks"]:
                    configured.append((event, entry["command"]))

        self.assertTrue(configured)
        for event, command in configured:
            with self.subTest(event=event, command=command):
                script = next((name for name in handlers if name in command), None)
                self.assertIsNotNone(script, f"{command!r} names no known hook script")
                subcommand = command.rsplit(" ", 1)[-1]
                self.assertIn(subcommand, handlers[script])

    def test_configured_events_and_matchers_match_the_documented_hook_contract(self) -> None:
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))

        # None: the event takes no matcher (SubagentStart/SubagentStop match on agent type, and the
        # office observer wants every one).
        expected = {
            "PreToolUse": ["*", "Agent|Task"],
            "PostToolUse": ["*"],
            "PostToolUseFailure": ["Agent|Task"],
            "SubagentStart": [None],
            "SubagentStop": [None],
            "PreCompact": ["auto"],
            "StopFailure": ["rate_limit"],
            "SessionStart": ["startup|resume|compact"],
        }

        self.assertEqual(set(settings["hooks"]), set(expected))
        for event, matchers in expected.items():
            with self.subTest(event=event):
                self.assertEqual([group.get("matcher") for group in settings["hooks"][event]], matchers)

    def test_the_enabled_settings_are_the_example_so_the_contract_above_covers_what_runs(self) -> None:
        enabled = ROOT / ".claude" / "settings.json"
        if not enabled.is_file():
            self.skipTest("no .claude/settings.json here: the hooks are not enabled in this checkout")
        self.assertEqual(
            json.loads(enabled.read_text(encoding="utf-8")),
            json.loads(SETTINGS_PATH.read_text(encoding="utf-8")),
            "settings.json drifted from settings.example.json: copy the example over it, or change both",
        )

    def test_referenced_scripts_exist_and_are_executable_python(self) -> None:
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))

        self.assertIn("scripts/hooks/statusline.py", settings["statusLine"]["command"])
        for path in (HOOK_PATH, AGENT_BUDGET_PATH, OFFICE_EVENTS_PATH, STATUSLINE_PATH):
            with self.subTest(script=path.name):
                self.assertTrue(path.is_file())
                self.assertTrue(os.access(path, os.X_OK))


class StatusLineTests(unittest.TestCase):
    def test_renders_the_three_numbers_that_decide_when_to_stop(self) -> None:
        statusline = load_module("statusline", STATUSLINE_PATH)

        line = statusline.build_line(
            {
                "model": {"display_name": "Opus"},
                "context_window": {"remaining_percentage": 24},
                "rate_limits": {"five_hour": {"used_percentage": 78.4, "resets_at": 0}},
                "prompt_cache": {"warm": True, "hit_ratio": 0.91},
                "cost": {"total_cost_usd": 1.234},
            }
        )

        self.assertIn("24% ctx", line)
        self.assertIn("5h 78%", line)
        self.assertIn("cache 91%", line)
        self.assertIn("$1.23", line)

    def test_falls_back_to_used_percentage_when_remaining_is_absent(self) -> None:
        statusline = load_module("statusline", STATUSLINE_PATH)

        self.assertIn("30% ctx", statusline.build_line({"context_window": {"used_percentage": 70}}))

    def test_a_cold_cache_is_called_out_because_it_is_the_restart_multiplier(self) -> None:
        statusline = load_module("statusline", STATUSLINE_PATH)

        self.assertIn("cache cold", statusline.build_line({"prompt_cache": {"warm": False}}))

    def test_rate_limit_windows_are_independently_absent(self) -> None:
        """Per the status line schema, each window may be missing and is dropped once it resets."""
        statusline = load_module("statusline", STATUSLINE_PATH)

        line = statusline.build_line({"rate_limits": {"seven_day": {"used_percentage": 12}}})

        self.assertIn("7d 12%", line)
        self.assertNotIn("5h", line)

    def test_absent_rate_limits_and_cache_are_omitted_not_faked(self) -> None:
        """Both objects are absent before the first API response, and on non-Pro/Max plans."""
        statusline = load_module("statusline", STATUSLINE_PATH)

        line = statusline.build_line({"model": {"display_name": "Opus"}, "rate_limits": {}})

        self.assertNotIn("5h", line)
        self.assertNotIn("cache", line)
        self.assertIn("Opus", line)

    def test_an_empty_payload_renders_rather_than_raising(self) -> None:
        statusline = load_module("statusline", STATUSLINE_PATH)

        self.assertIn("no session data", statusline.build_line({}))


class StatusLineColourTests(unittest.TestCase):
    """The colours are the point of the widget, so they are asserted, not assumed.

    Every other status line test asserts plain text, which a flattened
    `by_headroom` would still satisfy. These assert the escape codes, so losing
    the red warning at 15% headroom turns a test red instead of shipping quietly.
    """

    def setUp(self) -> None:
        self.statusline = load_module("statusline", STATUSLINE_PATH)

    def ctx(self, remaining: float) -> str:
        return self.statusline.build_line({"context_window": {"remaining_percentage": remaining}})

    def test_context_headroom_changes_colour_at_the_documented_boundaries(self) -> None:
        for remaining, colour, name in (
            (100, self.statusline.GREEN, "green well clear"),
            (30.1, self.statusline.GREEN, "green just above the handoff line"),
            (30, self.statusline.YELLOW, "yellow at the handoff line"),
            (15.1, self.statusline.YELLOW, "yellow just above the wrap-up line"),
            (15, self.statusline.RED, "red at the wrap-up line"),
            (0, self.statusline.RED, "red with nothing left"),
        ):
            with self.subTest(remaining=remaining, expected=name):
                self.assertIn(colour, self.ctx(remaining))

    def test_rate_limit_colour_follows_headroom_not_usage(self) -> None:
        line = self.statusline.build_line(
            {"rate_limits": {"five_hour": {"used_percentage": 90}, "seven_day": {"used_percentage": 10}}}
        )

        self.assertIn(self.statusline.RED, line)
        self.assertIn(self.statusline.GREEN, line)


class StatusLineRobustnessTests(unittest.TestCase):
    """Payload values the status line does not control, and must survive."""

    def setUp(self) -> None:
        self.statusline = load_module("statusline", STATUSLINE_PATH)

    def plain(self, line: str) -> str:
        for code in (self.statusline.RESET, self.statusline.DIM, self.statusline.GREEN,
                     self.statusline.YELLOW, self.statusline.RED):
            line = line.replace(code, "")
        return line

    def render(self, payload: dict) -> tuple[str, str]:
        """Render, and hand back what was discarded on stderr alongside the line."""
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            line = self.statusline.build_line(payload)
        return line, stderr.getvalue()

    def test_the_bar_is_ten_cells_whatever_the_percentage_says(self) -> None:
        for payload, name in (
            ({"used_percentage": 120}, "over-spent"),
            ({"remaining_percentage": 500}, "nonsense high"),
            ({"remaining_percentage": -50}, "nonsense low"),
            ({"remaining_percentage": 62}, "ordinary"),
        ):
            with self.subTest(case=name):
                bar = self.plain(self.statusline.build_line({"context_window": payload})).split(" ")[0]
                self.assertEqual(len(bar), 10, f"{name} rendered a {len(bar)}-cell bar")
                self.assertEqual(set(bar) - {"█", "░"}, set())

    def test_a_broken_reset_timestamp_costs_the_clock_and_nothing_else(self) -> None:
        """A millisecond epoch used to raise and take the whole line with it."""
        line, stderr = self.render(
            {
                "context_window": {"remaining_percentage": 40},
                "rate_limits": {"five_hour": {"used_percentage": 88, "resets_at": 1789000000000}},
            }
        )

        self.assertIn("5h 88%", line)
        self.assertIn("40% ctx", line)
        self.assertNotIn("→", line)
        self.assertIn("rate_limits.five_hour.resets_at", stderr,
                      "a rejected timestamp must be distinguishable from an absent one")

    def test_non_finite_and_boolean_numbers_read_as_absent(self) -> None:
        """`json.loads` accepts NaN, and `True` is an `int` — neither is a percentage."""
        for value, name in ((float("nan"), "NaN"), (float("inf"), "Infinity"), (True, "bool")):
            with self.subTest(value=name):
                line, stderr = self.render(
                    {"context_window": {"remaining_percentage": value}, "cost": {"total_cost_usd": 2}}
                )
                self.assertNotIn("ctx", line)
                self.assertIn("$2.00", line, "the rest of the line must still render")
                self.assertIn("context_window.remaining_percentage", stderr)

    def test_a_number_too_large_for_a_float_costs_only_its_own_segment(self) -> None:
        """`float()` raises OverflowError on a big enough int, inside the very
        helper that exists to keep bad values from reaching the renderer."""
        huge = int("9" * 400)
        for payload, name in (
            ({"context_window": {"remaining_percentage": huge}, "cost": {"total_cost_usd": 2}}, "context"),
            ({"cost": {"total_cost_usd": huge}, "model": {"display_name": "Opus"}}, "cost"),
        ):
            with self.subTest(field=name):
                line, stderr = self.render(payload)

                self.assertNotIn("unavailable", line)
                self.assertTrue(line.strip(), "the rest of the line must still render")
                self.assertIn("too large to be a number", stderr)

    def test_a_payload_string_cannot_break_out_of_the_single_line(self) -> None:
        line = self.statusline.build_line(
            {"model": {"display_name": "Opus\ninjected\x1b[2Jcleared"}}
        )

        self.assertNotIn("\n", line)
        self.assertNotIn("\x1b[2J", line)
        self.assertIn("Opus", line)

    def test_a_very_long_name_cannot_push_the_numbers_off_screen(self) -> None:
        line = self.statusline.build_line(
            {"model": {"display_name": "x" * 500}, "cost": {"total_cost_usd": 1}}
        )

        self.assertLess(len(self.plain(line)), 120)
        self.assertIn("$1.00", line)


class StatusLineWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.statusline = load_module("statusline", STATUSLINE_PATH)

    def test_the_workspace_segment_reads_a_field_the_payload_actually_carries(self) -> None:
        """`project_dir` is in the status line payload; `git_worktree` was not.

        Reading only a key the payload never sets is a segment that can never
        render, and nothing in the suite would have noticed.
        """
        line = self.statusline.build_line({"workspace": {"project_dir": "/home/user/some-repo"}})

        self.assertIn("some-repo", line)

    def test_a_worktree_is_preferred_when_a_release_provides_one(self) -> None:
        line = self.statusline.build_line(
            {"workspace": {"project_dir": "/home/user/some-repo", "git_worktree": "/tmp/wt/feature-x"}}
        )

        self.assertIn("feature-x", line)
        self.assertNotIn("some-repo", line)

    def test_an_unusable_git_worktree_does_not_shadow_a_good_project_dir(self) -> None:
        """Preferring a key must not let a broken one hide a usable fallback.

        A truthy non-string `git_worktree` (upstream schema drift) used to win
        the `or`, fail the type check, and drop the whole segment.
        """
        for worktree, name in ((12, "a number"), (["/tmp/wt"], "a list"), ({"a": 1}, "an object")):
            with self.subTest(git_worktree=name):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    line = self.statusline.build_line(
                        {"workspace": {"git_worktree": worktree, "project_dir": "/home/user/some-repo"}}
                    )

                self.assertIn("some-repo", line)
                self.assertIn("workspace.git_worktree", stderr.getvalue())

    def test_an_absent_field_is_not_reported_as_a_discard(self) -> None:
        """Absent is the normal case on most plans; noting it would drown the signal."""
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.statusline.build_line(
                {"model": {"display_name": "Opus"}, "context_window": {}, "rate_limits": {},
                 "prompt_cache": {}, "cost": {}, "workspace": {}}
            )

        self.assertEqual(stderr.getvalue(), "")

    def test_spend_limit_renders_like_the_windows_beside_it(self) -> None:
        """The docs list it as a `rate_limits` window, so it is rendered as one."""
        line = self.statusline.build_line({"rate_limits": {"spend_limit": {"used_percentage": 93}}})

        self.assertIn("spend 93%", line)


class StatusLineProcessTests(unittest.TestCase):
    """The hook contract is stdin in, one line out, exit 0 — asserted end to end.

    Every other status line test calls `build_line` directly, which skips the
    stdin decode, the non-object guard and the render fallback entirely.
    """

    def run_statusline(self, stdin: bytes) -> subprocess.CompletedProcess:
        # Strict decoding, as under en_US.UTF-8. Under C.UTF-8 (GitHub-hosted
        # runners) Python reads stdin with surrogateescape, which hid a crash on
        # invalid bytes until the suite first ran on a self-hosted runner.
        return subprocess.run(
            [sys.executable, str(STATUSLINE_PATH)],
            input=stdin,
            capture_output=True,
            timeout=30,
            env={**os.environ, "PYTHONIOENCODING": "utf-8:strict"},
        )

    def test_any_stdin_exits_zero_with_exactly_one_line(self) -> None:
        for stdin, name in (
            (b"", "empty"),
            (b"not json", "garbage"),
            (b"\xff\xfe\x00binary", "binary"),
            (b"[1,2,3]", "a JSON array"),
            (b'"a string"', "a JSON string"),
            (b"null", "JSON null"),
            (b"{}", "an empty object"),
            (b'{"cost": {"total_cost_usd": 1.5}}', "a real payload"),
        ):
            with self.subTest(stdin=name):
                result = self.run_statusline(stdin)

                self.assertEqual(result.returncode, 0, f"{name}: {result.stderr!r}")
                self.assertEqual(result.stdout.decode().count("\n"), 1, f"{name} printed {result.stdout!r}")

    def test_a_swallowed_payload_leaves_a_note_on_stderr(self) -> None:
        """Fail open, but not silently: a field that vanishes must be traceable."""
        for stdin, name in ((b"not json", "garbage"), (b"[1,2,3]", "a JSON array")):
            with self.subTest(stdin=name):
                result = self.run_statusline(stdin)

                self.assertEqual(result.returncode, 0)
                self.assertIn(b"statusline:", result.stderr)

    def test_a_well_formed_payload_says_nothing_on_stderr(self) -> None:
        result = self.run_statusline(b'{"model": {"display_name": "Opus"}}')

        self.assertEqual(result.stderr, b"")
        self.assertIn(b"Opus", result.stdout)


class DocsConformanceTests(unittest.TestCase):
    """The example line in the docs is computable, so a test computes it.

    A rendered example is the first thing a reader trusts and the first thing to
    drift when the renderer changes. Per `deterministic_work` in
    agent-routing/policy.yaml, that makes it a check rather than a review item.
    """

    DOCS_PATH = ROOT / "docs" / "session-budget.md"

    # The payload the documented example is meant to be rendered from.
    EXAMPLE_PAYLOAD = {
        "model": {"display_name": "Opus"},
        "workspace": {"project_dir": "/home/user/my-repo"},
        "context_window": {"remaining_percentage": 62},
        "rate_limits": {"five_hour": {"used_percentage": 41}},
        "prompt_cache": {"warm": True, "hit_ratio": 0.91},
        "cost": {"total_cost_usd": 1.23},
    }

    def docs_prose(self) -> str:
        """Whitespace-normalised, so reflowing a paragraph is not a CI failure.

        These assertions exist to catch a number drifting, not to freeze the
        prose around it — matching raw text would make every rewrap a red build
        and teach the next reader to distrust the check.
        """
        return " ".join(self.DOCS_PATH.read_text(encoding="utf-8").split())

    def documented_example(self) -> str:
        text = self.DOCS_PATH.read_text(encoding="utf-8")
        marker = "```text\n"
        self.assertEqual(
            text.count(marker), 1,
            "this test compares the first ```text block; a second one would be "
            "silently ignored, so add the new block as ```console or assert it here",
        )
        start = text.index(marker) + len(marker)
        return text[start:text.index("```", start)].strip()

    def test_the_documented_status_line_is_what_the_script_renders(self) -> None:
        statusline = load_module("statusline", STATUSLINE_PATH)
        rendered = statusline.build_line(self.EXAMPLE_PAYLOAD)
        for code in (statusline.RESET, statusline.DIM, statusline.GREEN,
                     statusline.YELLOW, statusline.RED):
            rendered = rendered.replace(code, "")

        self.assertEqual(rendered, self.documented_example())

    def test_the_documented_colour_boundaries_are_the_ones_in_the_code(self) -> None:
        """The doc states 30% and 15%; drifting either would mislead every reader."""
        statusline = load_module("statusline", STATUSLINE_PATH)

        self.assertIn("green above 30%, yellow from 30%, red from 15%", self.docs_prose())
        self.assertEqual(statusline.by_headroom(30.1), statusline.GREEN)
        self.assertEqual(statusline.by_headroom(30), statusline.YELLOW)
        self.assertEqual(statusline.by_headroom(15), statusline.RED)

    def test_the_documented_reset_clock_threshold_is_the_one_in_the_code(self) -> None:
        statusline = load_module("statusline", STATUSLINE_PATH)

        self.assertIn(f"at least {statusline.RESET_TIME_AT}% used", self.docs_prose())


if __name__ == "__main__":
    unittest.main()
