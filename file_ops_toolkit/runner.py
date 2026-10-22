"""Run a job list: for each row open its folder, find the named files, copy them to the destination."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .copier import copy_without_overwrite
from .excel import JobRow
from .finder import FolderError, display_name, find_matches, folder_key, scan_folder
from .paths import safe_dir_name

LAYOUTS = ("flat", "by_folder")


@dataclass(frozen=True)
class Options:
    recursive: bool = True  # look in sub-folders of each row's folder too
    layout: str = "flat"  # "flat": one destination folder; "by_folder": a sub-folder per source folder


@dataclass
class FileResult:
    source: str
    dest: str = ""
    outcome: str = ""  # "copied" | "already_there" | "error"
    detail: str = ""


@dataclass
class RowResult:
    row: int
    address: str
    file_name: str
    status: str  # a catalog key under `status`
    files: list[FileResult] = field(default_factory=list)
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


ProgressCallback = Callable[[RowResult], None]


class DestinationError(ValueError):
    """The destination cannot be used. `code` is a catalog key under `errors`."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def check_destination(rows: list[JobRow], dest: str, layout: str = "flat") -> None:
    """Refuse any folder a run would write to that is inside (or equal to) a folder the list reads from.

    That is the destination itself and, for the by-folder layout, every sub-folder the layout adds to it,
    each compared after symlinks and junctions are resolved: writing there would write into the source.
    """
    sources = {_comparable(job.address) for job in rows if not job.error}
    targets = {_comparable(dest)}
    if layout == "by_folder":
        targets |= {_comparable(os.path.join(dest, _by_folder_name(job.address))) for job in rows if not job.error}
    for target in targets:
        current = target
        while True:  # the target itself, then each parent: a source anywhere on the way makes it inside
            if current in sources:
                raise DestinationError("dest_inside_source")
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent


def _by_folder_name(address: str) -> str:
    return safe_dir_name(display_name(address))


def _comparable(path: str) -> str:
    """A path in one spelling: absolute, aliases resolved (also below folders that do not exist yet), no case."""
    return os.path.normcase(os.path.realpath(path)).rstrip("\\/")


def run_job(rows: list[JobRow], dest: str, options: Options = Options(),
            on_result: ProgressCallback | None = None,
            cancel: threading.Event | None = None) -> list[RowResult]:
    """Process every row; the result list is in Excel row order. A cancelled run keeps what it finished."""
    if options.layout not in LAYOUTS:
        raise ValueError(f"unknown layout {options.layout!r}")
    check_destination(rows, dest, options.layout)
    cancel = cancel or threading.Event()
    results: dict[int, RowResult] = {}

    def finish(result: RowResult) -> None:
        results[result.row] = result
        if on_result is not None:
            on_result(result)

    runnable: dict[str, list[JobRow]] = {}
    for job in rows:
        if job.error:
            finish(RowResult(job.row, job.address, job.file_name, job.error))
        else:
            runnable.setdefault(folder_key(job.address), []).append(job)

    for group in runnable.values():  # one folder at a time: its index is dropped before the next walk
        if cancel.is_set():
            break
        _run_folder(group, dest, options, finish, cancel)
    return [results[number] for number in sorted(results)]


def _run_folder(group: list[JobRow], dest: str, options: Options,
                finish: ProgressCallback, cancel: threading.Event) -> None:
    address = group[0].address
    try:
        index = scan_folder(address, options.recursive, cancel=cancel)
    except FolderError as exc:
        for job in group:
            finish(RowResult(job.row, job.address, job.file_name, exc.code))
        return
    if cancel.is_set():
        return
    target = str(Path(dest) / _by_folder_name(address)) if options.layout == "by_folder" else dest
    for job in group:
        if cancel.is_set():
            return
        finish(_run_row(job, index, target))


def _run_row(job: JobRow, index, target: str) -> RowResult:
    matches = find_matches(index, job.file_name)
    result = RowResult(job.row, job.address, job.file_name, "not_found")
    for source in matches:
        try:
            outcome = copy_without_overwrite(source, target)
            result.files.append(FileResult(source, outcome.dest, "already_there" if outcome.already_there else "copied"))
        except OSError as exc:
            result.files.append(FileResult(source, "", "error", exc.strerror or type(exc).__name__))
    if any(f.outcome == "error" for f in result.files):
        result.status = "error"
        result.detail = next(f.detail for f in result.files if f.outcome == "error")
    elif any(f.outcome == "copied" for f in result.files):
        result.status = "copied"
    elif result.files:
        result.status = "already_copied"
    return result


class JobRun:
    """One run in a background thread, with the state the UI polls. Thread-safe."""

    def __init__(self, rows: list[JobRow], dest: str, options: Options):
        self.rows, self.dest, self.options = rows, dest, options
        self.state = "idle"  # idle | running | done | cancelled | failed
        self.error = ""
        self.started_at = 0.0
        self.finished_at = 0.0
        self._results: list[RowResult] = []
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self.state == "running":
                raise RuntimeError("already running")
            self.state, self.started_at = "running", time.time()
        self._thread = threading.Thread(target=self._work, name="file-ops-run", daemon=True)
        self._thread.start()

    def _work(self) -> None:
        try:
            Path(self.dest).mkdir(parents=True, exist_ok=True)
            run_job(self.rows, self.dest, self.options, self._record, self._cancel)
            with self._lock:  # `_results` is append-only: a poller's `since` index must stay valid to the end
                self.state = "cancelled" if self._cancel.is_set() else "done"
        except Exception as exc:  # surfaced to the UI as a failed run rather than a dead thread
            with self._lock:
                self.state, self.error = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            self.finished_at = time.time()

    def _record(self, result: RowResult) -> None:
        with self._lock:
            self._results.append(result)

    def cancel(self) -> None:
        self._cancel.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def snapshot(self, since: int = 0) -> dict:
        """State, counters and the results from index `since` on (the UI asks only for what is new)."""
        with self._lock:
            results = list(self._results)
            state, error = self.state, self.error
        counts: dict[str, int] = {}
        copied_files = 0
        for result in results:
            counts[result.status] = counts.get(result.status, 0) + 1
            copied_files += sum(1 for f in result.files if f.outcome == "copied")
        return {
            "state": state,
            "error": error,
            "total": len(self.rows),
            "done": len(results),
            "counts": counts,
            "copied_files": copied_files,
            "next": len(results),
            "results": [r.as_dict() for r in results[since:]],
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 1) if self.started_at else 0,
        }

    def results(self) -> list[RowResult]:
        with self._lock:
            return sorted(self._results, key=lambda r: r.row)


def default_destination() -> str:
    return str(Path.home() / "Downloads" / "fetched-files") if os.path.isdir(Path.home() / "Downloads") \
        else str(Path.home() / "fetched-files")
