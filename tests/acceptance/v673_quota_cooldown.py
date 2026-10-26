#!/usr/bin/env python3
"""v673 — I-2 quota cooldown: a 429 is REMEMBERED, not re-paid every turn.

Today a provider answering 429 publishes `model.quota` and raises; the turn's
failover already walks the chain. The waste was the NEXT turn: nothing remembered
the closed window, so the same model led the chain again and paid one doomed call
plus its latency. Now a quota note puts that model LAST until the window expires.

  * `routing.note_exhausted(model, secs)` / `is_exhausted(model)` / `order_candidates`
    — process-local, no file, expires in place;
  * `rllm._open_with_retry` records the note on the quota branch;
  * the three chain builders order their candidates: `routing.model_chain`,
    `server.stream_with_fallback` and `api_v02.agent_run_v2`;
  * a single-model chain still returns that model (a closed quota must cost a
    retry, never a dead end).
"""
import inspect
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v673-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_APPROVALS"] = os.path.join(TMP, "approvals.json")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import rllm, routing  # noqa: E402

results = []
A = "openrouter:provider/primary-1"
B = "openrouter:provider/backup-2"


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


routing.note_exhausted(None, 10)
routing.note_exhausted("", 10)
routing.note_exhausted(A, 0)
routing.note_exhausted(B, 0)

# ------------------------------------------------------------- A. mechanics --
check("A1 a fresh model is not exhausted", routing.is_exhausted(A) is False)
_deadline = routing.note_exhausted(A, 60)
check("A2 a note marks exactly that model", routing.is_exhausted(A) is True
      and routing.is_exhausted(B) is False and _deadline is not None)
check("A3 ordering moves the exhausted model LAST, order kept otherwise",
      routing.order_candidates([A, B]) == [B, A], routing.order_candidates([A, B]))
check("A4 a single-model chain still returns that model (no dead end)",
      routing.order_candidates([A]) == [A], routing.order_candidates([A]))
check("A5 duplicates collapse and empty entries are ignored",
      routing.order_candidates([B, "", B, " "]) == [B])
routing.note_exhausted(A, 0)
check("A6 a zero window CLEARS the note", routing.is_exhausted(A) is False)
routing.note_exhausted(A, 0.15)
time.sleep(0.25)
check("A7 the note expires on its own", routing.is_exhausted(A) is False
      and routing.order_candidates([A, B]) == [A, B])
routing.note_exhausted(A, "garbage")
check("A8 a garbage window falls back to the default instead of raising",
      routing.is_exhausted(A) is True)
routing.note_exhausted(A, 0)


def _disabled(fn):
    orig = routing.load_config
    routing.load_config = lambda: {"quota_cooldown": False, "roles": {}}
    try:
        return fn()
    finally:
        routing.load_config = orig


check("A9 the config switch turns the cooldown off",
      _disabled(lambda: routing.note_exhausted(A, 60)) is None
      and routing.is_exhausted(A) is False)

# --------------------------------------------------------------- B. wiring --
check("B1 the shipped config enables it",
      routing.quota_cooldown_on() is True)

_orig_open = urllib.request.urlopen


def _429(*a, **k):
    raise urllib.error.HTTPError("http://127.0.0.1:1/v1/chat", 429,
                                 "Too Many Requests", {}, None)


urllib.request.urlopen = _429
try:
    _req = urllib.request.Request("http://127.0.0.1:1/v1/chat", data=b"{}")
    try:
        rllm._open_with_retry(_req, 1, model=A)
        _raised = False
    except urllib.error.HTTPError:
        _raised = True
finally:
    urllib.request.urlopen = _orig_open
check("B2 a real 429 still raises (the error is not swallowed)", _raised is True)
check("B3 …and the model is remembered for its window", routing.is_exhausted(A) is True)
_chain = routing.model_chain("agent")
if len(_chain) >= 2:
    routing.note_exhausted(_chain[0], 60)
    _after = routing.model_chain("agent")
    check("B4 the role chain puts an exhausted primary last, and keeps it",
          _after[0] != _chain[0] and _chain[0] in _after, _after)
    routing.note_exhausted(_chain[0], 0)
else:
    check("B4 the role chain puts an exhausted primary last, and keeps it", True,
          "single-model chain: nothing to reorder")
check("B5 stream_with_fallback orders its chain",
      "routing.order_candidates(chain)" in inspect.getsource(
          __import__("longrun.core.server", fromlist=["x"]).stream_with_fallback))
check("B6 the v2 loop orders its candidates",
      "order_candidates(candidates)" in inspect.getsource(
          __import__("longrun.core.api_v02", fromlist=["x"]).agent_run_v2))
check("B7 default 1h window when the transport reports none",
      routing.QUOTA_DEFAULT_COOLDOWN == 3600.0)

with open(os.path.join(REPO, "config", "routing.yaml"), encoding="utf-8") as f:
    _cfg = f.read()
check("B8 the config file documents the switch", "quota_cooldown: true" in _cfg)

routing.note_exhausted(A, 0)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
