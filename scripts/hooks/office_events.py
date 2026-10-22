#!/usr/bin/env python3
"""Append one line per agent-team event to `artifacts/handoff/office-events.jsonl`.

This is the data source of the agent-office dashboard (`scripts/office/`, see
docs/office-dashboard.md). It only observes: it never prints a decision, never
blocks a tool and always exits 0, so a bug here cannot break the session it is
watching. `agent_budget.py` is the hook that enforces; this one records.

Hook subcommands (the payload arrives on stdin; every one fails open):

    pre-tool-use           PreToolUse          matcher Agent|Task   -> spawn_request
    post-tool-use          PostToolUse         matcher *            -> spawn_result, or tool
    post-tool-use-failure  PostToolUseFailure  matcher Agent|Task   -> spawn_failed
    subagent-start         SubagentStart                            -> start
    subagent-stop          SubagentStop                             -> stop

What is stored: ids, tool names, the spawn's status, token and time counts, the short task
description of a spawn, and two pieces of free text of at most 240 characters: the error text of a
failed spawn, and a subagent's final reply (shown as the card's note) when the SubagentStop payload
carries `last_assistant_message`; the Claude Code build checked on 2026-10-11 does not send it.
Prompts, full replies, tool inputs and transcript paths are never stored. `OFFICE_EVENTS_NOTES=0`
drops both pieces of free text. The log is created readable by its owner only.

One JSON object per line, appended with a single `write` on an `O_APPEND`
descriptor, so two hooks firing at once cannot interleave. A `tool` event inside
a subagent carries its `agent_id`; that count over the agent's `maxTurns` is
the dashboard's per-agent progress estimate.

`OFFICE_EVENTS_DISABLE=1` turns the hook off. `OFFICE_EVENTS_SHAPE=1` also
appends the *shape* of every payload (key names and value types, never the
values) to `office-shapes.jsonl`: run it once to confirm the field names this
file reads against the Claude Code release in use, without logging prompts.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:  # POSIX advisory locks
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

EVENT_VERSION = 1
SPAWN_TOOLS = {"Agent", "Task"}
EVENTS_NAME = "office-events.jsonl"
SHAPES_NAME = "office-shapes.jsonl"
DISABLE_VAR = "OFFICE_EVENTS_DISABLE"
SHAPE_VAR = "OFFICE_EVENTS_SHAPE"
NOTES_VAR = "OFFICE_EVENTS_NOTES"
MAX_BYTES_VAR = "OFFICE_EVENTS_MAX_BYTES"
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
# A line stays under this so one `write` is never split on the way to the file.
MAX_LINE_BYTES = 3900
TEXT_LIMIT = 240


def log(message: str) -> None:
    print(f"office_events: {message}", file=sys.stderr)


def repo_root() -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def handoff_dir(root: Path) -> Path:
    return root / "artifacts" / "handoff"


def read_payload() -> dict[str, Any]:
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def clip(value: Any, limit: int = TEXT_LIMIT) -> str | None:
    """A short single-line string, or None. Prompts and replies are never stored whole."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


