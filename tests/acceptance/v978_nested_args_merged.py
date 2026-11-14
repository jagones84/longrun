#!/usr/bin/env python3
"""v978 — a duplicate `{"args": {...}}` layer is MERGED, never silently dropped (H3).

A live run (2026-11-14, `run_44ea468b`) emitted `fs.read` as
`{"path": "...", "args": {"start_line": N, "end_line": M}}` eight times. The old
`_unwrap_nested_args` only unwrapped when a required key was MISSING outside, so
a call with `path` present kept the wrapper: the range was dropped, the whole
file was read instead of the slice, and the observation only carried
"unknown argument 'args' … ignored". The model re-issued the same call.

Contract:
  A) the nested object is merged into the argument object;
  B) an outer key WINS over the same key nested;
  C) the real `fs.read` dispatch honours a range that arrived nested, with no
     "unknown argument" warning;
  D) a tool that DECLARES `args` (git: a string) is never rewritten;
  E) the original repair — required keys only inside the wrapper — still works.

Deterministic: temp data dirs, no model, no server, no network.

Run: python3 tests/acceptance/v978_nested_args_merged.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="v978_")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITs_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(_TMP, _k.lower())
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(_TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- A/B: the normaliser ----------------------------------------------------
got = T.normalize_args("fs.read", {"path": "a.py",
                                   "args": {"start_line": 10, "end_line": 40}})
check("A1 the nested range is merged up",
      got == {"path": "a.py", "start_line": 10, "end_line": 40}, got)
got2 = T.normalize_args("fs.read", {"path": "a.py", "args": {"path": "b.py",
                                                             "end_line": 7}})
check("B1 an outer key wins over the nested one", got2.get("path") == "a.py", got2)
check("B2 the nested-only key still lands", got2.get("end_line") == 7, got2)
check("B3 no `args` key survives", "args" not in got2, got2)

# --- C: the real dispatch honours the nested range --------------------------
readme = os.path.join(REPO, "README.md")
res = T._dispatch_execute_raw("fs.read", {"path": readme,
                                          "args": {"start_line": 1, "end_line": 2}}) or {}
body = str(res.get("content") or "")
check("C1 the call succeeds", res.get("ok") is True, res.get("error"))
check("C2 the range really limited the read", 0 < len(body.splitlines()) <= 2,
      len(body.splitlines()))
check("C3 no 'unknown argument' warning any more",
      "unknown argument" not in str(res.get("warning") or ""), res.get("warning"))

# --- D: a DECLARED `args` is never rewritten -------------------------------
git_args = T.normalize_args("git", {"args": {"status": True}, "cwd": "."})
check("D1 the git tool keeps its declared `args` key", "args" in git_args, git_args)

# --- E: the original repair still holds ------------------------------------
old = T.normalize_args("fs.read", {"args": {"path": "c.py"}})
check("E1 required keys inside the wrapper are still lifted", old.get("path") == "c.py", old)

ok = sum(RESULTS)
print("\nv978: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
