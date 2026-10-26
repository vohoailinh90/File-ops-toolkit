"""Find the files a folder holds whose name contains a given name. Reads only; nothing here writes."""

from __future__ import annotations

import os
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


# What counts as a file extension: a dot, a letter, then letters or digits (so ".pdf", but not the ".2" of "v1.2").
_EXTENSION = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,7}")


class FolderError(Exception):
    """A folder cannot be scanned. `code` is a catalog key under `status`."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def fold(name: str) -> str:
    """Windows compares names without case; macOS may hand back decomposed Unicode."""
    return unicodedata.normalize("NFC", name).casefold()


@dataclass
class FolderIndex:
    root: str
    files: list[tuple[str, str, str]] = field(default_factory=list)  # (folded stem, folded extension, path)
    unreadable: list[str] = field(default_factory=list)  # sub-folders that could not be opened


def scan_folder(root: str, recursive: bool = True, cancel: threading.Event | None = None) -> FolderIndex:
    """Index the files under `root` once, so many rows pointing at it cost one walk of the share."""
    try:
        if not os.path.isdir(root):
            raise FolderError("folder_missing" if not os.path.exists(root) else "folder_not_a_directory")
    except OSError as exc:
        raise FolderError("folder_unreadable") from exc
    index = FolderIndex(root=root)
    pending = [root]
    first = True
    while pending:
        if cancel is not None and cancel.is_set():
            break
        folder = pending.pop()
        try:
            _scan_dir(folder, index, pending, recursive)
        except OSError as exc:
            if first:
                raise FolderError("folder_unreadable") from exc
            index.unreadable.append(folder)
        first = False
    index.files.sort(key=lambda entry: entry[2])
    return index


def _scan_dir(folder: str, index: FolderIndex, pending: list[str], recursive: bool) -> None:
    """Add the files of one directory to the index and queue its sub-directories."""
    with os.scandir(folder) as entries:
        for entry in entries:
            if entry.name.startswith("~$"):  # Office's lock file for an open document
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if recursive:
                        pending.append(entry.path)
                elif entry.is_file():
                    _add(index, entry.name, entry.path)
            except OSError:
                index.unreadable.append(entry.path)


def split_name(name: str) -> tuple[str, str]:
    """A file name as (stem, extension). A trailing ".2" (of "Report_v1.2") is part of the stem, not an extension."""
    stem, extension = os.path.splitext(name)
    if _EXTENSION.fullmatch(extension):
        return stem, extension
    return name, ""


def _add(index: FolderIndex, name: str, path: str) -> None:
    stem, extension = split_name(name)
    index.files.append((fold(stem), fold(extension), path))


def find_matches(index: FolderIndex, name: str) -> list[str]:
    """Every file whose name contains `name`, so "Report_0128" finds Report_0128_ProjectX.pdf.

    The test is a plain, case-insensitive substring test on the file's own name (never a wildcard or a path).
    A name with an extension ("Report_0128.pdf") also needs that same extension, so it finds
    "Report_0128_ProjectX.pdf" but never "Report_0128.pdf.bak"; a name without one matches any extension.
    """
    stem, extension = split_name(name)
    needle, wanted = fold(stem), fold(extension)
    if not needle:
        return []  # an empty name would be "contained" by every file
    return [path for file_stem, file_extension, path in index.files
            if needle in file_stem and (not wanted or file_extension == wanted)]


def display_name(path: str) -> str:
    return Path(path.replace("\\", "/")).name
