#!/usr/bin/env python3
"""v1281 — `tools.execute` re-asserts the hard deny on EVERY call.

Bug hunt 2026-11-23. The gate (`registry.classify`) is applied by the CALLER
(`api_v02.tool_action`), and the `tools.py` module docstring said so — but
`execute` is ALSO reachable directly. A self-evolved Matrix tool (a module
"forged" from a mined tool sequence) runs every step through
`longrun.tools.tools.execute`, and its generated docstring promised it "never
bypasses a gate". Proved live: a forged step calling `shell.exec` with a
hard-denied command — one that `approvals.mode=full` must never lift — executed
with `ok=True`, because the nested `execute` never asked `registry.deny_hit`.
The hard deny is the ONE boundary FULL cannot lift, so under the live
`approvals.mode=full` it was the only net, and skipping it left none.

Fix: `execute` re-asserts `registry.deny_hit(tool, args)` immediately before the
dispatch — side-effect free (no approval round-trip, no firing accounting), the
same judge `classify` uses, so a nested/self-evolved caller cannot launder a
deny.

Contract:
  R0 self-test: the hard-deny rule is PRESENT for the probe command (non-vacuity)
  R1 REGRESSION: a direct/nested `execute` of that command is refused
     (ok=False, exit 126, denied=True, the error names the hard-deny pattern,
     and NOTHING ran)
  R2 no over-block: an ordinary, allowed tool call still runs to completion
  R3 parity: `registry.classify` and `tools.execute` agree on the same call
  R4 the forged-tool step runner routes through `execute` (so the guard sits on
     the forged path, not merely beside it)
  R5 the guard fires for a second spelling of the same boundary (the `.env` file)

Deterministic: `registry.deny_hit`/`classify` are pure; the refused call returns
BEFORE any dispatch, and R2 reads THIS file. No model, no network.
Run: python3 tests/acceptance/v1281_execute_reasserts_hard_deny.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-v1281-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "DATA_DIR", "GRAPH_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(_tmp, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry      # noqa: E402
from longrun.tools import tools as T    # noqa: E402

# Hermetic: the gate never needs the live external (MCP) catalog, and resolving it
# would open sockets — every acceptance test here is no-network.
registry._external_tools = lambda: {}

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# The probe: an interpreter one-liner naming the run/event store — a hard deny in
# `shell.exec.deny` (config/tools.yaml), the same spelling v1075/v1083 pin.
PROBE = "python3 -c \"open('data/events.db','w').write('{}')\""

# ---- R0: the rule exists (non-vacuity) -------------------------------------
_hit = registry.deny_hit("shell.exec", {"command": PROBE})
check("R0 the hard-deny rule is present for the probe", bool(_hit), _hit)

# ---- R3: the gate agrees (parity) ------------------------------------------
_dec, _why = registry.classify("shell.exec", {"command": PROBE})
check("R3 registry.classify denies the probe", _dec == "denied", (_dec, _why))

# ---- R1: the REGRESSION — a direct/nested execute is refused ---------------
_res = T.execute("shell.exec", {"command": PROBE})
check("R1 execute refuses the hard-denied call (ok=False)",
      _res.get("ok") is False, _res)
check("R1 exit_code is 126", _res.get("exit_code") == 126, _res)
check("R1 the result is marked denied", _res.get("denied") is True, _res)
check("R1 the reason names the hard-deny pattern",
      "hard-deny" in str(_res.get("error")), _res)
check("R1 nothing was executed (no stdout/observation)",
      not _res.get("stdout") and not _res.get("observation"), _res)

# ---- R5: a second spelling of the same boundary ----------------------------
_hit2 = registry.deny_hit("shell.exec", {"command": "cat .env"})
_res2 = T.execute("shell.exec", {"command": "cat .env"})
check("R5 the .env shell spelling is refused by the guard too",
      bool(_hit2) and _res2.get("ok") is False and _res2.get("denied") is True,
      (_hit2, _res2))

# ---- R2: no over-block — an ordinary allowed call still RUNS ---------------
_self = os.path.abspath(__file__)
check("R2 the benign path is NOT a hard-deny",
      registry.deny_hit("fs.read", {"path": _self}) == "")
_ok = T.execute("fs.read", {"path": _self})
check("R2 an ordinary fs.read still executes (ok=True)", _ok.get("ok") is True, _ok)
check("R2 and returns the file content", bool(_ok.get("content")), str(_ok)[:200])

# ---- R4: the forged-tool step runner routes through execute ----------------
_src = open(os.path.join(REPO, "src", "longrun", "util", "selfevolve.py"),
            encoding="utf-8").read()
check("R4 the forged-tool step runner calls tools.execute",
      "_tools.execute(name, step_args" in _src)

print("---")
_ok_n = sum(RESULTS)
print("v1281: %d/%d PASS" % (_ok_n, len(RESULTS)))
raise SystemExit(0 if _ok_n == len(RESULTS) else 1)
