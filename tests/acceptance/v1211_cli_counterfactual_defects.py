#!/usr/bin/env python3
"""v1211 — the three CLI defects A54 measured in r102c (round 142).

Measured, not inferred:
  * `sessions model-counterfactual -1` was documented as "the last message" but
    `modelcf.plan` resolved `-1` to the final message, which always lacks a
    recorded successor, so it could never succeed.
  * the CLI resolved the current session BEFORE validating its arguments, so
    without a current session every usage error read "no current session".
  * `docs/CLI.md` did not document the `no-action` verdict, nor 12 of the
    response keys the endpoint returns.

Deterministic: no model, no network, no server.

Run: python3 tests/acceptance/v1211_cli_counterfactual_defects.py
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1211-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import modelcf as M   # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


SESS = {"messages": [
    {"role": "user", "content": "first question"},
    {"role": "assistant", "content": "answered"},
    {"role": "user", "content": "observation"},
    {"role": "assistant", "content": "{\"action\": \"read\"}"},
]}

# ---- 1. a negative index means the last INTERVENABLE message -------------
plan, why = M.plan(SESS, -1, {"content": "a different observation"})
check("`-1` resolves to the last intervenable message", not why, why)
check("`-1` names the message it replaced", plan.get("index") == 2, plan)
check("`-1` carries the recorded reply",
      plan.get("recorded_reply") == "{\"action\": \"read\"}", plan)
p2, why2 = M.plan(SESS, -2, {"content": "a different observation"})
check("`-2` is an offset and lands on an intervenable message", not why2, why2)
check("`-2` names the observation before the last assistant", p2.get("index") == 2, p2)
p2b, why2b = M.plan(SESS, -3, {"content": "a different question"})
check("`-3` walks back past the assistant to the first user message",
      not why2b and p2b.get("index") == 0, (p2b, why2b))
p3, why3 = M.plan(SESS, 2, {"content": "positive still works"})
check("a positive index is unchanged", not why3 and p3.get("index") == 2, p3)
_, why4 = M.plan(SESS, -5, {"content": "too far"})
check("an offset outside the transcript is refused",
      "outside the transcript" in str(why4), why4)
_, why5 = M.plan(SESS, 9, {"content": "outside"})
check("a positive index outside the transcript is refused",
      "outside the transcript" in str(why5), why5)
_, why6 = M.plan(SESS, "x", {"content": "not an int"})
check("a non-integer index is refused with its own message",
      "index must be an integer" in str(why6), why6)
check("the index message documents the new meaning",
      "last intervenable message" in str(why6), why6)

TRAILING = {"messages": [
    {"role": "user", "content": "ask"},
    {"role": "assistant", "content": "reply"},
    {"role": "user", "content": "an unanswered nudge"},
]}
pt, whyt = M.plan(TRAILING, -1, {"content": "different ask"})
check("`-1` skips a trailing message with no recorded successor",
      not whyt and pt.get("index") == 0, (pt, whyt))
ONLY_USER = {"messages": [{"role": "user", "content": "lonely"}]}
_, whyu = M.plan(ONLY_USER, -1, {"content": "different"})
check("a transcript with no intervenable message says so",
      "no intervenable message" in str(whyu), whyu)

# ---- 2. the other refusals still hold -----------------------------------
_, whyr = M.plan(SESS, 1, {"content": "target the assistant"})
check("an assistant message is still refused", "only a USER message" in str(whyr), whyr)
_, whys = M.plan(SESS, 0, {"content": "first question"})
check("an unchanged replacement is still refused", "identical" in str(whys), whys)
_, whyb = M.plan(SESS, 0, {"content": ""})
check("an empty replacement is still refused", "change.content is required" in str(whyb), whyb)
_, whyn = M.plan({"messages": []}, 0, {"content": "x"})
check("an empty session is still refused", "no stored messages" in str(whyn), whyn)

# ---- 3. the three verdicts, including no-action -------------------------
check("two empty actions are `no-action`",
      M.compare({}, {})["verdict"] == "no-action")
check("`no-action` carries empty objects",
      M.compare({}, {})["recorded"] == {} and M.compare({}, {})["replayed"] == {})
check("one empty side is `different-action`",
      M.compare({}, {"action": "read"})["verdict"] == "different-action")
check("the empty-side move is named",
      M.compare({}, {"action": "read"})["moved"] == ["action"])
check("identical actions are `same-action`",
      M.compare({"action": "read", "path": "a"},
                {"action": "read", "path": "a"})["verdict"] == "same-action")
moved = M.compare({"action": "read", "path": "a"},
                  {"action": "read", "path": "b"})
check("a changed argument is `different-action`", moved["verdict"] == "different-action")
check("the moved key is named", moved["moved"] == ["path"], moved)

# ---- 4. the CLI validates args before resolving the session -------------
CLI = os.path.join(REPO, "forge.py")
STATE = os.path.join(TMP, "cli_state.json")
env = dict(os.environ)
env["LONGRUN_CLI_STATE"] = STATE
for stale in (STATE,):
    try:
        os.remove(stale)
    except OSError:
        pass


def run_cli(*argv):
    proc = subprocess.run([sys.executable, CLI] + list(argv), cwd=REPO,
                          env=env, capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout + proc.stderr


code, text = run_cli("sessions", "model-counterfactual")
check("no args and no session reads as a usage error", code == 2, (code, text))
check("the usage error is not hidden by the session check",
      "usage: sessions model-counterfactual" in text, text)
check("the session message is absent when args are invalid",
      "no current session" not in text, text)
code, text = run_cli("sessions", "model-counterfactual", "abc", "--content", "x")
check("a bad INDEX is reported before the session check",
      code == 2 and "INDEX must be an integer" in text, (code, text))
check("the bad-INDEX path does not mention a session",
      "no current session" not in text, text)
code, text = run_cli("sessions", "counterfactual")
check("the step branch validates its handle first too",
      code == 2 and "usage: sessions counterfactual" in text, (code, text))
code, text = run_cli("sessions", "model-counterfactual", "2", "--content", "x")
check("with valid args the missing session is finally reported",
      code == 2 and "no current session" in text, (code, text))

# ---- 5. docs/CLI.md carries the verdict and every response key ----------
doc = open(os.path.join(REPO, "docs", "CLI.md"), encoding="utf-8").read()
check("the no-action verdict is documented", "`no-action`" in doc)
check("the new -1 meaning is documented",
      "last intervenable message" in doc and "`-1`" in doc)
KEYS = ("ok", "status", "session", "index", "model", "fidelity", "caveat",
        "dropped", "first", "original", "replacement", "recorded_action",
        "replayed_action", "compare", "usage", "recorded_reply",
        "replayed_reply", "think")
missing = [key for key in KEYS if "`%s`" % key not in doc]
check("every response key is documented", not missing, missing)
check("the refusal shape is documented", "`plan`" in doc and "`error`" in doc)
check("the provider-failure status is documented", "502" in doc)

# ---- 6. the plan's own body matches what the docs promise ---------------
from longrun.core import api_v02  # noqa: E402
import inspect  # noqa: E402
src = inspect.getsource(api_v02.model_counterfactual_run)
absent = [key for key in KEYS if '"%s"' % key not in src]
check("the endpoint returns every documented key", not absent, absent)

# ---- result --------------------------------------------------------------
ok = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
