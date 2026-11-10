#!/usr/bin/env python3
"""v799 — the lesson distiller reads the turn's tool OUTCOMES, not just the prose.

Evidence for the need (2026-11-04): `maybe_reflect` was sent
`Goal: %s\nOutcome: %s` (500 + 800 chars of the final answer) and nothing else
(`agent/agent.py:2577-2582`). The tool cards were already persisted with `ok`,
`error` and `exit_code` (`memory/stores.py:856-899`) but never read, so a lesson
described the wording of an answer and could not see that `shell` failed three
times — the exact thing a lesson is supposed to prevent.

Contract locked here:
  * `_tool_evidence(cards)` is bounded (count + length), tolerates garbage and
    never raises;
  * an OK card contributes `tool OK`, a failed one carries exit code and error;
  * the prompt is BYTE-IDENTICAL to the old one when there is no evidence (so a
    turn with no tool cards behaves exactly as before);
  * with evidence the body gains one `Tool evidence:` block and the system
    instruction is unchanged;
  * `_improvement_pass` really passes THIS turn's cards (it slices them by the
    count captured at turn start, not the whole session history).

Deterministic, no live model, no network, no server.

Run: python3 tests/acceptance/v799_reflect_evidence.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v799-")
for _k, _v in (("LONGRUN_DATA_DIR", "data"), ("LONGRUN_CONFIG_DIR", "cfg"),
               ("LONGRUN_SESSIONS_DIR", "sessions"), ("LONGRUN_RUNS_DIR", "runs"),
               ("LONGRUN_DB", "events.db"), ("LONGRUN_GRAPH_DIR", "graphs"),
               ("LONGRUN_EDITS_DIR", "edits"), ("LONGRUN_PROJECTS_DIR", "projects")):
    os.environ[_k] = os.path.join(TMP, _v)
sys.path.insert(0, os.path.join(REPO, "src"))

# `server` must be imported FIRST: it re-exports the agent surface, and importing
# the agent module directly trips the circular import (same order as v446).
from longrun.core import server               # noqa: E402,F401
from longrun.agent import agent as A          # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ------------------------------------------------------- A. the evidence builder --
check("A1 no cards -> no evidence", A._tool_evidence(None) == []
      and A._tool_evidence([]) == [], (A._tool_evidence(None), A._tool_evidence([])))

_ok = A._tool_evidence([{"tool": "fs.read", "ok": True}])
check("A2 an OK card is one short line", _ok == ["fs.read OK"], _ok)

_bad = A._tool_evidence([{"tool": "shell", "ok": False, "exit_code": 1,
                          "error": "line one\nline two"}])
check("A3 a failure carries the tool, the exit code and the error",
      len(_bad) == 1 and "shell FAILED" in _bad[0] and "exit=1" in _bad[0]
      and "line one line two" in _bad[0], _bad)
check("A4 the error is collapsed to ONE line", "\n" not in (_bad[0] if _bad else ""))

_mixed = A._tool_evidence([{"tool": "a", "ok": True}, {}, None,
                           {"tool": "b", "ok": False, "error": "x"},
                           {"not_a_card": 1}])
check("A5 junk and empty entries are skipped, never raised",
      _mixed == ["a OK", "b FAILED: x"], _mixed)

_many = A._tool_evidence([{"tool": "t%d" % i, "ok": True} for i in range(40)])
check("A6 the count is bounded", len(_many) <= A.EVIDENCE_MAX, len(_many))
check("A7 every line is bounded",
      all(len(x) <= A.EVIDENCE_CHARS for x in
          A._tool_evidence([{"tool": "x" * 400, "ok": False, "error": "e" * 400}])))

try:
    class _Boom(dict):
        def get(self, *_a, **_k):
            raise RuntimeError("boom")
    check("A8 a broken card never raises", A._tool_evidence([_Boom()]) == [])
except Exception as exc:  # noqa: BLE001
    check("A8 a broken card never raises", False, exc)

# ------------------------------------------------ B. the prompt it produces -----
_seen = []


def _fake_stream(msgs, model, on_delta, timeout=60, cancel=None):
    _seen.append([dict(m) for m in msgs])
    return "prefer the narrow grep before a full read", None


_orig = A._router_stream
A._router_stream = _fake_stream
try:
    A._REFLECT_LATEST.clear()
    A.maybe_reflect({"id": "S-noev", "tool_cards": []}, "goal text", "answer text", True)
    _noev = _seen[-1] if _seen else []
    _body = (_noev[-1] or {}).get("content", "") if _noev else ""
    check("B1 no evidence -> the OLD body, byte for byte",
          _body == "Goal: goal text\nOutcome: answer text", repr(_body))
    check("B2 no evidence -> no empty block is appended", "Tool evidence" not in _body)

    A._REFLECT_LATEST.clear()
    A.maybe_reflect({"id": "S-ev", "tool_cards": []}, "goal text", "answer text", True,
                    evidence=["shell FAILED (exit=1): kaboom", "fs.read OK"])
    _ev = _seen[-1] if _seen else []
    _evbody = (_ev[-1] or {}).get("content", "") if _ev else ""
    check("B3 evidence is appended as one block", "Tool evidence:" in _evbody, repr(_evbody))
    check("B4 every evidence line is present",
          "shell FAILED (exit=1): kaboom" in _evbody and "fs.read OK" in _evbody, _evbody)
    check("B5 the goal and outcome are still there",
          _evbody.startswith("Goal: goal text\nOutcome: answer text"), _evbody[:60])
    check("B6 the system instruction is unchanged by the evidence",
          bool(_noev) and bool(_ev) and _noev[0] == _ev[0])

    A._REFLECT_LATEST.clear()
    A.maybe_reflect({"id": "S-blank", "tool_cards": []}, "g", "a", True, evidence=["", "  "])
    _blankbody = ((_seen[-1][-1] or {}).get("content", "") if _seen else "")
    check("B7 blank evidence lines add no block", _blankbody == "Goal: g\nOutcome: a",
          repr(_blankbody))
finally:
    A._router_stream = _orig

# ----------------------------------------- C. the call site passes THIS turn ----
_captured = {}


def _fake_reflect(sess, message, answer, used_tools, model=None, evidence=None):
    _captured["evidence"] = evidence
    return None


_orig_reflect = A.maybe_reflect
A.maybe_reflect = _fake_reflect
try:
    # `_improvement_pass` must forward the evidence it is handed. Six tools make
    # the importance gate (>= 5) pass, so the distiller really is called.
    A._improvement_pass({"id": "S-pass"}, "goal", "answer", ["a"] * 6, 3, "m", {},
                        evidence=["old.tool OK"])
    check("C1 _improvement_pass forwards the evidence it is given",
          _captured.get("evidence") == ["old.tool OK"], _captured.get("evidence"))
finally:
    A.maybe_reflect = _orig_reflect

_src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("D1 the turn start records the card boundary", "_cards_base = len(" in _src)
check("D2 the call site slices the cards from that boundary",
      "_cards_base:]" in _src and "evidence=_tool_evidence(" in _src)
check("D3 the boundary is captured BEFORE the call that reads it",
      0 <= _src.find("_cards_base = len(") < _src.find("evidence=_tool_evidence("))

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
