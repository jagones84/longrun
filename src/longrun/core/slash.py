"""The ONE catalogue behind the composer's `/` menu (v1051).

The menu used to be a hardcoded JavaScript array; plugins and documents did not
exist there at all. This module is the backend owner of the catalogue: the
built-in commands, the operator's own commands (`data/commands.yaml`), the
installed plugin bundles (with their member skills) and the resolved documents
folders. The WebUI keeps a first-paint fallback and replaces it with this
payload, so a command can never exist in one surface and be a no-op in another.

It never writes a command, a document or a plugin. The plugin projection uses
`market.installed()`, which may prune a record whose owner was deleted elsewhere
— the marketplace's own reconciliation, exactly like its panel; no new write.
"""
from __future__ import annotations

import os
import re

#: The built-ins the composer and `agent.py` own. `kind` says who executes it:
#: `goal`/`ui`/`menu` are UI actions, `doc` is a document endpoint.
BUILTINS = [
    {"id": "goal", "aliases": [], "title": "Goal", "icon": "\u25ce", "kind": "goal",
     "insert": "/goal ",
     "hint": "run until evidence-backed completion; pauses on blocker, error, Stop, "
             "or a configured safety/policy stop"},
    {"id": "plan", "aliases": [], "title": "Plan", "icon": "\U0001f5fa", "kind": "doc",
     "doc": "plan", "insert": "/plan ",
     "hint": "write a reviewed plan document and lock the session until you approve it"},
    {"id": "spec", "aliases": [], "title": "Spec", "icon": "\U0001f4d0", "kind": "doc",
     "doc": "spec", "insert": "/spec ",
     "hint": "write spec.md + tasks.md + checklist.md under .longrun/documents/specs"},
    {"id": "plugins", "aliases": ["plugin"], "title": "Plugins", "icon": "\U0001f9f1",
     "kind": "menu", "menu": "plugins", "insert": "/",
     "hint": "browse installed plugin bundles and the skills they carry"},
    {"id": "skills", "aliases": ["skill"], "title": "Skills", "icon": "\U0001f9e9",
     "kind": "menu", "menu": "skills", "insert": "/",
     "hint": "list the skills in this menu \u2014 the choice lands as /<name> in the message"},
    {"id": "compact", "aliases": [], "title": "Compact", "icon": "\U0001f5dc",
     "kind": "ui", "insert": "", "hint": "compact this session's context now"},
    {"id": "status", "aliases": [], "title": "Status", "icon": "\u24d8",
     "kind": "ui", "insert": "",
     "hint": "report everything about this session: identity, model, context "
             "saturation vs the max context, the plan and its open steps, approvals"},
    {"id": "reset", "aliases": [], "title": "Reset", "icon": "\u21ba", "kind": "ui",
     "insert": "",
     "hint": "start a fresh chat (a new session in this workspace) — nothing is deleted"},
    {"id": "unlock", "aliases": [], "title": "Unlock", "icon": "\u23cf", "kind": "ui",
     "insert": "",
     "hint": "leave /plan or /spec mode: release the gate and forget that document"},
    # 2026-11-22: the two verbs the operator asked for. Both are UI actions whose
    # backend is already owned elsewhere — `/context` reads `/api/context` and the
    # RH breakdown, `/restart` calls the `harness` tool (`restart.schedule_restart`),
    # so the composer and an agent share one implementation, not two.
    {"id": "context", "aliases": ["ctx"], "title": "Context", "icon": "\u2314",
     "kind": "ui", "insert": "",
     "hint": "this session's context: saturation, messages/tokens/budget and the "
             "full breakdown (the same card the inspector shows)"},
    {"id": "restart", "aliases": [], "title": "Restart", "icon": "\u27f3",
     "kind": "ui", "insert": "",
     "hint": "restart the harness now — the same door the agent's harness tool uses"},
]

#: Reserved tokens: a user command may add, never shadow a built-in.
RESERVED = tuple(sorted({c["id"] for c in BUILTINS} |
                        {a for c in BUILTINS for a in c.get("aliases") or []}))

MAX_PLUGINS = 20
MAX_MEMBERS = 40
MAX_BLOCK = 8192
_HEAD_BYTES = 4096


