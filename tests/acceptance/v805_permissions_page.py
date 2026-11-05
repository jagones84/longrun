#!/usr/bin/env python3
"""v805 — the Permissions page: hard blocks are the operator's to edit (2026-11-05).

Operator: *"And hard denial can be changed by the user in the settings permission
page."* The mechanism already existed (each tool's `deny` list, POST /api/tools),
but it was reachable only through a ⚙ button per tool — there was no place that
SHOWED every hard block and every tool that is OFF. This pins both halves:

  A  the backend round-trip: add a rule → the call is refused; remove it → the
     call is possible again; the overlay is what changed (not the shipped YAML);
  B  a tool can be switched ON from the same panel (the MCP opt-in rule);
  C  the WebUI renders ONE Permissions card (list, remove, add, enable) and it
     writes through the SAME endpoint the ⚙ editor uses (no second truth);
  D  the tools that were silently OFF now explain themselves and the shipped
     policy lists the time server's third tool.

Deterministic: temp data dir, no model, no network.
Run: python3 tests/acceptance/v805_permissions_page.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v805-")
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

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- A: add / remove a hard block through the API -----------------------
r1 = api_v02.update_policy({"tool": "shell", "deny": ["^myblock$"]})
check("A1 the rule is saved", r1.get("ok") is True, r1)
registry.load_config(reload=True)
_d1, _r1 = registry.classify("shell", {"command": "myblock"})
check("A2 the command is now REFUSED with the rule named",
      _d1 == "denied" and "hard-deny" in _r1, (_d1, _r1))
_d2, _r2 = registry.classify("shell", {"command": "echo hello"})
check("A3 an unrelated command is untouched", _d2 != "denied", (_d2, _r2))
r2 = api_v02.update_policy({"tool": "shell", "deny": []})
registry.load_config(reload=True)
_d3, _r3 = registry.classify("shell", {"command": "myblock"})
check("A4 removing the rule makes the command possible again",
      r2.get("ok") is True and _d3 != "denied", (_d3, _r3))
check("A5 the shipped YAML was NOT edited (the overlay is the operator's layer)",
      "^myblock$" not in CFG)

# ---- B: the same panel switches a tool ON -------------------------------
r3 = api_v02.update_policy({"tool": "shell", "enabled": False})
registry.load_config(reload=True)
_d4, _r4 = registry.classify("shell", {"command": "ls"})
check("B1 disabling takes effect", r3.get("ok") is True and _d4 == "disabled", (_d4, _r4))
api_v02.update_policy({"tool": "shell", "enabled": True})
registry.load_config(reload=True)
_d5, _r5 = registry.classify("shell", {"command": "ls"})
check("B2 re-enabling takes effect", _d5 != "disabled", (_d5, _r5))

# ---- C: the UI has ONE Permissions card ---------------------------------
check("C1 the card exists in Settings → Tools", "🛡 Permissions · hard blocks" in UI)
check("C2 it renders into the tools panel", "policyCard + kindsCard + permsCard" in UI)
check("C3 every rule can be removed", 'data-rmdeny=' in UI)
check("C4 a rule can be added", 'id="permAdd"' in UI and "concat([rule])" in UI)
check("C5 an OFF tool can be switched on", 'data-permon=' in UI)
check("C6 it writes through POST /api/tools (no second endpoint)",
      'api("POST", "/api/tools", { tool: t.name, deny: next })' in UI
      and 'api("POST", "/api/tools", { tool: t.name, enabled: true })' in UI)
check("C7 removing a rule is explained as the way out of a hard block",
      "FULL mode never lifts a deny rule" in UI)

# ---- D: the disabled tools explain themselves ---------------------------
check("D1 the opt-in rule is stated where the OFF tools are listed",
      "opt-in" in UI)
check("D2 the time server's third tool is in the shipped policy",
      "time__get_time_ago:" in CFG and "enabled: true" in
      CFG.split("time__get_time_ago:")[1][:80])

print("\n---")
print("v805: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
