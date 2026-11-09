#!/usr/bin/env python3
"""v923 — a model hop that fails AFTER being paid for is still accounted (DR-R).

The run loop walks the failover chain and calls `_account_call` only after a hop
SUCCEEDS. A provider that streams tokens and then dies (5xx mid-stream, a dropped
connection, a router swap) is paid for by the operator, and that spend vanished:
`tokens_spent` reported only the hop that answered.

Now the exception path accounts whatever `usage` the failed hop already reported.

The second half of the plan item — "a blank final reply ends in an error state" —
is PARKED, not shipped: `v770` A3 pins the opposite on purpose (the agent loop
keeps its nudge path, after an operator complaint about lost turns). See the plan.

Deterministic: the router is a stub, temp dirs, no model, no network, no server.
"""
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="sf-v923-")
for _k, _d in (("CONFIG_DIR", "cfg"), ("SESSIONS_DIR", "sessions"),
               ("GRAPH_DIR", "graphs"), ("EDITS_DIR", "edits"),
               ("RUNS_DIR", "runs"), ("COSTS_DIR", "costs"),
               ("ROLES_DIR", "roles")):
    _p = os.path.join(_tmp, _d)
    os.makedirs(_p, exist_ok=True)
    os.environ["LONGRUN_" + _k] = _p
os.environ["LONGRUN_DB"] = os.path.join(_tmp, "events.db")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02, server  # noqa: E402
from longrun.model import routing  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


CALLS = []
FINISH = '{"action":"finish","summary":"done"}'


def stub_stream(messages, alias, on_delta, timeout=None, usage=None, guard=None,
                cancel=None, no_reasoning=False, max_tokens=None,
                temperature=None, seed=None):
    """m1 streams 120 tokens and then DIES; m2 answers and finishes the run."""
    CALLS.append(alias)
    if alias == "m1":
        if usage is not None:
            usage.update({"prompt_tokens": 100, "completion_tokens": 20})
        raise RuntimeError("provider 500 mid-stream")
    if usage is not None:
        usage.update({"prompt_tokens": 10, "completion_tokens": 5})
    return FINISH, ""


_orig_stream = server._router_stream
_orig_order = routing.order_candidates
server._router_stream = stub_stream
routing.order_candidates = lambda c: list(c)
try:
    out = api_v02.agent_run_v2("prove the accounting", max_steps=1, model="m1",
                               fallbacks=["m2"], on_event=lambda *a, **k: None)
    st = api_v02.run_get(out["run_id"])
finally:
    server._router_stream = _orig_stream
    routing.order_candidates = _orig_order

check("A1 the run completed on the second candidate",
      st.status == "done" and "m2" in CALLS, (st.status, CALLS))
check("A2 the PAID, failed hop is counted (120 + 15 = 135 tokens)",
      int(getattr(st, "tokens_spent", 0) or 0) == 135,
      getattr(st, "tokens_spent", None))

# ---- B: a hop that reported NOTHING still costs nothing -------------------
CALLS.clear()


def stub_bare(messages, alias, on_delta, timeout=None, usage=None, guard=None,
              cancel=None, no_reasoning=False, max_tokens=None,
              temperature=None, seed=None):
    CALLS.append(alias)
    if alias == "m1":
        raise RuntimeError("connection reset before any byte")
    if usage is not None:
        usage.update({"prompt_tokens": 10, "completion_tokens": 5})
    return FINISH, ""


server._router_stream = stub_bare
routing.order_candidates = lambda c: list(c)
try:
    out2 = api_v02.agent_run_v2("no usage on the failed hop", max_steps=1,
                                model="m1", fallbacks=["m2"],
                                on_event=lambda *a, **k: None)
    st2 = api_v02.run_get(out2["run_id"])
finally:
    server._router_stream = _orig_stream
    routing.order_candidates = _orig_order

check("B1 an empty failed hop adds nothing (no invented tokens)",
      int(getattr(st2, "tokens_spent", 0) or 0) == 15,
      getattr(st2, "tokens_spent", None))

# ---- C: the accounting call is ON the exception path ----------------------
_src = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
            encoding="utf-8").read()
_i = _src.find("except Exception as _e:")
check("C1 the failover handler accounts the failed hop's usage",
      _i > 0 and "_account_call(st, _call_usage" in _src[_i:_i + 600],
      _src[_i:_i + 200] if _i > 0 else "handler not found")

print("\n---\nv923: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
