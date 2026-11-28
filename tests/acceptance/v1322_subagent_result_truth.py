#!/usr/bin/env python3
"""v1322 — a truncated child run is NOT a delivered result (one verdict, everywhere).

Live reproduction (2026-11-28, the session behind the operator's check): the durable
records `sub_5a7b03906a.json` / `sub_a1a7810e89.json` read `status="done"` +
`ok=True` + `termination="max_steps"` + `steps=7` — a child the step budget cut off
was recorded as a SUCCESS, its sentinel summary was handed back to the caller, and
the delegated step was closed as done.

Two causes, both fixed here:
  1. Every success verdict was `status == "done"`, which is true for a truncation
     (the run loops end `status="done"` with `termination="max_steps"`). The one
     honest predicate (`status == "done"` AND termination in ("", "completed")) now
     lives in `subagent._verdict` and is read by `_shrink` (the persisted record),
     `collect` (the live result) and the from-disk replay — so they cannot disagree.
  2. `_persist` is a full-document OVERWRITE, so the completion write dropped
     `output_schema`/`acceptance_criteria` set at spawn; the from-disk replay could
     then never validate the result. The completion record now carries both.

The triggering prompt also stopped teaching a literal `"max_steps":4` (the config
ships 8), which is what truncated the children in the first place.

Deterministic — no model, no network, no server.
Run: python3 tests/acceptance/v1322_subagent_result_truth.py
"""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-1322-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_SUBAGENT_DIR"] = os.path.join(TMP, "subagents")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import subagent as SA            # noqa: E402
from longrun.agent import agent as AG               # noqa: E402
from longrun.core import api_v02                    # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------- A: the verdict
check("A1 _verdict: a completed run is ok",
      SA._verdict({"status": "done", "termination": "completed"}) == (True, ""))
check("A2 _verdict: a run with no termination field is ok",
      SA._verdict({"status": "done"}) == (True, ""))
check("A3 _verdict: a max_steps truncation is NOT ok and names the termination",
      SA._verdict({"status": "done", "termination": "max_steps"})
      == (False, "subagent truncated: termination=max_steps"),
      SA._verdict({"status": "done", "termination": "max_steps"}))
check("A4 _verdict: an error status is never ok",
      SA._verdict({"status": "error"})[0] is False)
check("A5 _shrink: the persisted record is honest about a truncation",
      SA._shrink({"status": "done", "termination": "max_steps", "trace": []}).get("ok") is False
      and SA._shrink({"status": "done", "termination": "completed", "trace": []}).get("ok") is True
      and SA._shrink({"status": "done", "trace": []}).get("ok") is True)
check("A6 _shrink: the persisted error names the truncation",
      "termination=max_steps" in
      SA._shrink({"status": "done", "termination": "max_steps", "trace": []}).get("error", ""))

# ------------------------------------------------- B/C: the live collect verdict
_check_cls = type("_St", (), {})


def _stub_new_run(goal, model=None, max_steps=6, script=None):
    st = _check_cls()
    st.id = "run_%d" % (len(SA._running) + 1)
    st.status = "running"
    st.parent_run_id = None
    st.role = None
    st.tool_allow = None
    st.delegation = {}
    return st


_orig_new_run, _orig_run = api_v02.new_run, api_v02.agent_run_v2
api_v02.new_run = _stub_new_run
try:
    api_v02.agent_run_v2 = lambda *a, **k: {
        "status": "done", "summary": api_v02.max_steps_summary(8, "run_x"),
        "termination": "max_steps", "trace": [{"step": 1}]}
    _sp = SA.spawn("probe a truncation")
    _got = SA.collect(_sp.get("subagent_id"), timeout=10) or {}
    check("B1 live collect: a truncated child is NOT ok", _got.get("ok") is False,
          _got.get("ok"))
    check("B2 live collect: the result names the termination",
          "termination=max_steps" in str(_got.get("error")), _got.get("error"))

    _rec = SA.load_record(_sp.get("subagent_id")) or {}
    check("B3 live collect: the durable record is honest too",
          _rec.get("ok") is False and _rec.get("termination") == "max_steps", _rec.get("ok"))

    api_v02.agent_run_v2 = lambda *a, **k: {
        "status": "done", "summary": "delivered", "termination": "completed", "trace": []}
    _sp2 = SA.spawn("probe a completion")
    _got2 = SA.collect(_sp2.get("subagent_id"), timeout=10) or {}
    check("C1 live collect: a completed child IS ok", _got2.get("ok") is True, _got2.get("ok"))
