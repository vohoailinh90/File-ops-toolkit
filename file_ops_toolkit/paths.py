"""Turn what an Excel cell holds into a folder path, and judge file names from column B.

Pure string work: nothing here touches the disk, so the Windows forms (UNC shares,
`file://` links) are testable on any machine.
"""

from __future__ import annotations

import os
import re
from urllib.parse import unquote

_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]+://")
_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
_FORBIDDEN_IN_DIR_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class AddressError(ValueError):
    """The address cannot be a folder this tool can open. `code` is a catalog key under `status`."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def looks_like_path(text: str) -> bool:
    """A UNC share, a drive path or a file: link: the forms a folder address takes."""
    s = text.strip().strip("\"'")
    return s.startswith("\\\\") or bool(_DRIVE.match(s)) or s.lower().startswith("file:")


def normalize_address(raw: str) -> str:
    """The folder path a cell means, in Windows spelling for UNC and file: forms."""
    s = raw.strip().strip("\"'").strip()
    if not s:
        raise AddressError("missing_address")
    if s.lower().startswith("file:"):
        return _from_file_url(s)
    if _SCHEME.match(s):
        raise AddressError("unsupported_link")
    if s.startswith("//") and not s.startswith("///"):
        s = s.replace("/", "\\")  # //server/share written with forward slashes
    if not (looks_like_path(s) or os.path.isabs(s)):
        raise AddressError("invalid_address")  # plain text or a relative path would be read against the app's folder
    return s


def _from_file_url(url: str) -> str:
    rest = url[5:].split("#", 1)[0].split("?", 1)[0]
    rest = unquote(rest)
    if rest.startswith("//"):
        rest = rest[2:]
        if rest.startswith("/"):  # file:///...
            rest = rest[1:]
            if _DRIVE.match(rest):  # file:///C:/dir
                return rest.replace("/", "\\")
            if rest.startswith("\\\\"):  # file:///\\server\share
                return rest
            return "\\\\" + rest.lstrip("/").replace("/", "\\")  # file:////server/share
        host, _, tail = rest.partition("/")
        if host.lower() in ("", "localhost"):
            return tail.replace("/", "\\") if _DRIVE.match(tail) else "\\" + tail.replace("/", "\\")
        return "\\\\" + host + "\\" + tail.replace("/", "\\")  # file://server/share/dir
    if _DRIVE.match(rest.lstrip("/")):
        return rest.lstrip("/").replace("/", "\\")
    return rest


def clean_file_name(raw: str) -> str:
    """Column B's name, trimmed. Raises AddressError for a value that is not a plain file name."""
    name = raw.strip()
    if not name:
        raise AddressError("missing_name")
    if "/" in name or "\\" in name or "\x00" in name or name in (".", ".."):
        raise AddressError("invalid_name")
    return name


def safe_dir_name(name: str) -> str:
    """A source folder's own name made safe to reuse as a destination subfolder."""
    cleaned = _FORBIDDEN_IN_DIR_NAME.sub("_", name).strip(" .")
    return cleaned or "folder"
