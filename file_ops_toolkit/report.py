"""The run's result as a CSV that Japanese Excel opens correctly (UTF-8 with BOM)."""

from __future__ import annotations

import csv
import io

from .i18n import Translator
from .runner import RowResult


def _safe(cell: str) -> str:
    """Excel runs a cell that starts with = + - @ (or a tab/CR) as a formula; file names come from a share."""
    return "'" + cell if cell[:1] in ("=", "+", "-", "@", "\t", "\r") else cell


def report_csv(results: list[RowResult], tr: Translator) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([tr.t("report.row"), tr.t("report.address"), tr.t("report.file_name"),
                     tr.t("report.status"), tr.t("report.files"), tr.t("report.detail")])
    for r in results:
        files = "; ".join(f.dest or f.source for f in r.files)
        writer.writerow([r.row, _safe(r.address), _safe(r.file_name), tr.t(f"status.{r.status}"), _safe(files),
                         _safe(r.detail)])
    return out.getvalue().encode("utf-8-sig")
