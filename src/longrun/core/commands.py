"""User-defined `/` commands.

A command is a NAME, a one-line description and a PROMPT: picking it in the
composer expands the prompt into the message while the transcript keeps the
`/name` it was invoked with (the same split `send(text, display)` already
implements for skills).

The store is operator-owned data (`data/commands.yaml`), never shipped config:
the built-in commands live in the WebUI and a user command may not shadow one.
Writes are atomic, and a bad name is refused BY NAME rather than half-saved.
"""
from __future__ import annotations

import os
import re

import yaml

from longrun.util import paths, fswrite

# The built-in tokens the composer and `agent.py` already own. A user command
# with one of these names would be a second truth for the same token.
RESERVED = ("goal", "skills", "skill", "compact")
SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
MODES = ("send", "insert")
MAX_PROMPT = 8192
MAX_DESCRIPTION = 200
MAX_COMMANDS = 100


def path():
    return os.path.join(paths.DATA_DIR, "commands.yaml")


def _read_raw():
    try:
        with open(path(), encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return []
    except (OSError, yaml.YAMLError):
        return []
    rows = doc.get("commands") if isinstance(doc, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _clean(row):
    return {
        "name": str(row.get("name") or "").strip().lower(),
        "description": str(row.get("description") or "").strip(),
        "prompt": str(row.get("prompt") or ""),
        "aliases": [str(a).strip().lower() for a in (row.get("aliases") or []) if str(a).strip()],
        "mode": str(row.get("mode") or "send").strip().lower(),
    }


def list_commands():
    """Every user command, plus where they live (one owner, one file)."""
    rows = [_clean(r) for r in _read_raw()]
    rows = [r for r in rows if r["name"]]
    return {"ok": True, "commands": rows, "path": path(), "reserved": list(RESERVED),
            "modes": list(MODES), "max_prompt": MAX_PROMPT}


def get(name):
    wanted = str(name or "").strip().lower()
    for row in _read_raw():
        if str(row.get("name") or "").strip().lower() == wanted:
            return _clean(row)
    return None


def validate(doc, existing=None):
    """`(entry, error)` — every refusal names the field that failed."""
    if not isinstance(doc, dict):
        return None, "a command must be an object"
    entry = _clean(doc)
    name = entry["name"]
    if not SLUG.match(name):
        return None, "invalid name %r: lowercase letters, digits, - and _ (max 32)" % name
    if name in RESERVED:
        return None, "name %r is a built-in command" % name
    if not entry["prompt"].strip():
        return None, "prompt is required"
    if len(entry["prompt"]) > MAX_PROMPT:
        return None, "prompt exceeds %d characters" % MAX_PROMPT
    if len(entry["description"]) > MAX_DESCRIPTION:
        return None, "description exceeds %d characters" % MAX_DESCRIPTION
    if entry["mode"] not in MODES:
        return None, "mode must be one of %s" % (", ".join(MODES),)
    for alias in entry["aliases"]:
        if not SLUG.match(alias):
            return None, "invalid alias %r" % alias
        if alias in RESERVED:
            return None, "alias %r is a built-in command" % alias
        if alias == name:
            return None, "alias %r repeats the name" % alias
    taken = {}
    for row in (existing if existing is not None else _read_raw()):
        row = _clean(row)
        if row["name"] == name:
            continue  # the entry being replaced owns its own tokens
        taken[row["name"]] = row["name"]
        for alias in row["aliases"]:
            taken[alias] = row["name"]
    for token in [name] + entry["aliases"]:
        if token in taken:
            return None, "token %r is already used by %r" % (token, taken[token])
    return entry, ""


def _write(rows):
    body = yaml.safe_dump({"commands": rows}, sort_keys=False, allow_unicode=True,
                          default_flow_style=False)
    fswrite.write_text(path(), body)
    return path()


def upsert(doc):
    """Create or replace one command. The name is the identity."""
    rows = _read_raw()
    entry, why = validate(doc, existing=rows)
    if entry is None:
        return {"ok": False, "error": why}
    kept = [r for r in rows if str(r.get("name") or "").strip().lower() != entry["name"]]
    if len(kept) >= MAX_COMMANDS:
        return {"ok": False, "error": "at most %d commands" % MAX_COMMANDS}
    kept.append(entry)
    kept.sort(key=lambda r: str(r.get("name") or ""))
    return {"ok": True, "command": entry, "path": _write(kept)}


def remove(name):
    wanted = str(name or "").strip().lower()
    rows = _read_raw()
    kept = [r for r in rows if str(r.get("name") or "").strip().lower() != wanted]
    if len(kept) == len(rows):
        return {"ok": False, "error": "unknown command: %s" % wanted}
    return {"ok": True, "name": wanted, "path": _write(kept)}
