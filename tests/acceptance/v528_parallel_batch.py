#!/usr/bin/env python3
"""v528 — parallel `batch`: concurrent tool calls + parallel subagents (JAG-533).

Deterministic — no model, no server, no network.

  A) config ships the TWO GLOBAL caps, both default 4:
       runtime.max_parallel_tools (config/tools.yaml) — tool calls at once
       max_parallel               (config/subagents.yaml) — subagents at once
  B) both caps are read HOT from config and clamped to >= 1.
  C) `batch` items are extracted from calls / tool_calls / batch / parallel.
  D) a batch of tool calls really runs CONCURRENTLY (max in-flight == n under
     the cap) and a cap of 1 serialises them; one card per item, model order.
  E) the Harness panel exposes the parallel-tools field, the API persists it.
  F) the command palette is a DIRECT top-right button; the "☰" app menu is gone.
"""
import os
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

checks = []


def check(name, passed, detail=""):
    checks.append(bool(passed))
    print(("PASS " if passed else "FAIL ") + name
          + ((" :: " + str(detail)) if (detail and not passed) else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


tools_yaml = _read("config", "tools.yaml")
sub_yaml = _read("config", "subagents.yaml")
idx = _read("webui", "index.html")
api = _read("src", "longrun", "core", "api_v02.py")

check("A1 config/tools.yaml ships runtime.max_parallel_tools (default 4)",
      "max_parallel_tools: 4" in tools_yaml)
check("A2 config/subagents.yaml ships max_parallel for parallel agents",
      "max_parallel:" in sub_yaml)

# Import the server FIRST: agent.py <-> core/server.py are mutually recursive and
# core/server.py is the side that pulls the prompt constants out of agent.py.
from longrun.core import server as _server  # noqa: E402,F401
from longrun.agent import agent as A  # noqa: E402
from longrun.agent import subagent as SA  # noqa: E402
from longrun.agent import session_jobs as SJw  # noqa: E402

check("B1 _parallel_tool_cap() reads runtime.max_parallel_tools (4)",
      A._parallel_tool_cap() == 4, A._parallel_tool_cap())

_orig_ri = A._runtime_int
A._runtime_int = lambda k, d: 0
check("B2 a tool cap of 0 clamps to 1", A._parallel_tool_cap() == 1)
A._runtime_int = lambda k, d: -5
check("B3 a negative tool cap clamps to 1", A._parallel_tool_cap() == 1)
A._runtime_int = _orig_ri

check("B4 the parallel-subagent cap reads subagents.yaml max_parallel (4)",
      SJw._worker_cap() == 4, SJw._worker_cap())
_orig_load = SA.load_cfg
SA.load_cfg = lambda reload=False: {"max_parallel": 0}
check("B5 a subagent cap of 0 clamps to 1", SJw._worker_cap() == 1)
SA.load_cfg = _orig_load

check("C _batch_items reads calls / tool_calls / batch / parallel",
      len(A._batch_items({"calls": [{"tool": "a"}]})) == 1
      and len(A._batch_items({"tool_calls": [{"tool": "a"}, {"tool": "b"}]})) == 2
      and len(A._batch_items({"batch": [{"tool": "a"}]})) == 1
      and len(A._batch_items({"parallel": [{"tool": "a"}, {"tool": "b"}]})) == 2
      and A._batch_items({"calls": "nope"}) == []
      and A._batch_items(None) == [])


class _Reg:
    def tool_names(self):
        return ["fs.read"]


class _Fake:
    """A gated_call stand-in that proves concurrency by counting in-flight calls."""

    registry = _Reg()

    def __init__(self, delay):
        self.delay = delay
        self.inflight = 0
        self.maxinflight = 0
        self.lock = threading.Lock()

    def normalize_tool_args(self, tool, args):
        return dict(args or {})

    def gated_call(self, tool, args, **kw):
        with self.lock:
            self.inflight += 1
            self.maxinflight = max(self.maxinflight, self.inflight)
        try:
            time.sleep(self.delay)
            return {"status": "executed", "result": {"ok": True},
                    "observation": "obs:" + str((args or {}).get("path"))}
        finally:
            with self.lock:
                self.inflight -= 1


_orig_persist = A.persist_tool_card
_orig_ws = A._chat_workspace
A.persist_tool_card = lambda *a, **k: None
A._chat_workspace = lambda sess: None

sess = {"id": "v528"}
ev = []


def on_event(kind, **kw):
    ev.append((kind, kw))


three = {"action": "batch", "calls": [
    {"tool": "fs.read", "args": {"path": "a"}},
    {"tool": "fs.read", "args": {"path": "b"}},
    {"tool": "fs.read", "args": {"path": "c"}}]}

f1 = _Fake(0.25)
t0 = time.time()
obs = A._apply_chat_batch(sess, three, on_event, f1)
elapsed = time.time() - t0
check("D1 three tool calls run CONCURRENTLY (max in-flight == 3, wall ~ one delay)",
      f1.maxinflight == 3 and elapsed < 0.6
      and "obs:a" in obs and "obs:b" in obs and "obs:c" in obs,
      "max=%s elapsed=%.2f" % (f1.maxinflight, elapsed))
check("D2 one tool.call + one tool.result per item",
      sum(1 for k, _ in ev if k == "tool.call") == 3
      and sum(1 for k, _ in ev if k == "tool.result") == 3)

_orig_cap = A._parallel_tool_cap
A._parallel_tool_cap = lambda: 1
f2 = _Fake(0.12)
A._apply_chat_batch(sess, three, on_event, f2)
check("D3 a cap of 1 serialises the batch (max in-flight == 1)",
      f2.maxinflight == 1, "max=%s" % f2.maxinflight)
A._parallel_tool_cap = _orig_cap

A.persist_tool_card = _orig_persist
A._chat_workspace = _orig_ws

check("E the Harness panel exposes the parallel-tools field and the API persists it",
      'id="rtParallel"' in idx and "max_parallel_tools" in idx
      and '"max_parallel_tools"' in api)
check("F the command palette is a DIRECT button; the app menu is gone",
      'id="palette-open"' in idx and 'id="appmenuBtn"' not in idx
      and 'id="appMenu"' not in idx)

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
