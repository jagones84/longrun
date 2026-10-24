#!/usr/bin/env python3
"""v582 — BATCH-BUG: dispatch items inside a parallel batch must be delivered.

Reproduced live by A54 (2x): a single `dispatch` works, but dispatch items
inside `{"action":"batch","calls":[...]}` never activated the teammates
(single OK / batch NO), while subagent/tool items in the same batch ran fine.

Root causes locked here:
  R1 `_split_batch_items` routes only exact `action == "dispatch"`; a
     tool-envelope (`action=tool, tool=dispatch`), a capitalised action, or a
     bare `{agent, goal}` shape falls into the tool lane (rejected as "not a
     valid tool call") or the subagent lane (any `goal` key).
  R2 `_normalize_action` never unwraps the tool/dispatch envelope
     (`dispatch` missing from `_HARNESS_ACTION_NAMES`, `agent`/`to` not
     copied) and never shape-coerces dispatch.
  R3 a one-item batch is unwrapped and falls through to the tool path — it
     never re-hits the dispatch branch, so `batch` wrapping a single dispatch
     is dropped too.
  R4 the prompts never say dispatch may ride a batch (sequentially) nor that a
     tool-using subagent needs max_steps>=3 (SJ9.3 starved at 2).

Deterministic, no model, no network.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


from longrun.core import server as _srv  # noqa: E402,F401 — first: breaks the agent<->server import cycle
from longrun.agent import agent as _ag  # noqa: E402

# ---- R1: routing -------------------------------------------------------------
tools, subs, ds = _ag._split_batch_items([
    {"action": "tool", "tool": "dispatch",
     "args": {"agent": "A48", "goal": "read the first line"}},
])
check("R1a tool-envelope dispatch routes to dispatches, not tools",
      len(ds) == 1 and not tools and not subs, (len(tools), len(subs), len(ds)))

tools, subs, ds = _ag._split_batch_items([{"action": "Dispatch", "agent": "A48", "goal": "g"}])
check("R1b capitalised Dispatch routes to dispatches",
      len(ds) == 1 and not tools and not subs, (len(tools), len(subs), len(ds)))

tools, subs, ds = _ag._split_batch_items([{"agent": "A48", "goal": "read the first line"}])
check("R1c bare agent+goal shape routes to dispatches, never subagents",
      len(ds) == 1 and not tools and not subs, (len(tools), len(subs), len(ds)))

tools, subs, ds = _ag._split_batch_items([
    {"action": "dispatch", "agent": "A48", "goal": "g1"},
    {"action": "tool", "tool": "fs.read", "args": {"path": "a.py"}},
    {"action": "subagent", "goal": "summarise", "label": "s1"},
])
check("R1d mixed batch splits 1/1/1 with dispatch kept out of subagents",
      len(tools) == 1 and len(subs) == 1 and len(ds) == 1,
      (len(tools), len(subs), len(ds)))

tools, subs, ds = _ag._split_batch_items([{"action": "subagent", "goal": "x", "label": "s"}])
check("R1e plain subagent still routes to subagents",
      len(subs) == 1 and not tools and not ds, (len(tools), len(subs), len(ds)))

# ---- R2: normalisation ---------------------------------------------------------
check("R2a dispatch is a known harness action name",
      "dispatch" in _ag._HARNESS_ACTION_NAMES)
n = _ag._normalize_action({"action": "tool", "tool": "dispatch",
                           "args": {"agent": "A48", "goal": "read it"}})
check("R2b tool/dispatch envelope unwraps with agent+goal preserved",
      isinstance(n, dict) and n.get("action") == "dispatch"
      and n.get("agent") == "A48" and n.get("goal") == "read it", n)

# ---- R3: one-item batch must reach the dispatch branch --------------------------
import inspect  # noqa: E402

_loop_src = inspect.getsource(_ag.chat_once) if hasattr(_ag, "chat_once") else ""
if not _loop_src:
    # fall back: find the loop function holding the single-call path
    for _fn in ("chat_loop", "run_chat", "_chat_turn"):
        if hasattr(_ag, _fn):
            _loop_src = inspect.getsource(getattr(_ag, _fn))
            break
if not _loop_src:
    _loop_src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
                     encoding="utf-8").read()
_i = _loop_src.find("len(_batch) < 2") if "len(_batch) < 2" not in _loop_src else -1
_file_src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
                 encoding="utf-8").read()
_seg = _file_src[_file_src.find("len(_batch) < 2"):]
_seg = _seg[:_seg.find("tc = _chat_tool_call")]
check("R3 single-item batch re-dispatches (dispatch branch reachable)",
      "_apply_chat_dispatch" in _seg, _seg[:120].replace("\n", " "))

# ---- R4: prompts teach batch+dispatch and max_steps>=3 --------------------------
_AP = _ag.CHAT_PROMPT if hasattr(_ag, "CHAT_PROMPT") else _file_src
check("R4a agent prompt says dispatches may ride one batch",
      "dispatch" in _AP.lower() and "batch" in _AP.lower()
      and (("sequential" in _AP.lower()) or ("one batch" in _AP.lower()
           or "in one batch" in _AP.lower())), "prompt contract")
from longrun.core import api_v02 as _api  # noqa: E402

_TC = _api.tool_context()
check("R4b tool_context says dispatch items run sequentially",
      "dispatch" in _TC.lower() and "sequential" in _TC.lower())
check("R4c tool_context says a tool-using subagent needs max_steps>=3",
      "max_steps" in _TC and (">=3" in _TC or "at least 3" in _TC))
check("R4d AGENT_PROMPT_V2 batch line lists dispatch",
      "dispatch" in _api.AGENT_PROMPT_V2.lower())

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
