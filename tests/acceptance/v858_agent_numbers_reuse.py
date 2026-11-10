#!/usr/bin/env python3
"""v858 — an agent number belongs to a LIVE object, not to history.

Measured on the live store 2026-11-07: `seq` 299, 204 records for 150 sessions —
54 records pointed at session files that no longer exist (highest A296) and 95
numbers in 1..299 were holes nobody could reuse (`designate` always drew
`seq + 1`). The operator: "perché i numeri agenti non si resettano? veramente ci
son 299 agenti? … c'era una procedura di resettaggio del counter prima di creare
agenti quando morivano … oggetti … disseminati per la codebase".

  A) a new agent takes the LOWEST free number (A1 stays the pinned supervisor);
  B) a released number is reused, `seq` stays the HIGHEST in use;
  C) two live records never share a number;
  D) a registry whose A1 is held by a session hands A1 back to the pinned one;
  E) `reconcile()` drops the records of sessions that no longer exist, keeps the
     live ones and the pinned system session, and retracts `seq`;
  F) the sweep reuses `release()` (one cleanup cascade for jobs/routines/teams);
  G) startup runs the sweep before `backfill_agents()`.

Deterministic, no live model, no network, no server.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v858-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                    # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agents as A              # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _store():
    with open(A.AGENTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _put_store(d):
    with open(A.AGENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f)


def _sess(sid):
    with open(os.path.join(os.environ["LONGRUN_SESSIONS_DIR"], sid + ".json"),
              "w", encoding="utf-8") as f:
        json.dump({"id": sid, "title": sid, "messages": []}, f)


def _num(sid):
    return (A.REGISTRY.get(sid) or {}).get("n")


_put_store({"agents": {"architect": {"id": "A1", "n": 1, "session": "architect",
                                        "kind": "session"}},
            "seq": 1})

# ------------------------------- A. the lowest free number is used -----------
A.REGISTRY.designate("s-one", kind="session")
A.REGISTRY.designate("s-two", kind="session")
check("A1 the first new agent is A2 (A1 is the pinned supervisor)",
      _num("s-one") == 2, _num("s-one"))
check("A2 the next one is A3", _num("s-two") == 3, _num("s-two"))

# ------------------------------- B. a freed number comes back ----------------
A.REGISTRY.release("s-two")
check("B1 the released number is gone from the store", _num("s-two") is None)
A.REGISTRY.designate("s-three", kind="session")
check("B2 the next agent REUSES the freed A3 instead of A4",
      _num("s-three") == 3, _num("s-three"))
check("B3 `seq` stays the highest number in use",
      _store().get("seq") == 3, _store().get("seq"))

# ------------------------------- C. no two live records share a number ------
nums = [r.get("n") for r in _store()["agents"].values()]
check("C1 every live agent number is unique", len(nums) == len(set(nums)), nums)

# ------------------------------- D. the pinned number is never lost ---------
_put_store({"agents": {
    "architect": {"id": "A1", "n": 1, "session": "architect", "kind": "session"},
    "squatter": {"id": "A1", "n": 1, "session": "squatter", "kind": "session"},
}, "seq": 1})
A.REGISTRY.designate("architect")
store = _store()["agents"]
check("D1 the system session keeps A1",
      (store.get("architect") or {}).get("id") == "A1",
      (store.get("architect") or {}).get("id"))
check("D2 the other record is moved to a FREE number, never a duplicate",
      (store.get("squatter") or {}).get("id") == "A2",
      (store.get("squatter") or {}).get("id"))

# ------------------------------- E. the orphan sweep ------------------------
_sess("live-one")
_sess("live-two")
_put_store({"agents": {
    "architect": {"id": "A1", "n": 1, "session": "architect", "kind": "session"},
    "live-one": {"id": "A2", "n": 2, "session": "live-one", "kind": "session"},
    "live-two": {"id": "A3", "n": 3, "session": "live-two", "kind": "session"},
    "dead-one": {"id": "A9", "n": 9, "session": "dead-one", "kind": "session"},
    "dead-two": {"id": "A12", "n": 12, "session": "dead-two", "kind": "session"},
}, "seq": 12})
released = A.REGISTRY.reconcile()
store = _store()
check("E1 both dead records are released", sorted(released) == ["A12", "A9"], released)
check("E2 the live sessions keep their records",
      set(store["agents"]) == {"architect", "live-one", "live-two"},
      sorted(store["agents"]))
check("E3 the system session is never pruned", "architect" in store["agents"])
check("E4 `seq` is retracted to the highest LIVE number", store.get("seq") == 3,
      store.get("seq"))

# ------------------------------- F. one cleanup cascade ---------------------
store = _store()
store["agents"]["dead-three"] = {"id": "A21", "n": 21, "session": "dead-three",
                                 "kind": "session"}
_put_store(store)
calls = []
real_release = A.AgentRegistry.release
A.AgentRegistry.release = lambda self, sid: (calls.append(sid) or real_release(self, sid))
try:
    A.REGISTRY.reconcile()
finally:
    A.AgentRegistry.release = real_release
check("F1 the sweep removes records THROUGH release() (jobs/routines/teams scrub)",
      calls == ["dead-three"], calls)

# ------------------------------- G. startup sweep, before backfill ----------
http = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
            encoding="utf-8").read()
boot = http.split("def main(")[-1]
check("G1 startup reconciles agents before backfilling them",
      boot.find("REGISTRY.reconcile()") >= 0
      and boot.find("REGISTRY.reconcile()") < boot.find("backfill_agents()"),
      (boot.find("REGISTRY.reconcile()"), boot.find("backfill_agents()")))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
