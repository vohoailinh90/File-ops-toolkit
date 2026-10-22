"""Copy one file into the destination without ever replacing a file that is already there."""

from __future__ import annotations

import filecmp
import os
import shutil
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
        part = candidate.with_name(candidate.name + ".part")
        try:
            with open(source, "rb") as reader, open(part, "xb") as writer:
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
    """Move `part` to `final` only if `final` does not exist (os.replace would silently overwrite on POSIX)."""
    try:
        os.link(part, final)
    except FileExistsError:
        raise
    except OSError:  # a filesystem without hard links
        if final.exists():
            raise FileExistsError(str(final))
        os.replace(part, final)
        return
    os.unlink(part)


def _discard(part: Path) -> None:
    try:
        part.unlink()
    except OSError:
        pass
