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
    """
    try:
        from longrun.core import market as _mkt
        records = _mkt.installed().get("installed") or []
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
        members = []
        for member in (rec.get("members") or [])[:MAX_MEMBERS]:
            kind = str(member.get("kind") or "")
            mname = str(member.get("name") or "")
            if not mname:
                continue
            if kind == "skill":
                title, desc, path, missing = _skill_meta(member.get("target"), mname)
            else:
                title, desc, path, missing = mname, "", str(member.get("target") or ""), False
            members.append({"kind": kind, "name": mname, "title": title,
                            "description": desc, "path": path, "missing": missing})
        out.append({
            "id": rec.get("id") or ("plugin/" + name),
            "name": name,
            "title": str(item.get("title") or name.replace("-", " ").title()),
            "description": str(item.get("description") or ""),
            "icon": "\U0001f9f1",
            "members": members,
            "member_count": len(rec.get("members") or []),
        })
        if len(out) >= MAX_PLUGINS:
            break
    out.sort(key=lambda r: (r.get("name") or "").lower())
    return out


def plugin_block(name):
    """A bounded manifest for `/plugin:<name>`.

    The model gets the plugin's identity, description and one line per member
    (kind, name, description, path) and is told to open the members it needs.
    Injecting every member `SKILL.md` would flood the context; this is the
    "call the plugin whole" gesture without that cost.
    """
    wanted = str(name or "").strip().lower()
    if not wanted:
        return ""
    found = None
    for p in plugins():
        if wanted in (str(p.get("name") or "").lower(),
                      str(p.get("id") or "").lower(),
                      str(p.get("id") or "").split("/")[-1].lower()):
            found = p
            break
    if not found:
        return ""
    lines = [
        "PLUGIN ACTIVATION \u2014 '%s' (%s)" % (found.get("title") or found["name"], found["name"]),
        "Description: %s" % (found.get("description") or "no description"),
        "Members installed by this plugin (open the ones you need with fs.read; "
        "do not assume their content):",
    ]
    for m in found.get("members") or []:
        where = m.get("path") or ("MISSING target" if m.get("missing") else "")
        desc = (" \u2014 " + m["description"]) if m.get("description") else ""
        lines.append("- %s %s%s%s" % (m.get("kind") or "member", m.get("name") or "",
                                      desc, (" \u2014 " + where) if where else ""))
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
