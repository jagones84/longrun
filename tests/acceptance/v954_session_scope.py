#!/usr/bin/env python3
"""v954 — messaging and context belong to the same reporting line as jobs.

The `job.*` doors now obey ALL · SUBTREE · NOTHING (v953). Two session doors did
not: `sessions.send` could hand a message to ANY session — and an idle peer
starts a real turn, i.e. work with no job and no check — and `sessions.read`
could open ANY transcript. The Architect was also refused when it tried to
reset a team's chat, though it is the operator's own hand.

Rule pinned here (the same relationship, both directions):
  down   your subtree
  up     your reporting chain
  else   refused (exit 126) — a grant does NOT widen it
  the Architect session (`longrunAgent*`) and a caller with no org record (the
  operator's own chat) are unrestricted.

Deterministic: temp stores, no server, no model, no network, no delivery.
Run: python3 tests/acceptance/v954_session_scope.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v954-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents as AG           # noqa: E402
from longrun.agent import architect as LRA      # noqa: E402
from longrun.memory import stores as STORES      # noqa: E402
from longrun.tools import tools as T             # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


reg = AG.REGISTRY
LEAD = reg.designate("s-lead", name="Lead")["agent"]["id"]
SUB = reg.designate("s-sub", name="Sub", reports_to="s-lead")["agent"]["id"]
WORKER = reg.designate("s-worker", name="Worker", reports_to="s-sub")["agent"]["id"]
OUTSIDE = reg.designate("s-outside", name="Outsider")["agent"]["id"]
GRANTED = reg.designate("s-granted", name="Granted")["agent"]["id"]
for _sid in ("s-lead", "s-sub", "s-worker", "s-outside", "s-granted", "s-plain"):
    STORES.get_or_create_session(_sid)
LRA.set_session_access("s-granted", True)

# ---- A) the predicate: down, up, never sideways ---------------------------
check("A1 a lead reaches its direct report and its grandchild",
      T._may_message("s-lead", "s-sub")[0] is True
      and T._may_message("s-lead", "s-worker")[0] is True)
check("A2 a worker reaches its manager (report UP the line)",
      T._may_message("s-worker", "s-sub")[0] is True
      and T._may_message("s-worker", "s-lead")[0] is True)
check("A3 two unrelated agents cannot reach each other",
      T._may_message("s-sub", "s-outside")[0] is False
      and T._may_message("s-outside", "s-lead")[0] is False)
check("A4 a GRANT does not widen messaging",
      T._may_message("s-granted", "s-outside")[0] is False)
check("A5 an agent cannot open a session that is not in the org",
      T._may_message("s-lead", "s-plain")[0] is False)
check("A6 the Architect and the operator's own chat are unrestricted",
      T._may_message("longrunAgent", "s-outside")[0] is True
      and T._may_message("longrunAgent_1", "s-outside")[0] is True
      and T._may_message("", "s-outside")[0] is True
      and T._may_message("operator-chat", "s-outside")[0] is True)
check("A7 a session cannot message itself through the tool",
      T._may_message("s-lead", "s-lead")[0] is False)

# ---- B) the tool refuses before delivering --------------------------------
_sent = T._sessions({"action": "send", "session": "s-outside", "message": "do X"},
                    "s-lead")
check("B1 send to an unrelated agent is refused with 126 (no delivery)",
      _sent.get("ok") is False and _sent.get("exit_code") == 126
      and _sent.get("permission_denied") is True, _sent.get("error"))
_read = T._sessions({"action": "read", "session": "s-outside"}, "s-lead")
check("B2 read of an unrelated agent's transcript is refused with 126",
      _read.get("ok") is False and _read.get("exit_code") == 126, _read.get("error"))
_own = T._sessions({"action": "read", "session": "s-sub"}, "s-lead")
check("B3 read of your own report still works",
      _own.get("ok") is True and "session" in _own, _own.get("error"))
_arb = T._sessions({"action": "read", "session": "s-outside"}, "longrunAgent")
check("B4 the Architect reads any session",
      _arb.get("ok") is True, _arb.get("error"))

# ---- C) the Architect may tidy any chat -----------------------------------
check("C1 the Architect may reset/compact any session",
      T._may_manage("longrunAgent", "s-outside")[0] is True
      and T._may_manage("longrunAgent_7", "s-outside")[0] is True)
check("C2 a chief keeps the reporting-line rule (never sideways)",
      T._may_manage("s-lead", "s-worker")[0] is True
      and T._may_manage("s-lead", "s-outside")[0] is False)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
