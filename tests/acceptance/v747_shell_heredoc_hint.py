#!/usr/bin/env python3
"""v747 — a failed heredoc tells the model how to get out (EV-50).

Measured 2026-10-31: 3 `shell.exec` calls in one benchmark session died as
`python3 - <<'PY' …` patch scripts. Exit code and stdout were right, but nothing
named the FILE route, so the same shape was retried. The hint fires ONLY on a
failure whose command used a heredoc, and it reaches the model in the
observation line.

Deterministic: the shell runner is stubbed, no process, no model, no network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v747-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry             # noqa: E402
from longrun.tools import tools                # noqa: E402

registry._external_tools = lambda: {}
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


FAIL = {"ok": False, "exit_code": 1, "stdout": "Traceback …\n", "stderr": "",
        "backend": "terminal", "sandboxed": False}
OK = {"ok": True, "exit_code": 0, "stdout": "fine\n", "stderr": "",
      "backend": "terminal", "sandboxed": False}

tools._shell = lambda args, run_id: dict(OK if args.get("_ok") else FAIL)
SH = tools._DISPATCH["shell.exec"]        # the entry the model actually calls

HEREDOC = "python3 - <<'PY'\nprint(1)\nPY"

res = SH({"command": HEREDOC}, "v747")
check("A1 a failed heredoc is annotated", "hint" in res, res.get("hint"))
check("A2 the hint names fs.write and the file route",
      "fs.write" in str(res.get("hint")) and "python3 <file>" in str(res.get("hint")),
      res.get("hint"))

res = SH({"command": HEREDOC, "_ok": True}, "v747")
check("B1 a WORKING heredoc gets no hint", "hint" not in res)

res = SH({"command": "python3 -c 'exit(1)'"}, "v747")
check("C1 a failing one-liner (no heredoc) gets no hint", "hint" not in res)

obs = tools.observation(dict(FAIL, tool="shell.exec", hint="write the script to a file"))
check("D1 the observation carries the hint to the model",
      "hint: write the script to a file" in obs, obs[:200])

obs = tools.observation(dict(OK, tool="shell.exec"))
check("D2 a clean result has no hint line", "hint:" not in obs, obs[:200])

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
