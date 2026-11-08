#!/usr/bin/env python3
"""v878 — the rail's 🏷 marker follows the BACKEND, and a click always runs.

Live report (2026-11-08): *"Label added into the sidebar does not update when
clicked and terminates work, remaining in the running process animation. … fix
this so that the web always updates in response to changes in the backend."*

Three defects, each measured before the fix:

  A) the naming run's start/close pair was the ONLY source of the rail marker, so a
     `threads.named` that never arrived (live evidence: `threads.naming` at
     09:15:30 with no close; the service restarted at 09:17:00 and killed the
     daemon thread) left the row busy forever — and every re-render dropped the
     marker while a run WAS in flight (`_sessRowEl` never read `namingSessions`);
  B) a raise in `load_session` happened AFTER the in-flight guard was taken, so the
     session stayed in `_NAMING_IN_FLIGHT` forever and every later 🏷 answered
     "already naming this session" — the click did nothing, ever again;
  C) a Stop consumed by the naming run was never cleared, so the NEXT 🏷 broke at
     round 0 (named nothing) — the click "terminated work".

Deterministic: temp dirs, no model, no network, no live server.
"""
import atexit
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-878-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(tmp, "threads")
os.environ["LONGRUN_GRAPH_DIR"] = tmp
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(tmp, "ws")
for d in ("cfg", "sessions", "threads", "runs", "ws"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server            # noqa: E402 — breaks the import cycle
from longrun.core import httpapi as H      # noqa: E402
from longrun.util import steering          # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


events = []
_orig_pub = H.publish
H.publish = lambda kind, **kw: events.append(dict(kind=kind, **kw))
H._record_llm_cost = lambda *a, **k: None

# ---- A: the server says WHICH session is naming ---------------------------
gate = {"go": False}


def slow_name(sess, model=None, cancel=None):
    sid = (sess or {}).get("id")
    while not gate["go"]:
        time.sleep(0.02)
    return {"ok": True, "session": sid, "titled": 0, "remaining": 0, "model": "fake"}


_orig_name = H.autoname_untitled
H.autoname_untitled = slow_name
r = H.autoname_async({"id": "v878-a", "messages": []})
rows = H.annotate_naming([{"id": "v878-a"}, {"id": "v878-other"}])
check("A1 the run starts", r.get("started") is True, r)
check("A2 /api/sessions rows say WHICH chat is naming",
      rows[0].get("naming") is True and rows[1].get("naming") is False, rows)
gate["go"] = True
time.sleep(0.5)
rows = H.annotate_naming([{"id": "v878-a"}])
check("A3 a closed run clears the server flag", rows[0].get("naming") is False, rows)

# ---- B: a failed load does not leak the in-flight guard -------------------
H.autoname_untitled = _orig_name


def boom(_sid):
    raise RuntimeError("boom")


_orig_load = H.load_session
H.load_session = boom
raised = False
try:
    H.autoname_async("v878-b")
except Exception:
    raised = True
finally:
    H.load_session = _orig_load
H.autoname_untitled = slow_name
gate["go"] = False
r2 = H.autoname_async({"id": "v878-b", "messages": []})
check("B1 a failed load raises instead of silently leaking the guard", raised)
check("B2 the next click still STARTS (the guard is not stuck)", r2.get("started") is True, r2)
gate["go"] = True
time.sleep(0.5)

# ---- C: a consumed Stop does not kill the next run ------------------------
H.autoname_untitled = _orig_name
calls = {"n": 0}


def fake_stream(*a, **kw):
    calls["n"] += 1
    return '[]', "", "mock"


_orig_stream = H.stream_with_fallback
H.stream_with_fallback = fake_stream
steering.push_abort("v878-c")
first = H.autoname_untitled({"id": "v878-c", "messages": []}, model="mock",
                            cancel=lambda: steering._is_aborted("v878-c"))
check("C1 a Stop left behind makes the run pay for no model call",
      first.get("rounds") == 0 and calls["n"] == 0, (first, calls))
H.load_session = lambda sid: {"id": sid, "messages": []}
# the subroutine must NOT clear anything itself: the run's own close consumes the Stop
H.autoname_untitled = lambda sess, model=None, cancel=None: {
    "ok": True, "session": (sess or {}).get("id"), "titled": 0, "remaining": 0}
H.autoname_async({"id": "v878-c", "messages": []})
time.sleep(0.4)
check("C2 the run that consumed the Stop clears it (the next click can work)",
      steering._is_aborted("v878-c") is False)
H.stream_with_fallback = _orig_stream
H.publish = _orig_pub

# ---- D: the WebUI reconciles the marker from the backend -----------------
src = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
api = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
check("D1 the row paints `.naming` from the state, on EVERY render",
      '(namingSessions[s.id] ? " naming" : "")' in src)
check("D2 the list seeds it from the server flag (`s.naming`)",
      "if (s.naming) namingSessions[s.id] = true;" in src)
check("D3 a stale list cannot erase a just-arrived start",
      "_namingReqEpoch" in src and "_namingSeen[s.id]" in src)
check("D4 the server flag is published on the list route",
      'annotate_naming(list_sessions())' in api)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
