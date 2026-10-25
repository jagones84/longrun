#!/usr/bin/env python3
"""v322 — Paperclip-style job delegation: subjobs + attributed hand-off (JAG-322).

Reported by the user: a job assigned to ONE master ran, but (a) the worker's chat
showed the assignment as if the OPERATOR typed it ("YOU"), (b) there was no sign of
delegation in the master's chat, and (c) no subjob ids (J6.1, J6.2 …) — nothing tied
the work to a specific agent. And re-running a job whose agent had been deleted did
nothing (silent no-op, or a stuck "running").

This locks the fix:
  * a job is split into numbered SUBJOBS, one per delegable agent, tracked + timed;
  * the worker's turn is ATTRIBUTED to the coordinator ("A1 (Master) · J1.1");
  * the coordinator's chat gets a delegation record;
  * dispatch REFUSES when the job's agents no longer exist (no silent no-op).

Deterministic, no model (the chat generator is stubbed).
Run: python3 tests/acceptance/v322_job_delegation_subjobs.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-322-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402
from longrun.agent import agents  # noqa: E402
from longrun.orchestrate import jobs  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- stub the model turn: record attribution and persist user+assistant ----
calls = []


def _fake_stream(sess, message, model, mark=None, autonomous=False, jid=None,
                 sender=None, subjob=None, plan_only=False):
    calls.append({"sid": sess["id"], "sender": sender, "subjob": subjob})
    server.append_message(sess, "user", message,
                          meta=({"sender": sender, "subjob": subjob}
                                if (sender or subjob) else None))
    server.append_message(sess, "assistant", "FAKE[%s]" % subjob)
    yield "event: done\ndata: {}\n\n"


server.chat_stream_gen = _fake_stream

# ---- two agents: A1 master, A2 reports to A1 ------------------------------
server.get_or_create_session("sessM", "Master")
server.get_or_create_session("sessW", "Slave")
agents.REGISTRY.designate("sessM", name="Master", role="Head")
agents.REGISTRY.designate("sessW", name="Slave", role="Practical", reports_to="A1")

# ---- pure splitter --------------------------------------------------------
subs = jobs.plan_subjobs("J9", ["A1", "A2", "A3"], "A1",
                         "- A2: gather sources\n- A3: draft report", {})
check("A1 the coordinator is NOT a subjob", "J9.1" in subs and all(
    s["agent"] != "A1" for s in subs.values()))
check("A2 subjobs are numbered and bound to one agent each",
      subs.get("J9.1", {}).get("agent") == "A2" and subs.get("J9.2", {}).get("agent") == "A3",
      str(sorted(subs)))
check("A3 the assignment comes from the plan line",
      "gather sources" in (subs.get("J9.1", {}).get("assignment") or ""))

# ---- run a real job synchronously -----------------------------------------
res = jobs.JOBS.create("produce a small report", coordinator="A1",
                       agents=agents.REGISTRY.team_of("A1"))
check("B0 the job was created", res.get("ok") and res.get("job", {}).get("id"))
JID = res["job"]["id"]
jobs.JOBS._run(JID)
job = jobs.JOBS.get(JID)

check("B1 the job finished", job.get("status") == "done", str(job.get("status")))
sj = job.get("subjobs") or {}
check("B2 the run produced one subjob for the worker",
      len(sj) == 1 and sj.get(JID + ".1", {}).get("agent") == "A2", str(sj))
_s1 = sj.get(JID + ".1", {})
check("B3 the subjob is done and TIMED", _s1.get("status") == "done"
      and _s1.get("started") is not None and _s1.get("ended") is not None, str(_s1))

wmsgs = server.load_session("sessW").get("messages") or []
wuser = [m for m in wmsgs if m.get("role") == "user" and m.get("subjob")]
check("C1 the worker's turn is attributed to the coordinator, not YOU",
      bool(wuser) and wuser[0].get("sender") == "A1 (Master)", str(wuser[:1]))
check("C2 the worker's turn carries the subjob id",
      bool(wuser) and wuser[0].get("subjob") == JID + ".1")
check("C3 the worker's message names the delegation",
      bool(wuser) and "Delegation from A1 (Master)" in wuser[0].get("content", ""))

cinj = server.load_session("sessM").get("injects") or []
check("D1 the coordinator's chat records the delegation",
      any(i.get("kind") == "delegation" and (JID + ".1") in (i.get("text") or "")
          for i in cinj))

# ---- dispatch refuses when the agents are gone ----------------------------
# a job whose members were scrubbed to [] (agent deleted) refuses to run at all
gone = jobs.JOBS.create("orphan job", coordinator="A77", agents=["A77"])
GID = gone["job"]["id"]
jobs.JOBS._update(GID, lambda j: j.update({"agents": [], "coordinator": None}))
d = jobs.JOBS.dispatch(GID)
check("E1 dispatch refuses a job whose agents were deleted (empty roster)",
      d.get("ok") is False and "no agents" in (d.get("error") or ""), str(d))
check("E2 a refused dispatch does NOT mark the job running",
      (jobs.JOBS.get(GID) or {}).get("status") != "running")
# a job that still LISTS an agent whose record is gone fails loudly at run time
gone2 = jobs.JOBS.create("orphan run", coordinator="A88", agents=["A88"])
G2 = gone2["job"]["id"]
jobs.JOBS._run(G2)
_g2 = jobs.JOBS.get(G2) or {}
check("E3 running a job whose agent is gone fails loudly (never a silent done)",
      _g2.get("status") == "error" and "no agents" in (_g2.get("error") or ""),
      str(_g2.get("status")))

# ---- name <-> title sync (JAG-322 part c) ---------------------------------
agents.REGISTRY.designate("sessW", name="Slave Renamed")
check("F1 renaming an agent mirrors onto its session title",
      (server.load_session("sessW") or {}).get("title") == "Slave Renamed",
      str((server.load_session("sessW") or {}).get("title")))
agents.REGISTRY.set_name("sessW", "Slave From Session")
check("F2 renaming a session can set the agent name",
      (agents.REGISTRY.get("sessW") or {}).get("name") == "Slave From Session")

# ---- wiring ---------------------------------------------------------------
serv = open(os.path.join(REPO, "src", "longrun", "core/server.py"), encoding="utf-8").read()
serv += open(os.path.join(REPO, "src", "longrun", "core/httpapi.py"), encoding="utf-8").read()
jobsrc = open(os.path.join(REPO, "src", "longrun", "orchestrate/jobs.py"), encoding="utf-8").read()
agsrc = open(os.path.join(REPO, "src", "longrun", "agent/agents.py"), encoding="utf-8").read()
check("G1 chat_stream_gen carries sender/subjob",
      "sender=None, subjob=None" in serv and '"sender": sender, "subjob": subjob' in serv)
check("G2 jobs records subjobs + attribution",
      'j.setdefault("subjobs", {}).update(_subs)' in jobsrc  # v629: MERGE, not replace
      and "sender=sender, subjob=subjob" in jobsrc)
check("G3 the rename endpoint syncs the agent name",
      "REGISTRY.set_name(sid, title)" in serv)
check("G4 designate mirrors the name onto the title", "def sync_title(" in agsrc)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

