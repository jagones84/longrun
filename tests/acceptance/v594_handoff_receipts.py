#!/usr/bin/env python3
"""v594 (RED) — CCCC delivery facts for handoffs: stored/delivered/replied.

Handoffs (`_log_escalation`, delegation notes) are fire-and-forget injects:
nothing records whether the other side ever advanced past them. The slice:

- `jobs.record_handoff(jid, sub_id, to_sid, text, kind)` persists the inject
  in the target session AND appends a receipt {id, ts, to, kind, after} to
  the subjob (best-effort, never breaks the run).
- `jobs.handoff_state(receipt, target_len, subjob)` (pure): `replied` when the
  subjob is done/failed with a result; `delivered` when the target session
  advanced past the receipt (`target_len > after`, so the handoff entered its
  context); else `stored`.
- `jobs.handoff_status(jid, sub_id)` resolves live states for a subjob.
- `_log_escalation` routes both chats through `record_handoff` (same texts).

Deterministic: isolated jobs file, fake server sessions, no model/network.
Run: python3 tests/acceptance/v594_handoff_receipts.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo(start):
    p = start
    while True:
        if os.path.isdir(os.path.join(p, "src", "longrun")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            raise SystemExit("repository root not found from %s" % start)
        p = parent


REPO = _repo(HERE)
_tmp = tempfile.mkdtemp(prefix="lr-handoff-v594-")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(_tmp, "jobs.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.orchestrate import jobs as J  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: the API exists ---------------------------------------------------------
check("A1 jobs.record_handoff exists", callable(getattr(J, "record_handoff", None)))
check("A2 jobs.handoff_state exists", callable(getattr(J, "handoff_state", None)))
check("A3 jobs.handoff_status exists", callable(getattr(J, "handoff_status", None)))
rh = getattr(J, "record_handoff", None)
hs = getattr(J, "handoff_state", None)

# ---- B: pure state machine -------------------------------------------------------
if callable(hs):
    r = {"id": "h1", "ts": 1.0, "to": "S2", "kind": "escalation", "after": 3}
    check("B1 fresh receipt, quiet target -> stored",
          hs(r, 3, {"status": "running"}) == "stored")
    check("B2 target advanced -> delivered",
          hs(r, 5, {"status": "running"}) == "delivered")
    check("B3 subjob done with result -> replied",
          hs(r, 3, {"status": "done", "result": "ok"}) == "replied")
    check("B4 subjob failed with reason -> replied",
          hs(r, 9, {"status": "failed", "error": "x"}) == "replied")
    check("B5 done without any result is not a reply",
          hs(r, 9, {"status": "done"}) == "delivered")
    check("B6 malformed receipt -> stored, never crashes",
          hs(None, 0, {}) == "stored" and hs({}, 0, {}) == "stored")
else:
    for n in ("B1", "B2", "B3", "B4", "B5", "B6"):
        check(n, False, "handoff_state missing")

# ---- C: record through a fake server ----------------------------------------------
class _FakeSrv(object):
    def __init__(self):
        self.sessions = {}

    def get_or_create_session(self, sid):
        return self.sessions.setdefault(sid, {"id": sid, "messages": [],
                                              "injects": []})

    def persist_inject(self, sess, kind, text):
        rec = {"kind": kind, "text": text,
               "after": len(sess.get("messages", []))}
        sess.setdefault("injects", []).append(rec)
        return rec


if callable(rh):
    fake = _FakeSrv()
    real_srv = J._srv
    J._srv = lambda: fake
    try:
        created = J.JOBS.create("goal v594", agents=["A1"])
        if not created.get("ok"):
            check("C0 job created", False, repr(created))
            jid = None
        else:
            jid = created["job"]["id"]
            check("C0 job created", True, jid)
            sid = J._live_sessions if False else None
            J.JOBS._update(jid, lambda j: j.update({"agents": ["A1"]}))
            J.JOBS._update(jid, lambda j: j.setdefault("subjobs", {}).update(
                {"SJ1": {"id": "SJ1", "status": "running"}}))
            rec = J.record_handoff(jid, "SJ1", "S9", "hello worker", "delegation")
            check("C1 receipt recorded with after-boundary",
                  isinstance(rec, dict) and rec.get("to") == "S9"
                  and rec.get("after") == 0 and rec.get("kind") == "delegation",
                  repr(rec))
            check("C2 inject landed in the target session",
                  len(fake.sessions["S9"]["injects"]) == 1)
            st = J.handoff_status(jid, "SJ1")
            check("C3 quiet target -> stored",
                  st and st[0][1] == "stored", repr(st))
            fake.sessions["S9"]["messages"].append({"role": "user",
                                                    "content": "ack"})
            st = J.handoff_status(jid, "SJ1")
            check("C4 advanced target -> delivered",
                  st and st[0][1] == "delivered", repr(st))
            J.JOBS._update(jid, lambda j: j["subjobs"]["SJ1"].update(
                {"status": "done", "result": "did it"}))
            st = J.handoff_status(jid, "SJ1")
            check("C5 finished subjob -> replied",
                  st and st[0][1] == "replied", repr(st))
    finally:
        J._srv = real_srv
else:
    for n in ("C0", "C1", "C2", "C3", "C4", "C5"):
        check(n, False, "record_handoff missing")

# ---- D: escalation routes through receipts ------------------------------------------
try:
    with open(os.path.join(REPO, "src", "longrun", "orchestrate", "jobs.py"),
              encoding="utf-8") as f:
        _src = f.read()
except OSError as e:
    _src = ""
    print("WARN cannot read jobs.py: %s" % e)
_block = _src.split("def _log_escalation(", 1)
_block = _block[1] if len(_block) > 1 else ""
_nxt = _block.find("\n    def ")
_block = _block[:_nxt] if _nxt >= 0 else _block
check("D1 escalation writes both chats through record_handoff",
      _block.count("record_handoff(") >= 2, _block.count("record_handoff("))
check("D2 the old silent texts are kept (same words, now with receipts)",
      "returning subjob" in _block and "could not finish subjob" in _block)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
