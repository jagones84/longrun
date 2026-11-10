#!/usr/bin/env python3
"""v939 — a chief frees the context of its own team, at any level.

Operator: *"hai un team sotto di te, puoi resettare le loro sessions? … espandi i
tools per poter lanciare comandi di compattazione e reset chat dal capo team a
quelli sotto … per qualsiasi livello sotto, se dello stesso team e nella gerarchia
di riporto … verifica se ci sono i tools e sono allowed correttamente."*

`sessions.compact` / `sessions.reset` exist now, and `context.compact` can no
longer target ANY session: the target must be BELOW the caller in the reporting
line (transitive), never itself, never upward or sideways.

Deterministic: no model, no network, no server (the compactor is stubbed).

Run: python3 tests/acceptance/v939_team_session_tools.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v939-")
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
from longrun.agent import agents  # noqa: E402
from longrun.tools import tools as T  # noqa: E402
from longrun.tools import registry as R  # noqa: E402

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

REG = agents.REGISTRY

# --- A) the org rule -------------------------------------------------------
check("A1 a grandchild is below the root (transitive)",
      REG.can_manage(ROOT_SID, LOW_SID) is True)
check("A2 the mid manager may manage its direct report",
      REG.can_manage(MID_SID, LOW_SID) is True)
check("A3 upward is refused", REG.can_manage(LOW_SID, ROOT_SID) is False)
check("A4 sideways/out of line is refused", REG.can_manage(ROOT_SID, OTHER_SID) is False)
check("A5 itself is refused", REG.can_manage(ROOT_SID, ROOT_SID) is False)

# --- B) reset, through the real store -------------------------------------
out = T._sessions({"action": "reset", "session": LOW_SID}, ROOT_SID)
check("B1 the root resets a grandchild", out.get("ok") is True, out)
low = stores.load_session(LOW_SID) or {}
check("B2 messages, cards and injects are gone",
      not low.get("messages") and not low.get("tool_cards") and not low.get("injects"), low)
check("B3 other sessions are untouched",
      bool((stores.load_session(MID_SID) or {}).get("messages")))

_mk(LOW_SID)
out = T._sessions({"action": "reset", "session": ROOT_SID}, LOW_SID)
check("B4 a subordinate cannot reset its chief", out.get("ok") is False
      and "not below" in str(out.get("error")), out)
check("B5 the chief's transcript survives",
      bool((stores.load_session(ROOT_SID) or {}).get("messages")))

out = T._sessions({"action": "reset", "session": OTHER_SID}, ROOT_SID)
check("B6 an unrelated session is refused", out.get("ok") is False, out)
out = T._sessions({"action": "reset", "session": ROOT_SID}, ROOT_SID)
check("B7 resetting itself through this rule is refused", out.get("ok") is False, out)

# --- C) compact, with the compactor stubbed -------------------------------
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
    out = T._sessions({"action": "compact", "session": LOW_SID}, ROOT_SID)
    check("C1 the root compacts a grandchild", out.get("ok") is True and CALLS == [LOW_SID],
          (out, CALLS))
    CALLS.clear()
    out = T._sessions({"action": "compact", "session": ROOT_SID}, LOW_SID)
    check("C2 a subordinate cannot compact its chief",
          out.get("ok") is False and CALLS == [], (out, CALLS))
    CALLS.clear()
    out = T._context({"action": "compact", "session": ROOT_SID, "force": True}, LOW_SID)
    check("C3 context.compact no longer targets anybody's session",
          out.get("ok") is False and CALLS == [], (out, CALLS))
    CALLS.clear()
    out = T._context({"action": "compact", "force": True}, LOW_SID)
    check("C4 context.compact still works on the caller's own session",
          out.get("ok") is True and CALLS == [LOW_SID], (out, CALLS))
finally:
    httpapi.context_usage, httpapi.compact_session = _orig_usage, _orig_compact

# --- D) the tools are advertised ------------------------------------------
check("D1 sessions.compact is a real tool",
      R.tool_spec("sessions.compact") is not None)
check("D2 sessions.reset is a real tool",
      R.tool_spec("sessions.reset") is not None)
_spec = json.dumps(R._LEGACY_SCHEMAS.get("sessions") or {})
check("D3 the schema advertises both actions and the force flag",
      '"compact"' in _spec and '"reset"' in _spec and '"force"' in _spec)
check("D4 the schema states the reporting-line rule",
      "reporting line" in _spec, _spec[:120])

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
