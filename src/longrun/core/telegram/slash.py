"""Server-side `/` interpreter for the Telegram channel (2026-11-28).

The WebUI composer interprets slash commands in BROWSER JS (`webui/index.html`):
`/goal` sets `mode=goal`, `/plan` and `/spec` call the document endpoints, the `ui`
verbs call their own endpoints. A Telegram DM has no composer, so this module is the
SERVER-SIDE twin of that logic for the channel.

It holds NO table of its own: it reads the ONE catalogue (`core.slash.BUILTINS` +
`RESERVED`) and dispatches by each entry's `kind`, so a command can never exist in
one surface and be a no-op in the other. A token that is not a built-in (a SKILL
`/<name>` or `/plugin:<n>`) is passed through untouched — `agent._apply_skill_slash`
already resolves it INSIDE the turn, so there is no second implementation.

`interpret(text)` returns a PLAN the channel executes:

    {"kind": "turn",  "message": <str>, "mode": "goal"|""}
    {"kind": "doc",   "doc": "plan"|"spec", "message": <str>}
    {"kind": "ui",    "action": <builtin id or menu>, "message": <str>}
    {"kind": "skill", "message": <str>}                 # passthrough to a turn
"""
from __future__ import annotations


def _catalogue():
    """`{token: builtin}` for every built-in id AND its aliases, from the ONE list."""
    from longrun.core import slash
    cat = {}
    for entry in slash.BUILTINS:
        cat[str(entry.get("id") or "").lower()] = entry
        for alias in entry.get("aliases") or []:
            cat[str(alias).lower()] = entry
    return cat


def token_of(text):
    """The leading `/token` of `text` (lowercased), or None when it is not one."""
    s = str(text or "").lstrip()
    if not s.startswith("/"):
        return None
    head = s[1:].split(None, 1)[0] if len(s) > 1 else ""
    return head.strip().lower() or None


def interpret(text):
    """Map one incoming message to an executable plan (see the module docstring)."""
    raw = str(text or "")
    head_raw = raw.lstrip()
    token = token_of(raw)
    if token is None:
        return {"kind": "turn", "message": raw, "mode": ""}
    # rest after the token (preserve the text, trim only the edges)
    _, _, rest = head_raw[1:].partition(" ")
    rest = rest.strip()
    # A skill / plugin token (`/plugin:foo`, `/some-skill`) is NOT a built-in: the
    # turn itself resolves it, so pass the whole text through unchanged.
    entry = _catalogue().get(token) if ":" not in token else None
    if entry is None:
        return {"kind": "skill", "message": raw}
    kind = str(entry.get("kind") or "")
    if kind == "goal":
        return {"kind": "turn", "message": rest or raw, "mode": "goal"}
    if kind == "doc":
        return {"kind": "doc", "doc": entry.get("doc") or "plan", "message": rest}
    if kind == "menu":
        return {"kind": "ui", "action": entry.get("menu") or entry.get("id") or "",
                "message": rest}
    return {"kind": "ui", "action": entry.get("id") or token, "message": rest}


def catalogue():
    """Every built-in as `[{id, title, kind, hint}]` — the native menu source."""
    from longrun.core import slash
    out = []
    for entry in slash.BUILTINS:
        out.append({"id": entry.get("id"), "title": entry.get("title") or entry.get("id"),
                    "kind": entry.get("kind"), "hint": entry.get("hint") or ""})
    return out
