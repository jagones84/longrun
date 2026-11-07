#!/usr/bin/env python3
"""v865 — ONE kind per gate: the chip and the metric must name WHICH gate fired.

Live report 2026-11-07 (session `765d2ea340a1`): two `closure-check` chips a few
seconds apart with DIFFERENT texts, "non mi torna". They were two different gates —
the request-anchored close verdict and the VERIFY GATE — but SEVEN distinct
messages all travelled as `closure-check`, so the transcript told the operator
nothing and `gate_stats` merged seven mechanisms into one bucket.

Fixed without touching a single word of any message: every call site now carries its
own kind. Deterministic: temp dirs, no model, no network.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import atexit

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v865-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for d in ("cfg", "sessions", "threads"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _srv      # noqa: E402,F401  (import order)
from longrun.core import events as EV        # noqa: E402
from longrun.harness import cycle as CYCLE   # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()

# ---- A. each gate carries its own kind ---------------------------------------
OWN = {
    "failed-call": "_inject(_failed_call_check_prompt(_last_failed_err), \"failed-call\")",
    "intent-gate": "_inject(_intent_gate_text(), \"intent-gate\")",
    "evidence-gate": "_inject(_evidence_gate_text(), \"evidence-gate\")",
    "citation-check": "_inject(_cite, \"citation-check\")",
    "verify-gate": "_inject(_verify_gate_text(), \"verify-gate\")",
    "forced-close-verify": "_inject(_forced_close_verify_text(_request_thread_text), "
                           "\"forced-close-verify\")",
}
for kind, line in OWN.items():
    check("A-%s the gate injects as its own kind" % kind, line in SRC)

check("A1 the SAME text is never injected under two kinds",
      SRC.count("_inject(_verify_gate_text(), \"closure-check\")") == 0
      and SRC.count("_inject(_evidence_gate_text(), \"closure-check\")") == 0
      and SRC.count("_inject(_cite, \"closure-check\")") == 0
      and SRC.count("_inject(_intent_gate_text(), \"closure-check\")") == 0
      and SRC.count("_inject(_failed_call_check_prompt(") ==
      SRC.count("_failed_call_check_prompt(_last_failed_err), \"failed-call\")"))

# every remaining `"closure-check"` belongs to the close verdict itself: its inject
# call sites, the `_inject` branch that reads it, and the tuple that also names the
# forced close.
_cc = len(re.findall(r'_inject\(_closure_check_prompt\([^\n]*\), "closure-check"\)', SRC))
_all_cc = SRC.count('"closure-check"')
check("A2 `closure-check` now means ONLY the close verdict",
      _cc >= 5 and _all_cc == _cc + 2, (_cc, _all_cc))

# ---- B. the read-back findings ride the two CLOSE verdicts --------------------
check("B1 a closure-check carries the harness's own findings",
      'elif kind in ("closure-check", "forced-close-verify"):' in SRC
      and "_with_known_gaps(content, _review_known)" in SRC)
check("B2 a gate that is NOT a close verdict does not get them",
      'elif kind == "closure-check":' not in SRC)

# ---- C. the metric separates the gates ---------------------------------------
EV.publish("harness.gates", session="v865", work_steps=3,
           fired=[{"kind": "evidence-gate", "work_after": True},
                  {"kind": "verify-gate", "work_after": True},
                  {"kind": "final", "work_after": False}])
st = CYCLE.gate_stats(days=7)
by = {d.get("kind"): d for d in (st.get("kinds") or [])}
check("C1 each gate is its own row in the metric",
      (by.get("evidence-gate") or {}).get("fired") == 1
      and (by.get("verify-gate") or {}).get("fired") == 1, st)
check("C2 a merge into one bucket is gone",
      not (by.get("closure-check") or {}).get("fired"), st)

print("---")
okc = sum(results)
print("\nv865: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
