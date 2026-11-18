#!/usr/bin/env python3
"""v1147 — an undeclared-argument record names the call that carried it (round 81).

Round 79 gave the deny/always_ask records the refused input, and left the R4 staging
(`unknown_arg`) with only the argument name — which names no call. The suite that
decides whether the refusal may ship could say "`timeout` ×3" and not WHICH call
passed `timeout`. Round 81 records the subject at the same seam and shows it.

Contract:
  A `tools.execute` records the undeclared argument WITH the call's subject
  B the optimizer's "Unknown args" line names the call and no longer dumps timestamps
  C the Permissions row's tooltip names the call
  D the sample goes through the same redaction/bound as every other record

Deterministic: temp dirs, stubbed note_rule_hit, no model, no network.
Run: python3 tests/acceptance/v1147_unknown_arg_samples.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1147-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for _d in ("cfg", "data"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                 # noqa: E402,F401 — breaks the import cycle
from longrun.tools import registry as R         # noqa: E402
from longrun.tools import tools as T            # noqa: E402
from longrun.evolve import optimizer as O       # noqa: E402

R._external_tools = lambda: {}

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- A) the execute seam records the subject -------------------------------
# `shell.exec` needs no workspace root, so the call itself succeeds deterministically.
CAP = []
_orig_note = R.note_rule_hit
R.note_rule_hit = lambda tool, kind, pattern, sample=None: CAP.append((tool, kind, pattern, sample))
try:
    _res = T.execute("shell.exec", {"command": "echo hi", "bogus": 1})
finally:
    R.note_rule_hit = _orig_note

check("A1 the call ran and reported the ignored argument",
      _res.get("ok") and _res.get("warning"), (_res.get("ok"), _res.get("error")))
_ua = [c for c in CAP if c[1] == "unknown_arg"]
check("A2 the unknown argument was recorded", bool(_ua), CAP)
check("A3 the record carries the CALL's subject",
      bool(_ua) and _ua[0][3] == "echo hi", _ua[:1])
check("A4 the key still carries the argument's own message",
      bool(_ua) and "bogus" in str(_ua[0][2]), _ua[:1])


# ---- B) the optimizer's line ------------------------------------------------
UNK = {"fs.read:unknown_arg:unknown argument 'lines' (did you mean 'end_line'?)":
       {"n": 2, "first_ts": 1794000000.0, "last_ts": 1794999999.0, "samples": ["/srv/x.txt"]},
       "improve.repairs:unknown_arg:unknown argument 'since'": {"n": 5}}
_p = O._build_analysis_prompt({"tokens": 1, "steps": 1},
                              {"firings": {}, "retired_rules": [], "never_fired": [],
                               "unknown_args": UNK}, {}, {})
check("B1 the line names the call", "e.g. call: /srv/x.txt" in _p, _p[-600:])
check("B2 it names the argument and the tool", "fs.read" in _p and "'lines'" in _p)
check("B3 no timestamp is dumped to the model",
      "first_ts" not in _p and "last_ts" not in _p and "1794" not in _p, _p[-600:])
check("B4 a record without a call prints as a row, not as a dict dump",
      ("improve.repairs %r x5" % "unknown argument 'since'") in _p, _p[-600:])
check("B5 the header still says Unknown args (the section marker)",
      "Unknown args" in _p)


# ---- C) the Permissions row -------------------------------------------------
_ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
_start = _ui.index("function renderPermissions")
_render = _ui[_start:_ui.index("\nfunction ", _start + 10)]
check("C1 the row reads the sample from the record", ".slice(-1)[0]" in _render)
check("C2 the tooltip names the call", 'e.g. call: ' in _render
      and "${u.sample ?" in _render)


# ---- D) the same redaction and bound ---------------------------------------
_r = R.note_rule_hit("fs.read", "unknown_arg", "unknown argument 'x'",
                     "curl -H 'Authorization: Bearer abcdef0123456789abcdef' /tmp/a")
_rec = R._hits()[_r]
check("D1 the sample is redacted", "abcdef0123456789" not in _rec["samples"][0]
      and "Bearer <redacted>" in _rec["samples"][0], _rec["samples"])
_r = R.note_rule_hit("fs.read", "unknown_arg", "unknown argument 'y'", "z" * 400)
check("D2 the sample is bounded", len(R._hits()[_r]["samples"][0]) == R._SAMPLE_MAX)

print("---")
_passed = sum(RESULTS)
print("%d/%d PASS" % (_passed, len(RESULTS)))
sys.exit(0 if _passed == len(RESULTS) else 1)
