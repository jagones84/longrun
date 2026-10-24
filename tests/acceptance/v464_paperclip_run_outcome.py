#!/usr/bin/env python3
"""v464 — machine-readable Longrun run outcomes (Paperclip adapter, Task 1).

The Paperclip adapter may treat a task as done only when Longrun says the agent
EXPLICITLY finished. Today `agent_run_v2` reports `status: "done"` for an
explicit `finish`, for a max-step stop and for the no-progress guard, so the
caller cannot tell a real completion from a bounded stop. This test pins the
additive `termination` field and its five values:

  completed | max_steps | no_progress | aborted | error

It also pins the `batch` action in THIS loop (JAG-533): every call runs, and two
DIFFERENT batches are not mistaken for a repeat (SJ1.3 died at step 2 on exactly
that false positive, 2026-10-23).

Deterministic (scripted actions, no model), isolated (throwaway LONGRUN_* dirs).

Run: python3 tests/acceptance/v464_paperclip_run_outcome.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="sf-v464-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as API  # noqa: E402
from longrun.core import server as S  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- explicit finish ---------------------------------------------------------
res = API.agent_run_v2("goal A", max_steps=3,
                       script=[{"action": "finish", "summary": "all done"}])
check("test_explicit_finish_is_completed",
      res.get("termination") == "completed", res.get("termination"))

# --- step-limit stop ---------------------------------------------------------
res = API.agent_run_v2("goal B", max_steps=1,
                       script=[{"action": "note", "detail": "still working"}])
check("test_step_limit_is_not_completed",
      res.get("termination") == "max_steps", res.get("termination"))

# --- repeated-action guard ---------------------------------------------------
res = API.agent_run_v2("goal C", max_steps=4,
                       script=[{"action": "note", "detail": "same"},
                               {"action": "note", "detail": "same"}])
check("test_repeated_action_is_no_progress",
      res.get("termination") == "no_progress", res.get("termination"))

# --- operator abort ----------------------------------------------------------
st = API.new_run("goal D", max_steps=2)
API.run_control(st.id, "abort")
res = API.agent_run_v2("goal D", max_steps=2,
                       script=[{"action": "finish", "summary": "never reached"}],
                       run_id=st.id)
check("test_operator_abort_is_aborted",
      res.get("termination") == "aborted", res.get("termination"))

# --- forced exception --------------------------------------------------------
_orig_apply = S.apply_agent_action


def _boom(*a, **k):
    raise RuntimeError("forced failure")


S.apply_agent_action = _boom
try:
    res = API.agent_run_v2("goal E", max_steps=2,
                           script=[{"action": "note", "detail": "will explode"}])
finally:
    S.apply_agent_action = _orig_apply
check("test_exception_is_error",
      res.get("termination") == "error", res.get("termination"))

# --- `batch` really runs here, and is never a false 'repeat' (JAG-533) -------
_orig_tool_action = API.tool_action
_calls = []


def _fake_tool_action(st, tool, args, on_event, workspace=None):
    _calls.append((tool, (args or {}).get("path")))
    return ("obs:%s" % (args or {}).get("path"), {"tool": tool, "ok": True})


_BATCH_AB = {"action": "batch", "calls": [{"tool": "fs.read", "args": {"path": "a"}},
                                          {"tool": "fs.read", "args": {"path": "b"}}]}
_BATCH_CD = {"action": "batch", "calls": [{"tool": "fs.read", "args": {"path": "c"}},
                                          {"tool": "fs.read", "args": {"path": "d"}}]}
API.tool_action = _fake_tool_action
try:
    res = API.agent_run_v2("goal G", max_steps=3, script=[_BATCH_AB, _BATCH_CD])
    check("a `batch` action executes every call in the v2 loop",
          res.get("termination") == "completed" and _calls == [
              ("fs.read", "a"), ("fs.read", "b"),
              ("fs.read", "c"), ("fs.read", "d")],
          (res.get("termination"), _calls))
    check("the batch observation carries each call's own result",
          "obs:a" in str(((res.get("trace") or [{}])[0]).get("observation"))
          and "obs:b" in str(((res.get("trace") or [{}])[0]).get("observation")))
    _calls.clear()
    res = API.agent_run_v2("goal H", max_steps=4, script=[_BATCH_AB, _BATCH_AB])
    check("the SAME batch twice is still `no_progress` (guard kept)",
          res.get("termination") == "no_progress" and len(_calls) == 2,
          (res.get("termination"), len(_calls)))
finally:
    API.tool_action = _orig_tool_action

# --- native DSML markup is understood by THIS loop too (JAG-534) -------------
# Subagents run here, and this loop used `extract_json` alone: a model answering
# in its native markup produced a no-op "note" every iteration and the run died.
_orig_stream = S._router_stream
_orig_start_graph = S.start_run_graph
ONE = "<\uff5cDSML\uff5c"
C1 = "</\uff5cDSML\uff5c"
_NATIVE = (ONE + " calls>\n" + ONE + ' invoke name="fs.read">\n'
           + ONE + ' parameter name="path">a.txt</' + "\uff5cDSML\uff5c parameter>\n"
           + C1 + " invoke>\n" + C1 + " calls>")
_stream_calls = {"n": 0}


def _fake_stream(_msgs, _cand, _on=None, usage=None):
    _stream_calls["n"] += 1
    if _stream_calls["n"] == 1:
        return _NATIVE, ""
    return '{"action":"finish","summary":"ok"}', ""


S._router_stream = _fake_stream
S.start_run_graph = lambda *a, **k: None
_calls.clear()
API.tool_action = _fake_tool_action
try:
    res = API.agent_run_v2("goal I", max_steps=3, model="fake:model")
finally:
    S._router_stream = _orig_stream
    S.start_run_graph = _orig_start_graph
    API.tool_action = _orig_tool_action
check("a native-DSML answer runs the tool here too (subagent loop)",
      _calls == [("fs.read", "a.txt")] and res.get("termination") == "completed",
      (_calls, res.get("termination")))

# --- the public run record exposes the same field ----------------------------
res = API.agent_run_v2("goal F", max_steps=2,
                       script=[{"action": "finish", "summary": "ok"}])
pub = (API.run_get(res["run_id"]) or None)
check("test_public_run_exposes_termination",
      pub is not None and pub.public().get("termination") == "completed"
      and res.get("termination") == "completed",
      pub.public().get("termination") if pub else "no run")

# --- the five values are exactly the documented ones -------------------------
_ALLOWED = {"completed", "max_steps", "no_progress", "aborted", "error"}
check("termination values stay inside the documented set",
      all(t in _ALLOWED for t in ("completed", "max_steps", "no_progress",
                                  "aborted", "error")))

print("---")
ok = sum(RESULTS)
print("%d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
