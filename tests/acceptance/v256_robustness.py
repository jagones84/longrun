#!/usr/bin/env python3
"""v256 — two robustness fixes (JAG-256).

A) `tools.execute()` called `_dispatch_execute()` unprotected: a tool whose body
   raised (e.g. `int("abc")` on a wire-ish arg) propagated the exception instead
   of returning a graceful observation.
B) The assembled system prompt was published as a collapsed "system" inject on
   EVERY turn, so the transcript filled with N identical blocks ("the harness
   re-sends the system prompt ad infinitum"). It is now de-duplicated per session.

Deterministic, no live server, no network. Run: python3 tests/v256_robustness.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v256-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# A) a raising tool body must not escape execute()
def boom(*a, **k):
    raise ValueError("simulated int('abc') crash")


orig = tools._dispatch_execute
tools._dispatch_execute = boom
try:
    res = tools.execute("shell", {"command": "echo hi"})
    check("JAG-256 tool crash -> graceful result",
          isinstance(res, dict) and res.get("ok") is False
          and "tool crashed" in (res.get("error") or ""),
          str(res)[:80])
except Exception as e:  # noqa: BLE001
    check("JAG-256 tool crash -> graceful result", False, repr(e))
finally:
    tools._dispatch_execute = orig

# a normal tool still runs through execute()
try:
    res = tools.execute("self", {})
    check("JAG-256 a normal tool still executes",
          isinstance(res, dict) and res.get("ok") is not False, str(res)[:60])
except Exception as e:  # noqa: BLE001
    check("JAG-256 a normal tool still executes", False, repr(e))

# B) static guards
with open(os.path.join(REPO, "src", "longrun", "core/server.py"), encoding="utf-8") as f:
    sv = f.read()
with open(os.path.join(REPO, "src", "longrun", "agent/agent.py"), encoding="utf-8") as f:
    sv += f.read()
with open(os.path.join(REPO, "src", "longrun", "tools/tools.py"), encoding="utf-8") as f:
    tv = f.read()
check("JAG-256 system-prompt inject de-duplicated per session",
      "_LAST_SYS_INJECT" in sv and '_prev = _LAST_SYS_INJECT.get(sess["id"])' in sv
      and "elif _prev != _h:" in sv)
check("JAG-256 tool dispatch is wrapped in try/except",
      "a tool must never crash the harness" in tv)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

