#!/usr/bin/env python3
"""Status line showing what a session is actually spending.

Reads the status line payload on stdin and prints one line: model, workspace,
context remaining, rate-limit headroom, prompt-cache warmth, session cost.

Context and rate limits are the two ways a run dies mid-task, and the prompt
cache is the multiplier that makes restarting one expensive — a cold restart
re-reads its whole context at full price plus a cache write, where a warm
session reads it at ~0.1x. All three are in the payload; none of them are
visible to the model. Putting them on screen is what makes stopping deliberate.

Everything here is defensive on purpose: the payload is written by a different
program on a different release cadence, so every field is treated as optional
and every value as possibly the wrong type. A status line that raises is worse
than one that renders half the numbers.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

RESET = "\033[0m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
SEP = f" {DIM}·{RESET} "

# Show when a five-hour window resets only once it is close enough to matter.
RESET_TIME_AT = 60
# A name from the payload should not push the numbers off the right edge.
MAX_LABEL = 40

# Only this payload carries the context window's real size; the hook payloads do not. The status line leaves the
# size where scripts/hooks/session_budget.py looks for it, so a 1M-context session is measured against 1M and not
# against that script's 200K default. One file per session, named by its id and holding the size in tokens, so no
# two status lines ever read and rewrite the same file. Keep these four in step with session_budget.py (a test
# asserts it).
WINDOW_STATE = ("artifacts", "handoff", "context-window")
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
MIN_WINDOW_TOKENS = 1_000
MAX_WINDOW_TOKENS = 100_000_000
# One checkout can host many sessions over time; the newest few (by when their status line last drew) are kept.
MAX_RECORDED_SESSIONS = 32


def paint(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


def rejected(field: str, reason: str) -> None:
    """Discard a value and say why, per the contract in docs/session-budget.md.

    Only a value that was *present* and unusable is worth a line. An absent
    field is the normal case on most plans and would drown the signal.
    """
    if field:
        note(f"ignored {field}: {reason}")
    return None


def number(value: Any, field: str = "") -> float | None:
    """Return a usable percentage/amount, or None.

    Two payload values look numeric to `isinstance` but are not: `True` is an
    `int` in Python, and `json.loads` accepts `NaN`/`Infinity` by default, which
    would otherwise reach `round()` and take the whole line down.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return rejected(field, f"{type(value).__name__} is not a number")
    try:
        value = float(value)
    except (OverflowError, ValueError):
        # An int too large for a float still has to cost only its own segment.
        return rejected(field, "too large to be a number")
    if not math.isfinite(value):
        return rejected(field, "not a finite number")
    return value


def one_line(text: Any) -> str:
    """Flatten a payload string into something a single-line widget can hold.

    Newlines and escape sequences in a payload string would split or repaint
    the status line, so they are dropped rather than rendered.
    """
    flattened = "".join(ch for ch in str(text) if ch.isprintable())
    return flattened[:MAX_LABEL]


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def by_headroom(remaining: float) -> str:
    """Green with room, yellow when it is time to write a handoff, red when late."""
    if remaining <= 15:
        return RED
    if remaining <= 30:
        return YELLOW
    return GREEN


def context_segment(payload: dict[str, Any]) -> str | None:
    window = payload.get("context_window")
    if not isinstance(window, dict):
        return None
    remaining = number(window.get("remaining_percentage"), "context_window.remaining_percentage")
    if remaining is None:
        used = number(window.get("used_percentage"), "context_window.used_percentage")
        if used is None:
            return None
        remaining = 100 - used
    # The bar is a fixed ten cells wide; an out-of-range percentage must not
    # widen it, and a negative one must not empty it.
    remaining = clamp(remaining)
    filled = round((100 - remaining) / 10)
    bar = "█" * filled + "░" * (10 - filled)
    return paint(f"{bar} {remaining:.0f}% ctx", by_headroom(remaining))


def reset_suffix(resets_at: Any) -> str:
    """The reset clock is a decoration; it never costs the numbers beside it."""
    stamp = number(resets_at, "rate_limits.five_hour.resets_at")
    if stamp is None:
        return ""
    try:
        return datetime.fromtimestamp(stamp).strftime(" →%H:%M")
    except (ValueError, OverflowError, OSError) as exc:
        # An upstream change of timestamp format must not look like a window
        # that simply has no reset time.
        note(f"ignored rate_limits.five_hour.resets_at: {type(exc).__name__} ({exc})")
        return ""


def limit_segment(payload: dict[str, Any]) -> str | None:
    limits = payload.get("rate_limits")
    if not isinstance(limits, dict):
        return None
    parts = []
    for key, label in (
        ("five_hour", "5h"),
        ("seven_day", "7d"),
        ("spend_limit", "spend"),
    ):
        entry = limits.get(key)
        if not isinstance(entry, dict):
            continue
        used = number(entry.get("used_percentage"), f"rate_limits.{key}.used_percentage")
        if used is None:
            continue
        text = f"{label} {clamp(used):.0f}%"
        if key == "five_hour" and used >= RESET_TIME_AT:
            text += reset_suffix(entry.get("resets_at"))
        parts.append(paint(text, by_headroom(100 - clamp(used))))
    return " ".join(parts) if parts else None