finally:
    api_v02.new_run, api_v02.agent_run_v2 = _orig_new_run, _orig_run
    SA._running.clear()

# ------------------------------------------- D: the from-disk replay agrees too
SA._persist({"id": "rec_trunc", "status": "done", "termination": "max_steps",
             "summary": "stopped at max_steps=8", "steps": 8})
_d = SA.collect("rec_trunc", timeout=1) or {}
check("D1 a disk record of a truncation replays as NOT ok", _d.get("ok") is False, _d.get("ok"))
check("D2 the disk replay says where it came from", _d.get("from_disk") is True)
SA._persist({"id": "rec_ok", "status": "done", "termination": "completed",
             "summary": "done", "steps": 3})
check("D3 a completed disk record replays as ok",
      (SA.collect("rec_ok", timeout=1) or {}).get("ok") is True)
SA._persist({"id": "rec_legacy", "status": "done", "summary": "legacy", "steps": 2})
check("D4 a legacy record with no termination still replays as ok",
      (SA.collect("rec_legacy", timeout=1) or {}).get("ok") is True)

# ------------------------------ E: the completion record keeps the output contract
api_v02.new_run = _stub_new_run
_orig_run = api_v02.agent_run_v2
api_v02.agent_run_v2 = lambda *a, **k: {
    "status": "done", "summary": "done", "termination": "completed", "trace": []}
try:
    _sp3 = SA.spawn("probe the contract", output_schema={"type": "object"},
                    acceptance_criteria=["file_written:/tmp/v1322"])
    check("E0 the schema-bound spawn succeeded", bool(_sp3.get("subagent_id")), _sp3)
    SA.collect(_sp3.get("subagent_id"), timeout=10)
    _rec3 = SA.load_record(_sp3.get("subagent_id")) or {}
    check("E1 the COMPLETED record keeps output_schema",
          _rec3.get("output_schema") is not None, _rec3.get("output_schema"))
    check("E2 the COMPLETED record keeps acceptance_criteria",
          bool(_rec3.get("acceptance_criteria")), _rec3.get("acceptance_criteria"))
finally:
    api_v02.new_run, api_v02.agent_run_v2 = _orig_new_run, _orig_run
    SA._running.clear()

# ---------------------------------- F: the chat path reports the child as FAILED
_o_spawn, _o_collect = SA.spawn, SA.collect
SA.spawn = lambda goal, **kw: {"subagent_id": "sub_chat", "run_id": "run_chat",
                               "goal": goal}
SA.collect = lambda sid, timeout=None: {
    "ok": False, "status": "done",
    "error": "subagent truncated: termination=max_steps",
    "summary": "stopped at max_steps=8; trace: data/graphs/run_chat.json",
    "result": {"status": "done", "termination": "max_steps"}}
try:
    _ev = []
    _sess = {"id": "v1322chat", "messages": []}
    _out = AG._apply_chat_subagent(
        _sess, {"aim": "do a thing"}, lambda kind, **kw: _ev.append((kind, kw)))
finally:
    SA.spawn, SA.collect = _o_spawn, _o_collect
check("F1 the chat path reports a truncated child as FAILED (never 'finished')",
      "FAILED" in _out and "finished" not in _out, _out[:140])
check("F2 the tool.result event for it is ok=False",
      any(k == "tool.result" and kw.get("ok") is False for k, kw in _ev), _ev[-1:])

# ---------------------------- G: the prompt no longer teaches a truncating cap
_AG = _read("src", "longrun", "agent", "agent.py")
_API = _read("src", "longrun", "core", "api_v02.py")
_SUB = _read("src", "longrun", "agent", "subagent.py")
check("G1 no prompt/source still hardcodes a `max_steps` of 4",
      not re.search(r'"max_steps"\s*:\s*4\b', _AG + _API + _SUB))
check("G2 the chat prompt points the child budget at config/subagents.yaml",
      "config/subagents.yaml" in AG.CHAT_TOOL_PROMPT
      and "leave `max_steps` out" in AG.CHAT_TOOL_PROMPT)

_bad = results.count(False)
print("\n%d/%d checks passed%s" % (len(results) - _bad, len(results),
                                  "" if not _bad else " — FAILED"))
sys.exit(1 if _bad else 0)
