#!/usr/bin/env python3
"""v612 — batch lanes: tool vs subagent(SJ) vs dispatch never mix.

A `batch` carries full-action dicts in calls/tool_calls/batch/parallel.
Routing: dispatch items (teammate address + goal, any spelling but never a
`subagent` action) run as real turns in the peer session; `subagent` actions
or bare goal items become ONE Session Job (SJ) executed by the SJ scheduler;
everything else is a tool call. A dispatch must NEVER become an SJ subjob
(it would burn the subagent budget with different semantics).
Deterministic, no network, no model, no server.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


from longrun.core import server as _srv  # noqa: E402,F401 — import first: agent<->server cycle
from longrun.agent import agent as A  # noqa: E402

check("T1 _batch_items reads every envelope key, drops non-dicts",
      A._batch_items({"action": "batch", "calls": [{"action": "x"}, 42, "s"]}) == [{"action": "x"}]
      and A._batch_items({"tool_calls": [{"action": "y"}]}) == [{"action": "y"}]
      and A._batch_items({"batch": [{"action": "z"}]}) == [{"action": "z"}]
      and A._batch_items({"parallel": [{"action": "w"}]}) == [{"action": "w"}]
      and A._batch_items("nope") == [] and A._batch_items({}) == [], "")

check("T2 exact dispatch recognised",
      A._is_dispatch_item({"action": "dispatch", "agent": "A5", "goal": "do it"}), "")
check("T3 tool-envelope dispatch recognised",
      A._is_dispatch_item({"action": "tool", "tool": "dispatch", "agent": "A5", "goal": "do it"}), "")
check("T4 bare {agent, goal} recognised as dispatch",
      A._is_dispatch_item({"agent": "A5", "goal": "do it"}), "")
check("T5 capitalised action still a dispatch",
      A._is_dispatch_item({"action": "Dispatch", "to": "A5", "goal": "do it"}), "")
check("T6 a subagent action is NEVER a dispatch (even with agent+goal)",
      not A._is_dispatch_item({"action": "subagent", "agent": "A5", "goal": "do it"}), "")
check("T7 goal without address is not a dispatch (falls to SJ lane)",
      not A._is_dispatch_item({"goal": "research this"}), "")
check("T8 tool call without goal is not a dispatch",
      not A._is_dispatch_item({"action": "shell", "command": "ls"}), "")

tools, subs, disp = A._split_batch_items([
    {"action": "shell", "command": "ls"},
    {"action": "subagent", "goal": "deep work", "agent": "A9"},
    {"goal": "research this"},
    {"action": "dispatch", "agent": "A5", "goal": "run it"},
    {"agent": "A6", "goal": "help"},
    "junk",
])
check("T9 lanes split: 1 tool, 2 SJ subs, 2 dispatches",
      len(tools) == 1 and len(subs) == 2 and len(disp) == 2, (len(tools), len(subs), len(disp)))
check("T10 SJ lane holds ONLY subagent/goal items (tools + dispatches excluded)",
      all((x.get("action") == "subagent" or x.get("goal")) and not A._is_dispatch_item(x)
          for x in subs), "")

check("T11 dispatch groups by teammate, case-insensitive",
      A._dispatch_key({"agent": "A5"}) == A._dispatch_key({"to": "a5"}) == "a5", "")
check("T12 unaddressed dispatch gets no group (fails fast alone)",
      A._dispatch_key({"action": "dispatch"}) is None
      and A._dispatch_key({}) is None and A._dispatch_key("x") is None, "")

os.environ["LONGRUN_DISPATCH_WAIT"] = "45"
check("T13 dispatch wait honours env", A._dispatch_wait() == 45, "")
os.environ["LONGRUN_DISPATCH_WAIT"] = "5"
check("T14 dispatch wait never hangs the caller (floor 30s)",
      A._dispatch_wait() == 30, "")
del os.environ["LONGRUN_DISPATCH_WAIT"]
check("T15 dispatch wait default 300s", A._dispatch_wait() == 300, "")

SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("T16 batch execution builds ONE SJ from the sub lane only",
      "_sj.create" in SRC and "sub_items" in SRC, "scheduler call site")

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
