#!/usr/bin/env python3
"""v568 (STAGED — M10c unknown-outcome): a timed-out call must say its outcome
is UNKNOWN and demand inspection before re-issue (Paperclip parity).
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TMP = tempfile.mkdtemp(prefix="sf-v568-")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


if not hasattr(T, "observation"):
    check("0 observation exists", False, "tools.observation missing")
    print("TOTAL %d/%d" % (sum(results), len(results)))
    sys.exit(1)

base = {"tool": "fs.write", "backend": "local", "sandboxed": True}

obs_timeout = T.observation(dict(base, exit_code=124, ok=False,
                                 error="shell timed out after 180s",
                                 stdout="partial…"))
check("1a a 124 timeout observation names the unknown outcome",
      "OUTCOME UNKNOWN" in obs_timeout, obs_timeout[:300])
check("1b it demands inspection before re-issue",
      "inspect" in obs_timeout.lower() and "blindly" in obs_timeout.lower(),
      obs_timeout[:500])

obs_ok = T.observation(dict(base, exit_code=0, ok=True, stdout="wrote 3 lines"))
check("2a exit 0 carries no unknown-outcome block",
      "OUTCOME UNKNOWN" not in obs_ok, obs_ok[:200])
obs_err = T.observation(dict(base, exit_code=1, ok=False, error="no such file"))
check("2b exit 1 carries no unknown-outcome block",
      "OUTCOME UNKNOWN" not in obs_err, obs_err[:200])

# End-to-end at tool level: a handler-set timeout normalizes to 124 + block.
_real = T._dispatch_execute_raw
try:
    T._dispatch_execute_raw = lambda tool, args, run_id=None: {
        "ok": False, "timeout": True, "error": "timed out", "stdout": "half"}
    res = T._dispatch_execute("fs.write", {"path": "x", "content": "y"})
    check("3a tool-level timeout normalizes to exit 124",
          res.get("exit_code") == 124 and res.get("ok") is False, res.get("exit_code"))
    check("3b its observation carries the unknown-outcome block",
          "OUTCOME UNKNOWN" in T.observation(res), T.observation(res)[:300])
finally:
    T._dispatch_execute_raw = _real

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
