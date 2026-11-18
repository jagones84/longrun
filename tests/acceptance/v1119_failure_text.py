#!/usr/bin/env python3
"""v1119 — a failure is classed by what NAMES it, not by what printed first.

Round 53. Reading `shell.exec · tool-error` (18 classes, 12 of them singletons)
showed the heads were PROGRAM OUTPUT, not failures:

    ['id', 'ts', 'kind', 'data'] …          (a key list, then a Traceback)
    dill                                0.4.1
    aria=1 role=2 switches=3 regions=4
    class ReaderField(NamedTuple): …

The class was the first 140 characters of the result, so the same failure split
into one class per output line and the row could not say what failed. The text
that names a failure is: `error`, else `stderr`, else the line carrying a failure
marker (a Traceback's exception line, an `ERROR:` line, `fatal:` …), else the exit
code. Machine text stays as it was.

  A  the precedence: error → stderr → marker line → exit code → first line → ""
  B  a Traceback yields its EXCEPTION line, not the marker
  C  two different stdout texts with the same Traceback are ONE class
  D  stdout + a non-zero exit and no marker is `exit=<n> (no error text)`
  E  the run record stores the naming text (and the same class as the card)
  F  end to end: the same call in both corpora still dedupes (round 52)

Deterministic: temp dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1119_failure_text.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1119-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
_RUNS = os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")
for _d in (os.environ["LONGRUN_CONFIG_DIR"], os.environ["LONGRUN_DATA_DIR"],
           os.environ["LONGRUN_SESSIONS_DIR"], _RUNS):
    os.makedirs(_d, exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import record  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


FT = selfevolve.failure_text
TB = ("['id', 'ts', 'kind', 'data']\n"
      "['id', 'kind', 'goal', 'model', 'ts', 'tokens_in', 'tokens_out']\n"
      "Traceback (most recent call last):\n"
      "  File \"<stdin>\", line 5, in <module>\n"
      "KeyError: 'path'\n")

# A — the precedence.
check("A1 a real error wins over everything else",
      FT({"error": "boom", "stderr": "err", "result": "out", "exit_code": 3}) == "boom", "")
check("A2 stderr wins over the result when error is empty",
      FT({"error": "", "stderr": "fatal: not a git repository",
          "result": "out", "exit_code": 1}) == "fatal: not a git repository", "")
check("A3 a marker line inside the result is the failure",
      FT({"result": "hello\nERROR: no such file: /x\nbye", "exit_code": 1})
      == "ERROR: no such file: /x", "")
check("A4 nothing at all is empty", FT({}) == "", "")
check("A5 stdout with a zero exit falls back to its first line",
      FT({"result": "some plain output\nmore", "exit_code": 0}) == "some plain output", "")
check("A6 `except ImportError:` is source code, not an error line",
      FT({"result": "except ImportError:\n    pass", "exit_code": 1})
      == "exit=1 (no error text)",
      FT({"result": "except ImportError:\n    pass", "exit_code": 1}))

# B — a Traceback names its exception, not the marker.
check("B1 the exception line is the class, not `Traceback …`",
      FT({"result": TB, "exit_code": 1}).startswith("KeyError: 'path'"),
      FT({"result": TB, "exit_code": 1}))
check("B2 the marker is matched case-insensitively",
      FT({"result": "ok\ntraceback (most recent call last):\n  File \"x\", line 1\n"
                    "ValueError: bad"}) .startswith("ValueError: bad"),
      FT({"result": "ok\ntraceback (most recent call last):\n  File \"x\", line 1\nValueError: bad"}))

# C — the output before the failure no longer forks the class.
c1 = selfevolve.error_class(FT({"result": TB, "exit_code": 1}))
c2 = selfevolve.error_class(FT({"result": "totally different\n" + TB, "exit_code": 2}))
check("C1 the same failure after different output is ONE class", c1 == c2, (c1, c2))

# D — output alone, with a non-zero exit, is the exit code.
check("D1 stdout + exit 1 and no marker is the exit class",
      FT({"result": "dill 0.4.1\n", "exit_code": 1}) == "exit=1 (no error text)",
      FT({"result": "dill 0.4.1\n", "exit_code": 1}))

# E — the recorder stores the naming text.
steps = record._steps([
    {"tool": "shell", "ok": False, "exit_code": 1, "error": "", "result": TB},
    {"tool": "shell", "ok": False, "exit_code": 1, "error": "", "result": "dill 0.4.1\n"},
    {"tool": "shell", "ok": False},
])
check("E1 the step stores the exception line",
      steps[0]["error"].startswith("KeyError: 'path'"), steps[0]["error"])
check("E2 output alone becomes the exit class",
      steps[1]["error"] == "exit=1 (no error text)", steps[1]["error"])
check("E3 nothing at all stays empty (v1115 F1)",
      steps[2]["error"] == "" and steps[2]["obs_chars"] == 0, steps[2])

# F — the same call in both corpora is still ONE failure.
with open(os.path.join(os.environ["LONGRUN_SESSIONS_DIR"], "s_one.json"),
          "w", encoding="utf-8") as f:
    json.dump({"id": "s_one", "messages": [], "tool_cards": [
        {"tool": "shell", "ok": False, "exit_code": 1, "error": "",
         "result": TB, "ts": 1234.5}]}, f)
with open(os.path.join(_RUNS, "s_one.json"), "w", encoding="utf-8") as f:
    json.dump({"id": "s_one", "session_id": "s_one", "steps": [
        {"tool": "shell", "ok": False, "exit_code": 1, "error": "",
         "result": TB, "ts": 1234.5}]}, f)
rep = selfevolve.failure_candidates(limit=20, include_sessions=True)
cls = [c for c in rep["classes"] if c["tool"] == "shell"]
check("F1 the call counts once after the class change",
      cls and cls[0]["count"] == 1 and cls[0]["overlap"] == 1, cls)

print("\n---\nv1119: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