def _head(path):
    try:
        with open(path, "rb") as f:
            return f.read(_HEAD_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _skill_meta(target, name):
    """`(title, description, path, missing)` for one plugin member."""
    path = str(target or "")
    if path and os.path.isdir(path):
        path = os.path.join(path, "SKILL.md")
    if not path or not os.path.isfile(path):
        return name, "", str(target or ""), True
    text = _head(path)
    try:
        from longrun.memory import skills as _skills
        title, desc = _skills._parse_skill_md(text, name)
    except Exception:  # noqa: BLE001 \u2014 a member must not break the menu
        title, desc = name, ""
    return title or name, desc or "", path, False


def _live_catalog():
    try:
        from longrun.core import market as _mkt
        items, _, _ = _mkt.catalog()
        return {i.get("id"): i for i in (items or []) if i.get("id")}
    except Exception:  # noqa: BLE001 \u2014 the menu must render without the catalogue
        return {}


def plugins():
    """Installed plugin bundles, each with the members it actually installed.

    Only a record in `data/market/installed.json` is listed: an uninstalled
    package found on disk belongs to the Marketplace, not to the slash menu.
    Every member also carries its LIVE state (`market.plugin_states`), because
    "installed" and "ready" are not the same thing and the model must be told
    which one it is looking at.
    """
    try:
        from longrun.core import market as _mkt
        records = _mkt.installed().get("installed") or []
        states = _mkt.plugin_states(records)
    except Exception:  # noqa: BLE001
        return []
    live = _live_catalog()
    out = []
    for rec in records:
        if str(rec.get("kind") or "") != "plugin":
            continue
        name = str(rec.get("name") or "")
        if not name:
            continue
        item = live.get(rec.get("id")) or {}
        state = states.get(rec.get("id")) or {}
        # A plugin can carry a skill and a server with the SAME name (the
        # chrome-devtools package does), so the join is (kind, name), never name.
        by_name = {(str(r.get("kind") or ""), str(r.get("name") or "")): r
                   for r in state.get("members") or []}
        members = []
        for member in (rec.get("members") or [])[:MAX_MEMBERS]:
            kind = str(member.get("kind") or "")
            mname = str(member.get("name") or "")
            if not mname:
                continue
            row = by_name.get((kind, mname)) or {}
            if kind == "skill":
                title, desc, path, missing = _skill_meta(member.get("target"), mname)
            else:
                title, desc, path, missing = mname, "", str(member.get("target") or ""), False
            members.append({"kind": kind, "name": mname, "title": title,
                            "description": desc, "path": path, "missing": missing,
                            "state": str(row.get("state") or ""),
                            "tools": int(row.get("tools") or 0),
                            "error": str(row.get("error") or "")})
        total = int(state.get("total") or len(rec.get("members") or []))
        good = int(state.get("live") or 0)
        tools = sum(int(m.get("tools") or 0) for m in state.get("members") or [])
        ready = bool(state.get("ready"))
        started_all = all(m.get("state") != "starting" for m in state.get("members") or [])
        if ready and started_all:
            state_line = ("READY \u2014 %d/%d members live (%d tool%s)"
                          % (good, total, tools, "" if tools == 1 else "s"))
        elif ready:
            # Every member is in place; the servers simply have not been spawned yet.
            state_line = ("READY \u2014 %d/%d members (the servers start on first use)"
                          % (total, total))
        else:
            state_line = "NOT READY \u2014 %d of %d member(s) live" % (good, total)
        out.append({
            "id": rec.get("id") or ("plugin/" + name),
            "name": name,
            "title": str(item.get("title") or rec.get("title") or name.replace("-", " ").title()),
            "description": str(item.get("description") or rec.get("description") or ""),
            "origin_label": str(rec.get("origin_label") or ""),
            "icon": "\U0001f9f1",
            "members": members,
            "member_count": len(rec.get("members") or []),
            "ready": ready,
            "state_line": state_line,
        })
        if len(out) >= MAX_PLUGINS:
            break
    out.sort(key=lambda r: (r.get("name") or "").lower())
    return out


#: One sentence every activation carries: a member of an installed plugin is not
#: the model's to install. The 2026-11-15 turn exists because it was not said.
_NOT_YOURS = (
    "This plugin was installed by the marketplace into Longrun's own homes. NEVER "
    "install, download, configure, re-point or repair a member of it yourself: no "
    "mcp.upsert, no mcp.reload, no npm/npx/uvx, no editing "
    "config/mcp_clients.local.json. If a member is not running, say exactly that "
    "(with the reason below) and stop."
)

_MEMBER_TAIL = {
    "missing": ("MISSING (deleted elsewhere) \u2014 reinstall the plugin from "
                "Marketplace \u25b8 Plugins"),
    "disabled": "installed but disabled \u2014 enable it in Settings \u25b8 MCP",
    "starting": "enabled, starts with the next tool listing",
}


def plugin_block(name):
    """A bounded manifest for `/plugin:<name>`, live state included.

    The model gets the plugin's identity, provenance, readiness, one line per
    member (kind, name, state, path) and the rule that installation is NOT its
    job. Injecting every member `SKILL.md` would flood the context; this is the
    "call the plugin whole" gesture without that cost.

    An UNKNOWN name returns a refusal block instead of "": leaving the token as
    prose is what let a model conclude it had to install the plugin itself.
    """
    wanted = str(name or "").strip().lower()
    if not wanted:
        return ""
    found = None
    all_plugins = plugins()
    for p in all_plugins:
        if wanted in (str(p.get("name") or "").lower(),
                      str(p.get("id") or "").lower(),
                      str(p.get("id") or "").split("/")[-1].lower()):
            found = p
            break
    if not found:
        names = [str(p.get("name") or "") for p in all_plugins if p.get("name")][:20]
        return ("PLUGIN ACTIVATION \u2014 no installed plugin named '%s'.\n"
                "Installed plugins: %s.\n"
                "A plugin is installed by the operator from Marketplace \u25b8 Plugins (or "
                "`forge.py market plugin-add`), never by the model. Do NOT install skills, "
                "MCP servers or packages to satisfy this token: say the plugin is not "
                "installed and stop." % (wanted, ", ".join(names) or "none"))
    lines = [
        "PLUGIN ACTIVATION \u2014 '%s' (%s)" % (found.get("title") or found["name"], found["name"]),
        "Status: %s" % (found.get("state_line") or "unknown"),
        "Source: %s" % (found.get("origin_label") or "unknown"),
        "Description: %s" % (found.get("description") or "no description"),
        _NOT_YOURS,
        "Members (open the skills you need with fs.read; do not assume their content):",
    ]
    for m in found.get("members") or []:
        kind = m.get("kind") or "member"
        if kind == "skill":
            where = m.get("path") or ("MISSING target" if m.get("missing") else "")
            desc = (" \u2014 " + m["description"]) if m.get("description") else ""
            lines.append("- skill %s%s%s" % (m.get("name") or "", desc,
                                             (" \u2014 " + where) if where else ""))
            continue
        state = str(m.get("state") or "")
        tail = ""
        if state == "ready":
            n = int(m.get("tools") or 0)
            tail = "connected, %d tool%s" % (n, "" if n == 1 else "s")
        if not tail:
            tail = _MEMBER_TAIL.get(state) or ""
        if not tail and state == "needs-key":
            tail = ("needs its key: %s \u2014 add it in Settings \u25b8 Keys, then Reload "
                    "in Settings \u25b8 MCP" % (m.get("error") or "missing credential"))
        if not tail:
            tail = "not running: %s" % (m.get("error") or "no reason reported")
        lines.append("- %s %s \u2014 %s" % (kind, m.get("name") or "", tail))
    if not found.get("members"):
        lines.append("- no members recorded; the plugin is installed but empty")
    text = "\n".join(lines)
    return text[:MAX_BLOCK]


def catalog(session=""):
    """The payload `GET /api/slash` serves; never raises for a missing workspace."""
    from longrun.core import commands as _cmds
    from longrun.plan import docs as _docs
    try:
        user = _cmds.list_commands()
        user_rows = user.get("commands") or []
    except Exception:  # noqa: BLE001
        user_rows = []
    return {
        "ok": True,
        "version": 1,
        "commands": [dict(c) for c in BUILTINS],
        "user_commands": user_rows,
        "plugins": plugins(),
        "docs": _docs.config_view(session),
        "reserved": list(RESERVED),
    }
