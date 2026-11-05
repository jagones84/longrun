#!/usr/bin/env python3
"""v806 — Permissions is its own page; an always-ask rule survives FULL; the system
agent can never park a HUMAN IN THE LOOP card (2026-11-05).

Operator: *"Build permission page out of the tools e approval. Search diff of line
between permission and approvals. Git push in full does not ask for approval …
the human in the loop page appeared in A1 session why appeared blocking the work? I
don't want that."*

  A  the editor left Tools & approvals and became Settings ▸ Permissions, with the
     distinction stated where the reader lands;
  B  `always_ask` is a real policy field: it reaches a human even with
     approvals.mode=full, it round-trips through POST /api/tools, and the shipped
     git tool protects `push` with it;
  C  the SYSTEM agent (longrunAgent / A1) gets the "nobody is attached" nudge
     instead of a card — the automatic-looking block the operator reported;
  D  the mobile layout rules exist and are declared after the base ones (a media
     query earlier in the sheet would lose to them).

Deterministic: temp data dir, no model, no network.
Run: python3 tests/acceptance/v806_permissions_split.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v806-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402,F401
from longrun.core import api_v02  # noqa: E402
from longrun.tools import registry  # noqa: E402

UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
CFG = open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8").read()
AGENT = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
             encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- A: the page exists and is separate ---------------------------------
check("A1 Permissions is a Settings category",
      '["permissions", "Permissions"]' in UI)
check("A2 it has its own panel", 'data-cat="permissions"' in UI and 'id="permsPanel"' in UI)
check("A3 opening it renders through the same API",
      'renderPermissions($("permsPanel")' in UI)
check("A4 the card left Tools & approvals",
      "permsCard" not in UI.split("function renderPermissions")[0].split("function renderTools")[1])
check("A5 Tools & approvals links to it", "data-goperms" in UI)
check("A6 the difference is stated where the reader lands",
      "checked <b>before</b> approvals" in UI and "Approvals panel, not here" in UI)

# ---- B: always_ask survives FULL ----------------------------------------
check("B1 the shipped git tool protects push",
      "always_ask:" in CFG and "^push(\\\\s|$)" in CFG.split("always_ask:")[1][:120],
      CFG.split("always_ask:")[1][:120] if "always_ask:" in CFG else "missing")
registry.load_config(reload=True)
_d1, _r1 = registry.classify("git", {"args": "push origin Experimental-Refactor"})
check("B2 push asks even in the default policy", _d1 == "required", (_d1, _r1))
api_v02.update_policy({"approvals": {"mode": "full"}})
registry.load_config(reload=True)
_d2, _r2 = registry.classify("git", {"args": "push origin main"})
check("B3 FULL does not skip an always-ask rule", _d2 == "required", (_d2, _r2))
check("B4 the reason names the rule", "always-ask" in _r2, _r2)
_d3, _r3 = registry.classify("git", {"args": "status --short"})
check("B5 the rest of the tool stays automatic in FULL", _d3 == "auto", (_d3, _r3))
_d4, _r4 = registry.classify("shell", {"command": "echo hi"})
check("B6 unrelated tools are untouched", _d4 == "auto", (_d4, _r4))
api_v02.update_policy({"tool": "shell", "always_ask": ["^echo\\s+secret"]})
registry.load_config(reload=True)
_d5, _r5 = registry.classify("shell", {"command": "echo secret"})
check("B7 a rule can be added through POST /api/tools", _d5 == "required", (_d5, _r5))
api_v02.update_policy({"tool": "shell", "always_ask": []})
registry.load_config(reload=True)
_d6, _r6 = registry.classify("shell", {"command": "echo secret"})
check("B8 and removed again", _d6 == "auto", (_d6, _r6))
check("B9 the catalog exposes the field",
      "always_ask" in [t for t in registry.catalog() if t["name"] == "git.run"][0])
api_v02.update_policy({"approvals": {"mode": "normal"}})

# ---- C: the system agent cannot open a card -----------------------------
check("C1 the branch refuses a system session",
      'bool(sess.get("system")) and not goal_mode' in AGENT)
check("C2 the nudge says why", "or the system agent" in AGENT)
check("C3 a card is still ONE door (human.ask)",
      AGENT.count('on_event("hitl.request"') == 1)

# ---- D: mobile -----------------------------------------------------------
_mq = UI.split("@media (max-width: 640px)")
check("D1 the phone layout is full width with no overflow",
      "width: 100% !important; max-width: 100vw !important" in UI
      and "#settingsWin .sw-main { padding: 12px; overflow-x: hidden; }" in UI,
      "settings mobile rule missing")
check("D2 the rule row wraps on a phone",
      ".perm-row { flex-wrap: wrap; align-items: flex-start; }" in UI)
check("D3 the wrap rule is declared AFTER the base rule (or it would lose)",
      UI.rfind(".perm-row { flex-wrap: wrap; align-items: flex-start; }")
      > UI.find(".perm-row { display: flex;"))
check("D4 the tools header wraps instead of squeezing",
      ".tools-head { display: flex; flex-wrap: wrap" in UI)
check("D5 the add-rule controls stack on a phone",
      ".perm-add > * { flex: 1 1 100%; }" in UI)
check("D6 the 19-item nav becomes a select on a phone",
      'id="swNavSel"' in UI and "#settingsWin .sw-nav button { display: none; }" in UI)
check("D7 the select is hidden on a desktop",
      "#settingsWin .sw-nav-sel { display: none; }" in UI)

print("\n---")
print("v806: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
