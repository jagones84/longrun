#!/usr/bin/env python3
"""v1141 — the optimizer names WHY the provider call failed (round 76).

`run()` used to log "unparseable model reply" for every provider failure, so 95 of
170 live runs blamed the model's formatting for an infrastructure answer. Measured
on the live key on 2026-11-18: HTTP 403, "Key limit exceeded (total limit) …
$133.06 of $133.00 used; does not reset" — no reply at all.

Contract:
  A `_error_line` is a sanitized one-liner (status + provider message, no URL)
  B `_call_model` separates an HTTP error, a 200 carrying `error`, an empty 200
    and a real completion; the failure slot is cleared on every success
  C `run()` logs four different reasons, and the log row keeps the reply
  D the successful path still reaches the approvals pipeline

Deterministic: urlopen and the endpoint are stubbed, no network.
Run: python3 tests/acceptance/v1141_optimizer_call_failure.py
"""
import io
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1141-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_OPTIMIZER_LOG"] = os.path.join(TMP, "optimizer_runs.jsonl")
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_RUNS_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.evolve import optimizer as O      # noqa: E402
from longrun.model import providers as P       # noqa: E402
from longrun.util import improve as I          # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


BODY_403 = json.dumps({"error": {"message":
                      "Key limit exceeded (total limit). Manage it using "
                      "https://openrouter.ai/workspaces/default/keys/8f3bb92e "
                      "$133.06 of $133.00 used; does not reset.",
                      "code": 403}}).encode()


# ---- A) the sanitized line ---------------------------------------------------
_line = O._error_line(exc=urllib.error.HTTPError(
    "https://openrouter.ai/api/v1/chat/completions", 403, "Forbidden", None,
    io.BytesIO(BODY_403)))
check("A1 an HTTP error is named by its status", _line.startswith("HTTP 403: "), _line)
check("A2 the provider message survives", "$133.06 of $133.00" in _line, _line)
check("A3 no URL reaches the log", "http" not in _line and "8f3bb92e" not in _line, _line)
check("A4 whitespace is collapsed onto one line", "\n" not in _line, _line)
check("A5 a 200-style error object is named too",
      O._error_line(payload={"code": 429, "message": "rate limited"}).startswith("HTTP 429: "),
      O._error_line(payload={"code": 429, "message": "rate limited"}))
check("A6 an object without a code still says why",
      "rate limited" in O._error_line(payload={"message": "rate limited"})
      and O._error_line(payload={"message": "rate limited"}).startswith("call failed: "),
      O._error_line(payload={"message": "rate limited"}))
check("A7 a plain exception is named",
      O._error_line(exc=TimeoutError("timed out")).startswith("call failed: "),
      O._error_line(exc=TimeoutError("timed out")))
_long = O._error_line(payload={"message": "x" * 600})
check("A8 the line is bounded", len(_long) <= 260, len(_long))


# ---- B) _call_model's four outcomes -----------------------------------------
_orig_endpoint, _orig_urlopen = P.endpoint, urllib.request.urlopen
P.endpoint = lambda model: ("http://fake/v1", {}, "fake-model")


class _Resp:
    def __init__(self, obj):
        self._raw = json.dumps(obj).encode()

    def read(self):
        return self._raw


def _raise_403(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", None,
                                 io.BytesIO(BODY_403))


try:
    urllib.request.urlopen = _raise_403
    check("B1 an HTTP error returns None", O._call_model("p", model="m") is None)
    check("B2 B1 names the status and the limit",
          O._LAST_CALL_ERROR.startswith("HTTP 403: ")
          and "Key limit exceeded" in O._LAST_CALL_ERROR, O._LAST_CALL_ERROR)
    check("B3 B1 leaks no URL or key id",
          "http" not in O._LAST_CALL_ERROR and "8f3bb92e" not in O._LAST_CALL_ERROR,
          O._LAST_CALL_ERROR)

    urllib.request.urlopen = lambda req, timeout=None: _Resp(
        {"error": {"code": 402, "message": "payment required"}})
    check("B4 a 200 carrying `error` is a failure, not an empty reply",
          O._call_model("p", model="m") is None
          and "payment required" in O._LAST_CALL_ERROR, O._LAST_CALL_ERROR)

    urllib.request.urlopen = lambda req, timeout=None: _Resp({"choices": []})
    check("B5 an empty completion is '' with no error",
          O._call_model("p", model="m") == "" and O._LAST_CALL_ERROR == "",
          (O._LAST_CALL_ERROR,))

    urllib.request.urlopen = lambda req, timeout=None: _Resp(
        {"choices": [{"message": {"content": '{"skip": true}'}, "finish_reason": "stop"}]})
    _reply = O._call_model("p", model="m")
    check("B6 a completion is returned verbatim", _reply == '{"skip": true}', _reply)
    check("B7 a success CLEARS the previous failure",
          O._LAST_CALL_ERROR == "", O._LAST_CALL_ERROR)

    # Round 77: a reasoning model spends the whole budget thinking and is cut
    # before emitting any content (measured: 8192/8192 tokens, 43.5 s).
    urllib.request.urlopen = lambda req, timeout=None: _Resp(
        {"choices": [{"message": {"content": "", "reasoning_content": "…"}, "finish_reason": "length"}]})
    check("B9 a reply cut at the limit is a named failure, not an empty reply",
          O._call_model("p", model="m") is None
          and "finish_reason=length" in O._LAST_CALL_ERROR, O._LAST_CALL_ERROR)

    urllib.request.urlopen = lambda req, timeout=None: _Resp(
        {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]})
    check("B10 an empty answer the model chose to send is still 'empty'",
          O._call_model("p", model="m") == "" and O._LAST_CALL_ERROR == "",
          O._LAST_CALL_ERROR)
