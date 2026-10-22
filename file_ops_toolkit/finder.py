"""Find the files a folder holds under a given name. Reads only; nothing here writes."""

from __future__ import annotations

import os
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


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
    by_name: dict[str, list[str]] = field(default_factory=dict)
    by_stem: dict[str, list[str]] = field(default_factory=dict)
    unreadable: list[str] = field(default_factory=list)  # sub-folders that could not be opened


def scan_folder(root: str, recursive: bool = True, exclude: str | None = None,
                cancel: threading.Event | None = None) -> FolderIndex:
    """Index the files under `root` once, so many rows pointing at it cost one walk of the share.

    `exclude` is a directory never entered (the destination, so a re-run never re-finds its own copies).
    """
    try:
        if not os.path.isdir(root):
            raise FolderError("folder_missing" if not os.path.exists(root) else "folder_not_a_directory")
    except OSError as exc:
        raise FolderError("folder_unreadable") from exc
    skip = _key(exclude) if exclude else None
    index = FolderIndex(root=root)
    pending = [root]
    first = True
    while pending:
        if cancel is not None and cancel.is_set():
            break
        folder = pending.pop()
        try:
            _scan_dir(folder, index, pending, recursive, skip)
        except OSError as exc:
            if first:
                raise FolderError("folder_unreadable") from exc
            index.unreadable.append(folder)
        first = False
    for paths in list(index.by_name.values()) + list(index.by_stem.values()):
        paths.sort()
    return index


def _scan_dir(folder: str, index: FolderIndex, pending: list[str], recursive: bool, skip: str | None) -> None:
    """Add the files of one directory to the index and queue its sub-directories."""
    with os.scandir(folder) as entries:
        for entry in entries:
            if entry.name.startswith("~$"):  # Office's lock file for an open document
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if recursive and _key(entry.path) != skip:
                        pending.append(entry.path)
                elif entry.is_file():
                    _add(index, entry.name, entry.path)
            except OSError:
                index.unreadable.append(entry.path)


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _add(index: FolderIndex, name: str, path: str) -> None:
    index.by_name.setdefault(fold(name), []).append(path)
    stem = os.path.splitext(name)[0]
    if stem and stem != name:
        index.by_stem.setdefault(fold(stem), []).append(path)


def find_matches(index: FolderIndex, name: str) -> list[str]:
    """Every file named `name`; when none is, every file whose name without extension is `name`."""
    key = fold(name)
    return list(index.by_name.get(key) or index.by_stem.get(key) or [])


def folder_key(path: str) -> str:
    return fold(os.path.normcase(path).rstrip("\\/") or path)


def display_name(path: str) -> str:
    return Path(path.replace("\\", "/")).name
