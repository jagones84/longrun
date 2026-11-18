#!/usr/bin/env python3
"""v1148 — the witness reads regex escapes, not only word tokens (round 83).

A literal written with escapes (`127\\.0\\.0\\.1`, `\\.env`) was cut at the backslash
by the literal tokenizer, so the candidate inputs never contained the address and no
witness was built for that rule. Measured on the live service 2026-11-18: the
optimizer proposed removing the `127.0.0.1` control-API guard, `_uncovered_removal`
returned None, and the delta reached the operator's inbox although NO other live rule
matches `curl 127.0.0.1/api/settings`.

Contract:
  A an escaped literal is one literal (`127\\.0\\.0\\.1` -> `127.0.0.1`)
  B the measured 127.0.0.1 removal now yields a witness naming the address
  C the localhost rule keeps its witness (round 78's measured pair)
  D a simple escaped pattern yields its own readable witness
  E a removal still covered by a remaining rule is NOT refuted
  F run() turns the measured delta into a skip quoting the witness

Deterministic: patterns copied verbatim, no config, no model, no network.
Run: python3 tests/acceptance/v1148_witness_reads_escapes.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1148-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_OPTIMIZER_LOG"] = os.path.join(TMP, "optimizer_runs.jsonl")
for _d in ("cfg", "data", "runs"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.evolve import optimizer as O       # noqa: E402

R127 = r"(?:curl|wget)[^\n]*127\.0\.0\.1[^\n]*/api/(jobs|agents|teams|architect|tools|settings|docs|fs|edits)"
LOCAL = r"(?:curl|wget)[^\n]*localhost[^\n]*/api/(jobs|agents|teams|architect|tools|settings|docs|fs|edits)"
LIVE = [R127, LOCAL]

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- A) one literal, not four ----------------------------------------------
_lits = [m.group(0) for m in O._LITERAL_RE.finditer(O._ESCAPED_PUNCT_RE.sub(r"\1", R127))]
check("A1 the escaped address is one literal", "127.0.0.1" in _lits, _lits)
check("A2 the raw form still splits (the regression this fixes)",
      "127.0.0.1" not in [m.group(0) for m in O._LITERAL_RE.finditer(R127)])


# ---- B) the measured 127 removal is refuted --------------------------------
_w = O._removal_witness(R127, [LOCAL])
check("B1 a witness is found for the 127.0.0.1 rule", bool(_w), _w)
check("B2 the witness names the address", bool(_w) and "127.0.0.1" in _w, _w)
check("B3 the localhost rule does not cover it", bool(_w) and "localhost" not in _w, _w)

# ---- C) round 78's measured pair still refutes ----------------------------
_w2 = O._removal_witness(LOCAL, [R127])
check("C1 the localhost rule keeps its witness", bool(_w2) and "localhost" in _w2, _w2)


# ---- D) a simple escaped pattern ------------------------------------------
_w3 = O._removal_witness(r"cat\s+foo\.bar", [])
check("D1 a dotted literal is read whole", _w3 == "cat foo.bar", _w3)
_w4 = O._removal_witness(r"(?:^|[\s'\"=:(/])\.env(?!\.template\b)", [])
check("D2 the env rule yields a witness containing .env", bool(_w4) and ".env" in _w4, _w4)


# ---- E) covered by a remaining rule is not a refutation --------------------
_w5 = O._removal_witness(LOCAL, [LOCAL])
check("E1 an identical duplicate guards nothing unique (not refuted)", _w5 is None, _w5)
_w6 = O._removal_witness(r"curl localhost", ["curl"])
check("E2 a broader remaining rule covers the removal", _w6 is None, _w6)


# ---- F) run() quotes the witness ------------------------------------------
import longrun.tools.registry as R          # noqa: E402

_orig_spec = R.tool_spec
R.tool_spec = lambda name: ({"deny": list(LIVE)} if name in ("shell.exec", "shell") else {})
O._read_trace = lambda sid: {"tokens": 10, "steps": 2, "outcome": "ok", "model": "m"}
O._read_policy_hits = lambda: {"firings": {}, "retired_rules": [], "never_fired": [],
                               "unknown_args": {}}
O._read_job_cost = lambda jid: {}
O._read_feedback = lambda sid: {}
O._evolution_history = lambda: []
SUBMITTED = []
_orig_submit = O._submit
O._submit = lambda delta, evidence, sid: (SUBMITTED.append(delta) or "pid")
try:
    O._call_model = lambda prompt, model=None: json.dumps(
        {"target": "shell.exec", "field": "deny", "add": [],
         "remove": [R127], "reason": "duplicate of the localhost rule", "confidence": "low"})
    _r = O.run("v1148-a")
    check("F1 the measured delta is a skip", _r.get("skip") is True and not SUBMITTED,
          _r.get("reason"))
    check("F2 the reason quotes the witness with the address",
          "127.0.0.1" in (_r.get("reason") or ""), _r.get("reason"))
finally:
    O._submit = _orig_submit
    R.tool_spec = _orig_spec

print("---")
_passed = sum(RESULTS)
print("%d/%d PASS" % (_passed, len(RESULTS)))
sys.exit(0 if _passed == len(RESULTS) else 1)
