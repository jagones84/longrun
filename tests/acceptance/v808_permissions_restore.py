#!/usr/bin/env python3
"""v808 — a removed shipped rule can be put back (2026-11-05).

Operator: *"but i can delete hard blocks but never set them again to defaults!
if i delete a line of the defaults it can be put again, not lost forever"*.

The overlay only stores a DELTA against `config/tools.yaml`, so deleting a
shipped rule left it shadowed by the reduced list with no way back. Now:

  A  the catalogue still knows the SHIPPED list (`deny_default` /
     `always_ask_default`), resolved through the namespace key exactly like
     `tool_spec` resolves the policy;
  B  `POST /api/tools {tool, reset: ["deny"]}` puts the field back to the
     shipped value and the overlay stops carrying it — the default is restored,
     not copied into a second file;
  C  the shipped YAML is never edited (it stays the hand-edited source of truth);
  D  the Permissions page lists the removed defaults with one ↺ per rule and one
     "↺ all" per section, all through POST /api/tools.

Deterministic: temp data dir, no model, no network.
Run: python3 tests/acceptance/v808_permissions_restore.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v808-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402,F401  (import order)
from longrun.core import api_v02  # noqa: E402
from longrun.tools import registry  # noqa: E402

UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
CFG = open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8").read()
_CFG_MTIME = os.path.getmtime(registry.CONFIG_YAML)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def row(name):
    for t in registry.catalog():
        if t.get("name") == name:
            return t
    return {}


def overlay_text():
    path = registry.OVERLAY_YAML
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---- A: the shipped list is still known ----------------------------------
_ship = registry.shipped_tool("shell.exec") or {}
check("A1 the namespace key answers for the namespaced tool",
      isinstance(_ship.get("deny"), list) and len(_ship.get("deny")) >= 3, _ship.get("deny"))
_git_ship = registry.shipped_tool("git.run") or {}
check("A2 git.run reads the shipped `git` block",
      "^push(\\s|$)" in (_git_ship.get("always_ask") or []), _git_ship)
check("A3 an unknown tool has no shipped entry",
      registry.shipped_tool("nope.nope") is None)
_row = row("shell.exec")
check("A4 the catalogue carries the shipped defaults",
      (_row.get("deny_default") or []) == (_ship.get("deny") or []), _row.get("deny_default"))
check("A5 git.run publishes its always-ask default",
      (_row_git := row("git.run")).get("always_ask_default") == ["^push(\\s|$)"], _row_git)

# ---- B: delete a shipped rule, then put it back --------------------------
_first = _ship["deny"][0]
_r = api_v02.update_policy({"tool": "shell.exec", "deny": _ship["deny"][1:]})
registry.load_config(reload=True)
check("B1 the rule can be removed", _r.get("ok") is True, _r)
_d, _why = registry.classify("shell.exec", {"command": "rm -rf / "})
check("B2 with the rule gone the command is no longer hard-blocked",
      _d != "denied", (_d, _why))
check("B3 the removed rule is STILL offered as a default",
      _first in (row("shell.exec").get("deny_default") or []))

_r2 = api_v02.update_policy({"tool": "shell.exec", "reset": ["deny"]})
registry.load_config(reload=True)
check("B4 reset is accepted", _r2.get("ok") is True, _r2)
check("B5 the shipped list is back", (row("shell.exec").get("deny") or []) == _ship["deny"],
      row("shell.exec").get("deny"))
_d2, _why2 = registry.classify("shell.exec", {"command": "rm -rf / "})
check("B6 the command is refused again", _d2 == "denied", (_d2, _why2))
_ov_text = overlay_text()
try:
    import yaml
    _ov = (yaml.safe_load(_ov_text) or {}) if _ov_text.strip() else {}
except Exception:  # noqa: BLE001 — no overlay file in this run
    _ov = {}
check("B7 the overlay no longer overrides the field",
      "deny" not in (((_ov.get("tools") or {}).get("shell.exec")) or {}), _ov_text[-200:])
check("B8 the shipped file was never rewritten (the overlay is the operator's layer)",
      os.path.getmtime(registry.CONFIG_YAML) == _CFG_MTIME and "^myblock$" not in CFG)

# ---- B2: the same restore for the always-ask list ------------------------
_ask = (_git_ship.get("always_ask") or ["^push(\\s|$)"])[0]
api_v02.update_policy({"tool": "git.run", "always_ask": []})
registry.load_config(reload=True)
check("B9 always-ask can be emptied", (row("git.run").get("always_ask") or []) == [])
check("B10 it is still listed as a default",
      row("git.run").get("always_ask_default") == [_ask])
api_v02.update_policy({"tool": "git.run", "reset": ["always_ask"]})
registry.load_config(reload=True)
check("B11 reset brings it back", row("git.run").get("always_ask") == [_ask],
      row("git.run").get("always_ask"))

# ---- C: the API refuses a nonsense field --------------------------------
_bad = api_v02.update_policy({"tool": "shell.exec", "reset": ["nonsense"]})
check("C1 an unknown field is refused",
      _bad.get("ok") is False and "unknown field" in str(_bad.get("error")), _bad)

# ---- D: the Permissions page offers the way back ------------------------
check("D1 the page lists the removed defaults",
      "shipped default(s) removed" in UI and "key + \"_default\"" in UI)
check("D2 one rule can be restored", "data-permrest=" in UI)
check("D3 the whole section can be restored", "data-permrest" in UI
      and "data-permreset=" in UI and "reset: [key]" in UI)
check("D4 restoring goes through POST /api/tools (no second endpoint)",
      'api("POST", "/api/tools", body)' in UI
      and 'api("POST", "/api/tools", { tool: (tools[Number(i)] || {}).name, reset: [key] })' in UI)
check("D5 an empty recover block renders nothing",
      "!items.length ? \"\" :" in UI)

print("\n---")
print("v808: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
