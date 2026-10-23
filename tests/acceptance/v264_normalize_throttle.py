#!/usr/bin/env python3
"""v264 — near-miss action normalisation (JAG-264) + CoT delta throttling (JAG-265).

Two WebUI-freeze fixes, both deterministic to test:

* JAG-264: a small model conflates the two action namespaces — it wraps a harness
  action inside the tool envelope (`{"action":"tool","tool":"update_todos",...}`)
  or emits the bare payload with no `action`. The harness then looped on
  "not a valid tool call" (~40-72 events/s) and the page LOOKED frozen.
  `_normalize_action` maps those back to the intended action.

* JAG-265: `ThinkCoalescer` coalesces per-token chain-of-thought deltas into one
  bounded, time-throttled flush so a fast reasoning model cannot flood the SSE
  stream / durable feed.

Run: python3 tests/v264_normalize_throttle.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v264-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as s  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --------------------------------------------------------------- JAG-264 ----
n = s._normalize_action

check("None passes through", n(None) is None)
check("a non-dict passes through", n("plain text") == "plain text")

r = n({"action": "tool", "tool": "update_todos", "args": {"steps": [1]}})
check("tool-wrapped harness action is unwrapped to its canonical todo name",
      isinstance(r, dict) and r.get("action") == "todo.update" and r.get("steps") == [1],
      str(r))

r = n({"action": "tool", "tool": "subagent", "args": {"goal": "g"}, "thought": "t"})
check("tool-wrapped action keeps the intent + thought",
      r.get("action") == "subagent" and r.get("goal") == "g" and r.get("thought") == "t",
      str(r))

r = n({"action": "tool", "tool": "plan_step", "args": {"title": "x"}})
check("agent-loop action is unwrapped too", r.get("action") == "plan_step", str(r))

r = n({"action": "tool", "tool": "bash", "args": {"cmd": "ls"}})
check("a REAL tool call is left unchanged",
      r.get("action") == "tool" and r.get("tool") == "bash", str(r))

r = n({"todos": [{"label": "a"}]})
check("bare todos payload -> todo.write", r.get("action") == "todo.write", str(r))

r = n({"steps": [{"id": "1", "status": "done"}]})
check("bare steps payload -> todo.update", r.get("action") == "todo.update", str(r))

r = n({"note": "rethink"})
check("bare note payload -> todo.replan", r.get("action") == "todo.replan", str(r))

r = n({"action": "write_todos", "todos": []})
check("a legacy-spelled harness action is canonicalised",
      r.get("action") == "todo.write", str(r))

# --------------------------------------------------------------- JAG-535 ----
# ONE tool had TWO names: the registry advertises `self.info`, but a call written
# `self` + {"action":"info"} showed up in the chat card as a bare `self`, and its
# canonical `required` list was never enforced. The PARSER deliberately keeps the
# model's own spelling (locked by v278/v369), so the canonicalisation happens where
# the call is turned into a CARD / executed.
from longrun.tools import registry as reg  # noqa: E402
from longrun.tools import tools as T       # noqa: E402
from longrun.agent import agent as A       # noqa: E402

check("canonical_name maps a legacy namespace + action onto the dotted tool",
      reg.canonical_name("self", {"action": "info"}) == "self.info"
      and reg.canonical_name("knowledge", {"action": "search"}) == "knowledge.search")
check("canonical_name falls back to the namespace DEFAULT subtool when no action is given",
      reg.canonical_name("skills") == "skills.list"
      and reg.canonical_name("shell") == "shell.exec")
check("canonical_name leaves unknown / already-dotted / MCP names untouched",
      reg.canonical_name("bash", {"cmd": "ls"}) == "bash"
      and reg.canonical_name("fs.read") == "fs.read"
      and reg.canonical_name("PMCP__gateway__x") == "PMCP__gateway__x")

r = n({"action": "tool", "tool": "self", "args": {"action": "info"}})
check("the parser still returns the model's spelling untouched (v278/v369 contract)",
      r.get("tool") == "self", str(r))

check("the chat card name is canonicalised (one tool, one name in the transcript)",
      A._card_tool_name("self", {"action": "info"}) == "self.info"
      and A._card_tool_name("skills", {"action": "read", "name": "pdf"}) == "skills.read"
      and A._card_tool_name("bash", {"cmd": "ls"}) == "bash"
      and A._card_tool_name("subagent", {"goal": "g"}) == "subagent")

res = T.execute("self", {"action": "info"}, run_id="v264")
check("the executor records the canonical name too",
      res.get("tool") == "self.info" and res.get("ok") is True, str(res))

res_bad = T.execute("skills", {"action": "read"}, run_id="v264")
check("a legacy call now gets the CANONICAL schema's required-list validation",
      res_bad.get("ok") is False and res_bad.get("tool") == "skills.read"
      and res_bad.get("missing_args") == ["name"], str(res_bad))

# --------------------------------------------------------------- JAG-265 ----


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def adv(self, dt):
        self.t += dt


check("think flush interval is positive", s.CHAT_THINK_FLUSH_S > 0, str(s.CHAT_THINK_FLUSH_S))
check("think live cap is positive", s.CHAT_THINK_LIVE_CAP > 0, str(s.CHAT_THINK_LIVE_CAP))

clk = Clock()
out = []
c = s.ThinkCoalescer(lambda ch, t: out.append((ch, t)), flush_s=0.1, cap=1000, clock=clk)
c.feed("think", "abc")
check("no emit inside the flush window", out == [], str(out))
clk.adv(0.05)
c.feed("think", "def")
check("still buffered at half the window", out == [], str(out))
clk.adv(0.06)
c.feed("think", "ghi")
check("one coalesced flush once the window elapses",
      out == [("think", "abcdefghi")], str(out))

out.clear()
c.feed("think", "tail")
c.flush()
check("flush() drains the tail", out == [("think", "tail")], str(out))

out2 = []
clk2 = Clock()
c2 = s.ThinkCoalescer(lambda ch, t: out2.append((ch, t)), flush_s=10.0, cap=5, clock=clk2)
c2.feed("think", "abc")
c2.feed("think", "def")
check("cap forces a flush with a truncation marker",
      len(out2) == 1 and out2[0][0] == "think" and "truncated" in out2[0][1],
      str(out2))
c2.feed("think", "zzz")
c2.flush()
check("after the cap no further think is emitted", out2 == out2[:1], str(out2))

out3 = []
clk3 = Clock()
c3 = s.ThinkCoalescer(lambda ch, t: out3.append((ch, t)), flush_s=10.0, cap=1000, clock=clk3)
c3.feed("think", "hello")
c3.feed("answer", "world")
check("a non-think channel flushes CoT first, preserving order",
      out3 == [("think", "hello"), ("answer", "world")], str(out3))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

