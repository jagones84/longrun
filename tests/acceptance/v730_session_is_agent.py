#!/usr/bin/env python3
"""v730 — a session IS an agent: it is born with `A<n>`, and the number RESETS (EV-30).

The operator rule is explicit (`.trae/rules/project_rules.md`): *"IDs reset after
resets/deletes — agent numbers, todos, jobs, every object."* The old contract gave
a chat a `J<n>` from a MONOTONIC counter (`.jobseq`, test v316) and only
*designated* it as an agent later, so the rail showed `J219` for a chat and `A8`
for a team member — two identities for the same object, and a counter that never
came back. This test pins the replacement:

  A  a new session gets an agent record (`A<n>`, kind="session") at creation
  B  deleting the top session frees the number (the rule, not a high-water mark)
  C  the old `job` field and its monotonic counter are gone
  D  legacy sessions without a record are backfilled in creation order
  E  the org chart hides session records; a plain chat is not "risky to delete"

Deterministic, no model, no network. Run: python3 tests/acceptance/v730_session_is_agent.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-730-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402  (server first: httpapi imports it)
from longrun.core import httpapi  # noqa: E402
from longrun.agent import agents as agents_mod  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:200]) if detail else ""))


def num_of(sid):
    a = agents_mod.REGISTRY.get(sid) or {}
    return a.get("n")


def new_session(title):
    return server.get_or_create_session(None, title=title)


# ---- A: born as an agent ---------------------------------------------------
sa = new_session("alpha")
sb = new_session("beta")
na, nb = num_of(sa["id"]), num_of(sb["id"])
check("A1 a new session IS an agent (has its own A<n> record)", bool(na) and bool(nb),
      "%s -> A%s, %s -> A%s" % (sa["id"], na, sb["id"], nb))
rec = agents_mod.REGISTRY.get(sa["id"]) or {}
check("A2 the record is marked kind=session and carries the id A<n>",
      rec.get("kind") == "session" and rec.get("id") == "A%s" % na, rec)
check("A3 numbers are assigned in order", nb == na + 1, "A%s then A%s" % (na, nb))

# ---- B: the counter RESETS on delete (the operator rule) -------------------
gone = httpapi.delete_session(sb["id"])
check("B1 the session and its agent record are gone",
      gone.get("ok") is True and agents_mod.REGISTRY.get(sb["id"]) is None, gone)
sc = new_session("gamma")
check("B2 deleting the TOP session frees its number (no high-water mark)",
      num_of(sc["id"]) == nb, "expected A%s, got A%s" % (nb, num_of(sc["id"])))

# ---- C: the old J contract is gone -----------------------------------------
check("C1 a session carries no `job` field any more",
      "job" not in sa and "job" not in (server.load_session(sa["id"]) or {}),
      sorted((server.load_session(sa["id"]) or {}).keys())[:8])
check("C2 the session summary has no `job` either",
      all("job" not in row for row in server.list_sessions()))
check("C3 the monotonic counter file is not written",
      not os.path.isfile(os.path.join(server.SESSIONS_DIR, ".jobseq")))
src = open(os.path.join(REPO, "src", "longrun", "memory", "stores.py"), encoding="utf-8").read()
check("C4 no ensure_job/_max_job/_write_seq survives in the store",
      all(tok not in src.split('"""', 2)[-1] for tok in ("def ensure_job", "def _max_job",
                                                        "_write_seq(")))

# ---- D: legacy sessions are backfilled in creation order -------------------
legacy = {"id": "legacy000001", "title": "old one", "created": 1.0, "messages": [],
          "job": 210}
with open(os.path.join(server.SESSIONS_DIR, "legacy000001.json"), "w", encoding="utf-8") as f:
    json.dump(legacy, f)
server.backfill_agents()
lrec = agents_mod.REGISTRY.get("legacy000001") or {}
check("D1 a session stored under the old contract gets an A record",
      lrec.get("kind") == "session" and lrec.get("id"), lrec)
saved = server.load_session("legacy000001") or {}
check("D2 its stale `job` is not kept as a second label", "job" not in saved, sorted(saved.keys())[:8])

# ---- E: the org chart hides session records; deleting is not "risky" -------
tree = agents_mod.REGISTRY.tree()
check("E1 the org chart lists only TEAM agents", all(a.get("kind") != "session"
                                                     for a in tree["agents"]),
      [a.get("id") for a in tree["agents"]][:6])
check("E2 every session is still in list() (the UI badge reads it)",
      any(a.get("session") == sa["id"] for a in agents_mod.REGISTRY.list()["agents"]))
check("E3 guards() treats a plain chat like any session",
      agents_mod.REGISTRY.guards(sa["id"]) == {"is_agent": False, "blocked": False},
      agents_mod.REGISTRY.guards(sa["id"]))

# ---- F: the UI no longer prints a J sequence -------------------------------
ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("F1 no session-sequence fallback is rendered or cached",
      "_sessJob" not in ui and '"J" + curJob' not in ui)
check("F2 the todo prefix falls back to an A id",
      '"A" + curJob' in ui)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
