#!/usr/bin/env python3
"""v1039 — a plugin is a CONTAINER (skills + MCP servers); a Matrix module is its own kind.

The defect this pins: `plugin` used to mean an in-process Matrix module, so the
Plugin tab could only ever show the modules that ship with the harness — no
commercial plugin concept existed. A plugin now names its members and writes
nothing itself:

  A  the five kinds, and the shipped starter-kit bundle
  B  refusals: no members, an unsupported member kind, a duplicate, an unpinned member
  C  a bundle installs each member through its OWNER and records ONE row
  D  a failing member rolls the bundle back (nothing half-installed)
  E  rm removes only the members this install created
  F  the page names the five kinds and prints what a plugin will install
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-v1039-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_TMP, "data", "sessions")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_TMP, "skills")
os.environ["LONGRUN_SKILLS_LOCAL_DIR"] = os.path.join(_TMP, "skills", "local")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import market  # noqa: E402
from longrun.interop import mcp_client  # noqa: E402
from longrun.memory import skills  # noqa: E402

mcp_client.CONFIG_LOCAL_JSON_PATH = os.path.join(os.environ["LONGRUN_CONFIG_DIR"],
                                                 "mcp_clients.local.json")
mcp_client.CONFIG_LOCAL_PATH = os.path.join(os.environ["LONGRUN_CONFIG_DIR"],
                                            "mcp_clients.local.yaml")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def by_id():
    return {i["id"]: i for i in market.catalog()[0]}


def catalog(rows):
    path = market._local_catalog_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"schema": market.SCHEMA, "items": rows}, f)


def skill_dir(name):
    return os.path.join(os.environ["LONGRUN_SKILLS_DIR"], "market", name)


def clients():
    return mcp_client.load_doc().get("clients") or {}


GOOD_SKILL = {"kind": "skill", "name": "release-notes",
              "sha256": "58cd588464583aa27bb706ab06c4f6a28050a6778088097eaa6e4d9b98c9780a",
              "source": {"type": "bundled", "path": "market/skills/release-notes/SKILL.md"}}
GOOD_MCP = {"kind": "mcp", "name": "filesystem",
            "server": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem",
                                                   "/tmp"]}}


# ── A: the kind model and the shipped bundle ────────────────────────────────
check("A1 five kinds: plugin, skill, mcp, connector, matrix",
      market.KINDS == ("plugin", "skill", "mcp", "connector", "matrix"), market.KINDS)
items = by_id()
check("A2 the shipped catalogue carries an installable plugin",
      items["plugin/starter-kit"]["installable"] is True, items["plugin/starter-kit"])
check("A3 the bundle declares a skill and an MCP server",
      [(m["kind"], m["name"]) for m in items["plugin/starter-kit"]["members"]]
      == [("skill", "release-notes"), ("mcp", "filesystem")],
      items["plugin/starter-kit"]["members"])
mods = [i for i in items.values() if i["kind"] == "matrix"]
check("A4 the Matrix modules are their own kind, present and never installable",
      len(mods) >= 5 and all(m["present"] and not m["installable"] for m in mods), len(mods))
check("A5 the `matrix/` ids are all of kind matrix",
      all(i["kind"] == "matrix" for i in items.values() if i["id"].startswith("matrix/")))

# ── B: what is refused, by name ─────────────────────────────────────────────
catalog([{"id": "plugin/none", "kind": "plugin", "name": "none", "title": "None"}])
check("B1 a plugin with no members is refused",
      "no members" in market.install("plugin/none")["error"])
catalog([{"id": "plugin/cmd", "kind": "plugin", "name": "cmd", "title": "Cmd",
          "members": [{"kind": "command", "name": "standup"}]}])
check("B2 an unsupported member kind is refused by name",
      "unsupported member kind: command" in market.install("plugin/cmd")["error"])
catalog([{"id": "plugin/dupe", "kind": "plugin", "name": "dupe", "title": "Dupe",
          "members": [GOOD_SKILL, dict(GOOD_SKILL)]}])
check("B3 a duplicated member is refused",
      "duplicate member" in market.install("plugin/dupe")["error"])
catalog([{"id": "plugin/unpinned", "kind": "plugin", "name": "unpinned", "title": "Unpinned",
          "members": [{"kind": "skill", "name": "loose",
                       "source": {"type": "https", "url": "https://h.test/x.zip"}}]}])
check("B4 a member without a digest makes the whole entry not installable",
      by_id()["plugin/unpinned"]["installable"] is False)
check("B5 nothing was installed by any refusal", market.installed()["count"] == 0)

# ── D: a failing member rolls the bundle back ───────────────────────────────
catalog([{"id": "plugin/broken", "kind": "plugin", "name": "broken", "title": "Broken",
          "members": [GOOD_SKILL,
                      {"kind": "skill", "name": "ghost", "sha256": "a" * 64,
                       "source": {"type": "bundled", "path": "market/skills/ghost/SKILL.md"}}]}])
broken = market.install("plugin/broken")
check("D1 the install fails naming the member", broken.get("ok") is False
      and "member ghost (skill)" in broken.get("error", ""), broken)
check("D2 the member that DID install was rolled back",
      not os.path.isdir(skill_dir("release-notes")) and market.installed()["count"] == 0,
      os.path.isdir(skill_dir("release-notes")))

# ── C: the happy path goes through the owners ───────────────────────────────
os.remove(market._local_catalog_path())
kit = market.install("plugin/starter-kit")
check("C1 the bundle installs", kit.get("ok") is True and kit.get("target") == "2 members", kit)
check("C2 the skill landed through memory.skills", os.path.isdir(skill_dir("release-notes")))
check("C3 the MCP server landed through the client document, DISABLED",
      clients().get("filesystem", {}).get("enabled") is False, clients().get("filesystem"))
rec = [r for r in market.installed()["installed"] if r["id"] == "plugin/starter-kit"]
check("C4 ONE record carries both members",
      len(rec) == 1 and len(rec[0].get("members") or []) == 2, rec)
check("C5 the members were marked as created by this install",
      all(m.get("created") for m in rec[0]["members"]), rec[0]["members"])
aud = market.audit()
check("C6 audit sees the plugin as live", aud["drift"] == 0
      and aud["rows"][0]["state"] == "ok", aud["rows"])

# ── E: rm removes only what the install created ─────────────────────────────
gone = market.forget("plugin/starter-kit", remove_target=True)
check("E1 rm removed the skill and the client",
      gone.get("ok") is True and not os.path.isdir(skill_dir("release-notes"))
      and "filesystem" not in clients(),
      (gone, os.path.isdir(skill_dir("release-notes")), list(clients())))

market.install("skill/release-notes")
check("E2 a plain skill install is the baseline", os.path.isdir(skill_dir("release-notes")))
kit2 = market.install("plugin/starter-kit")
rec2 = [r for r in market.installed()["installed"] if r["id"] == "plugin/starter-kit"][0]
created = {m["name"]: m["created"] for m in rec2["members"]}
check("E3 a member that already existed is NOT marked created",
      kit2.get("ok") is True and created.get("release-notes") is False
      and created.get("filesystem") is True, created)
market.forget("plugin/starter-kit", remove_target=True)
check("E4 rm leaves the pre-existing skill alone and removes the new client",
      os.path.isdir(skill_dir("release-notes")) and "filesystem" not in clients())
market.forget("skill/release-notes", remove_target=True)

# ── F: the page names the five kinds ────────────────────────────────────────
JS = open(os.path.join(REPO, "webui", "assets", "market.js"), encoding="utf-8").read()
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("F1 the sections are ordered plugin → skill → mcp → connector → matrix",
      'const KIND_ORDER = ["plugin", "skill", "mcp", "connector", "matrix"]' in JS)
check("F2 the legend says what a plugin is",
      "Plugin = skills + MCP servers" in UI and "Matrix = in-process tool" in UI)
check("F3 there is a Matrix tab and no plugin/module conflation",
      'data-kind="matrix"' in UI and "Matrix</button>" in UI)
check("F4 the card prints the member summary",
      "MEMBER_NOUN" in JS and '" members"' in JS and "item.members" in JS)
check("F5 the disabled plugin says WHY, never 'no sha256'",
      "a member is missing its digest or its server" in JS)

print("\n---\nv1039: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
