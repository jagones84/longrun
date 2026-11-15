#!/usr/bin/env python3
"""v1046 — one reset/compact rule: own session always, then the reporting line.

Operator 2026-11-15: *"every agent can compact/reset its session and the boss of a
team can compact/reset all the other sub/dispatchable agents of the team under its
line of command at any depth level."*

Measured before: `_may_manage` refused `caller == target`, so `sessions.reset` /
`sessions.compact` answered "the calling session cannot reset/compact itself",
while `context.compact` silently allowed self through a shortcut. Two doors, two
policies.

  A1 the rule allows the caller's OWN session
  A2 no caller in scope is still refused
  A3 sessions.reset on itself clears ITS transcript, not the sibling's
  A4 sessions.compact on itself runs (with the compactor stubbed)
  B1 a chief still reaches a grandchild (transitive)
  B2 a subordinate still cannot reach its chief
  B3 sideways is still refused
  C1 context.compact on ANOTHER session asks the same rule
  C2 context.compact on ITSELF asks the same rule (no shortcut left)
  C3 both doors refuse a foreign session with the same reason
  D1 the Architect remains above every team

Deterministic: no model, no network, no server (the compactor is stubbed).
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1046-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
sys.path.insert(0, os.path.join(REPO, "src"))

ROOT_SID, MID_SID, LOW_SID, OTHER_SID = (
    "111111111111", "222222222222", "333333333333", "444444444444")
with open(os.environ["LONGRUN_AGENTS_FILE"], "w", encoding="utf-8") as fh:
    json.dump({"agents": {
        ROOT_SID: {"id": "A1", "n": 1, "kind": "org", "session": ROOT_SID,
                   "name": "Root", "reports_to": None},
        MID_SID: {"id": "A2", "n": 2, "kind": "org", "session": MID_SID,
                  "name": "Mid", "reports_to": "A1"},
        LOW_SID: {"id": "A3", "n": 3, "kind": "org", "session": LOW_SID,
                  "name": "Low", "reports_to": "A2"},
        OTHER_SID: {"id": "A4", "n": 4, "kind": "org", "session": OTHER_SID,
                    "name": "Other", "reports_to": None},
    }, "seq": 4}, fh)

from longrun.core import server as _srv  # noqa: E402,F401 — import order (agent cycle)
from longrun.memory import stores  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _mk(sid, text="work"):
    stores.save_session({"id": sid, "title": "t-" + sid[:4],
                         "messages": [{"role": "user", "content": text * 20},
                                      {"role": "assistant", "content": "ok"}],
                         "tool_cards": [{"tool": "shell.exec"}],
                         "injects": [{"kind": "nudge"}]})


for _sid in (ROOT_SID, MID_SID, LOW_SID, OTHER_SID):
    _mk(_sid)

# --- A) the rule ----------------------------------------------------------
check("A1 the rule allows the caller's OWN session",
      T._may_manage(LOW_SID, LOW_SID)[0] is True, T._may_manage(LOW_SID, LOW_SID))
check("A2 no caller in scope is still refused",
      T._may_manage("", LOW_SID)[0] is False, T._may_manage("", LOW_SID))

out = T._sessions({"action": "reset", "session": LOW_SID}, LOW_SID)
check("A3 sessions.reset on itself runs", out.get("ok") is True, out)
check("A3b its own transcript is the one cleared",
      not (stores.load_session(LOW_SID) or {}).get("messages"),
      (stores.load_session(LOW_SID) or {}).get("messages"))
check("A3c the sibling keeps its transcript",
      bool((stores.load_session(MID_SID) or {}).get("messages")))

from longrun.core import httpapi  # noqa: E402

CALLS = []
_orig_usage, _orig_compact = httpapi.context_usage, httpapi.compact_session
httpapi.context_usage = lambda session_id=None: {"tokens_used": 900, "budget_tokens": 1000,
                                                 "pct": 90.0, "auto_compact_pct": 70,
                                                 "over_threshold": True, "messages": 42}
httpapi.compact_session = lambda sid, origin=None, **k: (
    CALLS.append(sid) or {"input_messages": 42, "output_tokens": 8, "compacted": 34,
                          "kept": 8, "input_tokens": 900, "summary": "s"})
try:
    out = T._sessions({"action": "compact", "session": LOW_SID}, LOW_SID)
    check("A4 sessions.compact on itself runs",
          out.get("ok") is True and CALLS == [LOW_SID], (out, CALLS))

    # --- B) the hierarchy is unchanged ------------------------------------
    CALLS.clear()
    out = T._sessions({"action": "compact", "session": LOW_SID}, ROOT_SID)
    check("B1 a chief still reaches a grandchild",
          out.get("ok") is True and CALLS == [LOW_SID], (out, CALLS))
    CALLS.clear()
    out = T._sessions({"action": "compact", "session": ROOT_SID}, LOW_SID)
    check("B2 a subordinate still cannot reach its chief", out.get("ok") is False, out)
    CALLS.clear()
    out = T._sessions({"action": "reset", "session": OTHER_SID}, ROOT_SID)
    check("B3 sideways is still refused", out.get("ok") is False, out)

    # --- C) ONE rule for both compact doors -------------------------------
    seen = []
    real_may = T._may_manage

    def _recorder(caller, target):
        seen.append((str(caller), str(target)))
        return real_may(caller, target)
    T._may_manage = _recorder
    try:
        CALLS.clear()
        out = T._context({"action": "compact", "session": ROOT_SID, "force": True}, LOW_SID)
        check("C1 context.compact on ANOTHER session asks the same rule",
              out.get("ok") is False and seen == [(LOW_SID, ROOT_SID)], (out, seen))
        seen.clear()
        CALLS.clear()
        out = T._context({"action": "compact", "force": True}, LOW_SID)
        check("C2 context.compact on ITSELF asks the same rule (no shortcut)",
              out.get("ok") is True and seen == [(LOW_SID, LOW_SID)], (out, seen))
        seen.clear()
        out = T._context({"action": "compact", "session": OTHER_SID, "force": True}, ROOT_SID)
        check("C3 both doors refuse a foreign session with the same reason",
              out.get("ok") is False and "not below" in str(out.get("error")), out)
    finally:
        T._may_manage = real_may
finally:
    httpapi.context_usage, httpapi.compact_session = _orig_usage, _orig_compact

# --- D) the Architect is still the operator's hand ------------------------
check("D1 the Architect remains above every team",
      T._may_manage("architect", OTHER_SID)[0] is True,
      T._may_manage("architect", OTHER_SID))

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
