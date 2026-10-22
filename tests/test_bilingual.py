"""The bilingual (Japanese/English) feature: catalog checker, Python runtime, web runtime.

Everything a derived repository copies out of `.claude/skills/bilingual/runtime/`
is exercised here, and so is `scripts/i18n_check.py`, the CI gate that keeps
its catalogs in step. See `.claude/skills/bilingual/SKILL.md`.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import date
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "scripts" / "i18n_check.py"
RUNTIME_DIR = ROOT / ".claude" / "skills" / "bilingual" / "runtime"
PY_RUNTIME_PATH = RUNTIME_DIR / "python" / "i18n.py"
WEB_RUNTIME_PATH = RUNTIME_DIR / "web" / "i18n.ts"
STARTER_LOCALES = RUNTIME_DIR / "locales"
WEB_CHECK = ROOT / "tests" / "web" / "i18n_runtime_check.mts"


def load_module(name: str, path: Path):
    """Load from source, never from the bytecode cache (see test_session_budget)."""
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


checker = load_module("i18n_check", CHECKER_PATH)
runtime = load_module("bilingual_i18n", PY_RUNTIME_PATH)

EN = {"actions": {"save": "Save"}, "status": {"error": "Failed: {message}"},
      "files": {"n_one": "{count} file", "n_other": "{count} files"}}
JA = {"actions": {"save": "保存"}, "status": {"error": "失敗: {message}"},
      "files": {"n_one": "{count} 件", "n_other": "{count} 件"}}


def write_catalogs(directory: Path, **catalogs: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in catalogs.items():
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        (directory / f"{name}.json").write_text(text, encoding="utf-8")
    return directory


def run_checker(*args: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = checker.main(list(args))
    return code, out.getvalue()


class CheckerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def check(self, **catalogs: object) -> tuple[int, str]:
        return run_checker(str(write_catalogs(self.tmp / "locales", **catalogs)))

    def test_consistent_catalogs_pass(self) -> None:
        code, out = self.check(en=EN, ja=JA)
        self.assertEqual(code, 0, out)
        self.assertIn("0 error(s)", out)

    def test_the_starter_catalogs_shipped_with_the_skill_pass(self) -> None:
        code, out = run_checker(str(STARTER_LOCALES))
        self.assertEqual(code, 0, out)
        self.assertIn("0 warning(s)", out)

    def test_a_missing_required_locale_is_an_error(self) -> None:
        code, out = self.check(en=EN)
        self.assertEqual(code, 1)
        self.assertIn("missing ja.json", out)

    def test_missing_key_is_an_error(self) -> None:
        ja = json.loads(json.dumps(JA))
        del ja["actions"]["save"]
        code, out = self.check(en=EN, ja=ja)
        self.assertEqual(code, 1)
        self.assertIn("missing key 'actions.save' (present in en)", out)

    def test_placeholder_mismatch_is_an_error(self) -> None:
        ja = json.loads(json.dumps(JA))
        ja["status"]["error"] = "失敗: {msg}"
        code, out = self.check(en=EN, ja=ja)
        self.assertEqual(code, 1)
        self.assertIn("'status.error' has different placeholders", out)

    def test_empty_message_is_an_error(self) -> None:
        ja = json.loads(json.dumps(JA))
        ja["actions"]["save"] = "  "
        code, out = self.check(en=EN, ja=ja)
        self.assertEqual(code, 1)
        self.assertIn("'actions.save' is empty", out)

    def test_a_plural_form_needs_its_partner(self) -> None:
        en = json.loads(json.dumps(EN))
        ja = json.loads(json.dumps(JA))
        del en["files"]["n_other"], ja["files"]["n_other"]
        code, out = self.check(en=en, ja=ja)
        self.assertEqual(code, 1)
        self.assertIn("plural key 'files.n_one' has no 'files.n_other'", out)

    def test_non_string_leaves_dotted_keys_and_bad_json_are_errors(self) -> None:
        code, out = self.check(en={"a": 1, "b.c": "x"}, ja="{not json")
        self.assertEqual(code, 1)
        self.assertIn("'a' must be a string, got int", out)
        self.assertIn("key 'b.c'", out)
        self.assertIn("not valid UTF-8 JSON", out)

    def test_identical_text_is_a_warning_not_an_error(self) -> None:
        ja = json.loads(json.dumps(JA))
        ja["actions"]["save"] = "Save"
        code, out = self.check(en=EN, ja=ja)
        self.assertEqual(code, 0, out)
        self.assertIn("warning:", out)
        self.assertIn("'actions.save' is identical in en and ja", out)

    def test_extra_locales_are_parity_checked_and_can_be_required(self) -> None:
        vi = {"actions": {"save": "Lưu"}}
        code, out = self.check(en=EN, ja=JA, vi=vi)
        self.assertEqual(code, 1)
        self.assertIn("vi.json: missing key 'status.error'", out)

        code, out = run_checker(str(write_catalogs(self.tmp / "other" / "locales", en=EN, ja=JA)),
                                "--require", "ja,en,vi")
        self.assertEqual(code, 1)
        self.assertIn("missing vi.json", out)

    def test_discovery_skips_dependencies_and_hidden_directories(self) -> None:
        write_catalogs(self.tmp / "app" / "locales", en=EN, ja=JA)
        write_catalogs(self.tmp / "node_modules" / "lib" / "locales", en=EN)
        write_catalogs(self.tmp / ".cache" / "locales", en=EN)
        self.assertEqual(checker.discover(self.tmp), [self.tmp / "app" / "locales"])
        code, out = run_checker("--root", str(self.tmp))
        self.assertEqual(code, 0, out)

    def test_discovery_descends_below_a_catalog_directory(self) -> None:
        outer = write_catalogs(self.tmp / "app" / "locales", en=EN, ja=JA)
        nested = write_catalogs(self.tmp / "app" / "locales" / "plugin" / "locales", en=EN)
        self.assertEqual(checker.discover(self.tmp), [outer, nested])
        self.assertEqual(checker.discover(outer), [outer, nested], "a root named locales/ is a catalog too")
        code, out = run_checker("--root", str(self.tmp))
        self.assertEqual(code, 1, out)
        self.assertIn(f"{nested}: missing ja.json", out)

    def link(self, path: Path, target: str) -> Path:
        """A directory link at `path`, or a skip where this platform cannot make one."""
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"cannot create a symbolic link here: {exc}")
        return path

    def test_discovery_checks_a_catalog_directory_reached_through_a_link(self) -> None:
        """The runtimes follow `app/locales -> ../shared`, so the gate has to check it too."""
        write_catalogs(self.tmp / "shared", en=EN)
        linked = self.link(self.tmp / "app" / "locales", "../shared")
        self.assertEqual(checker.discover(self.tmp), [linked])
        code, out = run_checker("--root", str(self.tmp))
        self.assertEqual(code, 1, out)
        self.assertIn(f"{linked}: missing ja.json", out)

    def test_a_catalog_link_is_checked_wherever_it_leads(self) -> None:
        """A hidden or dependency target is not walked, but a `locales` link into
        one is still the app's catalog, so it is still checked."""
        write_catalogs(self.tmp / ".i18n", en=EN)
        write_catalogs(self.tmp / "node_modules" / "shared-i18n", en=EN)
        web = self.link(self.tmp / "web" / "locales", "../.i18n")
        api = self.link(self.tmp / "api" / "locales", "../node_modules/shared-i18n")
        self.assertEqual(checker.discover(self.tmp), [api, web])
        code, out = run_checker("--root", str(self.tmp))
        self.assertEqual(code, 1, out)
        for linked in (api, web):
            with self.subTest(link=linked.parent.name):
                self.assertIn(f"{linked}: missing ja.json", out)

    def test_discovery_walks_a_linked_directory_above_a_catalog(self) -> None:
        """`app -> ../shared-app` is walked, since the runtimes load app/locales through it,
        even though the link leads out of the root."""
        root = self.tmp / "repo"
        write_catalogs(self.tmp / "shared-app" / "locales", en=EN)
        self.link(root / "app", "../shared-app")
        self.assertEqual(checker.discover(root), [root / "app" / "locales"])
        code, out = run_checker("--root", str(root))
        self.assertEqual(code, 1, out)
        self.assertIn(f"{root / 'app' / 'locales'}: missing ja.json", out)

    def test_a_catalog_reachable_by_two_paths_is_checked_once(self) -> None:
        """A second path to a catalog, through a `locales` link or a linked parent,
        adds no second report, and a link back to the root cannot loop."""
        real = write_catalogs(self.tmp / "app" / "locales", en=EN, ja=JA)
        self.link(self.tmp / "web" / "locales", "../app/locales")
        self.link(self.tmp / "mirror", "app")
        self.link(self.tmp / "app" / "loop", "..")
        self.assertEqual(checker.discover(self.tmp), [real])
        code, out = run_checker("--root", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("i18n: 1 catalog dir(s)", out)

    def test_discovery_ends_on_link_cycles(self) -> None:
        """Each real directory is walked once. Without that, two links back to a
        parent would double the walk at every level until the OS refuses the
        path, so this runs in a subprocess with a deadline rather than in-process."""
        write_catalogs(self.tmp / "a" / "locales", en=EN, ja=JA)
        self.link(self.tmp / "a" / "b" / "l1", "..")
        self.link(self.tmp / "a" / "b" / "l2", "..")
        result = subprocess.run([sys.executable, str(CHECKER_PATH), "--root", str(self.tmp)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("i18n: 1 catalog dir(s)", result.stdout)

    def test_discovery_does_not_follow_links_into_dependencies_or_above_the_root(self) -> None:
        """A link into `node_modules` (to it, or to a package inside it) is still a
        dependency, a link into a hidden directory is still hidden, and a link to
        the root's parent would walk everything around the repository."""
        root = self.tmp / "repo"
        app = write_catalogs(root / "app" / "locales", en=EN, ja=JA)
        write_catalogs(root / "node_modules" / "lib" / "locales", en=EN)
        self.link(root / "app" / "deps", "../node_modules")
        self.link(root / "ui", "node_modules/lib")
        write_catalogs(root / ".config" / "tool" / "locales", en=EN)
        self.link(root / "cfg", ".config/tool")
        write_catalogs(self.tmp / "elsewhere" / "locales", en=EN)
        self.link(root / "up", "..")
        self.assertEqual(checker.discover(root), [app])
        code, out = run_checker("--root", str(root))
        self.assertEqual(code, 0, out)

    def test_a_repository_under_a_hidden_directory_still_follows_its_links(self) -> None:
        """Only the part of a link's target below what it shares with the root is
        inspected, so ~/.work/repo can still link to ~/.work/shared-app."""
        root = self.tmp / ".work" / "repo"
        write_catalogs(self.tmp / ".work" / "shared-app" / "locales", en=EN)
        self.link(root / "app", "../shared-app")
        self.assertEqual(checker.discover(root), [root / "app" / "locales"])
        code, out = run_checker("--root", str(root))
        self.assertEqual(code, 1, out)
        self.assertIn(f"{root / 'app' / 'locales'}: missing ja.json", out)

    def test_a_catalog_link_whose_target_is_missing_is_an_error(self) -> None:
        """The runtimes would load nothing from it, so the gate must not pass it over."""
        dangling = self.link(self.tmp / "app" / "locales", "../gone")
        self.assertEqual(checker.discover(self.tmp), [dangling])
        code, out = run_checker("--root", str(self.tmp))
        self.assertEqual(code, 1, out)
        self.assertIn(f"{dangling}: not a directory (a link to '../gone')", out)

    def test_a_json_file_that_is_not_a_locale_is_an_error(self) -> None:
        """Nothing in a catalog directory escapes the gate: a file it skipped
        could still be loaded by some runtime and fail in front of a user."""
        code, out = self.check(en=EN, ja=JA, **{"en.us": "{broken", "schema": {"type": "object"}, "ja-JP": JA})
        self.assertEqual(code, 1, out)
        for name in ("en.us.json", "schema.json", "ja-JP.json"):
            with self.subTest(file=name):
                self.assertIn(f"{name}: not a <language>.json name", out)

    def test_require_names_only_language_codes_the_runtimes_can_select(self) -> None:
        """`--require ja-JP` could never be satisfied by a catalog either runtime selects."""
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            checker.main(["--require", "ja-JP,en", str(self.tmp)])
        self.assertEqual(raised.exception.code, 2)

    def test_a_duplicate_key_is_an_error(self) -> None:
        """`json.loads` keeps only the last duplicate, so `a.x` below would vanish
        from a catalog whose source visibly holds it."""
        en = {"a": {"x": "Hello", "y": "Bye"}, "b": {"z": "Zed"}}
        ja = '{"a": {"x": "こんにちは"}, "a": {"y": "さようなら"}, "b": {"z": "ゼット", "z": "ゼッド"}}'
        code, out = self.check(en=en, ja=ja)
        self.assertEqual(code, 1, out)
        self.assertIn("duplicate key 'a'", out)
        self.assertIn("duplicate key 'b.z'", out)

    def test_a_discovery_root_that_does_not_exist_is_a_usage_error(self) -> None:
        """A misspelt --root would otherwise discover nothing and pass the gate."""
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            checker.main(["--root", str(self.tmp / "missing")])
        self.assertEqual(raised.exception.code, 2)

    def test_no_catalogs_is_not_a_failure(self) -> None:
        code, out = run_checker("--root", str(self.tmp))
        self.assertEqual(code, 0)
        self.assertIn("nothing to check", out)

    def test_a_directory_argument_that_does_not_exist_is_a_usage_error(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            checker.main([str(self.tmp / "missing")])
        self.assertEqual(raised.exception.code, 2)

    def test_the_command_line_exit_status_follows_the_findings(self) -> None:
        bad = write_catalogs(self.tmp / "locales", en=EN)
        result = subprocess.run([sys.executable, str(CHECKER_PATH), str(bad)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout)


class PythonRuntimeTests(unittest.TestCase):
    def test_normalize_locale(self) -> None:
        cases = {"ja_JP.UTF-8": "ja", "en-US": "en", "Japanese_Japan": "ja",
                 "English_United States": "en", "": None, None: None, "C": "c"}
        for tag, expected in cases.items():
            with self.subTest(tag=tag):
                self.assertEqual(runtime.normalize_locale(tag), expected)

    def test_detect_locale_precedence(self) -> None:
        env = {"APP_LANG": "en", "LANG": "ja_JP.UTF-8"}
        self.assertEqual(runtime.detect_locale("ja", env=env, os_locale=""), "ja", "explicit choice wins")
        self.assertEqual(runtime.detect_locale(None, env=env, os_locale=""), "en", "APP_LANG beats LANG")
        self.assertEqual(runtime.detect_locale(None, env={}, os_locale="Japanese_Japan"), "ja", "Windows OS locale")
        self.assertEqual(runtime.detect_locale("fr", env={}, os_locale="", default="ja"), "ja", "default last")

    def test_posix_variables_decide_as_posix_reads_them(self) -> None:
        """The first of LC_ALL, LC_MESSAGES, LANG that is set decides alone, as for
        every gettext program; scripts rely on LC_ALL=C for untranslated output.
        `default="ja"` keeps "decided English" apart from "fell back to default"."""
        cases = [
            ({"LC_ALL": "C", "LANG": "ja_JP.UTF-8"}, "en", "LC_ALL=C means untranslated"),
            ({"LC_ALL": "C.UTF-8", "LANG": "ja_JP.UTF-8"}, "en", "C.UTF-8, as containers set it"),
            ({"LC_MESSAGES": "POSIX", "LANG": "ja_JP.UTF-8"}, "en", "POSIX means untranslated"),
            ({"LC_ALL": "fr_FR.UTF-8", "LANG": "en_US.UTF-8"}, "ja", "an unsupported LC_ALL is the default, not LANG"),
            ({"LC_MESSAGES": "en_US.UTF-8", "LANG": "ja_JP.UTF-8"}, "en", "LC_MESSAGES beats LANG"),
            ({"LC_ALL": "", "LC_MESSAGES": "  ", "LANG": "en_US.UTF-8"}, "en", "an empty variable is unset"),
        ]
        for env, expected, why in cases:
            with self.subTest(why):
                self.assertEqual(runtime.detect_locale(None, env=env, os_locale="Japanese_Japan", default="ja"),
                                 expected)
        self.assertEqual(runtime.detect_locale(None, env={"LANG": "fr_FR.UTF-8"}, os_locale="Japanese_Japan"), "en",
                         "the OS locale is only asked when no POSIX variable is set")

    def test_messages_params_plurals_and_fallback(self) -> None:
        tr = runtime.Translator({"en": EN, "ja": JA}, "ja")
        self.assertEqual(tr.locale, "ja")
        self.assertEqual(tr.t("actions.save"), "保存")
        self.assertEqual(tr.t("status.error", message="timeout"), "失敗: timeout")
        self.assertEqual(tr.t("files.n", count=1), "1 件")
        tr.set_locale("en-US")
        self.assertEqual(tr.t("files.n", count=1), "1 file")
        self.assertEqual(tr.t("files.n", count=2), "2 files")
        self.assertEqual(tr.t("no.such.key"), "no.such.key")

    def test_a_key_missing_from_the_active_locale_falls_back(self) -> None:
        tr = runtime.Translator({"en": {"only": {"en": "English only"}}, "ja": {}}, "ja")
        self.assertEqual(tr.t("only.en"), "English only")

    def test_a_fallback_plural_follows_the_fallback_locales_rule(self) -> None:
        """Japanese active, the plural only in English: the English message must be
        chosen by the English rule — "1 file", not "1 files"."""
        tr = runtime.Translator({"en": EN, "ja": {"actions": {"save": "保存"}}}, "ja")
        self.assertEqual(tr.t("files.n", count=1), "1 file")
        self.assertEqual(tr.t("files.n", count=2), "2 files")
        with_ja_plural = runtime.Translator({"en": EN, "ja": JA}, "ja")
        self.assertEqual(with_ja_plural.t("files.n", count=1), "1 件", "a plural the active catalog has is taken from it")

    def test_count_must_be_a_number(self) -> None:
        tr = runtime.Translator({"en": EN, "ja": JA}, "en")
        for bad in ("1", True, 1j):
            with self.subTest(count=bad), self.assertRaises(TypeError):
                tr.t("files.n", count=bad)
        self.assertEqual(tr.t("files.n", count=Fraction(3)), "3 files", "any real number counts")
        self.assertEqual(tr.t("files.n", count=Decimal("1")), "1 file", "Decimal, as from money or a database")
        self.assertEqual(tr.t("files.n", count=Decimal("2")), "2 files")
        self.assertEqual(tr.t("files.n", count=Decimal("NaN")), "NaN files", "NaN is never one, as in Intl")
        self.assertEqual(tr.t("files.n", count=Decimal("sNaN")), "sNaN files", "a signalling NaN must not raise")
        self.assertEqual(tr.t("actions.save", count=None), "Save", "None means no count")

    def test_plural_category_follows_cldr_at_the_edges(self) -> None:
        """English "one" is 1 or -1 (CLDR takes the absolute value); Japanese never has it."""
        expected = {-2: "other", -1: "one", 0: "other", 1: "one", 1.5: "other", 2: "other", 21: "other"}
        for count, category in expected.items():
            with self.subTest(count=count):
                self.assertEqual(runtime.plural_category("en", count), category)
                self.assertEqual(runtime.plural_category("ja", count), "other")

    def test_set_locale_rejects_an_unsupported_locale(self) -> None:
        tr = runtime.Translator({"en": EN, "ja": JA}, "ja")
        with self.assertRaises(ValueError):
            tr.set_locale("fr")
        self.assertEqual(tr.locale, "ja")

    def test_placeholders_are_never_format_evaluated(self) -> None:
        self.assertEqual(runtime.format_message("{a} {b}", {"a": 1}), "1 {b}")
        self.assertEqual(runtime.format_message("{0} {a.__class__} {", {"a": 1}), "{0} {a.__class__} {")

    def test_from_dir_reads_the_starter_catalogs(self) -> None:
        tr = runtime.Translator.from_dir(STARTER_LOCALES, "ja")
        self.assertEqual(set(tr.locales), {"ja", "en"})
        self.assertEqual(tr.t("actions.save"), "保存")
        self.assertEqual(tr.t("files.processed", count=3), "3 件のファイルを処理しました")

    def test_from_dir_loads_only_what_the_checker_checks(self) -> None:
        """A JSON file the checker would not accept as a catalog is not one here
        either, so a broken stray file cannot crash the app at startup."""
        with tempfile.TemporaryDirectory() as directory:
            locales = write_catalogs(Path(directory) / "locales", en=EN, ja=JA)
            (locales / "en.us.json").write_text("{broken", encoding="utf-8")
            (locales / "schema.json").write_text('{"type": "object"}', encoding="utf-8")
            (locales / "ja-JP.json").write_text(json.dumps(JA, ensure_ascii=False), encoding="utf-8")
            tr = runtime.Translator.from_dir(locales, "ja")
        self.assertEqual(set(tr.locales), {"ja", "en"})

    def test_regional_catalog_names_fail_loudly_instead_of_never_being_chosen(self) -> None:
        """ja-JP.json would load under "ja-JP" while detection selects "ja", so the app
        would show raw keys or silently fall back to English. It is refused instead."""
        with tempfile.TemporaryDirectory() as directory:
            locales = write_catalogs(Path(directory) / "locales", **{"ja-JP": JA, "en-US": EN})
            with self.assertRaises(FileNotFoundError):
                runtime.Translator.from_dir(locales, "ja-JP")

    def test_format_date(self) -> None:
        day = date(2026, 9, 25)
        self.assertEqual(runtime.format_date(day, "ja"), "2026年9月25日")
        self.assertEqual(runtime.format_date(day, "en"), "September 25, 2026")
        self.assertEqual(runtime.format_date(day, "ja", "short"), "2026/09/25")
        self.assertEqual(runtime.format_date(day, "en", "short"), "2026-09-25")
        with self.assertRaises(ValueError):
            runtime.format_date(day, "en", "medium")


class RuntimeAgreementTests(unittest.TestCase):
    """One catalog serves both runtimes and one checker guards it, so all three
    must agree on what a placeholder is."""

    def test_placeholder_pattern_is_identical_everywhere(self) -> None:
        source = WEB_RUNTIME_PATH.read_text(encoding="utf-8")
        match = re.search(r"const PLACEHOLDER = /(.+)/g", source)
        self.assertIsNotNone(match, "PLACEHOLDER not found in i18n.ts")
        self.assertEqual(checker.PLACEHOLDER.pattern, runtime.PLACEHOLDER.pattern)
        self.assertEqual(match.group(1), runtime.PLACEHOLDER.pattern)

    def test_the_runtime_loads_exactly_the_files_the_checker_accepts(self) -> None:
        self.assertEqual(checker.LOCALE_FILE.pattern, runtime.LOCALE_FILE.pattern)

    def test_both_runtimes_ship_the_same_locales(self) -> None:
        source = WEB_RUNTIME_PATH.read_text(encoding="utf-8")
        match = re.search(r"export const LOCALES = \[(.+)\] as const", source)
        self.assertIsNotNone(match)
        web_locales = tuple(re.findall(r'"(\w+)"', match.group(1)))
        self.assertEqual(web_locales, runtime.SUPPORTED_LOCALES)
        self.assertEqual(web_locales, checker.DEFAULT_REQUIRED)


def node_runs_typescript() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "probe.mts"
        probe.write_text("const n: number = 1\nconsole.log(n)\n", encoding="utf-8")
        result = subprocess.run([node, "--experimental-strip-types", str(probe)], capture_output=True, text=True)
        return result.returncode == 0


def run_web(script: str, **env: str) -> object:
    """Run a TypeScript snippet against the web runtime and return the JSON it prints."""
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "probe.mts"
        probe.write_text(
            f"import * as i18n from {json.dumps(WEB_RUNTIME_PATH.as_uri())}\n{script}", encoding="utf-8"
        )
        result = subprocess.run(["node", "--experimental-strip-types", str(probe)],
                                capture_output=True, text=True, env={**os.environ, **env})
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


@unittest.skipUnless(node_runs_typescript(), "needs Node 22.6+ (TypeScript type stripping); CI installs it")
class WebRuntimeTests(unittest.TestCase):
    def test_web_runtime_behaves_like_the_python_one(self) -> None:
        result = subprocess.run(
            ["node", "--experimental-strip-types", str(WEB_CHECK)],
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_both_runtimes_choose_the_same_plural_form(self) -> None:
        """One catalog serves both runtimes, so the same count must pick the same form in each."""
        catalog = {"n_one": "one", "n_other": "other"}
        counts = [-2, -1, 0, 1, 1.5, 2, 21, 100]
        script = (
            f"import {{ createTranslator }} from {json.dumps(WEB_RUNTIME_PATH.as_uri())}\n"
            f"const catalog = {json.dumps(catalog)}\n"
            f"const out = {{}}\n"
            f"for (const locale of ['ja', 'en']) {{\n"
            f"  const t = createTranslator({{ ja: catalog, en: catalog }}, locale)\n"
            f"  out[locale] = {json.dumps(counts)}.map((count) => t('n', {{ count }}))\n"
            f"}}\n"
            f"console.log(JSON.stringify(out))\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "plural_parity.mts"
            probe.write_text(script, encoding="utf-8")
            result = subprocess.run(["node", "--experimental-strip-types", str(probe)],
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        web = json.loads(result.stdout)
        for locale in ("ja", "en"):
            tr = runtime.Translator({"ja": catalog, "en": catalog}, locale)
            with self.subTest(locale=locale):
                self.assertEqual([tr.t("n", count=count) for count in counts], web[locale])

    def test_both_runtimes_choose_a_fallback_plural_by_the_fallback_rule(self) -> None:
        """Japanese active, the plural only in the English fallback: both must say "1 file"."""
        catalogs = {"ja": {}, "en": {"n_one": "{count} file", "n_other": "{count} files"}}
        counts = [-1, 0, 1, 2]
        script = (
            f"import {{ createTranslator }} from {json.dumps(WEB_RUNTIME_PATH.as_uri())}\n"
            f"const t = createTranslator({json.dumps(catalogs)}, 'ja')\n"
            f"console.log(JSON.stringify({json.dumps(counts)}.map((count) => t('n', {{ count }}))))\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "fallback_plural.mts"
            probe.write_text(script, encoding="utf-8")
            result = subprocess.run(["node", "--experimental-strip-types", str(probe)],
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        tr = runtime.Translator(catalogs, "ja")
        self.assertEqual([tr.t("n", count=count) for count in counts], json.loads(result.stdout))
        self.assertEqual(json.loads(result.stdout)[2], "1 file")

    def test_both_runtimes_treat_object_member_names_as_ordinary_keys(self) -> None:
        """A key named `__proto__` or `constructor` is a key like any other, and a
        missing one degrades to its name instead of reaching an Object member."""
        catalog = {"__proto__": "proto text", "constructor": "ctor text"}
        keys = ["__proto__", "constructor", "toString", "hasOwnProperty", "valueOf"]
        web = run_web(
            f"const en = JSON.parse({json.dumps(json.dumps(catalog))})\n"
            f"const t = i18n.createTranslator({{ ja: {{}}, en }}, 'en')\n"
            f"console.log(JSON.stringify({json.dumps(keys)}.map((key) => t(key))))\n"
        )
        tr = runtime.Translator({"ja": {}, "en": catalog}, "en")
        self.assertEqual(web, [tr.t(key) for key in keys])
        self.assertEqual(web[:3], ["proto text", "ctor text", "toString"])

    def test_both_runtimes_format_a_calendar_date_the_same_west_of_utc(self) -> None:
        """A date-only value is the same day in Los Angeles as in Python's `date`."""
        days = ["2026-09-25", "2026-01-01", "2024-02-29", "0001-01-01", "9999-12-31"]
        cases = [(day, locale, style) for day in days for locale in ("ja", "en") for style in ("long", "short")]
        web = run_web(
            f"const cases = {json.dumps(cases)}\n"
            "console.log(JSON.stringify(cases.map(([day, locale, style]) => i18n.formatDate(day, locale, style))))\n",
            TZ="America/Los_Angeles",
        )
        expected = [runtime.format_date(date.fromisoformat(day), locale, style) for day, locale, style in cases]
        self.assertEqual(web, expected)


if __name__ == "__main__":
    unittest.main()
