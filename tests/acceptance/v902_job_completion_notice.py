#!/usr/bin/env python3
"""v902 — a finished job tells the AGENT that assigned it (2026-11-08).

Operator: *"when the delegated agent has finished he shall send the message to
the delegating agent even if it is busy (that command is put on queue
automatically)"*.

Before this, a job wrote its result into `data/jobs.json` and nothing else: the
agent that started it only learned the outcome by polling `job.get`. Now

  * `util.inbox.deliver` is the ONE rule for "reach a session": queued when a
    turn is running (the loop drains it at its next boundary), a real turn when
    idle — the same rule `sessions.send` uses, which calls it too;
  * a terminal job delivers ONE notice to `assigned_by` and records the outcome
    in `notified` (never twice, never on a job nobody assigned);
  * a restart closes the job's still-`running` children instead of leaving them
    spinning forever.

Deterministic, no model, no server. Run: python3 tests/acceptance/v902_job_completion_notice.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-902-")
for k, v in {
    "LONGRUN_AGENTS_FILE": os.path.join(TMP, "agents.json"),
    "LONGRUN_SESSIONS_DIR": os.path.join(TMP, "sessions"),
    "LONGRUN_GRAPH_DIR": os.path.join(TMP, "graphs"),
    "LONGRUN_DB": os.path.join(TMP, "events.db"),
    "LONGRUN_CONFIG_DIR": os.path.join(TMP, "cfg"),
    "LONGRUN_JOBS_FILE": os.path.join(TMP, "jobs.json"),
    "LONGRUN_TEAMS_FILE": os.path.join(TMP, "teams.json"),
}.items():
    os.environ[k] = v
for d in ("sessions", "graphs", "cfg"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S            # noqa: E402
from longrun.agent import agents as A           # noqa: E402
from longrun.util import inbox                  # noqa: E402
from longrun.orchestrate import jobs as J       # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- fixtures ---------------------------------------------------------------
_store = {"sess_owner": {"id": "sess_owner", "messages": [{"role": "user", "content": "hi"}]},
          "sess_peer": {"id": "sess_peer", "messages": []}}
S.load_session = lambda sid: _store.get(sid)

M = A.REGISTRY.designate("sess_owner", name="Owner", role="orchestrator")["agent"]
A.REGISTRY.designate("sess_worker", name="Worker", role="builder", reports_to=M["id"])
# 2026-11-11: `sessions.send` now follows the org rule (operator, 2026-11-10), so the
# peer the owner steers must BE a peer in its line — a record is what a live session
# always has (EV-30 / ensure_agent); without it the send is refused as "not in the
# org chart", which is not what this pin is about.
A.REGISTRY.designate("sess_peer", name="Peer", role="builder", reports_to=M["id"])
owner_id, worker_id = M["id"], A.REGISTRY.team_of(M["id"])[-1]

# ---- A) the one delivery rule ----------------------------------------------
busy = {"on": False}
turns = []
steers = []


def _fake_dispatch(session, message, model=None):
    turns.append((session, message))
    if busy.get("fail"):
        return {"ok": False, "jobs": [], "error": "boom"}
    if busy.get("answer_busy"):
        return {"ok": True, "jobs": [{"job": "orbit-1", "state": "busy",
                                      "error": "session busy"}]}
    return {"ok": True, "jobs": [{"job": "orbit-1", "state": "running"}]}


import longrun.orbit.api as orbit_api            # noqa: E402
from longrun.util import steering                 # noqa: E402
from longrun.core import events as events_mod     # noqa: E402

orbit_api.dispatch_message = _fake_dispatch
steering.push_steer = lambda sid, text, steer_id=None: (steers.append((sid, text)) or len(steers))
events_mod.turn_active = lambda sid: bool(busy.get("on"))

r = inbox.deliver("", "x")
check("A1 empty target refused", r.get("ok") is False and "required" in r.get("error", ""), r)
r = inbox.deliver("ghost", "x")
check("A2 unknown session is a clean refusal", r.get("ok") is False
      and "no such session" in r.get("error", ""), r)
r = inbox.deliver("sess_owner", "x", from_session="sess_owner")
check("A3 self-delivery refused", r.get("ok") is False
      and "calling session" in r.get("error", ""), r)
turns.clear()
r = inbox.deliver("sess_peer", "hello peer")
check("A4 an IDLE peer gets a real turn", r.get("ok") is True and r.get("mode") == "turn"
      and len(turns) == 1 and turns[0][0] == "sess_peer", r)
check("A5 the result reports the pre-delivery message count", r.get("messages") == 0, r)
turns.clear()
busy["on"] = True
r = inbox.deliver("sess_peer", "hello busy peer")
check("A6 a BUSY peer gets the message QUEUED, not dropped",
      r.get("ok") is True and r.get("mode") == "steer" and len(steers) == 1
      and steers[0][0] == "sess_peer" and not turns, (r, steers, turns))
busy["on"] = False
busy["answer_busy"] = True
steers.clear()
r = inbox.deliver("sess_peer", "race")
check("A7 losing the busy race still queues (no lost wake-up)",
      r.get("mode") == "steer" and len(steers) == 1, (r, steers))
busy["answer_busy"] = False
busy["fail"] = True
r = inbox.deliver("sess_peer", "boom")
check("A8 a failed turn start is an explicit error, not a silent drop",
      r.get("ok") is False and "boom" in r.get("error", ""), r)
busy["fail"] = False

# ---- B) `sessions.send` keeps its behaviour on the shared rule --------------
from longrun.tools import tools as T              # noqa: E402
steers.clear()
busy["on"] = True
s = T._sessions({"action": "send", "session": "sess_peer", "message": "hi"}, "sess_owner")
check("B1 sessions.send to a busy peer still answers mode=steer with a message_id",
      s.get("ok") is True and s.get("mode") == "steer" and s.get("message_id"), s)
s = T._sessions({"action": "send", "session": "ghost", "message": "hi"}, "sess_owner")
check("B2 sessions.send still says 'no such session' with its hint",
      s.get("ok") is False and "no such session" in s.get("error", "")
      and "action=list" in s.get("error", ""), s)
s = T._sessions({"action": "send", "session": "sess_owner", "message": "hi"}, "sess_owner")
check("B3 sessions.send still refuses a self-send", s.get("ok") is False
      and "cannot message itself" in s.get("error", ""), s)
busy["on"] = False

# ---- C) a terminal job notifies its assigner --------------------------------
deliveries = []
inbox.deliver = lambda sid, text, from_session=None: (deliveries.append((sid, text)) or
                                                      {"ok": True, "mode": "turn",
                                                       "session": sid, "messages": 0})


def _make_job(**kw):
    res = J.JOBS.create(kw.pop("goal", "write the parser"), coordinator=worker_id,
                        agents=[worker_id], mode="run", **kw)
    return res["job"]["id"]


jid = _make_job(assigned_by=owner_id)
job = J.JOBS.get(jid) or {}
check("C1 the job records WHO assigned it", job.get("assigned_by") == owner_id, job.get("assigned_by"))
J.JOBS._update(jid, lambda j: j.update({"status": "done", "runs": {worker_id: {
    "state": "done", "result": "the parser is done: parser.py:1-40"}}}))
J.JOBS._notify(jid)
check("C2 a finished job delivers exactly ONE notice to the assigner",
      len(deliveries) == 1 and deliveries[0][0] == "sess_owner", deliveries)
text = deliveries[0][1] if deliveries else ""
check("C3 the notice names the job, its status and the worker's result",
      jid in text and "done" in text and "the parser is done" in text, text[:200])
check("C4 the notice points at the full record (job.get), never a dead end",
      "job.get" in text and jid in text, text[-120:])
check("C5 the notice is bounded", len(text) <= 1800, len(text))
job = J.JOBS.get(jid) or {}
check("C6 the delivery outcome is recorded on the job",
      (job.get("notified") or {}).get("ok") is True
      and (job.get("notified") or {}).get("mode") == "turn", job.get("notified"))
J.JOBS._notify(jid)
check("C7 a re-run never delivers a second copy",
      len(deliveries) == 1 and (J.JOBS.get(jid) or {}).get("notified", {}).get("at"),
      len(deliveries))

deliveries.clear()
jid2 = _make_job(goal="nobody assigned this")
J.JOBS._update(jid2, lambda j: j.update({"status": "done"}))
J.JOBS._notify(jid2)
check("C8 a job with no assigner tells nobody", not deliveries, deliveries)

deliveries.clear()
jid3 = _make_job(goal="team goal", assigned_by=owner_id)
J.JOBS._update(jid3, lambda j: j.update({"status": "done", "mode": "coordinator",
                                         "coordinator": owner_id}))
J.JOBS._notify(jid3)
check("C9 a coordinator is not told about its OWN synthesis turn",
      not deliveries and (J.JOBS.get(jid3) or {}).get("notified", {}).get("mode") == "self",
      (deliveries, (J.JOBS.get(jid3) or {}).get("notified")))

deliveries.clear()
jid4 = _make_job(goal="partial work", assigned_by=owner_id)
J.JOBS._update(jid4, lambda j: j.update({
    "status": "partial", "failed_subjobs": [worker_id],
    "runs": {worker_id: {"state": "failed", "error": "STEP FAILED: no network"}}}))
J.JOBS._notify(jid4)
text4 = deliveries[0][1] if deliveries else ""
check("C10 a PARTIAL job says which worker failed, in the notice",
      "NOT deliver" in text4 and worker_id in text4 and "no network" in text4, text4[:240])

deliveries.clear()
jid5 = _make_job(goal="broken job", assigned_by=owner_id)
J.JOBS._update(jid5, lambda j: j.update({"status": "error", "error": "provider 500"}))
J.JOBS._notify(jid5)
text5 = deliveries[0][1] if deliveries else ""
check("C11 an ERROR job says so (plainly, with the reason)",
      "ENDED" in text5 and "provider 500" in text5, text5[:200])

# ---- D) a restart closes the job's children ---------------------------------
jid6 = _make_job(goal="interrupted", assigned_by=owner_id)
J.JOBS._update(jid6, lambda j: j.update({
    "status": "running",
    "runs": {worker_id: {"state": "running"}},
    "subjobs": {jid6 + ".1": {"status": "retrying"}}}))
J.JOBS.reconcile()
j6 = J.JOBS.get(jid6) or {}
check("D1 reconcile ends the job", j6.get("status") == "error", j6.get("status"))
check("D2 its running worker record ends too (no spinner on dead work)",
      ((j6.get("runs") or {}).get(worker_id) or {}).get("state") == "failed",
      (j6.get("runs") or {}).get(worker_id))
check("D3 its retrying subjob ends too",
      ((j6.get("subjobs") or {}).get(jid6 + ".1") or {}).get("status") == "failed",
      (j6.get("subjobs") or {}).get(jid6 + ".1"))

# ---- E) the wiring is the ONE rule in both consumers ------------------------
JOBS_SRC = open(os.path.join(REPO, "src", "longrun", "orchestrate", "jobs.py"),
                encoding="utf-8").read()
TOOLS_SRC = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"),
                 encoding="utf-8").read()
check("E1 the job runner notifies on BOTH terminal paths",
      JOBS_SRC.count("self._notify(jid)") == 2, JOBS_SRC.count("self._notify(jid)"))
check("E2 the job runner delivers through the shared rule",
      "from longrun.util import inbox as inbox_mod" in JOBS_SRC
      and "inbox_mod.deliver(" in JOBS_SRC)
check("E3 sessions.send no longer keeps its own busy/idle branch",
      "steering.push_steer(target" not in TOOLS_SRC
      and "inbox_mod.deliver(" in TOOLS_SRC)
check("E4 one owner for the notice text",
      JOBS_SRC.count("def _notice_text") == 1 and JOBS_SRC.count("def deliver(") == 0)
INBOX_SRC = open(os.path.join(REPO, "src", "longrun", "util", "inbox.py"),
                 encoding="utf-8").read()
check("E5 the rule lives in util/inbox.py and names both branches",
      "def deliver(" in INBOX_SRC and "push_steer" in INBOX_SRC
      and "dispatch_message" in INBOX_SRC)

# ---- summary ----------------------------------------------------------------
bad = results.count(False)
print("\n%d/%d checks passed" % (len(results) - bad, len(results)))
sys.exit(1 if bad else 0)
