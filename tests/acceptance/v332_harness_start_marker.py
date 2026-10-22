#!/usr/bin/env python3
"""v332 — the harness leaves a durable 'session started' marker (JAG-332).

The full system prompt is emitted every turn but TRANSIENTLY (kind 'system', not
persisted), so after a reload the operator saw NO harness message at the start of a
session and could not tell that a real prompt was passed. This writes ONE durable
marker per session, on the first turn, stating what the harness loaded.

Deterministic, no model. Run: python3 tests/acceptance/v332_harness_start_marker.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-332-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def _markers():
    return [r for r in ((server.load_session("v332s") or {}).get("injects") or [])
            if r.get("kind") == "harness-start"]


sess = server.get_or_create_session("v332s", "probe")
check("A1 a fresh session has no start marker yet", _markers() == [])

server._harness_start_note(sess)
m = _markers()
check("A2 the first turn writes exactly one durable start marker", len(m) == 1, str(len(m)))
txt = (m[0].get("text") if m else "") or ""
check("A3 the marker names the harness wiring", "harness wiring" in txt, txt[:60])
check("A4 the marker reports Global_rules.md / Project_rules.md + skills + tools + prompt size",
      "Global_rules.md" in txt and "skills index" in txt
      and "tool registry" in txt and "system prompt" in txt)
check("A5 the marker carries the session boundary (after=0)", m and m[0].get("after") == 0)
check("A7 the system-prompt line is ACCURATE (re-sent per request, KV-cached)",
      "re-sent with each request" in txt and "KV-cache" in txt)

server._harness_start_note(server.load_session("v332s"))
check("A6 the marker is idempotent (never duplicated)", len(_markers()) == 1)

with open(os.path.join(REPO, "src", "longrun", "core/server.py"), encoding="utf-8") as f:
    src = f.read()
with open(os.path.join(REPO, "src", "longrun", "agent/agent.py"), encoding="utf-8") as f:
    src += f.read()
check("B1 chat_once calls it on the FIRST turn only",
      "_harness_start_note(sess)" in src
      and 'if len(sess.get("messages") or []) <= 1:' in src)
check("B2 it persists a 'harness-start' inject", 'persist_inject(sess, "harness-start"' in src)
check("B3 it publishes harness.inject so the live chat shows it",
      'publish("harness.inject", session=sid, inject_kind="harness-start"' in src)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