finally:
    P.endpoint, urllib.request.urlopen = _orig_endpoint, _orig_urlopen

_orig_model = O._optimizer_model
O._optimizer_model = lambda: None
try:
    check("B8 no model configured is its own state",
          O._call_model("p") is None and "no model" in O._LAST_CALL_ERROR,
          O._LAST_CALL_ERROR)
finally:
    O._optimizer_model = _orig_model


# ---- C) run() logs four different reasons -----------------------------------
O._read_trace = lambda sid: {"tokens": 10, "steps": 2, "outcome": "ok", "model": "m"}
O._read_policy_hits = lambda: {}
O._read_job_cost = lambda jid: {}
O._read_feedback = lambda sid: {}


def _run_with_urlopen(fn):
    O.run("v1141-a")  # warm any lazy import
    urllib.request.urlopen = fn
    return O.run("v1141-a")


try:
    _orig_endpoint = P.endpoint
    P.endpoint = lambda model: ("http://fake/v1", {}, "fake-model")
    _r = _run_with_urlopen(_raise_403)
    check("C1 a provider failure names the call, not the model's format",
          _r.get("reason", "").startswith("model call failed: HTTP 403: "),
          _r.get("reason"))
    check("C2 its log row keeps an empty reply", _r.get("reply") == "", _r.get("reply"))

    _r = _run_with_urlopen(lambda req, timeout=None: _Resp({"choices": []}))
    check("C3 an empty completion is 'empty reply from the model'",
          _r.get("reason") == "empty reply from the model", _r.get("reason"))

    _r = _run_with_urlopen(lambda req, timeout=None: _Resp(
        {"choices": [{"message": {"content": "I see no problem here."}}]}))
    check("C4 prose is 'unparseable model reply'",
          _r.get("reason") == "unparseable model reply", _r.get("reason"))
    check("C5 the prose is kept in the row", "no problem" in (_r.get("reply") or ""),
          _r.get("reply"))

    # Round 77: a model-reported skip is the model's own reasoning — the one skip
    # whose text the operator wants to read.
    _r = _run_with_urlopen(lambda req, timeout=None: _Resp(
        {"choices": [{"message": {"content":
                                  '{"skip": true, "reason": "the rules are load-bearing"}'},
                      "finish_reason": "stop"}]}))
    check("C9 a model-reported skip keeps the model's reasoning",
          _r.get("reason") == "model reported skip"
          and "load-bearing" in (_r.get("reply") or ""), _r.get("reply"))
finally:
    P.endpoint = _orig_endpoint
    urllib.request.urlopen = _orig_urlopen

O._call_model = lambda prompt, model=None: None
_r = O.run("v1141-a")
check("C6 a seam that returns nothing is 'no reply from the model'",
      _r.get("reason") == "no reply from the model", _r.get("reason"))
notes = [json.loads(line) for line in
         open(os.environ["LONGRUN_OPTIMIZER_LOG"], encoding="utf-8") if line.strip()]
_check = [n["proposal"].get("reason") for n in notes]
check("C7 every reason reached the log", len(notes) >= 4, len(notes))
check("C8 the four reasons are distinct in the log",
      sum(1 for r in _check if str(r).startswith("model call failed")) >= 1
      and any(r == "empty reply from the model" for r in _check)
      and any(r == "unparseable model reply" for r in _check)
      and any(r == "no reply from the model" for r in _check), _check)


# ---- D) the successful path still reaches the approvals pipeline -------------
O._call_model = lambda prompt, model=None: json.dumps(
    {"target": "shell.exec", "field": "approval", "value": "required",
     "reason": "probe", "confidence": "low"})
_r = O.run("v1141-a")
check("D1 a real delta is still submitted", bool(_r.get("proposal_id")), _r)
check("D2 it is a registry proposal waiting on the operator",
      any(p.get("id") == _r.get("proposal_id") and p.get("status") == "pending"
          for p in I.list_proposals()), _r.get("proposal_id"))

print("---")
passed = sum(RESULTS)
print("%d/%d PASS" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
