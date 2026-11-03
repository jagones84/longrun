#!/usr/bin/env python3
"""v782 — a multi-invoke DSML message runs EVERY invoke, never just the first.

Live 2026-11-03 (session b7329cccf94c msg 190): the model emitted TWO invokes
in one DSML message (`shell.exec` + `dispatch` to A49). `_dsml_action` parsed
only the FIRST — the dispatch never ran, no error, exit 0, and the marker had
0 hits in the teammate's session. The operator read it as "batch drops dispatch";
the batch was innocent, the parser was the drop.

Locked here:
  * two usable invokes -> {"action":"batch","calls":[both]} (loop runs each lane);
  * three invokes -> batch of three, in model order;
  * single invoke -> unchanged single action (v369 stays green);
  * one usable + one nameless -> the usable one (nothing runnable is lost);
  * none usable -> None (E4 "truthful retry" contract holds);
  * `_split_batch_items` routes the parsed batch: shell.exec to tools,
    dispatch to dispatches, nothing to subagents;
  * `_normalize_action` leaves the batch untouched.

Deterministic, no live model, no network. Run: python3 tests/acceptance/v782_dsml_multi_invoke.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v782-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _s  # noqa: E402,F401  (server bootstraps agent)
from longrun.agent import agent as a  # noqa: E402

D = "\uff5c\uff5cDSML\uff5c\uff5c"
OPEN = "<" + D
CLOSE = "</" + D

# The live shape (msg 190): a tool invoke plus a dispatch invoke, same message.
TWO = (
    OPEN + " calls>\n"
    + OPEN + ' invoke name="shell.exec">\n'
    + OPEN + ' parameter name="command" string="true">true</' + D + " parameter>\n"
    + CLOSE + " invoke>\n"
    + OPEN + ' invoke name="dispatch">\n'
    + OPEN + ' parameter name="agent" string="true">A49</' + D + " parameter>\n"
    + OPEN + ' parameter name="goal" string="true">LDD-RETRY-A49-9C4E7B2D58A16F03</' + D + " parameter>\n"
    + CLOSE + " invoke>\n"
    + CLOSE + " calls>"
)

THREE = (
    OPEN + " calls>\n"
    + OPEN + ' invoke name="fs.read">\n'
    + OPEN + ' parameter name="path" string="true">/tmp/a</' + D + " parameter>\n"
    + CLOSE + " invoke>\n"
    + OPEN + ' invoke name="shell.exec">\n'
    + OPEN + ' parameter name="command" string="true">true</' + D + " parameter>\n"
    + CLOSE + " invoke>\n"
    + OPEN + ' invoke name="dispatch">\n'
    + OPEN + ' parameter name="agent" string="true">A49</' + D + " parameter>\n"
    + OPEN + ' parameter name="goal" string="true">go</' + D + " parameter>\n"
    + CLOSE + " invoke>\n"
    + CLOSE + " calls>"
)

ONE = (
    OPEN + " calls>\n"
    + OPEN + ' invoke name="shell">\n'
    + OPEN + ' parameter name="command" string="true">ls -la /tmp</' + D + " parameter>\n"
    + CLOSE + " invoke>\n"
    + CLOSE + " calls>"
)

MIXED = (
    OPEN + " calls>\n"
    + OPEN + " invocation>\n"
    + OPEN + ' parameter name="cmd">ls -la</' + D + " parameter>\n"
    + CLOSE + " invocation>\n"
    + OPEN + ' invoke name="self.info">\n'
    + CLOSE + " invoke>\n"
    + CLOSE + " calls>"
)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- the live case: two invokes become a batch, nothing dropped --------------
act = a._dsml_action(TWO)
check("two invokes parse to a batch of two",
      isinstance(act, dict) and act.get("action") == "batch"
      and isinstance(act.get("calls"), list) and len(act["calls"]) == 2, str(act))
tools = [c.get("tool") or c.get("action") for c in (act.get("calls") or [])]
check("the batch keeps shell.exec AND dispatch, in model order",
      tools == ["shell.exec", "dispatch"], str(tools))
check("the dispatch keeps its address and goal",
      act["calls"][1].get("agent") == "A49"
      and "LDD-RETRY-A49" in str(act["calls"][1].get("goal")), str(act["calls"][1]))
check("the full pipeline agrees (_extract_action)",
      a._extract_action(TWO) == act, str(a._extract_action(TWO)))

# ---- the batch reaches the right lanes ---------------------------------------
_batch = act.get("calls") if isinstance(act, dict) else []
_t, _s2, _d = a._split_batch_items(_batch)
check("shell.exec lands in the tool lane",
      len(_t) == 1 and (_t[0].get("tool") or "") == "shell.exec", str(_t))
check("dispatch lands in the dispatch lane, not subagents",
      len(_d) == 1 and len(_s2) == 0
      and a._is_dispatch_item(_d[0]), str((_d, _s2)))
check("the dispatch groups by teammate",
      a._dispatch_key(_d[0]) == "a49", str(a._dispatch_key(_d[0])))
check("_normalize_action leaves the batch untouched",
      a._normalize_action(dict(act)) == act, "")

# ---- three invokes stay ordered ----------------------------------------------
act3 = a._dsml_action(THREE)
check("three invokes parse to a batch of three in order",
      isinstance(act3, dict) and act3.get("action") == "batch"
      and [c.get("tool") or c.get("action") for c in act3["calls"]]
      == ["fs.read", "shell.exec", "dispatch"], str(act3))

# ---- single-invoke behaviour is unchanged (v369 contract) --------------------
one = a._dsml_action(ONE)
check("one invoke still parses to a single action",
      isinstance(one, dict) and one.get("action") == "tool"
      and one.get("tool") == "shell"
      and one.get("args") == {"command": "ls -la /tmp"}, str(one))

# ---- a nameless invoke is unusable, a usable sibling still runs --------------
mixed = a._dsml_action(MIXED)
check("one usable + one nameless yields the usable one",
      isinstance(mixed, dict) and mixed.get("tool") == "self.info", str(mixed))
check("a lone nameless invoke still yields None (truthful retry)",
      a._dsml_action(
          OPEN + " calls>\n" + OPEN + " invocation>\n"
          + OPEN + ' parameter name="cmd">ls</' + D + " parameter>\n"
          + CLOSE + " invocation>\n" + CLOSE + " calls>") is None, "")

print("---")
okc = sum(results)
print("v782: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
