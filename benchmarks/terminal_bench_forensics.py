#!/usr/bin/env python3
"""Bounded, secret-redacted forensic artifacts for Terminal-Bench arms."""

import json
import os
import posixpath
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

MAX_TEXT_CHARS = 32_000
MAX_TRACE_ITEMS = 500
_TRAJECTORY_ROOT = "/tmp/oc/.openclaw/trajectory-exports"
_TRAJECTORY_FILES = frozenset({
    "manifest.json",
    "events.jsonl",
    "artifacts.json",
    "metadata.json",
})
_TRAJECTORY_EVENTS = frozenset({
    "session.started",
    "trace.metadata",
    "tool.call",
    "tool.result",
    "model.fallback_step",
    "model.completed",
    "trace.artifacts",
    "session.ended",
})
_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|authorization|password|secret|credential)",
    re.IGNORECASE,
)
_SECRET_TEXT = re.compile(
    r"(Bearer\s+)[A-Za-z0-9._~+/=-]+"
    r"|\bsk-[A-Za-z0-9_-]{12,}"
    r"|\b((?:OPENROUTER|ANTHROPIC|API|AUTH)[A-Z0-9_]*(?:KEY|TOKEN|SECRET)"
    r"\s*[=:]\s*)[^\s,;]+"
    r"|\b((?:PASSWORD|PASSWD|PWD)\s*[=:]\s*)[^\s,;]+",
    re.IGNORECASE,
)
_TRUNCATION = "\n...[TRUNCATED forensic field]"


def _redact_text(value: str, secrets: tuple[str, ...], max_chars: int) -> str:
    """Redact known credentials and bound one text field."""
    text = value
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<REDACTED>")
    text = _SECRET_TEXT.sub(
        lambda match: ((match.group(1) or "") + "<REDACTED>"),
        text,
    )
    if len(text) > max_chars:
        text = text[:max_chars] + _TRUNCATION
    return text


def sanitize_payload(
    value: Any,
    secrets: Iterable[str] = (),
    max_chars: int = MAX_TEXT_CHARS,
) -> Any:
    """Return JSON-safe content with secret fields redacted and strings bounded."""
    known_secrets = tuple(sorted(
        (str(secret) for secret in secrets if secret),
        key=len,
        reverse=True,
    ))
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            cleaned[name] = ("<REDACTED>" if _SECRET_KEY.search(name)
                             else sanitize_payload(item, known_secrets, max_chars))
        return cleaned
    if isinstance(value, (list, tuple)):
        cleaned_list = [sanitize_payload(item, known_secrets, max_chars)
                        for item in value[:MAX_TRACE_ITEMS]]
        if len(value) > MAX_TRACE_ITEMS:
            cleaned_list.append({
                "_truncated_items": len(value) - MAX_TRACE_ITEMS,
            })
        return cleaned_list
    if isinstance(value, str):
        return _redact_text(value, known_secrets, max_chars)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(str(value), known_secrets, max_chars)


def longrun_trace(
    session: Mapping[str, Any],
    costs: Any = None,
    plan: Any = None,
    secrets: Iterable[str] = (),
) -> dict[str, Any]:
    """Select non-system Longrun messages, tool cards, injects, plan, and costs."""
    all_messages = [
        message for message in (session.get("messages") or [])
        if isinstance(message, Mapping) and message.get("role") != "system"
    ]
    all_cards = session.get("tool_cards") or []
    all_injects = session.get("injects") or []
    messages: list[dict[str, Any]] = []
    for message in all_messages[-MAX_TRACE_ITEMS:]:
        item = {
            key: message[key]
            for key in ("role", "content", "name", "tool_calls", "tool_call_id", "ts")
            if key in message
        }
        messages.append(item)
    trace = {
        "schema": "longrun.terminal-bench.forensic.v1",
        "session": session.get("id") or "",
        "workspace": session.get("workspace") or "",
        "messages": messages,
        "tool_cards": all_cards[-MAX_TRACE_ITEMS:],
        "injects": all_injects[-MAX_TRACE_ITEMS:],
        "costs": costs or {},
        "plan": plan or {},
        "truncated": {
            "messages": len(all_messages) > MAX_TRACE_ITEMS,
            "tool_cards": len(all_cards) > MAX_TRACE_ITEMS,
            "injects": len(all_injects) > MAX_TRACE_ITEMS,
        },
    }
    return sanitize_payload(trace, secrets)


