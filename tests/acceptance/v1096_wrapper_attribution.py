#!/usr/bin/env python3
"""v1096 — the harness's wrapper prefix does not split the attribution.

Round 27 (Trial by Trace, arXiv:2610.32285 — failure attribution). Some tool
errors reach the card as `[tool] exit=<n> ok=False backend=…` + the real message,
some as the message alone. The register read the family from the 80-char class
head, so the prefixed shape said `exit=` and filed an argument-contract failure
under `nonzero-exit` — measured 2026-11-18: 14 of 26 "missing REQUIRED argument"
cards (10 shell.exec, 2 fs.read, 2 web.search) were attributed to the wrong
family, where the remedy is "read stderr" instead of "re-read the schema".

  A  the prefixed argument error is `missing-argument`; the prefixed gate is
     still `gate`; a plain prefixed exit is still `nonzero-exit`
  B  the tail search stays NARROW: `required:` alone in a text does not pull
     (`TAIL_OVERRIDES`), while "missing required argument" / "unknown argument" do
  C  both shapes of one failure land in ONE issue, with no phantom nonzero-exit
  D  no invented family: a prefixed text that names no measured cause stays
     nonzero-exit

Deterministic: temp session/runs dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1096_wrapper_attribution.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1096-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs"), exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SESS = os.environ["LONGRUN_SESSIONS_DIR"]
MISS = ("shell.exec: missing REQUIRED argument(s) 'command'. Required: command. "
        "Arg types: {'command': 'string'}")
PREFIX = "[shell.exec] exit=64 ok=False backend=None sandboxed=None\nERROR: "
HEAD = selfevolve.error_class(PREFIX + MISS)

# ------------------------------------------------------------ A: the label --
check("A1 the prefixed argument error is `missing-argument`",
      selfevolve.failure_family("shell.exec", HEAD, PREFIX + MISS) == "missing-argument",
      selfevolve.failure_family("shell.exec", HEAD, PREFIX + MISS))
check("A2 the prefixed gate refusal is still `gate`",
      selfevolve.failure_family(
          "fs.write", "[fs.write] exit=<n> ok=False",
          "[fs.write] exit=<n> ok=False — plan mode: the plan needs approval")
      == "gate", "")
check("A3 a prefixed exit with no measured cause is still `nonzero-exit`",
      selfevolve.failure_family("shell.exec", HEAD, PREFIX + "something unknown went wrong")
      == "nonzero-exit", "")
check("A4 a prefixed timeout stays nonzero-exit: `timeout` is not a tail needle "
      "(the round-24 schema-listing trap)",
      selfevolve.failure_family("shell.exec", HEAD,
                                PREFIX + "timeout — the terminal was reset")
      == "nonzero-exit", "")

# ------------------------------------------------------ B: the narrow tail --
SCHEMA = ("Arg types: {'command': str, 'timeout_secs': int}; Required: command")
check("B1 `required:` alone does not pull a plain exit into missing-argument",
      selfevolve.failure_family("shell.exec", HEAD, PREFIX + SCHEMA) == "nonzero-exit",
      selfevolve.failure_family("shell.exec", HEAD, PREFIX + SCHEMA))
check("B2 `missing required argument` in the tail does",
      selfevolve.failure_family("shell.exec", HEAD, PREFIX + SCHEMA
                                + " — missing REQUIRED argument(s) 'command'")
      == "missing-argument", "")
check("B3 `unknown argument` in the tail does too",
      selfevolve.failure_family("glob.list", HEAD, PREFIX
                                + "unknown argument 'path' — accepts: pattern, root")
      == "missing-argument", "")

# ------------------------------------ C: both shapes are ONE attribution ----
def session(sid, cards):
    with open(os.path.join(SESS, sid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)


session("s1", [
    {"tool": "shell.exec", "ok": False, "error": PREFIX + MISS},
    {"tool": "shell.exec", "ok": False, "error": PREFIX + MISS},
    {"tool": "shell.exec", "ok": False, "error": MISS},
    {"tool": "shell.exec", "ok": False, "error": MISS},
])
rep = selfevolve.failure_candidates(limit=200, include_sessions=True)
issues = [i for i in rep["issues"] if i["tool"] == "shell.exec"]
miss_issues = [i for i in issues if i["family"] == "missing-argument"]
check("C1 one issue holds both shapes", len(miss_issues) == 1, issues)
check("C2 and it carries all four failures", miss_issues
      and miss_issues[0]["count"] == 4, miss_issues[0] if miss_issues else {})
check("C3 no phantom `shell.exec · nonzero-exit` issue is left",
      not [i for i in issues if i["family"] == "nonzero-exit"], issues)

print("\n---\nv1096: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
