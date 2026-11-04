#!/usr/bin/env python3
"""v800 — a scan reads the operator's own sessions and PROPOSES routines (disabled).

Evidence for the need (2026-11-04): the harness could mine sequences of tool NAMES
(`util/selfevolve.py:22-29`) but nothing read WHAT the operator keeps asking for, so
every routine had to be invented by hand — the install had exactly one (`R1`).

Contract locked here:
  * only a real human request is sampled: an `internal` message and a `[harness]`
    injection are the harness talking to itself and never reach the scout;
  * every proposed routine is created `enabled=False` — a scan can propose, it can
    never start an automation;
  * at most `CANDIDATES_MAX` are created, cadence is clamped to `MIN_EVERY`, and a
    goal that already exists as a routine is skipped, never duplicated;
  * a garbage answer, an empty session list or a model failure returns a reason,
    never an exception;
  * one `routine_proposal` audit row is written (with the E-2 harness stamp).

Deterministic: the model call is injected, no live model and no server.

Run: python3 tests/acceptance/v800_session_scan.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v800-")
for _k, _v in (("LONGRUN_DATA_DIR", "data"), ("LONGRUN_CONFIG_DIR", "cfg"),
               ("LONGRUN_SESSIONS_DIR", "sessions"), ("LONGRUN_RUNS_DIR", "runs"),
               ("LONGRUN_DB", "events.db"), ("LONGRUN_AGENTS_FILE", "data/agents.json"),
               ("LONGRUN_ROUTINES_FILE", "data/routines.json")):
    os.environ[_k] = os.path.join(TMP, _v)
os.makedirs(os.path.join(TMP, "data"), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util.fswrite import write_json          # noqa: E402
from longrun.agent import agents                     # noqa: E402
from longrun.orchestrate import routines             # noqa: E402
from longrun.orchestrate import scan                 # noqa: E402
from longrun.util import improve                     # noqa: E402

# one designated agent, so a routine has an owner
write_json(agents.AGENTS_FILE,
           {"agents": {"S-agent": {"id": "A1", "n": 1, "name": "tester"}}, "seq": 1})

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


SESSIONS = [
    {"id": "S1", "title": "deploy", "messages": [
        {"role": "user", "content": "check the deployment logs every morning and tell me what broke"},
        {"role": "assistant", "content": "I will look at them now and report back to you"},
        {"role": "user", "content": "[harness] tool result: 200 OK (must be ignored)"},
        {"role": "user", "content": "internal agentic note", "internal": True},
        {"role": "user", "content": "too short"}]},
    {"id": "S2", "title": "repo", "messages": [
        {"role": "user", "content": "sweep the repository for stale branches every evening please"}]},
]

# ------------------------------------------------------------- A. the sampler --
_lines = scan._operator_lines(SESSIONS)
check("A1 one entry per session that has a real request", len(_lines) == 2, _lines)
check("A2 the injected harness text is excluded",
      all("[harness]" not in t for _t, picked in _lines for t in picked), _lines)
check("A3 an internal message is excluded",
      all("internal agentic note" != t for _t, picked in _lines for t in picked), _lines)
check("A4 a too-short message is excluded",
      all("too short" != t for _t, picked in _lines for t in picked), _lines)
check("A5 the operator's own words survive",
      any("deployment logs" in t for _t, picked in _lines for t in picked), _lines)

_prompt = scan._prompt(_lines)
check("A6 the prompt asks for JSON candidates",
      "candidates" in _prompt[0]["content"] and "JSON" in _prompt[0]["content"])
check("A7 the prompt carries the sampled requests",
      "deployment logs" in _prompt[1]["content"], _prompt[1]["content"][:120])

# ------------------------------------------------------------- B. the proposal --
_seen_prompts = []


def _call(msgs):
    _seen_prompts.append(msgs)
    return json.dumps({"candidates": [
        {"goal": "Check the deployment logs each morning and report what broke.",
         "every_seconds": 86400, "why": "asked twice this week"},
        {"goal": "Sweep the repository for stale branches and list them.",
         "every_seconds": 5, "why": "weekly habit"},
        {"goal": "Third one must be dropped by the cap.",
         "every_seconds": 3600, "why": "over the cap"}]})


got = scan.scan_sessions(sessions=SESSIONS, call=_call, agent="A1")
check("B1 the scan succeeds", got.get("ok") is True and not got.get("reason"),
      (got.get("ok"), got.get("reason")))
check("B2 at most CANDIDATES_MAX routines are created",
      len(got.get("created") or []) == scan.CANDIDATES_MAX, len(got.get("created") or []))
_rows = live = routines.REGISTRY.list()["routines"]
check("B3 the routines exist in the registry", len(live) == scan.CANDIDATES_MAX,
      [r.get("id") for r in live])
check("B4 EVERY proposed routine is DISABLED",
      all(r.get("enabled") is False for r in live), [r.get("enabled") for r in live])
check("B5 the cadence is clamped to MIN_EVERY",
      all(int(r.get("every_seconds") or 0) >= routines.MIN_EVERY for r in live),
      [r.get("every_seconds") for r in live])
check("B6 the scout saw the real prompt", bool(_seen_prompts)
      and "deployment logs" in _seen_prompts[0][-1]["content"])

# --------------------------------------------------------------- C. no doubles --
again = scan.scan_sessions(sessions=SESSIONS, call=_call, agent="A1")
check("C1 a second scan creates nothing new", not (again.get("created") or []),
      [r.get("id") for r in (again.get("created") or [])])
check("C2 it says why", bool(again.get("reason")), again.get("reason"))
check("C3 the registry did not grow",
      len(routines.REGISTRY.list()["routines"]) == scan.CANDIDATES_MAX)

# ------------------------------------------------------------------ D. failures --
_bad = scan.scan_sessions(sessions=SESSIONS, call=lambda _m: "not json at all",
                          agent="A1")
check("D1 a garbage answer is a reason, not a crash",
      _bad.get("ok") is True and not (_bad.get("created") or [])
      and bool(_bad.get("reason")), _bad)
check("D1b the raw answer is kept for diagnosis (declined vs parser)",
      _bad.get("answer_preview") == "not json at all", _bad.get("answer_preview"))
_fenced = scan.scan_sessions(
    sessions=[{"id": "S3", "title": "fenced", "messages": [
        {"role": "user", "content": "please sweep the tmp folder for stale files every day"}]}],
    call=lambda _m: 'Sure:\n```json\n{"candidates":[{"goal":"Sweep tmp for stale files '
                    'daily and log them.","every_seconds":86400,"why":"x"}]}\n```',
    agent="A1")
check("D1c a chatty/fenced answer still parses", len(_fenced.get("created") or []) == 1,
      _fenced)
_empty = scan.scan_sessions(sessions=[], call=_call, agent="A1")
check("D2 no sessions -> no work, with a reason",
      _empty.get("scanned") == 0 and bool(_empty.get("reason")), _empty)
_noagent = scan.scan_sessions(sessions=SESSIONS, call=_call, agent="A999")
check("D3 an unknown owner is refused", _noagent.get("ok") is False
      and bool(_noagent.get("reason")), _noagent)


def _boom(_m):
    raise RuntimeError("model exploded")


_boomres = scan.scan_sessions(sessions=SESSIONS, call=_boom, agent="A1")
check("D4 a model failure is reported, never raised",
      _boomres.get("ok") is False and "exploded" in str(_boomres.get("reason")),
      _boomres)

# --------------------------------------------------------------- E. the audit --
_rows = [json.loads(x) for x in
         open(improve.LEDGER_PATH, encoding="utf-8").read().splitlines() if x.strip()]
_props = [r for r in _rows if r.get("kind") == "routine_proposal"]
check("E1 the scan writes a routine_proposal row", bool(_props), len(_props))
check("E2 that row carries the harness stamp",
      bool(_props) and isinstance(_props[-1].get("harness"), dict),
      _props[-1].get("harness") if _props else None)

# -------------------------------------------------------------- F. source pins --
_src = open(os.path.join(REPO, "src", "longrun", "orchestrate", "scan.py"),
            encoding="utf-8").read()
check("F1 a scan never enables a routine", "enabled=False" in _src
      and "enabled=True" not in _src)
check("F2 there is no second cadence floor", _src.count("MIN_EVERY") >= 2)

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
