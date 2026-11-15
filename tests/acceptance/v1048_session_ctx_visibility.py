#!/usr/bin/env python3
"""v1048 — every chat shows its context saturation, and a manager sees its team.

Operator 2026-11-16: *"each chat context status shall be visible in the sessions webui
even if not the active one selected at the moment … and the boss team of an agent
(report to) shall know the status of its sub agents teams (the ones that can be
dispatched by him) including llm, context saturation etcetera"*.

Before: the rail painted a ctx ring ONLY on the active row (`_ctxRingHtml` returned ""
for every other session), so switching chats was the only way to learn how full a
session was, and a manager had no per-agent status at all.

The number is ONE value, recorded where it is already known: at turn end the chat loop
writes `sess["ctx"]` from the router's real `prompt_tokens` of its last request and the
budget of the model that served it. `stores.list_sessions` serves it for every row (and
overlays the LIVE router number while a turn still runs), the rail paints a pill per
row, `sessions.list` prints it for a manager, and `/api/orbit/sessions` feeds the deck's
AGENTS table.

  A1 a persisted ctx reaches the session row (pct / tokens / budget)
  A2 a session that never ran has NO number (None, never a fabricated 0)
  A3 a running turn's router number overrides the persisted one
  B1 the turn records sess["ctx"] before the reply is saved
  C1 the rail renders the pill for a NON-active row too
  C2 sessions.list prints model and ctx for every row
  C3 the orbit roster carries ctx_pct
  C4 the deck's AGENTS row paints it beside the role
  D1 the ⋮ menu closes from ONE persistent listener (it re-opens after a close)

Deterministic: temp stores, no model, no network, no server.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1048-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
sys.path.insert(0, os.path.join(REPO, "src"))

SID, NEVER = "aaaaaaaaaaaa", "bbbbbbbbbbbb"

from longrun.core import server as _srv  # noqa: E402,F401 — import order (agent cycle)
from longrun.memory import stores  # noqa: E402
from longrun.tools import tools as T  # noqa: E402


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")
AGENT_SRC = _read("src", "longrun", "agent", "agent.py")
REGISTRY_SRC = _read("src", "longrun", "orbit", "registry.py")
ORBIT = _read("src", "longrun", "orbit", "web", "orbit.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def seed(sid, ctx=None):
    doc = {"id": sid, "title": "t-" + sid[:4],
           "messages": [{"role": "user", "content": "hi"},
                        {"role": "assistant", "content": "ok"}]}
    if ctx:
        doc["ctx"] = ctx
    stores.save_session(doc, truncate=True)


def row(sid):
    for r in stores.list_sessions():
        if r.get("id") == sid:
            return r
    return {}


# The background backfill runs its own thread; keep it out of a deterministic test.
stores._ctx_backfill_request = lambda sid: None


# --- A) the row carries the real number -----------------------------------
seed(SID, {"tokens_used": 640, "budget_tokens": 1000, "pct": 64.0,
           "model": "local:x", "at": 1.0})
r = row(SID)
check("A1 a persisted ctx reaches the session row",
      r.get("ctx_pct") == 64.0 and r.get("ctx_tokens") == 640
      and r.get("ctx_budget") == 1000, r)

seed(NEVER)
r2 = row(NEVER)
check("A2 a session that never ran has NO number (never a fabricated 0)",
      r2.get("ctx_pct") is None and r2.get("ctx_tokens") is None, r2)

# A3 — the live router number is fresher than the persisted one: a turn in flight.
stores._REAL_PROMPT_TOKENS[SID] = 800
r3 = row(SID)
check("A3 a running turn's router number overrides the persisted one",
      r3.get("ctx_pct") == 80.0 and r3.get("ctx_tokens") == 800, r3)
stores._REAL_PROMPT_TOKENS.pop(SID, None)

# A4 — an old session (no recorded ctx) is served the background value once computed.
stores._CTX_BACKFILL[NEVER] = {"pct": 12.5, "tokens_used": 125, "budget_tokens": 1000}
r4 = row(NEVER)
check("A4 the background pass fills a session that never recorded a number",
      r4.get("ctx_pct") == 12.5 and r4.get("ctx_tokens") == 125, r4)
stores._CTX_BACKFILL.pop(NEVER, None)

# --- B) where the number is written ---------------------------------------
_i_ctx = AGENT_SRC.find('sess["ctx"] = {"tokens_used"')
_i_append = AGENT_SRC.find('reply = append_message(sess, "assistant", content')
check("B1 the turn records sess[\"ctx\"] before the reply is saved",
      0 < _i_ctx < _i_append
      and "_REAL_PROMPT_TOKENS.get(sess[\"id\"])" in AGENT_SRC
      and "context_budget(model)" in AGENT_SRC, (_i_ctx, _i_append))

# --- C) every surface -----------------------------------------------------
_i_ring = HTML.find("function _ctxRingHtml(")
_ring = HTML[_i_ring:HTML.find("function _repaintCtx(", _i_ring)]
check("C1 the rail renders the pill for a NON-active row too",
      "if (!isActive && pct == null) return \"\";" in _ring
      and "const isActive = s.id === sessionId;" in _ring
      and "s.ctx_pct" in _ring, _ring[:200])

TOOLS_SRC = _read("src", "longrun", "tools", "tools.py")
check("C2 sessions.list prints model and ctx for every row",
      "model=%s%s" in TOOLS_SRC and "ctx=%s%%" in TOOLS_SRC
      and "r.get(\"ctx_pct\")" in TOOLS_SRC, "")

check("C3 the orbit roster carries ctx_pct",
      '"ctx_pct": s.get("ctx_pct")' in REGISTRY_SRC
      and '"ctx_tokens": s.get("ctx_tokens")' in REGISTRY_SRC, "")

check("C4 the deck's AGENTS row paints it beside the role",
      'class="actx' in ORBIT and "a.ctx_pct" in ORBIT
      and "ctxChip" in ORBIT and 'ctxChip + \'<span class="arole">' in ORBIT, "")

# --- D) the ⋮ menus re-open after a close ---------------------------------
_i_open = HTML.find("async function openSessMenu(")
_open = HTML[_i_open:HTML.find("/* The ONE rail team menu", _i_open)]
_i_team = HTML.find("function openTeamMenu(")
_team = HTML[_i_team:HTML.find("/* The ⊕ on a real team header", _i_team)]
check("D1 the ⋮ menus close from ONE persistent listener (they re-open after a close)",
      "closeSessMenu, { once: true }" not in HTML
      and "function _wireSessMenuClose(" in HTML
      and "_wireSessMenuClose();" in HTML
      and "{ once: true }" not in _open and "{ once: true }" not in _team,
      _open[-120:])
check("D2 both rail menus are the same body-level popover, placed from their trigger",
      "document.body.appendChild(m)" in _open and "_placeMenu(m," in _open
      and "document.body.appendChild(m)" in _team and "_placeMenu(m," in _team, "")

with open(os.environ["LONGRUN_AGENTS_FILE"], "w", encoding="utf-8") as fh:
    json.dump({"agents": {}, "seq": 0}, fh)

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
