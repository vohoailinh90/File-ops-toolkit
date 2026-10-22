"""The mutation checker is itself a check, so it gets the same treatment.

A tool that claims a test suite is sound, while quietly reporting a verdict it
never produced, is the exact failure it was written to prevent.
"""

from __future__ import annotations

import ast
import contextlib
import io
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "scripts" / "mutation_check.py"
MANIFEST_DIR = ROOT / "tests" / "mutations"


def load_module(name: str, path: Path):
    """Load from source, never from the bytecode cache (see test_session_budget)."""
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


class ManifestConformanceTests(unittest.TestCase):
    """A manifest that has drifted from the source silently stops proving anything.

    These are the deterministic half: no test is executed, only the claim that
    each mutation still describes a real, unique site in the file it names.
    """

    def setUp(self) -> None:
        self.checker = load_module("mutation_check", CHECKER_PATH)

    def manifests(self):
        found = sorted(MANIFEST_DIR.glob("*.yaml"))
        self.assertTrue(found, "no mutation manifests found; the checker guards nothing")
        return found

    def test_every_manifest_parses_and_declares_its_required_fields(self) -> None:
        for path in self.manifests():
            with self.subTest(manifest=path.name):
                manifest = self.checker.load_manifest(path)
                self.assertTrue(manifest["mutations"])

    def test_every_mutation_still_matches_its_source_exactly_once(self) -> None:
        """The check that makes the manifest self-maintaining.

        Edit a guarded file without updating the manifest and this goes red,
        rather than the manifest quietly skipping the behavior it covered.
        """
        for path in self.manifests():
            manifest = self.checker.load_manifest(path)
            for entry in manifest["mutations"]:
                where = self.checker.resolve(entry, manifest)
                with self.subTest(manifest=path.name, mutation=entry["label"]):
                    self.assertTrue(where.is_file(), f"{where} does not exist")
                    source = where.read_text(encoding="utf-8")
                    self.assertEqual(
                        source.count(entry["find"]), 1,
                        "must match exactly one site; update the manifest alongside the code",
                    )

    def test_every_mutation_actually_changes_the_source(self) -> None:
        for path in self.manifests():
            manifest = self.checker.load_manifest(path)
            for entry in manifest["mutations"]:
                with self.subTest(manifest=path.name, mutation=entry["label"]):
                    self.assertNotEqual(entry["find"], entry["replace"])

    def test_every_named_test_target_can_be_resolved(self) -> None:
        """A typo in a test path would make the mutation look caught by nothing.

        Resolved by reading the source, not by importing it. `find_spec` on a
        dotted path needs `tests` to be an importable package, which depends on
        whether the runner put the repository root on `sys.path` — true under
        `python -m pytest`, false under bare `pytest`, which is what CI runs.
        A check that passes or fails according to how it was invoked is not a
        check. The target is static text, so `ast` settles it either way.
        """
        for path in self.manifests():
            manifest = self.checker.load_manifest(path)
            for entry in manifest["mutations"]:
                package, module, *rest = entry["test"].split(".")
                source = ROOT / package / f"{module}.py"
                with self.subTest(manifest=path.name, target=entry["test"]):
                    self.assertTrue(source.is_file(), f"{source} does not exist")
                    if not rest:
                        continue
                    tree = ast.parse(source.read_text(encoding="utf-8"))
                    names = {
                        (node.name, child.name)
                        for node in ast.walk(tree)
                        if isinstance(node, ast.ClassDef)
                        for child in node.body
                        if isinstance(child, ast.FunctionDef)
                    }
                    classes = {klass for klass, _ in names}
                    self.assertIn(rest[0], classes, f"no class {rest[0]} in {source.name}")
                    if len(rest) > 1:
                        self.assertIn((rest[0], rest[1]), names,
                                      f"no test {rest[1]} on {rest[0]}")


class DirtyTreeGuardTests(unittest.TestCase):
    """The guard is only worth having if it sees every kind of dirty."""

    def setUp(self) -> None:
        self.checker = load_module("mutation_check", CHECKER_PATH)

    def test_a_rename_is_reported_under_both_of_its_names(self) -> None:
        """`R  old -> new` used to parse into one string matching neither name,
        so the guard let a run proceed against a file with a rename in flight."""
        paths = self.checker.parse_porcelain("R  scripts/a.py -> scripts/b.py\n")

        self.assertEqual(paths, {"scripts/a.py", "scripts/b.py"})

    def test_ordinary_statuses_still_parse(self) -> None:
        paths = self.checker.parse_porcelain(
            " M scripts/mutation_check.py\n"
            "?? tests/mutations/new.yaml\n"
            "A  tests/added.py\n"
        )

        self.assertEqual(paths, {"scripts/mutation_check.py", "tests/mutations/new.yaml",
                                 "tests/added.py"})

    def test_a_quoted_path_loses_its_quotes(self) -> None:
        """Porcelain quotes a path containing spaces; the manifest never does."""
        paths = self.checker.parse_porcelain(' M "scripts/with space.py"\n')

        self.assertEqual(paths, {"scripts/with space.py"})

    def test_blank_output_is_a_clean_tree(self) -> None:
        self.assertEqual(self.checker.parse_porcelain("\n\n"), set())


class RestoreFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = load_module("mutation_check", CHECKER_PATH)

    def test_a_failed_restore_names_the_file_it_left_mutated(self) -> None:
        """Nothing can fix the file at that point, so the message is all the
        operator gets. An exception that does not say which file is corrupted
        leaves them worse off than no message at all."""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "guarded.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            manifest_path = Path(directory) / "m.yaml"
            manifest_path.write_text(yaml.safe_dump({
                "mutations": [{
                    "label": "restore will fail",
                    "file": str(source),
                    "find": "VALUE = 1",
                    "replace": "VALUE = 2",
                    "test": ("tests.test_mutation_check.CheckerBehaviourTests"
                             ".test_a_mutation_matching_two_sites_is_refused"),
                }]
            }), encoding="utf-8")

            calls = {"n": 0}
            real_write = Path.write_text

            def failing_write(self, data, **kwargs):
                calls["n"] += 1
                if calls["n"] == 2:  # the restore, not the mutation
                    raise OSError("no space left on device")
                return real_write(self, data, **kwargs)

            stderr = io.StringIO()
            with mock.patch.object(Path, "write_text", failing_write), \
                    contextlib.redirect_stderr(stderr), \
                    self.assertRaises(OSError):
                self.checker.check(manifest_path, allow_outside=True)

        message = stderr.getvalue()
        self.assertIn("NOT RESTORED", message)
        self.assertIn("guarded.py", message, "the message must name the file")


class CheckerBehaviourTests(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = load_module("mutation_check", CHECKER_PATH)

    def test_a_mutation_matching_no_site_is_refused_rather_than_reported(self) -> None:
        with self.assertRaises(self.checker.ManifestError) as caught:
            self.checker.mutate("abc", {"label": "x", "find": "zzz", "replace": "y"}, Path("f"))

        self.assertIn("matched 0 times", str(caught.exception))

    def test_a_mutation_matching_two_sites_is_refused(self) -> None:
        """Two matches means an unintended site is mutated as well as the intended one."""
        with self.assertRaises(self.checker.ManifestError) as caught:
            self.checker.mutate("a a", {"label": "x", "find": "a", "replace": "b"}, Path("f"))

        self.assertIn("matched 2 times", str(caught.exception))

    def test_a_manifest_without_mutations_is_refused(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
            handle.write(yaml.safe_dump({"target": "x"}))
        with self.assertRaises(self.checker.ManifestError):
            self.checker.load_manifest(Path(handle.name))

    def test_a_manifest_entry_missing_a_field_is_refused(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
            handle.write(yaml.safe_dump({"mutations": [{"label": "x", "find": "a"}]}))
        with self.assertRaises(self.checker.ManifestError) as caught:
            self.checker.load_manifest(Path(handle.name))

        self.assertIn("replace", str(caught.exception))

    def test_a_manifest_cannot_rewrite_a_file_outside_the_repository(self) -> None:
        """The dirty-tree guard reads `git status`, which says nothing about a file
        git does not track — so confinement, not the guard, is what protects them."""
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / "victim.txt"
            outside.write_text("ORIGINAL\n", encoding="utf-8")
            manifest_path = Path(directory) / "m.yaml"
            manifest_path.write_text(yaml.safe_dump({
                "mutations": [{
                    "label": "escapes the repository",
                    "file": str(outside),
                    "find": "ORIGINAL",
                    "replace": "REWRITTEN",
                    # A narrow, subprocess-free target: naming the whole module
                    # would re-enter this checker from inside it.
                    "test": ("tests.test_mutation_check.CheckerBehaviourTests"
                             ".test_a_mutation_matching_two_sites_is_refused"),
                }]
            }), encoding="utf-8")

            results = self.checker.check(manifest_path)

            self.assertEqual([verdict for verdict, _, _ in results], [self.checker.BROKEN])
            self.assertIn("outside the repository", results[0][2])
            self.assertEqual(outside.read_text(encoding="utf-8"), "ORIGINAL\n",
                             "the file must never have been written at all")

    def test_a_test_that_does_not_exist_is_broken_not_caught(self) -> None:
        """The bug this baseline exists to stop.

        `unittest` exits non-zero for a test it cannot find, and non-zero is
        exactly what this script reads as "the test caught the mutation". A
        mistyped class name therefore produced a green verdict for a behavior
        nothing guarded — and did, for one entry in statusline.yaml, until the
        manifest conformance check flagged it.
        """
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "m.yaml"
            manifest_path.write_text(yaml.safe_dump({
                "target": "scripts/hooks/statusline.py",
                "mutations": [{
                    "label": "names a test that does not exist",
                    "find": "    return GREEN",
                    "replace": "    return RED",
                    "test": "tests.test_session_budget.StatusLineColourTests.no_such_test",
                }]
            }), encoding="utf-8")

            results = self.checker.check(manifest_path)

            self.assertEqual([verdict for verdict, _, _ in results], [self.checker.BROKEN])
            self.assertIn("does not pass on unmutated source", results[0][2])

    def test_a_test_that_does_not_guard_the_mutation_is_reported_as_survived(self) -> None:
        """The verdict the whole tool exists to produce.

        A mutation is applied to a file no test reads, and the named test is one
        that passes regardless. The tool must call that SURVIVED, not caught.
        """
        with tempfile.TemporaryDirectory() as directory:
            unguarded = Path(directory) / "unguarded.py"
            unguarded.write_text("VALUE = 1\n", encoding="utf-8")
            manifest_path = Path(directory) / "m.yaml"
            manifest_path.write_text(yaml.safe_dump({
                "mutations": [{
                    "label": "nothing reads this file",
                    "file": str(unguarded),
                    "find": "VALUE = 1",
                    "replace": "VALUE = 2",
                    "test": (
                        "tests.test_mutation_check.CheckerBehaviourTests"
                        ".test_a_mutation_matching_no_site_is_refused_rather_than_reported"
                    ),
                }]
            }), encoding="utf-8")

            results = self.checker.check(manifest_path, allow_outside=True)

            self.assertEqual([verdict for verdict, _, _ in results], [self.checker.SURVIVED])
            self.assertEqual(unguarded.read_text(encoding="utf-8"), "VALUE = 1\n",
                             "the source must be restored whatever the verdict")


if __name__ == "__main__":
    unittest.main()
