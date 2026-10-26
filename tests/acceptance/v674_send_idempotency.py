#!/usr/bin/env python3
"""v674 — `sessions.send` is idempotent under a retry (I-3).

A retried agent-to-agent send must not deliver the same text twice. The tool
now accepts `idempotency_key`: the same key to the SAME peer returns the
ORIGINAL message_id with `idempotent: true` and delivers nothing (no steer slot,
no peer turn), while a different key, a different target, a failed first attempt
and a call with no key keep today's behaviour.

Deterministic: fake sessions dict, stubbed Orbit dispatch, isolated data dirs.
No network, no model, no server.
"""
import json
import os
import sys
import tempfile
import time

_tmp = tempfile.mkdtemp(prefix="sf-v674-")
os.environ["LONGRUN_DATA_HOME"] = os.path.join(_tmp, "home")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_MESSAGES_DIR"] = os.path.join(_tmp, "messages")
for _d in (os.environ["LONGRUN_DATA_DIR"], os.environ["LONGRUN_SESSIONS_DIR"],
           os.environ["LONGRUN_MESSAGES_DIR"]):
    os.makedirs(_d, exist_ok=True)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402
from longrun.orbit import api as orbit_api  # noqa: E402
from longrun.tools import registry, tools  # noqa: E402
from longrun.util import steering  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


ME, PEER = "sess-me", "sess-peer"
FAKE = {ME: {"id": ME, "messages": []}, PEER: {"id": PEER, "messages": []}}
calls = []


def fake_dispatch(session, message, model=None):
    calls.append({"session": session, "message": message, "model": model})
    return {"ok": True, "count": 1,
            "jobs": [{"job": "job-" + session, "session": session, "state": "running"}]}


def _map(sender):
    with open(tools._idem_path(sender), "r", encoding="utf-8") as f:
        return json.load(f)


# ---- A: the per-sender map (TTL, target scope, cap, corrupt file) ------------
tools._idem_store("sA", "k1", PEER, "mid-1")
check("A1 a stored key returns its ORIGINAL message_id",
      tools._idem_lookup("sA", "k1", PEER) == "mid-1", tools._idem_lookup("sA", "k1", PEER))
check("A2 the map is per sender (another sender knows nothing)",
      tools._idem_lookup("sB", "k1", PEER) == "", tools._idem_lookup("sB", "k1", PEER))
check("A3 a key is scoped to its target (a different peer is not a duplicate)",
      tools._idem_lookup("sA", "k1", "peer-other") == "", tools._idem_lookup("sA", "k1", "peer-other"))
check("A4 an unknown key is empty", tools._idem_lookup("sA", "nope", PEER) == "", "")

_stale = _map("sA")
_stale["stale"] = {"message_id": "mid-stale", "session": PEER,
                   "ts": time.time() - tools._IDEM_TTL - 60}
with open(tools._idem_path("sA"), "w", encoding="utf-8") as f:
    json.dump(_stale, f)
check("A5 a record past the TTL is not a hit",
      tools._idem_lookup("sA", "stale", PEER) == "", tools._idem_lookup("sA", "stale", PEER))
tools._idem_store("sA", "k2", PEER, "mid-2")
check("A6 an expired record is pruned when the next key is stored",
      "stale" not in _map("sA") and _map("sA").get("k2", {}).get("message_id") == "mid-2",
      sorted(_map("sA")))

for i in range(tools._IDEM_KEEP + 10):
    tools._idem_store("sCap", "k%03d" % i, PEER, "m%03d" % i)
_cap = tools._idem_read("sCap")
check("A7 the map is bounded at _IDEM_KEEP and keeps the newest keys",
      len(_cap) == tools._IDEM_KEEP and "k%03d" % (tools._IDEM_KEEP + 9) in _cap
      and "k000" not in _cap, len(_cap))

with open(tools._idem_path("sBroken"), "w", encoding="utf-8") as f:
    f.write("{not json")
check("A8 a corrupt map reads as empty (a bad file never breaks a send)",
      tools._idem_read("sBroken") == {} and tools._idem_lookup("sBroken", "k", PEER) == "",
      tools._idem_read("sBroken"))