def text_of(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def notes_enabled() -> bool:
    """Free text out of a payload (a failed spawn's error, a reply excerpt) is kept unless OFFICE_EVENTS_NOTES=0."""
    return os.environ.get(NOTES_VAR, "").strip() != "0"


def number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


# ---------------------------------------------------------------------------
# Payload -> event
# ---------------------------------------------------------------------------


def base_event(kind: str, payload: dict[str, Any], now: float) -> dict[str, Any]:
    return {"v": EVENT_VERSION, "ev": kind, "ts": round(now, 3), "session": text_of(payload.get("session_id"))}


def spawn_agent(tool_input: Any) -> str:
    """The subagent type the spawn asks for; the harness runs `general-purpose` when it is omitted."""
    if isinstance(tool_input, dict):
        raw = text_of(tool_input.get("subagent_type"))
        if raw:
            return raw.strip()
    return "general-purpose"


def event_pre_tool_use(payload: dict[str, Any], now: float) -> dict[str, Any] | None:
    if str(payload.get("tool_name") or "") not in SPAWN_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    event = base_event("spawn_request", payload, now)
    event.update(
        tool_use_id=text_of(payload.get("tool_use_id")),
        agent=spawn_agent(tool_input),
        task=clip(tool_input.get("description")) if isinstance(tool_input, dict) else None,
    )
    return event


def event_post_tool_use(payload: dict[str, Any], now: float) -> dict[str, Any] | None:
    tool = str(payload.get("tool_name") or "")
    if tool in SPAWN_TOOLS:
        response = payload.get("tool_response")
        response = response if isinstance(response, dict) else {}
        event = base_event("spawn_result", payload, now)
        event.update(
            tool_use_id=text_of(payload.get("tool_use_id")),
            agent=spawn_agent(payload.get("tool_input")),
            agent_id=text_of(response.get("agentId")),
            status=clip(response.get("status"), 40),
            tokens=number(response.get("totalTokens")),
            duration_ms=number(response.get("totalDurationMs")),
            tool_uses=number(response.get("totalToolUseCount")),
        )
        return event
    event = base_event("tool", payload, now)
    event.update(
        agent_id=text_of(payload.get("agent_id")),
        agent=text_of(payload.get("agent_type")),
        tool=clip(tool, 60),
    )
    return event


def event_post_tool_use_failure(payload: dict[str, Any], now: float) -> dict[str, Any] | None:
    if str(payload.get("tool_name") or "") not in SPAWN_TOOLS:
        return None
    event = base_event("spawn_failed", payload, now)
    event.update(
        tool_use_id=text_of(payload.get("tool_use_id")),
        agent=spawn_agent(payload.get("tool_input")),
        error=clip(payload.get("error")) if notes_enabled() else None,
    )
    return event


def event_subagent_start(payload: dict[str, Any], now: float) -> dict[str, Any] | None:
    event = base_event("start", payload, now)
    event.update(agent_id=text_of(payload.get("agent_id")), agent=text_of(payload.get("agent_type")))
    return event


def event_subagent_stop(payload: dict[str, Any], now: float) -> dict[str, Any] | None:
    event = base_event("stop", payload, now)
    event.update(
        agent_id=text_of(payload.get("agent_id")),
        agent=text_of(payload.get("agent_type")),
        note=clip(payload.get("last_assistant_message")) if notes_enabled() else None,
    )
    return event


EVENT_BUILDERS = {
    "pre-tool-use": event_pre_tool_use,
    "post-tool-use": event_post_tool_use,
    "post-tool-use-failure": event_post_tool_use_failure,
    "subagent-start": event_subagent_start,
    "subagent-stop": event_subagent_stop,
}


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def encode_line(event: dict[str, Any]) -> bytes:
    """The event as one UTF-8 line under MAX_LINE_BYTES, dropping empty fields first, then trimming text."""
    event = {key: value for key, value in event.items() if value is not None}
    for limit in (TEXT_LIMIT, 120, 60, 20):
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        data = line.encode("utf-8")
        if len(data) <= MAX_LINE_BYTES:
            return data
        event = {key: (clip(value, limit) if isinstance(value, str) else value) for key, value in event.items()}
    return (json.dumps({k: event[k] for k in ("v", "ev", "ts") if k in event}) + "\n").encode("utf-8")


def rotate_if_large(path: Path) -> None:
    """Keep one previous generation, so the log cannot grow without bound.

    Two hooks can both see the log over the limit. Only one may rotate: the other skips, or finds the
    fresh small file when it re-checks under the lock, so a rotation never moves a new file over `.1`.
    """
    try:
        limit = int(os.environ.get(MAX_BYTES_VAR, DEFAULT_MAX_BYTES))
        if path.stat().st_size <= limit:
            return
        lock = os.open(path.with_name(path.name + ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
    except (OSError, ValueError):
        return
    try:
        if fcntl is not None:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # held elsewhere: that process is rotating
        if path.stat().st_size > limit:
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        pass
    finally:
        os.close(lock)


def append_line(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rotate_if_large(path)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def shape_of(value: Any, depth: int = 0) -> Any:
    """Key names and value types only: enough to verify a field name, nothing that could be a secret."""
    if isinstance(value, dict):
        return {key: shape_of(item, depth + 1) for key, item in value.items()} if depth < 4 else "object"
    if isinstance(value, list):
        return [shape_of(value[0], depth + 1)] if value and depth < 4 else "array"
    return type(value).__name__


def record(command: str, payload: dict[str, Any], root: Path, now: float | None = None) -> dict[str, Any] | None:
    """Write the event for `command`; return it, or None when there is nothing to record."""
    builder = EVENT_BUILDERS.get(command)
    if builder is None:
        return None
    moment = time.time() if now is None else now
    if os.environ.get(SHAPE_VAR, "").strip() == "1":
        shape = {"ts": round(moment, 3), "hook": command, "event": payload.get("hook_event_name"), "shape": shape_of(payload)}
        append_line(handoff_dir(root) / SHAPES_NAME, (json.dumps(shape, ensure_ascii=False) + "\n").encode("utf-8"))
    event = builder(payload, moment)
    if event is None:
        return None
    append_line(handoff_dir(root) / EVENTS_NAME, encode_line(event))
    return event


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in EVENT_BUILDERS:
        log(f"usage: office_events.py {{{'|'.join(EVENT_BUILDERS)}}} (payload on stdin)")
        return 0
    if os.environ.get(DISABLE_VAR, "").strip() == "1":
        return 0
    try:
        record(argv[1], read_payload(), repo_root())
    except Exception as exc:  # fail open: an observer must never break the session it observes
        log(f"{argv[1]} failed, continuing: {exc!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
