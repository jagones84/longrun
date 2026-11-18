#!/usr/bin/env python3
"""v1145 — the hit ledger keeps the call that was blocked, not only its count (round 79).

The loop could refute a removal with a synthetic witness (round 78) but not the
model's other premise: "this guard blocked a legitimate call 35 times". The ledger
carried `n` / `first_ts` / `last_ts` and nothing about WHICH call — measured on the
live file 2026-11-18: 52 keys, 0 samples. So every friction claim was a count.

Contract:
  A `note_rule_hit(..., sample=...)` keeps the last few distinct inputs, redacted
  B `classify` records the real subject at both firing sites (deny, always_ask)
  C the samples survive `policy_report()` and a reload from disk
  D the optimizer shows them (prompt + live-policy snapshot)
  E `_unchanged_friction` refutes a removal whose recorded input stays blocked
  F `run()` turns that refutation into a skip, and still submits a real fix

Deterministic: temp data/config dirs, no network, no model.
Run: python3 tests/acceptance/v1145_policy_hit_samples.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1145-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_OPTIMIZER_LOG"] = os.path.join(TMP, "optimizer_runs.jsonl")
for _d in ("cfg", "data", "runs"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                 # noqa: E402,F401 — breaks the import cycle
from longrun.tools import registry as R         # noqa: E402
from longrun.evolve import optimizer as O       # noqa: E402
from longrun.util import improve as I           # noqa: E402

R._external_tools = lambda: {}                  # never start an MCP client in a test

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


CFG = {"tools": {"shell.exec": {"enabled": True, "approval": "auto",
                                "deny": ["rm -rf"], "always_ask": ["deploy"]}},
       "approvals": {"mode": "normal"}}
R.load_config = lambda reload=False: CFG


# ---- A) the sample is recorded, bounded, deduplicated and redacted -----------
_rep = R.policy_report()
R._HITS = {}                                    # start from a clean ledger for A
R.classify("shell.exec", {"command": "rm -rf /tmp/x"})
_rec = R.policy_report()["firings"].get("shell.exec:deny:rm -rf") or {}
check("A1 the blocked input is recorded",
      _rec.get("samples") == ["rm -rf /tmp/x"], _rec)
check("A2 the counter is unchanged", _rec.get("n") == 1, _rec)

R.classify("shell.exec", {"command": "rm -rf /tmp/x"})
_rec = R.policy_report()["firings"].get("shell.exec:deny:rm -rf") or {}
check("A3 the same input twice is one sample", _rec.get("samples") == ["rm -rf /tmp/x"]
      and _rec.get("n") == 2, _rec)

for _i in range(4):
    R.classify("shell.exec", {"command": "rm -rf /tmp/d%d" % _i})
_rec = R.policy_report()["firings"].get("shell.exec:deny:rm -rf") or {}
check("A4 at most three inputs are kept", len(_rec.get("samples") or []) == 3, _rec)
check("A5 the newest input is last",
      (_rec.get("samples") or [""])[-1] == "rm -rf /tmp/d3", _rec)

_r = R.note_rule_hit("t", "deny", "p", 'curl -H "Authorization: Bearer abcdef0123456789" x')
_rec = R._hits()[_r]
check("A6 a bearer token is redacted", "abcdef0123456789" not in _rec["samples"][0]
      and "Bearer <redacted>" in _rec["samples"][0], _rec["samples"])
_r = R.note_rule_hit("t", "deny", "q", "export OPENAI_API_KEY=sk-abcdef0123456789")
check("A7 an sk- key is redacted", "sk-abcdef0123456789" not in R._hits()[_r]["samples"][0],
      R._hits()[_r]["samples"])
_r = R.note_rule_hit("t", "deny", "s", "git show 0123456789abcdef0123456789abcdef01234567")
check("A8 a long hex id is redacted", "<hex>" in R._hits()[_r]["samples"][0],
      R._hits()[_r]["samples"])
_r = R.note_rule_hit("t", "deny", "w", "a\n\tb   c")
check("A9 whitespace is collapsed", R._hits()[_r]["samples"] == ["a b c"],
      R._hits()[_r]["samples"])
_r = R.note_rule_hit("t", "deny", "l", "x" * 400)
check("A10 the sample is bounded", len(R._hits()[_r]["samples"][0]) == R._SAMPLE_MAX,
      len(R._hits()[_r]["samples"][0]))
_r = R.note_rule_hit("t", "deny", "n")
check("A11 no sample means no samples key", "samples" not in R._hits()[_r], R._hits()[_r])
_r = R.note_rule_hit("t", "deny", "e", "   ")
check("A12 an empty sample is not recorded", "samples" not in R._hits()[_r], R._hits()[_r])


# ---- B) classify's other firing site ----------------------------------------
R.classify("shell.exec", {"command": "deploy to prod"})
_rec = R.policy_report()["firings"].get("shell.exec:always_ask:deploy") or {}
check("B1 an always-ask firing keeps its subject too",
      _rec.get("samples") == ["deploy to prod"], _rec)


# ---- C) the report and the disk ---------------------------------------------
check("C1 policy_report carries the samples",
      (R.policy_report()["firings"].get("shell.exec:deny:rm -rf") or {})
      .get("samples") == ["rm -rf /tmp/d1", "rm -rf /tmp/d2", "rm -rf /tmp/d3"],
      R.policy_report()["firings"].get("shell.exec:deny:rm -rf"))
_disk = json.load(open(R._HIT_PATH, encoding="utf-8"))
check("C2 the samples are persisted",
      (_disk.get("shell.exec:deny:rm -rf") or {}).get("samples"), _disk.get("shell.exec:deny:rm -rf"))
R._HITS = None                                  # simulate a restart
check("C3 a reload still has them",
      (R.policy_report()["firings"].get("shell.exec:deny:rm -rf") or {})
      .get("samples") == ["rm -rf /tmp/d1", "rm -rf /tmp/d2", "rm -rf /tmp/d3"],
      R.policy_report()["firings"].get("shell.exec:deny:rm -rf"))


# ---- D) the optimizer shows the blocked call --------------------------------
HITS = {"firings": {"shell.exec:deny:rm -rf": {"n": 35,
                                               "samples": ["rm -rf /tmp/x"]},
                    "shell.exec:deny:gone-rule": {"n": 9,
                                                  "samples": ["old thing"]}},
        "retired_rules": ["shell.exec:deny:gone-rule"],
        "never_fired": [], "unknown_args": []}
_live, _gone = O._hit_rows(HITS)
check("D1 the live row carries its sample", _live[0].get("sample") == "rm -rf /tmp/x", _live)
check("D2 the retired row carries its own too",
      _gone[0].get("sample") == "old thing", _gone)
_prompt = O._build_analysis_prompt({"tokens": 10, "steps": 2}, HITS, {}, {})
check("D3 the prompt names the blocked call", "blocked: rm -rf /tmp/x" in _prompt,
      _prompt[:200])
check("D4 it does not print a retired rule's sample", "old thing" not in _prompt)
check("D5 it tells the model a count is not evidence", "a count is not evidence" in _prompt)

_orig_spec = R.tool_spec
try:
    R.tool_spec = lambda name: ({"approval": "auto", "deny": ["rm -rf"],
                                 "always_ask": [], "auto_approve": []}
                                if name == "shell.exec" else {})
    _snap = O._policy_snapshot(HITS)
finally:
    R.tool_spec = _orig_spec
check("D6 the snapshot names the blocked call", "blocked: rm -rf /tmp/x" in _snap, _snap)

_ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("D7 the Permissions evidence tooltip shows the blocked call",
      "e.g. blocked: " in _ui and "hit.samples" in _ui)


# ---- E) the refutation ------------------------------------------------------
DENY = ["curl localhost", "curl"]
HITS2 = {"firings": {"shell.exec:deny:curl localhost": {"n": 35,
                                                       "samples": ["curl localhost/api/jobs"]},
                     "shell.exec:deny:curl": {"n": 12,
                                              "samples": ["curl example.com/api"]}},
         "retired_rules": [], "never_fired": [], "unknown_args": []}
try:
    R.tool_spec = lambda name: ({"deny": list(DENY)} if name == "shell.exec" else {})
    _f = O._unchanged_friction({"target": "shell.exec", "field": "deny",
                                "remove": ["curl localhost"]}, HITS2)
    check("E1 a removal that leaves the recorded call blocked is refuted",
          _f and _f.get("pattern") == "curl localhost" and _f.get("also") == ["curl"], _f)
    _f = O._unchanged_friction({"target": "shell.exec", "field": "deny",
                                "remove": ["curl"]}, HITS2)
    check("E2 a removal that unblocks the recorded call is not refuted", _f is None, _f)
    _f = O._unchanged_friction({"target": "shell.exec", "field": "approval",
                                "value": "required"}, HITS2)
    check("E3 a non-deny field is never refuted here", _f is None, _f)
    _f = O._unchanged_friction({"target": "nosuch.tool", "field": "deny",
                                "remove": ["curl localhost"]}, HITS2)
    check("E4 an unknown row is the validator's refusal, not this check", _f is None, _f)
    _f = O._unchanged_friction({"target": "shell.exec", "field": "deny",
                                "remove": ["curl localhost"]}, {"firings": {}})
    check("E5 no recorded input means nothing to refute", _f is None, _f)
    _f = O._unchanged_friction({"target": "shell.exec", "field": "deny",
                                "remove": ["curl localhost"],
                                "add": ["curl localhost/api"]}, HITS2)
    check("E6 an added rule that covers the call still refutes", _f is not None, _f)
finally:
    R.tool_spec = _orig_spec


# ---- F) run() -----------------------------------------------------------------
SUBMITTED = []
O._read_trace = lambda sid: {"tokens": 10, "steps": 2, "outcome": "ok", "model": "m"}
O._read_policy_hits = lambda: HITS2
O._read_job_cost = lambda jid: {}
O._read_feedback = lambda sid: {}
O._evolution_history = lambda: []
_orig_submit = O._submit
O._submit = lambda delta, evidence, sid: (SUBMITTED.append(delta) or "pid-1")
try:
    R.tool_spec = lambda name: ({"deny": list(DENY)} if name == "shell.exec" else {})
    O._call_model = lambda prompt, model=None: json.dumps(
        {"target": "shell.exec", "field": "deny", "remove": ["curl localhost"],
         "reason": "this guard blocked 35 legitimate local calls", "confidence": "high"})
    _r = O.run("v1145-a")
    check("F1 the refuted removal is a skip",
          _r.get("skip") is True and not SUBMITTED, _r.get("reason"))
    check("F2 the reason quotes the real call",
          "curl localhost/api/jobs" in (_r.get("reason") or ""), _r.get("reason"))
    check("F3 the skip keeps the delta and the model's reply",
          _r.get("delta") and _r.get("reply"), list(_r))

    O._call_model = lambda prompt, model=None: json.dumps(
        {"target": "shell.exec", "field": "deny", "add": ["wget"],
         "reason": "wget is the same class of fetch as curl", "confidence": "high"})
    _r = O.run("v1145-a")
    check("F4 a real delta still reaches the operator",
          bool(_r.get("proposal_id")) and len(SUBMITTED) == 1, _r.get("reason"))
finally:
    O._submit = _orig_submit
    R.tool_spec = _orig_spec

print("---")
passed = sum(RESULTS)
print("%d/%d PASS" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
