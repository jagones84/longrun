#!/usr/bin/env python3
"""v1099 — a missing-argument failure carries the one-line call shape (R4).

Round 30. The register measured 20 `shell.exec · missing-argument` failures with
11 retried in the SAME shape: the error text already names the required keys,
the accepted arguments and an example, and the model still re-issued the call.
The fix is the mechanism that worked for the shell dialect and the timeout: a
short `hint` next to the failure, built from the tool's OWN example args.

  A  `_missing_args_reply` returns the call shape and the required keys
  B  the real dispatcher attaches it, `observation` renders it as `hint: …`
  C  a success carries no hint; the hint is one line (never a second blob)

Deterministic: temp config/data, no model, no network, no server.
Run: python3 tests/acceptance/v1099_missing_arg_hint.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1099-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---------------------------------------------------------- A: the reply ----
rep = T._missing_args_reply("shell.exec", ["command"], args={})
check("A1 the reply is still a failure with the required key named",
      rep.get("ok") is False and rep.get("exit_code") == 64
      and rep.get("missing_args") == ["command"], rep)
hint = str(rep.get("hint") or "")
check("A2 it carries the call shape", "the call shape is" in hint, hint)
check("A3 and the required key, from the tool's own schema",
      "required: command" in hint, hint)
rep2 = T._missing_args_reply("fs.read", ["path"], args={})
check("A4 the shape follows the tool (fs.read -> path)",
      "required: path" in str(rep2.get("hint") or ""), rep2.get("hint"))

# ------------------------------------------------------- B: the surface -----
res = T.execute("shell.exec", {})
check("B1 the dispatcher answers the same failure",
      res.get("ok") is False and res.get("exit_code") == 64, res.get("error"))
check("B2 with the hint attached", "the call shape is" in str(res.get("hint") or ""),
      res.get("hint"))
obs = T.observation(res)
check("B3 the observation renders it as one `hint:` line",
      "hint: the call shape is" in obs, obs[:600])
check("B4 the error text is untouched (the evidence stays)",
      "missing REQUIRED argument(s) 'command'" in obs, obs[:300])

# ------------------------------------------------------------ C: the rest ---
check("C1 the hint is one line — never a second blob",
      "\n" not in str(res.get("hint") or ""), res.get("hint"))
ok = T.execute("fs.read", {"path": os.path.abspath(__file__)})
check("C2 a success carries no hint",
      ok.get("ok") is True and not ok.get("hint"), (ok.get("ok"), ok.get("hint")))

print("\n---\nv1099: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