def cache_segment(payload: dict[str, Any]) -> str | None:
    cache = payload.get("prompt_cache")
    if not isinstance(cache, dict):
        return None
    if not cache.get("warm"):
        return paint("cache cold", YELLOW)
    ratio = number(cache.get("hit_ratio"), "prompt_cache.hit_ratio")
    if ratio is not None:
        return paint(f"cache {ratio:.0%}", GREEN if ratio >= 0.8 else YELLOW)
    return paint("cache warm", GREEN)


def place_segment(payload: dict[str, Any]) -> str | None:
    """Where the session is working.

    `project_dir` is the field the status line payload actually carries;
    `git_worktree` is preferred when a release provides it.
    """
    workspace = payload.get("workspace")
    if not isinstance(workspace, dict):
        return None
    for key in ("git_worktree", "project_dir"):
        place = workspace.get(key)
        if isinstance(place, str) and place.strip():
            return paint(one_line(os.path.basename(place.rstrip("/")) or place), DIM)
        if place is not None:
            # Preferring a key must not mean a broken one shadows a good one.
            rejected(f"workspace.{key}", f"{type(place).__name__} is not a path")
    return None


def build_line(payload: dict[str, Any]) -> str:
    segments: list[str] = []

    model = payload.get("model")
    if isinstance(model, dict) and model.get("display_name"):
        segments.append(one_line(model["display_name"]))

    for segment in (
        place_segment(payload),
        context_segment(payload),
        limit_segment(payload),
        cache_segment(payload),
    ):
        if segment:
            segments.append(segment)

    cost = payload.get("cost")
    if isinstance(cost, dict):
        total = number(cost.get("total_cost_usd"), "cost.total_cost_usd")
        if total is not None:
            segments.append(paint(f"${total:.2f}", DIM))

    return SEP.join(segments) if segments else paint("no session data", DIM)


def project_root() -> Path:
    """The checkout this script belongs to, found the way session_budget.repo_root() finds it."""
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env_root) if env_root else Path(__file__).resolve().parents[2]


def window_size(payload: dict[str, Any]) -> int | None:
    """The context window size in tokens the payload reports, or None when it is absent or implausible."""
    window = payload.get("context_window")
    if not isinstance(window, dict):
        return None
    size = number(window.get("context_window_size"), "context_window.context_window_size")
    if size is None:
        return None
    if size != int(size) or not MIN_WINDOW_TOKENS <= size <= MAX_WINDOW_TOKENS:
        return rejected("context_window.context_window_size", f"{size:g} is not a plausible window size")
    return int(size)


def modified(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0  # removed by a status line that pruned at the same moment


def forget_the_oldest(directory: Path, keep: Path) -> None:
    """Keep the MAX_RECORDED_SESSIONS most recently drawn sessions, and always `keep`, the one just written (a
    filesystem with coarse timestamps can tie it with the oldest)."""
    recorded = [path for path in directory.iterdir() if SESSION_ID.fullmatch(path.name)]
    oldest = [path for path in sorted(recorded, key=modified) if path != keep]
    for path in oldest[:max(0, len(recorded) - MAX_RECORDED_SESSIONS)]:
        path.unlink(missing_ok=True)


def record_window_size(payload: dict[str, Any], root: Path | None = None) -> None:
    """Remember this session's window size for the hooks, which cannot see it.

    The size goes in a file of its own, so concurrent status lines of different sessions share nothing to lose. It
    is rewritten only when it changes, through a temporary file renamed into place, so a hook reading it never sees
    half a write; otherwise the file is touched, which is what keeps a session that is still drawing out of the
    oldest-first pruning.
    """
    session = payload.get("session_id")
    size = window_size(payload)
    if size is None or not isinstance(session, str) or not SESSION_ID.fullmatch(session):
        return
    directory = (root or project_root()).joinpath(*WINDOW_STATE)
    path = directory / session
    try:
        known = path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        known = None
    if known == str(size):
        try:
            os.utime(path)
            return
        except FileNotFoundError:
            pass  # pruned by another status line just now: write it again
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".{session}.{os.getpid()}.tmp"
    try:
        tmp.write_text(str(size), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    forget_the_oldest(directory, path)


def note(reason: str) -> None:
    """Fail open, but never fail silently: a dropped field must leave a trace.

    A payload field that disappears in a future release would otherwise show up
    as a segment that quietly stops rendering, which is indistinguishable from
    the segment legitimately having no data.
    """
    print(f"statusline: {reason}", file=sys.stderr)


def main() -> int:
    raw = ""
    try:
        # Bytes, decoded here. sys.stdin.read() decodes with the locale's error
        # handler, which is strict under en_US.UTF-8 (lenient only under C or
        # C.UTF-8), so one invalid byte would crash the hook in most terminals.
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    except OSError as exc:
        note(f"could not read stdin ({exc})")
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        note(f"payload is not JSON ({exc})")
        payload = {}
    if not isinstance(payload, dict):
        note(f"payload is {type(payload).__name__}, expected an object")
        payload = {}
    try:
        record_window_size(payload)
    except Exception as exc:  # a side channel for the hooks must never cost the line
        note(f"could not record the window size ({type(exc).__name__}: {exc})")
    try:
        print(build_line(payload))
    except Exception as exc:  # a broken status line must never look like a broken session
        note(f"render failed ({type(exc).__name__}: {exc})")
        print(paint("status line unavailable", DIM))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
