#!/usr/bin/env python3
"""v470 — one transient 5xx from the model endpoint must not kill an agent run (JAG-477).

The DGX router runs with `--models-max 1 --parallel 1`, so a task whose own tool
calls the model endpoint (a smoke test curling :8080) forces a model swap and the
NEXT harness call can get HTTP 500. That used to end the run as `error` after two
steps. A single short retry is enough; a 4xx is a contract error and must still
fail fast (no retry).

Deterministic: the model stream is stubbed, `time.sleep` is neutralised.
Run: python3 tests/acceptance/v470_agent_model_retry.py
"""
import os
import sys
import tempfile
import urllib.error

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v470-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as API  # noqa: E402
from longrun.core import server as SRV   # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# The run must not touch a real model or the real graph/checkpoint stores.
SRV.start_run_graph = lambda *a, **k: None
SRV.finish_run_graph = lambda *a, **k: None
API.time.sleep = lambda *_: None

FINISH = '{"thought":"done","action":"finish","summary":"ok"}'


def _http_error(code):
    return urllib.error.HTTPError("http://127.0.0.1:8080/v1/chat/completions",
                                  code, "Internal Server Error", {}, None)


def _run_with(sequence):
    """Run one agent loop whose model stream follows `sequence` (exceptions or text)."""
    calls = {"n": 0}
    seen = []

    def fake_stream(_msgs, _cand, _on_delta=None):
        i = calls["n"]
        calls["n"] += 1
        item = sequence[min(i, len(sequence) - 1)]
        if isinstance(item, Exception):
            raise item
        return item, ""

    SRV._router_stream = fake_stream
    st = API.new_run("goal", "fake:model", 2)
    res = API.agent_run_v2("goal", 2, "fake:model",
                           lambda kind, **d: seen.append(kind), run_id=st.id)
    return res, calls["n"], seen


# 1. a 500 first, then a normal answer -> the run SUCCEEDS on the retry.
res, n, seen = _run_with([_http_error(500), FINISH])
check("a transient 500 is retried and the run completes",
      res.get("termination") == "completed" and n == 2,
      "termination=%s calls=%s" % (res.get("termination"), n))
check("the retry is visible in the run events", "model.retry" in seen, seen)

# 2. a 4xx is a contract error: fail fast, never retry.
res2, n2, _seen2 = _run_with([_http_error(400), FINISH])
check("a 4xx fails fast without a retry",
      res2.get("termination") == "error" and n2 == 1,
      "termination=%s calls=%s" % (res2.get("termination"), n2))

print("---")
ok = sum(RESULTS)
print("v470: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
