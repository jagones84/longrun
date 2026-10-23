#!/usr/bin/env python3
"""v310 — a headless turn on the OPEN session must reach the screen, and a job
must not be "accepted" without its coordinator's reply (JAG-310).

Observed bug: the user watched the coordinator's session, saw the injected
"Team results:" prompt as the LAST message, and NO reply — "the coordinator
received a report but never replied". On disk the reply WAS persisted (chat.done,
5096 chars). Root cause (two independent holes):

  1. UI delivery: `attachIfRunning` ran only at session open/switch, and the
     global feed handler printed a one-line "user" note + `loadCtx()` — it never
     followed the turn and never rendered the answer. A turn that STARTS on an
     already-open session but was not begun by this browser (a headless JOB turn
     or a routine) was therefore invisible until a manual reload.
  2. Acceptance: `_run_agent` fell back to the last assistant message of the
     WHOLE session, so a job whose coordinator produced no NEW reply was still
     marked `done` with a STALE/duplicate answer.

Locked here:
  * the feed follows the open session's turn (attach) and pulls the reply on done;
  * `_run_agent` only ever returns THIS turn's reply (never a stale one);
  * `_run` refuses to mark a job `done` when the coordinator produced no reply.

Deterministic, no browser, no model. Run: python3 tests/v310_agent_turn_delivery.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
TMP = tempfile.mkdtemp(prefix="sf-v310-")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


from longrun.orchestrate import jobs  # noqa: E402

OLD = {"role": "assistant", "content": "OLD REPLY from a previous run"}


class FakeSrv:
    """Minimal server stand-in: one headless turn that appends `turn_add`."""

    def __init__(self, msgs, turn_add):
        self.msgs = list(msgs)
        self.turn_add = list(turn_add)

    def get_or_create_session(self, sid):
        return {"id": sid, "messages": list(self.msgs)}

    def load_session(self, sid):
        return {"id": sid, "messages": list(self.msgs)}

    def chat_stream_gen(self, sess, message, model, mark, autonomous, jid,
                        sender=None, subjob=None, plan_only=False):
        self.msgs = self.msgs + list(self.turn_add)
        return iter(())


_orig_srv = jobs._srv

# (a) a turn that produced NOTHING must NOT return the stale previous reply -------
jobs._srv = lambda: FakeSrv([OLD], [])
out = jobs.JOBS._run_agent("s1", "Team results: ...", model="m", jid=None)
check("a turn with no reply returns EMPTY, not a stale previous reply",
      out == "", "out=%r" % out)

# (b) a turn that DID reply returns THIS turn's reply -----------------------------
jobs._srv = lambda: FakeSrv([OLD], [{"role": "assistant", "content": "NEW REPLY this turn"}])
out = jobs.JOBS._run_agent("s1", "Team results: ...", model="m", jid=None)
check("a turn that replied returns THIS turn's reply",
      out == "NEW REPLY this turn", "out=%r" % out)

# (c) the substantial reply of THIS turn wins over a trailing summary -------------
jobs._srv = lambda: FakeSrv([OLD], [{"role": "assistant", "content": "DELIVERABLE " + "x" * 500},
                                    {"role": "assistant", "content": "done"}])
out = jobs.JOBS._run_agent("s1", "go", model="m", jid=None)
check("the substantial reply of THIS turn wins", out.startswith("DELIVERABLE"), "out=%r" % out[:40])

jobs._srv = _orig_srv

# (d) _run must REFUSE to accept a job whose coordinator produced no reply --------
from longrun.agent import agents as agents_mod  # noqa: E402

agents_mod.REGISTRY.designate("coordX", name="Coord", role="orchestrator")
aid = agents_mod.REGISTRY.get("coordX")["id"]      # e.g. "A1" (create takes AGENT ids)
jid = jobs.JOBS.create("goal X", coordinator=aid, agents=[aid])["job"]["id"]
jobs.JOBS._run_agent = lambda *a, **k: ""          # the coordinator answers NOTHING
jobs.JOBS._run(jid)
st = (jobs.JOBS.get(jid) or {}).get("status")
check("a job is NOT accepted when the coordinator answers nothing",
      st == "error", "st=%r" % st)

jid2 = jobs.JOBS.create("goal Y", coordinator=aid, agents=[aid])["job"]["id"]
jobs.JOBS._run_agent = lambda *a, **k: "FINAL ANSWER"
jobs.JOBS._run(jid2)
st2 = (jobs.JOBS.get(jid2) or {}).get("status")
check("a job IS accepted when the coordinator answers", st2 == "done", "st=%r" % st2)

# ------------------------------------------------------------------ source locks
j = read("src", "longrun", "orchestrate/jobs.py")
check("the reply is extracted from THIS turn only",
      '_best_reply(s.get("messages", [])[before:])' in j)
check("the whole-session stale fallback is gone",
      'for m in reversed(s.get("messages", [])):' not in j
      and "for m in reversed(turn):" not in j)
check("a job is refused when the coordinator produced no reply",
      "coordinator produced no final reply" in j)

ui = read("webui", "index.html")
check("the feed follows a turn that starts on the open session",
      "if (d.session && d.session === sessionId) attachIfRunning(sessionId);" in ui)
check("the feed pulls the reply when the turn ends off-stream",
      "function _rebuildOnFeedDone(sid)" in ui and "_rebuildOnFeedDone(d.session);" in ui)
check("the old one-line-only chat.done handler is gone",
      'es.addEventListener("chat.done", () => { push("💬 chat done"); loadCtx(); });' not in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

