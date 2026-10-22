"""The run's result as a CSV that Japanese Excel opens correctly (UTF-8 with BOM)."""

from __future__ import annotations

import csv
import io

from .i18n import Translator
from .runner import RowResult


def report_csv(results: list[RowResult], tr: Translator) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([tr.t("report.row"), tr.t("report.address"), tr.t("report.file_name"),
                     tr.t("report.status"), tr.t("report.files"), tr.t("report.detail")])
    for r in results:
        files = "; ".join(f.dest or f.source for f in r.files)
        writer.writerow([r.row, r.address, r.file_name, tr.t(f"status.{r.status}"), files, r.detail])
    return out.getvalue().encode("utf-8-sig")
