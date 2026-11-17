#!/usr/bin/env python3
"""v1080 — a recorded read-only call can be re-executed with ONE fact changed.

HD-1 asks for the instrument the attribution literature uses: freeze a step,
change one fact, re-run, compare (CausalFlow, arXiv:2605.25338). Longrun logged
the steps but could not run the intervention, so every failure explanation was
correlational. The first cut is the step the harness owns deterministically: a
READ-ONLY card can be re-executed with a changed argument and the two
observations compared. A mutating card is refused — re-running a write is a
duplicate effect, not a counterfactual.

Contract:
  P1 the plan merges one argument over the recorded args
  P2 a mutating tool is refused, before anything executes
  P3 an empty or no-op change is refused (a re-run is not an intervention)
  P4 bad card / bad args / bad change shape are refused, never raised
  P5 the comparison names the fields that moved, on FULL text
  P6 the surfaces exist: route, CLI verb + --arg, docs
  P7 the CLI posts exactly the handle and the change, and prints the verdict

Deterministic: no server, no model, no network.
Run: python3 tests/acceptance/v1080_counterfactual_step.py
"""
import contextlib
import io
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1080-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_CLI_STATE"] = os.path.join(TMP, "cli_session.json")
for d in ("data/sessions", "cfg"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import counterfactual as CF  # noqa: E402
from longrun.core import forge  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


READ = {"id": "a1b2c3d4", "tool": "fs.read", "ok": False, "exit_code": 1,
        "args": json.dumps({"path": "missing.txt"}), "error": "No such file",
        "result": ""}

# ---- P1: the one changed fact -----------------------------------------------
p = CF.plan(READ, {"path": "README.md"})
check("P1a the plan names the tool", p.get("tool") == "fs.read", p)
check("P1b the patch is merged over the recorded args",
      p.get("args") == {"path": "README.md"}, p.get("args"))
check("P1c the changed keys are named", p.get("changed") == ["path"], p)
check("P1d the recorded args are kept beside it",
      p.get("original_args") == {"path": "missing.txt"}, p)
p2 = CF.plan(READ, {"args": {"path": "a.py"}, "note": "explicit form"})
check("P1e the explicit args form is accepted", p2.get("args") == {"path": "a.py"}, p2)
p3 = CF.plan({"tool": "glob", "args": {"pattern": "*.md"}}, {"pattern": "*.py"})
check("P1f a dict-valued card works too", p3.get("args") == {"pattern": "*.py"}, p3)
check("P1g the card is not mutated", READ["args"] == json.dumps({"path": "missing.txt"}))

# ---- P2: mutating tools are refused -----------------------------------------
for tool in ("fs.write", "fs.edit", "shell.exec", "python.run", "git.run"):
    e = CF.plan({"tool": tool, "args": {"path": "x"}}, {"path": "y"})
    check("P2 %s is refused as a duplicate effect" % tool,
          "not read-only" in (e.get("error") or ""), e)

# ---- P3: a change must change something -------------------------------------
check("P3a an empty change is refused", "empty" in (CF.plan(READ, {}).get("error") or ""))
check("P3b the same value is refused",
      "does not differ" in (CF.plan(READ, {"path": "missing.txt"}).get("error") or ""))
check("P3c a non-object change is refused",
      "object" in (CF.plan(READ, ["path"]).get("error") or ""))

# ---- P4: bad inputs never raise ---------------------------------------------
check("P4a no card is refused", CF.plan(None, {"path": "x"}).get("error"))
check("P4b a card without a tool is refused", CF.plan({"args": {}}, {"a": 1}).get("error"))
check("P4c non-JSON recorded args are refused",
      "not JSON" in (CF.plan({"tool": "fs.read", "args": "{oops"}, {"path": "x"}
                             ).get("error") or ""))
check("P4d a non-object change.args is refused",
      "change.args" in (CF.plan(READ, {"args": "path=x"}).get("error") or ""))
check("P4e a card with no recorded args starts empty",
      CF.plan({"tool": "diff"}, {"a": 1}).get("args") == {"a": 1})

# ---- P5: the comparison ------------------------------------------------------
same = CF.compare(READ, {"ok": False, "exit_code": 1, "error": "No such file", "result": ""})
check("P5a an identical observation is same", same.get("same") is True
      and same.get("verdict") == "same-observation", same)
diff = CF.compare(READ, {"ok": True, "exit_code": 0, "error": "", "result": "hello"})
check("P5b a different observation names every moved field",
      diff.get("same") is False
      and diff.get("changed") == ["ok", "exit_code", "error", "result"], diff)
one = CF.compare(READ, {"ok": False, "exit_code": 1, "error": "Permission denied",
                        "result": ""})
check("P5c one field is enough", one.get("changed") == ["error"], one)
long_a = "x" * 450 + "A" + "y" * 50
long_b = "x" * 450 + "B" + "y" * 50
deep = CF.compare({"tool": "fs.read", "ok": True, "result": long_a},
                  {"ok": True, "result": long_b})
check("P5d a diff past the 400-char view still counts", deep.get("same") is False, deep)
check("P5e the view is bounded but reports the real size",
      len(deep["before"]["result"]) == 400 and deep["before"]["result_chars"] == len(long_a),
      deep.get("before"))
check("P5f a missing result is a verdict, not a crash",
      CF.compare(READ, None).get("verdict") == "no-result")
# The loop persists the RENDERED observation for a tool whose payload is
# `content` (fs.read), so the comparison must read that same text.
CARD_FS = {"tool": "fs.read", "ok": True, "exit_code": 0, "error": "",
           "result": "[fs.read] exit=0 ok=True backend=host sandboxed=False\nA"}
same_fs = CF.compare(CARD_FS, {"ok": True, "exit_code": 0, "content": "A"},
                     "[fs.read] exit=0 ok=True backend=host sandboxed=False\nA")
check("P5g the rendered observation is compared, not the raw content",
      same_fs.get("same") is True, same_fs)
diff_fs = CF.compare(CARD_FS, {"ok": True, "exit_code": 0, "content": "A"},
                     "[fs.read] exit=0 ok=True backend=host sandboxed=False\nB")
check("P5h a changed observation is different", diff_fs.get("same") is False
      and diff_fs.get("changed") == ["result"], diff_fs)

# ---- P6: the surfaces --------------------------------------------------------
API = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
FORGE = open(os.path.join(REPO, "src", "longrun", "core", "forge.py"), encoding="utf-8").read()
DOC = open(os.path.join(REPO, "docs", "CLI.md"), encoding="utf-8").read()
check("P6a the route exists and goes through the ONE gated door",
      'endswith("/counterfactual")' in API and "gated_call(plan[\"tool\"]" in API
      and "fidelity\": \"live-tree\"" in API)
check("P6b the CLI verb exists", 'args.action == "counterfactual"' in FORGE
      and '"counterfactual"' in FORGE)
check("P6c the CLI takes repeatable --arg", 'p.add_argument("--arg", action="append")' in FORGE)
check("P6d the docs name the verb and both verdicts",
      "sessions counterfactual" in DOC and "same-observation" in DOC
      and "different-observation" in DOC and "/counterfactual" in DOC)

# ---- P7: the CLI posts the request -----------------------------------------
class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


calls = []
VERDICT = {"same": False, "changed": ["error"], "verdict": "different-observation",
           "before": {"ok": False}, "after": {"ok": True}}


def fake_req(method, path, body=None, **kw):
    calls.append((method, path, body))
    return {"ok": True, "fidelity": "live-tree", "caveat": "live tree",
            "compare": VERDICT}


out, err = io.StringIO(), io.StringIO()
old_req, old_cur = forge.req, forge._current_session
forge.req, forge._current_session = fake_req, (lambda: "s1")
code = 0
try:
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        forge.cmd_sessions(Args(action="counterfactual", value="a1b2c3d4",
                                arg=["path=README.md", "limit=5"], workspace=None,
                                at=None, title=None, model=None))
except SystemExit as e:
    code = e.code if isinstance(e.code, int) else 1
finally:
    forge.req, forge._current_session = old_req, old_cur
check("P7a it posts the handle and the parsed change",
      calls == [("POST", "/api/sessions/s1/counterfactual",
                 {"handle": "a1b2c3d4", "change": {"path": "README.md", "limit": 5}})],
      calls)
check("P7b it prints the verdict first", code == 0
      and out.getvalue().startswith("different-observation"), out.getvalue()[:80])

calls.clear()
out2, err2 = io.StringIO(), io.StringIO()
code2 = 0
forge.req, forge._current_session = fake_req, (lambda: "s1")
try:
    with contextlib.redirect_stdout(out2), contextlib.redirect_stderr(err2):
        forge.cmd_sessions(Args(action="counterfactual", value="a1b2c3d4", arg=[],
                                workspace=None, at=None, title=None, model=None))
except SystemExit as e:
    code2 = e.code if isinstance(e.code, int) else 1
finally:
    forge.req, forge._current_session = old_req, old_cur
check("P7c no --arg is a usage error and never spends a call",
      code2 == 2 and calls == [] and "ONE fact" in err2.getvalue(),
      (code2, calls, err2.getvalue()))

print("\n---\nv1080: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
