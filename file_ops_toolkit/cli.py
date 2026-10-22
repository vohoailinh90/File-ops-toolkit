"""Command line: `serve` opens the web UI (the default); `run` does a list without a browser."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .excel import ExcelError, read_jobs
from .i18n import Translator
from .report import report_csv
from .runner import LAYOUTS, DestinationError, Options, run_job

LOCALES_DIR = Path(__file__).resolve().parent / "locales"


def build_parser(tr: Translator) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="file-ops-toolkit", description=tr.t("cli.description"))
    parser.add_argument("--lang", choices=tr.locales, help=tr.t("cli.lang_help"))
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help=tr.t("cli.serve_help"))
    serve.add_argument("--port", type=int, default=8765, help=tr.t("cli.port_help"))
    serve.add_argument("--no-browser", action="store_true", help=tr.t("cli.no_browser_help"))
    run = sub.add_parser("run", help=tr.t("cli.run_help"))
    run.add_argument("excel", help=tr.t("cli.excel_help"))
    run.add_argument("dest", help=tr.t("cli.dest_help"))
    run.add_argument("--no-recursive", action="store_true", help=tr.t("cli.no_recursive_help"))
    run.add_argument("--layout", choices=LAYOUTS, default="flat", help=tr.t("cli.layout_help"))
    run.add_argument("--report", help=tr.t("cli.report_help"))
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    tr = Translator.from_dir(LOCALES_DIR, locale=_lang_from(argv))
    args = build_parser(tr).parse_args(argv)
    if args.lang:
        tr.set_locale(args.lang)
    if args.command in (None, "serve"):
        from .server import serve
        serve(port=getattr(args, "port", 8765), open_browser=not getattr(args, "no_browser", False))
        return 0
    return _run(args, tr)


def _lang_from(argv: list[str]) -> str | None:
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def _run(args: argparse.Namespace, tr: Translator) -> int:
    try:
        rows = read_jobs(args.excel)
    except ExcelError as exc:
        print(tr.t("errors." + exc.code), file=sys.stderr)
        return 2
    except OSError as exc:
        print(tr.t("errors.cannot_open", message=str(exc)), file=sys.stderr)
        return 2
    try:
        results = run_job(rows, args.dest, Options(recursive=not args.no_recursive, layout=args.layout),
                          on_result=lambda r: print(f"[{r.row}] {tr.t('status.' + r.status)} {r.file_name}"))
    except DestinationError as exc:
        print(tr.t("errors." + exc.code), file=sys.stderr)
        return 2
    copied = sum(1 for r in results for f in r.files if f.outcome == "copied")
    problems = sum(1 for r in results if r.status not in ("copied", "already_copied") or r.warning)
    print(tr.t("cli.summary", count=copied, rows=len(results), problems=problems))
    if args.report:
        Path(args.report).write_bytes(report_csv(results, tr))
    return 0 if not problems else 1
