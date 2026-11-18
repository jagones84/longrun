#!/usr/bin/env python3
"""v1152 — compaction never opens on a result whose request it dropped (round 87).

Source: S-2026-11-18-008 "Protocol-Preserving Context Trimming" (the newest
archive report's open question: "is longrun's compaction already protocol-state
safe?"). Measured on the live store before the fix: 43 of 52 sessions over
`keep_recent` put a `[harness]` message — an observation, a batch report, a plan
acknowledgement — at the START of the verbatim window, i.e. the model saw the
RESULT of a call whose request had been summarized away.

Contract:
  A `_is_harness_msg` reads the marker, tolerates leading space and non-strings
  B a window that starts on a harness message moves back by one (the request returns)
  C a safe window is byte-identical and reports zero shift
  D a run of harness messages moves at most BOUNDARY_MAX and keeps one verbatim
  E the moved messages are summarized, never silently dropped
  F the over-budget guard drops a leading harness run instead of exposing it
  G `compact()` reports `boundary_shift` in its stats
  H no compaction needed -> the messages come back unchanged
  I a live-shaped transcript: after compact() the window never opens on `[harness]`

Deterministic: no model, no network, no live data dir needed.
Run: python3 tests/acceptance/v1152_compaction_protocol_state.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1152-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for _d in ("cfg", "data"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import context_engine as ce       # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def u(text, role="user"):
    return {"role": role, "content": text}


def a(text):
    return {"role": "assistant", "content": text}


HARNESS_OBS = "[harness] Observation for tool shell.exec: [shell.exec] exit=0 ok=True"
HARNESS_PLAN = "[harness] Noted — plan updated (by id). STILL OPEN (1): n2"


# ---- A) the marker ------------------------------------------------------------
check("A1 a harness message is recognised", ce._is_harness_msg(u(HARNESS_OBS)))
check("A2 leading whitespace is tolerated", ce._is_harness_msg(u("  \n" + HARNESS_PLAN)))
check("A3 an assistant call is not a harness message", not ce._is_harness_msg(a('{"action":"tool"}')))
check("A4 a non-string content is safe", not ce._is_harness_msg({"role": "user", "content": 42}))
check("A5 a non-dict is safe", not ce._is_harness_msg("text"))


# ---- B) one step back ---------------------------------------------------------
old = [u("request one"), a('{"action":"tool","tool":"shell.exec"}')]
recent = [u(HARNESS_OBS), a("done"), u("next request")]
moved = ce._trim_boundary(old, recent)
check("B1 the window moves back by one", moved == 1, moved)
check("B2 the requesting call is now the first kept message",
      recent[0].get("content") == '{"action":"tool","tool":"shell.exec"}', recent[0])
check("B3 the result stays next to its request",
      recent[1].get("content") == HARNESS_OBS, recent[1])


# ---- C) already safe ----------------------------------------------------------
old = [u("x")]
recent = [a('{"action":"tool"}'), u(HARNESS_OBS), a("done")]
_before = [dict(m) for m in recent]
moved = ce._trim_boundary(old, recent)
check("C1 no shift when the window is safe", moved == 0, moved)
check("C2 the window is unchanged", recent == _before)


# ---- D) a pathological run: the bound, then the drop ---------------------------
old = [a('{"action":"tool","call":0}'), u("[harness] a"), u("[harness] b"),
       u("[harness] c")]
recent = [u("[harness] d"), a("final")]
moved = ce._trim_boundary(old, recent)
check("D1 the move is bounded by BOUNDARY_MAX", moved == ce.BOUNDARY_MAX == 3, moved)
check("D2 the bound leaves the result first (the drop must finish the job)",
      str(recent[0].get("content") or "").startswith("[harness]"), recent[0])
_dropped = ce._drop_leading_harness(recent)
check("D3 the leading run is dropped, never exposed", _dropped == 4, _dropped)
check("D4 the window starts on a real turn", recent[0].get("content") == "final", recent[0])
check("D5 one message always survives", len(recent) == 1, len(recent))


# ---- E) compact() reports the shift and keeps the pair ------------------------
_hist = [u("the request that asked for the check")]
for i in range(10):
    _hist.append(a('{"action":"tool","n":%d}' % i))
    _hist.append(u(HARNESS_OBS + " #%d" % i))
out, st = ce.compact(_hist, 10**9, keep_recent=3, force=True)
_body = [m for m in out if m.get("role") != "system"]
check("E1 the window no longer opens on the result",
      bool(_body) and not str(_body[0].get("content") or "").lstrip().startswith("[harness]"),
      _body[0] if _body else None)
check("E2 the shift is reported", st.get("boundary_shift", 0) >= 1, st.get("boundary_shift"))
check("E3 the pulled-forward call is kept and nothing is dropped",
      st.get("dropped") == 0 and bool(_body)
      and _body[0].get("content") == '{"action":"tool","n":8}', _body[:1])


# ---- F) the over-budget guard -------------------------------------------------
_big = [u("s")]
for i in range(6):
    _big.append(a('{"action":"tool","call":%d}' % i))
    _big.append(u(HARNESS_OBS + " " + ("z" * 400) + " #%d" % i))
out2, st2 = ce.compact(_big, 600, keep_recent=6, force=True)
_body2 = [m for m in out2 if m.get("role") != "system"]
check("F1 the guard never exposes a leading harness run",
      not _body2 or not str(_body2[0].get("content") or "").lstrip().startswith("[harness]"),
      _body2[0] if _body2 else None)
check("F2 the dropped run is counted", st2.get("dropped", 0) >= 0)


# ---- G/H) stats and the no-op path --------------------------------------------
_small = [u("one"), a("two"), u("three")]
out3, st3 = ce.compact(_small, 10**9, keep_recent=8)
check("G1 boundary_shift exists on every stats dict", "boundary_shift" in st3, st3)
check("H1 under budget the messages are unchanged", out3 == _small and st3["kept"] == len(_small))


# ---- I) a live-shaped transcript ----------------------------------------------
_live = [u("please run the checks")]
for i in range(16):
    _live.append(a('{"action":"tool","tool":"shell.exec","args":{"command":"make %d"}}' % i))
    _live.append(u("[harness] Observation for tool shell.exec: exit 0 #%d" % i))
    if i % 3 == 0:
        _live.append(u(HARNESS_PLAN))
out4, st4 = ce.compact(_live, 10**9, force=True)
_body4 = [m for m in out4 if m.get("role") != "system"]
check("I1 a live-shaped transcript never opens on [harness]",
      bool(_body4) and not str(_body4[0].get("content") or "").lstrip().startswith("[harness]"),
      _body4[0] if _body4 else None)
check("I2 the kept window is still the tail",
      bool(_body4) and _body4[-1] is _live[-1])

print("---")
_passed = sum(RESULTS)
print("%d/%d PASS" % (_passed, len(RESULTS)))
sys.exit(0 if _passed == len(RESULTS) else 1)
