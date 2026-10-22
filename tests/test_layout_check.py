"""scripts/layout_check.py: the gate that keeps a repository's root to what users run.

See .claude/skills/repo-layout/SKILL.md.
"""

from __future__ import annotations

import contextlib
import io
import shutil
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "scripts" / "layout_check.py"


def load_module(name: str, path: Path):
    """Load from source, never from the bytecode cache (see test_session_budget)."""
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


checker = load_module("layout_check", CHECKER_PATH)

ENTRY = 'def main():\n    pass\n\n\nif __name__ == "__main__":\n    main()\n'
MODULE = "def helper():\n    return 1\n"


def run_checker(*args: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = checker.main(list(args))
    return code, out.getvalue()


class LayoutCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def write(self, relative: str, text: str = ENTRY) -> None:
        path = self.tmp / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def check(self, *args: str) -> tuple[int, str]:
        return run_checker(str(self.tmp), *args)

    def test_this_repository_passes(self) -> None:
        code, out = run_checker(str(ROOT))
        self.assertEqual(code, 0, out)

    def test_a_clean_layout_passes(self) -> None:
        self.write("app.py")
        self.write("README.md", "# app\n")
        self.write("app_pkg/core.py", MODULE)
        self.write("tests/test_core.py", MODULE)
        self.write("tests/support/fixtures.py", MODULE)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("0 error(s)", out)

    def test_a_test_file_in_the_root_is_an_error(self) -> None:
        for name in ("test_cli.py", "cli_test.py", "conftest.py", "Conftest.py", "run_tests_sample.py", "TestRunner.py",
                     "APITest.py"):
            with self.subTest(name=name):
                self.write(name)
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn(f"{name}: test file in the root", out)
                (self.tmp / name).unlink()

    def test_acronyms_without_a_test_word_are_not_tests(self) -> None:
        for stem in ("HTTPServer", "IOError", "latest", "contest", "pytest_helper", "runtests"):
            with self.subTest(stem=stem):
                self.assertFalse(checker.is_test_name(stem))
        for stem in ("APITest", "XMLTests", "TestHTTP", "testAPI", "UITest"):
            with self.subTest(stem=stem):
                self.assertTrue(checker.is_test_name(stem))

    def test_words_that_merely_contain_test_are_not_tests(self) -> None:
        self.write("latest_report.py")
        self.write("attest.py")
        self.write("LatestReport.py")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_javascript_test_in_the_root_is_an_error(self) -> None:
        for name in ("geometry.test.mjs", "app.spec.ts", "Widget.Test.TSX", "foo-test.js", "foo_test.cjs",
                     "test-foo.mjs", "test.js", "spec.ts", "api-spec.js", "CalculatorSpec.js", "userSpec.ts"):
            with self.subTest(name=name):
                self.write(name, "export {};\n")
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn(f"{name}: test file in the root", out)
                (self.tmp / name).unlink()

    def test_ordinary_javascript_files_are_not_checked(self) -> None:
        for name in ("build.mjs", "vite.config.ts", "latest.js", "inspect.js", "special.ts", "contest.mjs",
                     "SpecialOffer.tsx"):
            self.write(name, "export {};\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_python_suffixes_are_matched_case_insensitively(self) -> None:
        for name, message in (("helper.PY", "helper.PY: library module in the root"),
                              ("test_sample.Py", "test_sample.Py: test file in the root"),
                              ("gui_helper.pyw", "gui_helper.pyw: library module in the root")):
            with self.subTest(name=name):
                self.write(name, MODULE)
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn(message, out)
                (self.tmp / name).unlink()

    def test_a_pyw_launcher_is_an_entry_point(self) -> None:
        self.write("app.pyw")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_test_directory_in_the_root_is_an_error(self) -> None:
        self.write("test_support/helpers.py", MODULE)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("test_support/: test directory in the root", out)

    def test_a_spec_directory_holding_tests_is_an_error(self) -> None:
        for name, test_file in (("spec", "models/user_spec.rb"), ("Specs", "app.spec.ts")):
            with self.subTest(name=name):
                self.write(f"{name}/{test_file}", "x\n")
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn(f"{name}/: test directory in the root", out)
                shutil.rmtree(self.tmp / name)

    def test_a_specs_directory_of_documents_is_not_a_test_directory(self) -> None:
        self.write("specs/001-login/spec.md", "# Login\n")
        self.write("specs/001-login/plan.md", "# Plan\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_library_module_in_the_root_is_an_error(self) -> None:
        self.write("si_marking_template.py", MODULE)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("si_marking_template.py: library module in the root", out)

    def test_a_reversed_main_guard_counts(self) -> None:
        self.write("app.py", 'if "__main__" == __name__:\n    pass\n')
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_nested_main_guard_does_not_count(self) -> None:
        self.write("app.py", 'def f():\n    if __name__ == "__main__":\n        pass\n')
        code, out = self.check()
        self.assertEqual(code, 1, out)

    def test_a_streamlit_app_needs_the_marker(self) -> None:
        app = "import streamlit as st\nst.title('x')\n"
        self.write("dashboard.py", app)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("dashboard.py: library module in the root", out)
        self.assertIn("a Streamlit app? declare it with `# layout: entry-point`", out)
        self.write("dashboard.py", "# layout: entry-point\n" + app)
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_plain_module_gets_the_generic_hint(self) -> None:
        self.write("helpers.py", MODULE)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("move it into the app's package, or declare a real launcher", out)
        self.assertNotIn("Streamlit", out)

    def test_the_entry_point_marker_declares_a_launcher(self) -> None:
        for source in ("# layout: entry-point\nimport runpy\nrunpy.run_module('app')\n",
                       "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n  # Layout: Entry-Point  \nx = 1\n"):
            with self.subTest(source=source):
                self.write("launcher.py", source)
                code, out = self.check()
                self.assertEqual(code, 0, out)

    def test_the_marker_counts_only_in_the_first_lines(self) -> None:
        self.write("late.py", "x = 1\n" * 10 + "# layout: entry-point\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("late.py: library module in the root", out)

    def test_the_marker_inside_a_string_is_not_a_declaration(self) -> None:
        for source in ('"""Docs.\n\n# layout: entry-point\n"""\nx = 1\n',
                       "TEXT = '''\n# layout: entry-point\n'''\n"):
            with self.subTest(source=source):
                self.write("documented.py", source)
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn("documented.py: library module in the root", out)

    def test_the_marker_must_be_the_whole_comment(self) -> None:
        self.write("notes.py", "# see layout: entry-point docs\nx = 1\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)

    def test_declared_launchers_count_toward_the_entry_point_limit(self) -> None:
        for name in ("a.py", "b.py", "c.py", "d.py"):
            self.write(name, "# layout: entry-point\nimport streamlit\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("4 entry points in the root", out)

    def test_setup_py_is_exempt(self) -> None:
        self.write("setup.py", "from setuptools import setup\nsetup()\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_too_many_entry_points_is_an_error(self) -> None:
        for name in ("a.py", "b.py", "c.py", "d.py"):
            self.write(name)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("4 entry points in the root", out)
        code, out = self.check("--max-root-scripts", "4")
        self.assertEqual(code, 0, out)

    def test_an_unparseable_root_file_is_an_error(self) -> None:
        self.write("broken.py", "def (:\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("broken.py: cannot be read or parsed", out)

    def test_a_utf8_bom_launcher_is_an_entry_point(self) -> None:
        (self.tmp / "app.py").write_bytes(b"\xef\xbb\xbf" + ENTRY.encode("utf-8"))
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_coding_cookie_is_honoured(self) -> None:
        source = "# -*- coding: latin-1 -*-\nNAME = '\xe9'\n" + ENTRY
        (self.tmp / "app.py").write_bytes(source.encode("latin-1"))
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_an_unreadable_root_file_is_an_error_not_a_crash(self) -> None:
        (self.tmp / "latin1.py").write_bytes(b"x = '\xe9'\n")
        (self.tmp / "dangling.py").symlink_to(self.tmp / "missing.py")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("latin1.py: cannot be read or parsed", out)
        self.assertIn("dangling.py: cannot be read or parsed (FileNotFoundError)", out)

    def test_hidden_tool_directories_are_ignored(self) -> None:
        for name in (".tox/test_x.py", ".venv/lib/helper.py", ".pytest_cache/v/x.py", ".git/hooks/x.py",
                     ".github/workflows/x.py", ".mypy_cache/x.py"):
            self.write(name, MODULE)
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_hidden_python_files_are_inspected(self) -> None:
        self.write(".helper.py", MODULE)
        self.write(".test_example.py", MODULE)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn(".helper.py: library module in the root", out)
        self.assertIn(".test_example.py: test file in the root", out)

    def test_a_hidden_test_directory_is_an_error(self) -> None:
        self.write(".test_support/helpers.py", MODULE)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn(".test_support/: test directory in the root", out)

    def test_a_name_the_console_cannot_encode_is_escaped_not_a_crash(self) -> None:
        self.write("\u4fee\u6b63.py", MODULE)
        raw = io.BytesIO()
        console = io.TextIOWrapper(raw, encoding="cp1252")
        with contextlib.redirect_stdout(console):
            code = checker.main([str(self.tmp)])
        console.flush()
        out = raw.getvalue().decode("cp1252")
        self.assertEqual(code, 1, out)
        self.assertIn("\\u4fee\\u6b63.py: library module in the root", out)

    def test_an_allowed_root_module_is_exempt_and_nothing_else_is(self) -> None:
        self.write("app.py")
        self.write("file_handlers.py", MODULE)
        self.write("helper.py", MODULE)
        code, out = self.check("--allow-root-module", "file_handlers.py")
        self.assertEqual(code, 1, out)
        self.assertNotIn("file_handlers.py", out)
        self.assertIn("helper.py: library module in the root", out)
        code, out = self.check("--allow-root-module", "file_handlers.py", "--allow-root-module", "helper.py")
        self.assertEqual(code, 0, out)

    def test_an_allowance_matches_the_exact_file_name(self) -> None:
        self.write("app.py")
        self.write("helper.py", MODULE)
        code, out = self.check("--allow-root-module", "Helper.py")
        self.assertEqual(code, 1, out)
        self.assertIn("helper.py: library module in the root", out)
        self.assertIn("Helper.py: given to --allow-root-module but not a library module", out)

    def test_an_allowance_does_not_outlive_its_module(self) -> None:
        self.write("app.py")
        for name, why in (("gone.py", "missing"), ("app.py", "an entry point")):
            with self.subTest(name=name):
                code, out = self.check("--allow-root-module", name)
                self.assertEqual(code, 1, out)
                self.assertIn(f"{name}: given to --allow-root-module but not a library module", out)

    def test_an_allowance_does_not_exempt_a_test_file(self) -> None:
        self.write("test_helper.py", MODULE)
        code, out = self.check("--allow-root-module", "test_helper.py")
        self.assertEqual(code, 1, out)
        self.assertIn("test_helper.py: test file in the root", out)

    def test_bad_arguments_exit_2(self) -> None:
        code, _ = run_checker(str(self.tmp / "missing"))
        self.assertEqual(code, 2)
        code, _ = self.check("--max-root-scripts", "-1")
        self.assertEqual(code, 2)
        for value in ("pkg/mod.py", "notes.txt"):
            code, _ = self.check("--allow-root-module", value)
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
