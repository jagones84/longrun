#!/usr/bin/env python3
"""v1154 — the post-turn proposer can be switched off (round 90).

Measured on the live store: `agent.chat_once` ends every turn with
`optimizer.run(sid)`, which asks a model for one registry delta whenever the
trace has >= 1 tool call (`MIN_TOOL_CALLS = 1`). The log holds 202 such calls
(18 in the last hour). Consequence measured in a DETERMINISTIC test: `v693`
drives a real `chat_once`, so it reached the network —
`connect(('3.173.21.63', 443))` — and its `network.assert_not_called` guard was
the only thing that noticed. The battery had been spending model calls silently.

Contract:
  A unset = ON (production behaviour unchanged)
  B "0" / "false" / "no" / "off" = OFF (case and whitespace ignored)
  C anything else = ON (a typo never silently disables RSI)
  D the only call site asks `enabled()` before `run()`
  E the battery exports LONGRUN_OPTIMIZER=0 for every test it runs
  F a test that drives chat_once declares it too (v693)

Deterministic: the module is read, no model, no network.
Run: python3 tests/acceptance/v1154_rsi_opt_out.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.evolve import optimizer as O               # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


_orig = os.environ.pop("LONGRUN_OPTIMIZER", None)
try:
    check("A1 unset means ON (production unchanged)", O.enabled() is True, O.enabled())

    for raw in ("0", "false", "FALSE", "no", "OFF", "  0  ", "Off"):
        os.environ["LONGRUN_OPTIMIZER"] = raw
        check("B %r turns it off" % raw, O.enabled() is False, O.enabled())

    for raw in ("1", "true", "yes", "on", "", "maybe", "00"):
        os.environ["LONGRUN_OPTIMIZER"] = raw
        check("C %r leaves it on" % raw, O.enabled() is True, O.enabled())
finally:
    os.environ.pop("LONGRUN_OPTIMIZER", None)
    if _orig is not None:
        os.environ["LONGRUN_OPTIMIZER"] = _orig

agent_src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
                 encoding="utf-8").read()
api_src = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
               encoding="utf-8").read()
check("D1 the chat call site asks enabled() before run()",
      "if _opt.enabled():\n            _opt.run(sess[\"id\"])" in agent_src,
      "call site")
check("D2 the run worker asks enabled() before run()",
      "if _opt.enabled():   # round 90: one switch for both call sites" in api_src,
      "run worker")
check("D3 those are the only two post-turn calls to optimizer.run",
      agent_src.count("_opt.run(") == 1 and api_src.count("_opt.run(") == 1,
      (agent_src.count("_opt.run("), api_src.count("_opt.run(")))

battery = open(os.path.join(REPO, "tests", "battery.sh"), encoding="utf-8").read()
check("E1 the battery exports LONGRUN_OPTIMIZER=0",
      "LONGRUN_OPTIMIZER=0" in battery, "battery.sh")

v693 = open(os.path.join(REPO, "tests", "acceptance",
                         "v693_harness_chat_diagnostics.py"), encoding="utf-8").read()
check("F1 v693 declares the opt-out itself",
      'os.environ["LONGRUN_OPTIMIZER"] = "0"' in v693, "v693 header")

# G — the same promise for the router probe: a saved session queues the context
# backfill, whose meter asks `rllm.router_models()`. Offline it must answer
# without opening a socket.
from longrun.model import rllm as R                      # noqa: E402

check("G1 the battery exports LONGRUN_OFFLINE=1",
      "LONGRUN_OFFLINE=1" in battery, "battery.sh")
check("G2 v693 declares it too", 'os.environ["LONGRUN_OFFLINE"] = "1"' in v693,
      "v693 header")

_orig_urlopen = R.urllib.request.urlopen


def _boom(*a, **k):
    raise AssertionError("the router must not be contacted offline")


R.urllib.request.urlopen = _boom
try:
    os.environ["LONGRUN_OFFLINE"] = "1"
    check("G3 offline router_models answers [] without a request",
          R.router_models() == [], R.router_models())
finally:
    R.urllib.request.urlopen = _orig_urlopen
    os.environ.pop("LONGRUN_OFFLINE", None)

print("---")
print("%d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
