#!/usr/bin/env python3
"""v1151 — what the agent did AFTER a refusal (round 86).

The hit ledger knows a deny rule FIRED; it does not know whether the guard cost the
turn. A count alone let the model call any busy rule "friction". The transcript
carries the other half: each `[harness] BLOCKED by harness policy` message names the
tool and the exact pattern, and the next assistant message is the next attempt.

Contract:
  A a block followed by another tool call is `continued`
  B a block followed by a second block is `repeated`
  C a block followed by prose is `gave_up`
  D a block at the end of the transcript is `gave_up`
  E a non-block message is ignored; the key is `<tool>:deny:<pattern>` verbatim
  F only the last REFUSAL_SCAN_MAX messages are read
  G the prompt row carries the refusal split; a rule without refusals has none
  H the prompt says `gave up` is friction and `continued` is not
  I run() records the counts in `evidence`
  J no transcript is no evidence ({} and no crash)

Deterministic: a synthetic transcript in a temp data dir, no model, no network.
Run: python3 tests/acceptance/v1151_refusal_outcomes.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1151-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_OPTIMIZER_LOG"] = os.path.join(TMP, "optimizer_runs.jsonl")
for _d in ("cfg", "data", "runs"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.evolve import optimizer as O       # noqa: E402
from longrun.memory import stores as S          # noqa: E402

PAT = r"(?:^|[\s'\"=:(/])\.env(?!\.template\b)"
BLOCK_TMPL = ("[harness] BLOCKED by harness policy — this is NOT a failure of your "
              "arguments, and repeating the same call cannot work. Tell the OPERATOR, in "
              "plain words, which action is blocked and what they must change (the ▶ on "
              "the plan bar, an approval, or the policy/config). Then continue with "
              "anything else that helps, or answer with what you have.\n\n"
              "Action 'shell.exec' BLOCKED by the harness policy: matches hard-deny "
              "pattern %s — denied because the env file holds the API bearer — read what "
              "is configured with `self.info`. It was NOT executed. A hard rule has no "
              "approval to grant, so repeating the same call cannot work — change the "
              "command or the policy.")
BLOCK = BLOCK_TMPL % ("'" + PAT + "'")
# The live harness formats the pattern with `%r` (registry.classify): the text is a
# Python repr, so its backslashes and quotes are doubled.
BLOCK_REPR = BLOCK_TMPL % repr(PAT)
TOOL = '{"action":"tool","tool":"python.run","args":{"code":"x"}}'
OBS = "[harness] Observation for tool python.run: [python.run] exit=0 ok=True"
ANSWER = "I cannot read the env file; the policy blocks it. Here is what I have."

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def _sess(sid, msgs):
    S.save_session({"id": sid, "title": "v1151", "messages": msgs})


KEY = "shell.exec:deny:" + PAT

# ---- A/B/C/D) the four outcomes ----------------------------------------------
_sess("v1151a", [
    {"role": "user", "content": "go"},
    {"role": "user", "content": BLOCK},
    {"role": "assistant", "content": TOOL},
    {"role": "user", "content": OBS},
    # repeated: the next attempt is blocked again
    {"role": "user", "content": BLOCK},
    {"role": "assistant", "content": TOOL},
    {"role": "user", "content": BLOCK},
    {"role": "assistant", "content": TOOL},
    {"role": "user", "content": OBS},
    # gave up: prose after a block
    {"role": "user", "content": BLOCK},
    {"role": "assistant", "content": ANSWER},
    # and one at the very end with no assistant after it
    {"role": "user", "content": BLOCK},
])
_r = O._read_refusals("v1151a")
check("A1 one refused call continued with another tool call",
      _r.get(KEY, {}).get("continued") == 2, _r.get(KEY))
check("B1 a block answered by another block is `repeated`",
      _r.get(KEY, {}).get("repeated") == 1, _r.get(KEY))
check("C1 a block answered with prose is `gave_up`",
      _r.get(KEY, {}).get("gave_up") == 2, _r.get(KEY))
check("C2 every block is counted once",
      _r.get(KEY, {}).get("n") == 5, _r.get(KEY))
check("D1 the key is tool:deny:pattern verbatim", KEY in _r, list(_r))

# ---- E) non-block messages are ignored ----------------------------------------
_sess("v1151b", [
    {"role": "user", "content": "hello"},
    {"role": "assistant", "content": TOOL},
    {"role": "user", "content": OBS},
])
check("E1 a transcript with no block yields {}", O._read_refusals("v1151b") == {})

# ---- R) the real `%r` rendering decodes to the ledger pattern -------------------
_sess("v1151r", [
    {"role": "user", "content": BLOCK_REPR},
    {"role": "assistant", "content": TOOL},
    {"role": "user", "content": OBS},
])
_rr = O._read_refusals("v1151r")
check("R1 the repr-escaped pattern decodes to the ledger key", KEY in _rr, list(_rr))
check("R2 the decoded key has no doubled backslash", "\\\\" not in (list(_rr) or [""])[0],
      list(_rr))


# ---- F) the tail bound ---------------------------------------------------------
_filler = [{"role": "assistant", "content": "working"}] * 405
_sess("v1151c", [
    {"role": "user", "content": BLOCK},            # outside the 400-message window
    {"role": "assistant", "content": TOOL},
] + _filler + [
    {"role": "user", "content": BLOCK},            # inside it
    {"role": "assistant", "content": ANSWER},
])
_rf = O._read_refusals("v1151c")
check("F1 only the last REFUSAL_SCAN_MAX messages are read",
      _rf.get(KEY, {}).get("n") == 1 and _rf.get(KEY, {}).get("gave_up") == 1,
      _rf.get(KEY))
check("F2 the bound is 400", O.REFUSAL_SCAN_MAX == 400)

# ---- G/H) the prompt -----------------------------------------------------------
_HITS = {"firings": {KEY: {"n": 5, "samples": ["cat .env"]}},
         "retired_rules": [], "never_fired": [], "unknown_args": {},
         "fired_rules": [KEY], "configured_rules": [KEY]}
_REF = {KEY: {"n": 5, "continued": 2, "repeated": 1, "gave_up": 2}}
_p = O._build_analysis_prompt({"tokens": 1, "steps": 2}, _HITS, {}, {},
                              history=[], refusals=_REF)
check("G1 the row carries the split",
      "after 5 refusal(s): 2 continued with another call, 1 repeated the same call, "
      "2 gave up" in _p, _p[:400])
_p2 = O._build_analysis_prompt({"tokens": 1, "steps": 2}, _HITS, {}, {},
                               history=[], refusals={})
check("G2 a rule with no refusals prints no split",
      "after 5 refusal(s)" not in _p2)
check("H1 the prompt says gave up is friction, continued is not",
      "`gave up` is friction" in _p and "did not stop the work" in _p)


# ---- I) run() records the counts ----------------------------------------------
XKEY = "shell.exec:deny:" + r"cat\s+\.env"
XB = BLOCK.replace(PAT, r"cat\s+\.env")
_sess("v1151d", [
    {"role": "user", "content": XB},
    {"role": "assistant", "content": TOOL},
    {"role": "user", "content": OBS},
    {"role": "user", "content": XB},
    {"role": "assistant", "content": ANSWER},
])
O._read_trace = lambda sid: {"tokens": 10, "steps": 2, "outcome": "ok", "model": "m"}
O._read_policy_hits = lambda: {"firings": {XKEY: {"n": 2, "samples": ["cat .env"]}},
                               "retired_rules": [], "never_fired": [],
                               "unknown_args": {}, "fired_rules": [XKEY],
                               "configured_rules": [XKEY]}
O._read_job_cost = lambda jid: {}
O._read_feedback = lambda sid: {}
O._evolution_history = lambda: []
SUBMITTED = []
_orig_submit = O._submit
O._submit = lambda delta, evidence, sid: (SUBMITTED.append(delta) or "pid")
try:
    O._call_model = lambda prompt, model=None: json.dumps({"skip": True,
                                                           "reason": "nothing"})
    _run = O.run("v1151d")
    check("I1 evidence counts both refusals",
          _run.get("evidence", {}).get("refusals") == 2, _run.get("evidence"))
    check("I2 evidence counts the give-up",
          _run.get("evidence", {}).get("refusals_gave_up") == 1,
          _run.get("evidence"))
    check("I3 the prompt built for the run carries the split",
          "after 2 refusal(s): 1 continued with another call, 0 repeated the same "
          "call, 1 gave up" in (_run.get("prompt") or ""))
finally:
    O._submit = _orig_submit

# ---- J) no transcript -----------------------------------------------------------
check("J1 an unknown session is no evidence", O._read_refusals("nope-1151") == {})
check("J2 an empty id is no evidence", O._read_refusals("") == {})

print("---")
_passed = sum(RESULTS)
print("%d/%d PASS" % (_passed, len(RESULTS)))
sys.exit(0 if _passed == len(RESULTS) else 1)
