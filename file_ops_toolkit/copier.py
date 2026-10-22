"""Copy one file into the destination without ever replacing a file that is already there."""

from __future__ import annotations

import filecmp
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_RENAMES = 999


@dataclass(frozen=True)
class CopyOutcome:
    dest: str
    already_there: bool  # an identical copy from an earlier run, so nothing was written


def copy_without_overwrite(src: str, dest_dir: str) -> CopyOutcome:
    """Copy `src` into `dest_dir` as `name`, `name (2)`, ... and never touch an existing file.

    A file with the same size, modification time and bytes is the copy of an earlier run: it is
    reported, not duplicated, so running the same list twice is safe. Any other file with the name is a
    different file, and the new one takes the next free name. `src` is only read.
    """
    source = Path(src)
    target_dir = Path(dest_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stat = source.stat()
    for attempt in range(1, MAX_RENAMES + 1):
        candidate = target_dir / (source.name if attempt == 1 else _numbered(source.name, attempt))
        if candidate.exists():
            if _same_file(source, candidate, stat):
                return CopyOutcome(str(candidate), True)
            continue
        part: Path | None = None  # set only once this call has created it, so only this call ever deletes it
        try:
            fd, part_name = tempfile.mkstemp(dir=target_dir, prefix=candidate.name + ".", suffix=".part")
            part = Path(part_name)
            with os.fdopen(fd, "wb") as writer, open(source, "rb") as reader:
                shutil.copyfileobj(reader, writer, length=1024 * 1024)
            shutil.copystat(source, part)
            _publish(part, candidate)
        except FileExistsError:
            _discard(part)
            continue  # another process took the name between the check and the write
        except BaseException:
            _discard(part)
            raise
        return CopyOutcome(str(candidate), False)
    raise FileExistsError(f"no free name for {source.name} in {target_dir}")


def _numbered(name: str, number: int) -> str:
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        return f"{name} ({number})"
    return f"{stem} ({number}).{ext}"


def _same_file(source: Path, candidate: Path, src_stat: os.stat_result) -> bool:
    """Size and time are the cheap filter; the byte comparison is what makes "same" true."""
    try:
        found = candidate.stat()
        if found.st_size != src_stat.st_size or int(found.st_mtime) != int(src_stat.st_mtime):
            return False
        return filecmp.cmp(source, candidate, shallow=False)
    except OSError:
        return False


def _publish(part: Path, final: Path) -> None:
    """Give `part` its final name, failing with FileExistsError if `final` exists, with no window to overwrite it.

    A hard link is atomic and never replaces. Where the filesystem has none, Windows' rename refuses an
    existing target; elsewhere the final file is created exclusively (`xb`) and filled from `part`, which is
    the one way left that cannot replace a file another process created in the meantime.
    """
    try:
        os.link(part, final)
    except FileExistsError:
        raise
    except OSError:  # a filesystem without hard links
        if os.name == "nt":
            os.rename(part, final)  # raises FileExistsError when `final` exists
            return
        _fill_exclusively(part, final)
        return
    os.unlink(part)


def _fill_exclusively(part: Path, final: Path) -> None:
    with open(final, "xb") as writer:  # ours from here on: a failure below removes it again
        try:
            with open(part, "rb") as reader:
                shutil.copyfileobj(reader, writer, length=1024 * 1024)
            shutil.copystat(part, final)
        except BaseException:
            writer.close()
            _discard(final)
            raise
    os.unlink(part)


def _discard(part: Path | None) -> None:
    if part is None:
        return
    try:
        part.unlink()
    except OSError:
        pass