# ---- B..F: the live send path ------------------------------------------------
_orig_load = server.load_session
_orig_active = server._ACTIVE_CHAT
_orig_dispatch = orbit_api.dispatch_message
r1 = r2 = r3 = r4 = r5 = r6 = r7 = r8 = r9 = r_nokey1 = r_nokey2 = None
try:
    server.load_session = lambda sid: FAKE.get(sid)
    server._ACTIVE_CHAT = {}
    orbit_api.dispatch_message = fake_dispatch
    steering.STEER_INBOX.clear()

    # B: idle peer -> one server-side turn, then nothing
    r1 = tools._sessions({"action": "send", "session": PEER, "message": "do it",
                          "idempotency_key": "K1"}, ME)
    _n1 = len(calls)
    r2 = tools._sessions({"action": "send", "session": PEER, "message": "do it",
                          "idempotency_key": "K1"}, ME)
    _n2 = len(calls)
    check("B1 the first send starts exactly one peer turn",
          r1.get("ok") is True and r1.get("mode") == "turn" and r1.get("message_id")
          and _n1 == 1, (r1.get("mode"), _n1))
    check("B2 a retry with the same key delivers NOTHING (one dispatch, same id)",
          _n2 == 1 and r2.get("ok") is True and r2.get("idempotent") is True
          and r2.get("message_id") == r1.get("message_id"), (len(calls), r2))
    check("B3 the retry explains itself and points at sessions.wait",
          "duplicate" in (r2.get("stdout") or "")
          and r1.get("message_id") in (r2.get("stdout") or ""), r2.get("stdout"))
    check("B4 the key is on disk (a restart cannot resurrect the double delivery)",
          _map(ME).get("K1", {}).get("message_id") == r1.get("message_id"), _map(ME))

    # C: running peer -> one steer slot, then nothing
    server._ACTIVE_CHAT = {PEER: {"tok": object()}}
    steering.STEER_INBOX.clear()
    r3 = tools._sessions({"action": "send", "session": PEER, "message": "steer me",
                          "idempotency_key": "K2"}, ME)
    _inbox1 = len(steering.drain_steer(PEER))
    r4 = tools._sessions({"action": "send", "session": PEER, "message": "steer me",
                          "idempotency_key": "K2"}, ME)
    _inbox2 = len(steering.drain_steer(PEER))
    check("C1 a running peer gets the message through ONE steer slot",
          r3.get("ok") is True and r3.get("mode") == "steer" and _inbox1 == 1,
          (r3.get("mode"), _inbox1))
    check("C2 the retry queues no second steer and keeps mode=steer",
          r4.get("idempotent") is True and _inbox2 == 0
          and r4.get("message_id") == r3.get("message_id") and r4.get("mode") == "steer",
          (r4.get("idempotent"), _inbox2, r4.get("mode")))

    # D: different keys are different messages
    server._ACTIVE_CHAT = {}
    _n0 = len(calls)
    r5 = tools._sessions({"action": "send", "session": PEER, "message": "one",
                          "idempotency_key": "K3"}, ME)
    r6 = tools._sessions({"action": "send", "session": PEER, "message": "two",
                          "idempotency_key": "K4"}, ME)
    check("D1 two different keys deliver twice with two ids",
          len(calls) - _n0 == 2 and r5.get("idempotent") is not True
          and r6.get("idempotent") is not True
          and r5.get("message_id") != r6.get("message_id"), len(calls) - _n0)

    # E: no key -> unchanged behaviour
    _n0 = len(calls)
    r_nokey1 = tools._sessions({"action": "send", "session": PEER, "message": "plain"}, ME)
    r_nokey2 = tools._sessions({"action": "send", "session": PEER, "message": "plain"}, ME)
    check("E1 a send without a key is not deduplicated (2 deliveries, no flag)",
          len(calls) - _n0 == 2 and "idempotent" not in r_nokey1
          and "idempotent" not in r_nokey2
          and r_nokey1.get("message_id") != r_nokey2.get("message_id"), len(calls) - _n0)

    # F: a FAILED first attempt must leave the key free for the retry
    orbit_api.dispatch_message = lambda session, message, model=None: {
        "ok": False, "error": "provider down"}
    r7 = tools._sessions({"action": "send", "session": PEER, "message": "retry me",
                          "idempotency_key": "K5"}, ME)
    orbit_api.dispatch_message = fake_dispatch
    r8 = tools._sessions({"action": "send", "session": PEER, "message": "retry me",
                          "idempotency_key": "K5"}, ME)
    r9 = tools._sessions({"action": "send", "session": PEER, "message": "retry me",
                          "idempotency_key": "K5"}, ME)
    check("F1 the failed dispatch stays a failure", r7.get("ok") is False
          and r7.get("error") == "provider down", r7.get("error"))
    check("F2 the key was not burned: the retry is DELIVERED (not a duplicate)",
          r8.get("ok") is True and r8.get("mode") == "turn"
          and r8.get("idempotent") is not True and r8.get("message_id"),
          (r8.get("ok"), r8.get("idempotent")))
    check("F3 after that delivery the key IS a duplicate",
          r9.get("idempotent") is True and r9.get("message_id") == r8.get("message_id"),
          (r9.get("idempotent"), r9.get("message_id")))
finally:
    server.load_session = _orig_load
    server._ACTIVE_CHAT = _orig_active
    orbit_api.dispatch_message = _orig_dispatch
    steering.STEER_INBOX.clear()
    with tools._SESSION_SENDS_LOCK:
        for _mid in (r1, r2, r3, r4, r5, r6, r8, r9, r_nokey1, r_nokey2):
            tools._SESSION_SENDS.pop((_mid or {}).get("message_id"), None)

# ---- G: the argument reaches the model and survives the namespaced tool ------
_send = (registry.tool_spec("sessions.send") or {}).get("schema") or {}
check("G1 the sessions.send schema declares idempotency_key",
      "idempotency_key" in (_send.get("properties") or {}),
      sorted((_send.get("properties") or {})))
check("G2 its guidance tells the model a retry is safe",
      "idempotency_key" in (registry._SUBTOOL_GUIDANCE.get("sessions.send") or ""), "")
check("G3 the subtool field map keeps the key (a namespaced call cannot strip it)",
      "idempotency_key" in registry._SUBTOOL_FIELDS["sessions"]["send"],
      registry._SUBTOOL_FIELDS["sessions"]["send"])
check("G4 the legacy `sessions` schema documents it as well",
      "idempotency_key" in ((registry.TOOL_SCHEMAS.get("sessions") or {}).get("properties") or {}),
      sorted(((registry.TOOL_SCHEMAS.get("sessions") or {}).get("properties") or {})))

print("---")
okc = sum(results)
print("v674: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