def session_key_for_id(session_list: Any, session_id: str) -> str | None:
    """Resolve one exact SQLite sessionId to its unique OpenClaw sessionKey."""
    rows = (session_list.get("sessions") or []
            if isinstance(session_list, Mapping) else session_list)
    if not isinstance(rows, list) or not session_id:
        return None
    keys = {
        str(key)
        for row in rows
        if isinstance(row, Mapping) and row.get("sessionId") == session_id
        for key in (row.get("key") or row.get("sessionKey") or row.get("session_key"),)
        if key
    }
    return next(iter(keys)) if len(keys) == 1 else None


def is_openclaw_trajectory_path(path: str) -> bool:
    """Accept only approved bundle files below OpenClaw's trajectory export root."""
    normalized = posixpath.normpath(str(path or "").replace("\\", "/"))
    root = posixpath.normpath(_TRAJECTORY_ROOT)
    if normalized.startswith(root + "/"):
        relative = posixpath.relpath(normalized, root)
    elif normalized.startswith("/"):
        return False
    else:
        relative = normalized
    parts = relative.split("/")
    return (
        relative not in ("", ".", "..")
        and ".." not in parts
        and posixpath.basename(relative) in _TRAJECTORY_FILES
    )


def filter_trajectory_events(content: str) -> tuple[str, int]:
    """Keep diagnostic runtime events while excluding submitted/compiled prompts."""
    kept: list[str] = []
    dropped = 0
    for line in (content or "").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            dropped += 1
            continue
        if not isinstance(record, Mapping):
            dropped += 1
            continue
        event_type = next(
            (record.get(key) for key in
             ("type", "event", "kind", "eventType", "eventName")
             if isinstance(record.get(key), str)),
            "",
        )
        if not event_type and record.get("traceSchema") == "openclaw-trajectory":
            kept.append(json.dumps(
                {
                    "traceSchema": "openclaw-trajectory",
                    "schemaVersion": record.get("schemaVersion", 1),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ))
            continue
        if event_type not in _TRAJECTORY_EVENTS:
            dropped += 1
            continue
        safe_record = sanitize_payload(record)
        kept.append(json.dumps(safe_record, ensure_ascii=False, separators=(",", ":")))
    return ("\n".join(kept) + ("\n" if kept else "")), dropped


def openclaw_trace(
    envelope: Any,
    stderr: str = "",
    trajectory_files: Mapping[str, str] | None = None,
    secrets: Iterable[str] = (),
    trajectory_files_truncated: bool = False,
    capture_error: str = "",
) -> dict[str, Any]:
    """Keep the CLI envelope, diagnostic tail, and approved trajectory bundle files."""
    bundle: dict[str, str] = {}
    filtered_events = 0
    all_files = list((trajectory_files or {}).items())
    files_truncated = trajectory_files_truncated or len(all_files) > MAX_TRACE_ITEMS
    for path, content in all_files[:MAX_TRACE_ITEMS]:
        normalized = str(path or "").replace("\\", "/")
        if not is_openclaw_trajectory_path(normalized):
            continue
        relative = (posixpath.relpath(normalized, _TRAJECTORY_ROOT)
                    if normalized.startswith(_TRAJECTORY_ROOT + "/")
                    else normalized)
        if posixpath.basename(relative) == "events.jsonl":
            content, dropped = filter_trajectory_events(content)
            filtered_events += dropped
        bundle[relative] = content
    stderr_text = stderr or ""
    stderr_truncated = len(stderr_text) > MAX_TEXT_CHARS
    if stderr_truncated:
        stderr_limit = MAX_TEXT_CHARS - len(_TRUNCATION)
        stderr_text = stderr_text[-stderr_limit:] + _TRUNCATION
    return sanitize_payload(
        {
            "schema": "openclaw.terminal-bench.forensic.v1",
            "envelope": envelope if isinstance(envelope, Mapping) else {},
            "stderr_tail": stderr_text,
            "trajectory_files": bundle,
            "trajectory_available": "events.jsonl" in {
                posixpath.basename(path) for path in bundle
            },
            "filtered_event_count": filtered_events,
            "truncated": {
                "stderr": stderr_truncated,
                "trajectory_files": files_truncated,
            },
            "capture_error": capture_error,
        },
        secrets,
    )


def write_forensic(
    directory: str | os.PathLike[str],
    name: str,
    payload: Mapping[str, Any],
    secrets: Iterable[str] = (),
) -> str:
    """Atomically write one sanitized JSON artifact inside the logging directory."""
    if Path(name).name != name or name in ("", ".", ".."):
        raise ValueError("forensic artifact name must be a filename")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(root),
            prefix=".forensic-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = handle.name
            json.dump(sanitize_payload(payload, secrets), handle,
                      ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
        os.replace(temp_path, target)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
    return str(target)
