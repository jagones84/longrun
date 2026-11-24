#!/usr/bin/env python3
"""v1051 (RED) — ONE `/` catalogue: built-ins, user commands, plugins, docs paths.

The composer menu used to be a hardcoded JavaScript array with three rows, and a
plugin had no slash surface at all. This slice pins the backend owner
(`core/slash.py`), the reserved tokens, the installed-plugin projection and the
route that serves it. Deterministic: temp dirs, no model, no network.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="lr-v1051-")
for _d in ("cfg", "sessions", "data", "projects"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
os.environ["LONGRUN_WORKSPACE"] = os.path.join(TMP, "ws")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_WORKSPACE"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import slash  # noqa: E402
from longrun.core import commands  # noqa: E402
from longrun.memory import stores  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTTPAPI = read("src", "longrun", "core", "api_v02.py")

# ---------------------------------------------------------------- A: built-ins
ids = [c["id"] for c in slash.BUILTINS]
# v1051c: `/reset` (a fresh chat) and `/unlock` (leave the plan/spec mode) joined
# the catalogue; the order is the menu order, so this list is pinned in full.
# v1237: `/status` (the one read-only report about a session) joined between
# `compact` and `reset`.
# 2026-11-24: `/reset` now RESETS the session it is typed in (the harness's own
# `sessions.reset`), so the fresh-chat verb is its own entry, `/new`.
check("A1 the twelve built-ins are declared once",
      ids == ["goal", "plan", "spec", "plugins", "skills", "compact",
              "status", "reset", "new", "unlock", "context", "restart"], ids)
check("A2 plan/spec are DOCUMENT commands with a doc kind",
      all(c.get("kind") == "doc" and c.get("doc") in ("plan", "spec")
          for c in slash.BUILTINS if c["id"] in ("plan", "spec")))
check("A3 plugin/skill are submenu openers",
      all(c.get("kind") == "menu" and c.get("menu") in ("plugins", "skills")
          for c in slash.BUILTINS if c["id"] in ("plugins", "skills")))
check("A4 aliases keep the frontier spellings",
      any(c["id"] == "plugins" and "plugin" in (c.get("aliases") or []) for c in slash.BUILTINS)
      and any(c["id"] == "skills" and "skill" in (c.get("aliases") or []) for c in slash.BUILTINS))
check("A5 the reserved set is derived from the SAME table",
      set(slash.RESERVED) == set(commands.RESERVED)
      and {"plan", "spec", "plugins", "plugin"} <= set(commands.RESERVED),
      (slash.RESERVED, commands.RESERVED))

# ------------------------------------------------------------ B: user commands
res = commands.upsert({"name": "plan", "description": "shadow", "prompt": "x"})
check("B1 a user command cannot shadow /plan", res.get("ok") is False and "built-in" in res.get("error", ""), res)
res = commands.upsert({"name": "deploy", "description": "ship it", "prompt": "Ship the change."})
check("B2 a free user command saves", res.get("ok") is True, res)

# --------------------------------------------------------------- C: plugin data
skill_dir = os.path.join(TMP, "skills", "local", "demo-skill")
os.makedirs(skill_dir, exist_ok=True)
with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
    f.write("---\nname: Demo Skill\ndescription: Does demo things\n---\n# Demo\n")
market_dir = os.path.join(os.environ["LONGRUN_DATA_DIR"], "market")
os.makedirs(market_dir, exist_ok=True)
with open(os.path.join(market_dir, "installed.json"), "w", encoding="utf-8") as f:
    json.dump([{
        "id": "plugin/demo", "kind": "plugin", "name": "demo", "version": "1.0",
        "sha256": "", "publisher": "", "source": "", "origin": "local",
        "category": "", "installed": "2026-11-16T00:00:00Z", "enabled": True,
        "target": "1 members",
        "members": [{"kind": "skill", "name": "demo-skill", "target": skill_dir,
                     "created": True, "enabled": True}],
    }], f)

sess = stores.get_or_create_session(None, title="v1051", workspace=os.environ["LONGRUN_WORKSPACE"])
sid = sess["id"]
cat = slash.catalog(sid)
check("C1 the catalogue serves the six built-ins",
      [c["id"] for c in cat["commands"]] == ids, [c["id"] for c in cat.get("commands", [])])
check("C2 the user commands ride along",
      any(c.get("name") == "deploy" for c in cat["user_commands"]), cat.get("user_commands"))
check("C3 the installed plugin is projected with its skill member",
      len(cat["plugins"]) == 1 and cat["plugins"][0]["name"] == "demo"
      and cat["plugins"][0]["members"][0]["name"] == "demo-skill"
      and cat["plugins"][0]["members"][0]["missing"] is False,
      cat.get("plugins"))
check("C4 the member title/description come from SKILL.md",
      cat["plugins"][0]["members"][0]["title"] == "Demo Skill"
      and "demo things" in cat["plugins"][0]["members"][0]["description"],
      cat["plugins"][0]["members"][0])
check("C5 the resolved documents folders are absolute under the workspace",
      cat["docs"].get("root", "").startswith(os.environ["LONGRUN_WORKSPACE"])
      and cat["docs"].get("rel_root") == ".longrun/documents", cat.get("docs"))
check("C6 /plugin:<name> builds a bounded member manifest",
      "PLUGIN ACTIVATION" in slash.plugin_block("demo")
      and "demo-skill" in slash.plugin_block("demo")
      and len(slash.plugin_block("demo").encode("utf-8")) <= slash.MAX_BLOCK,
      slash.plugin_block("demo")[:200])
check("C7 an unknown plugin is an explicit refusal, never prose",
      "no installed plugin named" in slash.plugin_block("no-such-plugin")
      and len(slash.plugin_block("no-such-plugin").encode("utf-8")) <= slash.MAX_BLOCK,
      slash.plugin_block("no-such-plugin")[:120])

# ------------------------------------------------------------- D: route wiring
check("D1 GET /api/slash dispatches the catalogue",
      'if path == "/api/slash":' in HTTPAPI and "slash.catalog(qs.get(\"session\")" in HTTPAPI)
check("D2 GET /api/docs dispatches the document status",
      'if path == "/api/docs":' in HTTPAPI and "docs.status(qs.get(\"session\")" in HTTPAPI)
check("D3 the document writes are behind one route pair",
      'if path in ("/api/docs/plan", "/api/docs/spec"):' in HTTPAPI
      and "_docs.create_plan if path.endswith" in HTTPAPI)
check("D4 the operator decisions are explicit actions (approve, implement, reject, unlock)",
      'if path in ("/api/docs/approve", "/api/docs/reject", "/api/docs/unlock",' in HTTPAPI
      and '"/api/docs/implement"' in HTTPAPI)

print("\n---\nv1051: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
