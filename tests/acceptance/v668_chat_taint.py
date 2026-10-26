#!/usr/bin/env python3
"""v668 — I-4: the CHAT path applies the standing-approval taint rule (M2a).

The rule existed but was dead on the main chat path: `gated_call` hardcoded
`registry.classify(..., None)`, so a recalled memory block could never suspend
an `approval: auto` tool. This test pins the wiring:

* the memory buckets the chat prompt actually emits are taint markers;
* `gated_call` takes the proposing context and hands it to `classify`;
* both chat call sites (single call + batch) pass the context they sent;
* `approvals.mode=full` still bypasses (the operator driving).

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v668-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry       # noqa: E402
from longrun.core import api_v02         # noqa: E402

registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _mode(mode):
    cfg = registry.load_config()
    ap = cfg.setdefault("approvals", {})
    saved = ap.get("mode", "normal")
    ap["mode"] = mode
    return saved


def _restore(saved):
    registry.load_config().setdefault("approvals", {})["mode"] = saved


# The three buckets `model/prompt.py:_provider_memory` writes into the system
# prompt. User facts are included on purpose: `memory.store` is written by the
# MODEL, so a poisoned write reaches it too (ClawMMU: derived data is untrusted).
MEM_FACTS = "## Memory \u2014 user facts (told by the user; trust these)\n- repo is /x"
MEM_LESSONS = "## Memory \u2014 self-distilled lessons (your own past reflections; " \
              "verify before relying)\n- always run the battery"
MEM_CORE = "## Core memory (always visible \u2014 edit with memory{action:'set_core'})\nop notes"
CLEAN = "## Rules\n- be useful"

# ---- A. markers cover what the chat prompt emits ---------------------------
check("A1 memory headers are taint markers",
      all(m in registry._TAINT_MARKERS
          for m in ("## Memory \u2014 user facts", "## Memory \u2014 self-distilled lessons",
                    "## Core memory")),
      registry._TAINT_MARKERS)
check("A2 a memory-bucket system prompt is untrusted",
      all(registry.context_has_untrusted([{"role": "system", "content": c}])
          for c in (MEM_FACTS, MEM_LESSONS, MEM_CORE)))
check("A3 a prompt without memory stays clean",
      registry.context_has_untrusted([{"role": "system", "content": CLEAN}]) is False)

# ---- B. the gate takes the proposing context -------------------------------
import inspect                          # noqa: E402

_src = inspect.getsource(api_v02.gated_call)
check("B1 gated_call accepts hist and forwards it to classify",
      "hist" in inspect.signature(api_v02.gated_call).parameters
      and "classify(tool, args, workspace, hist)" in _src)

with open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
          encoding="utf-8") as f:
    _agent = f.read()
check("B2 both chat call sites pass the context they sent",
      _agent.count("hist=msgs") >= 2, _agent.count("hist=msgs"))
check("B3 the batch runner threads hist through",
      "def _apply_chat_batch(sess, act, on_event, av02, node=None, after=None, hist=None)" in _agent
      and "hist=hist" in _agent)

# ---- C. end-to-end gate behaviour (tool execution stubbed) -----------------
_exec = {"n": 0}


def _fake_execute(tool, args, run_id=None, **kw):
    _exec["n"] += 1
    return {"ok": True, "stdout": "", "exit_code": 0}


api_v02.toolmod.execute = _fake_execute
api_v02.toolmod.observation = lambda res, max_chars=1600: "ok"

saved = _mode("normal")
try:
    res = api_v02.gated_call("skills", {"action": "list"}, wait=False,
                             hist=[{"role": "system", "content": MEM_LESSONS}])
    check("C1 a recalled memory suspends an auto tool (pending, not executed)",
          res.get("status") == "pending"
          and "standing auto-approval suspended" in str(res.get("reason")),
          "%s %s" % (res.get("status"), res.get("reason")))
    check("C2 the tool did not run",
          _exec["n"] == 0, _exec["n"])

    res = api_v02.gated_call("skills", {"action": "list"}, wait=False, hist=None)
    check("C3 a context-free one-shot call keeps auto (executed)",
          res.get("status") == "executed", res.get("status"))

    res = api_v02.gated_call("skills", {"action": "list"}, wait=False,
                             hist=[{"role": "system", "content": CLEAN}])
    check("C4 a clean context keeps auto (executed)",
          res.get("status") == "executed", res.get("status"))
finally:
    _restore(saved)

saved = _mode("full")
try:
    res = api_v02.gated_call("skills", {"action": "list"}, wait=False,
                             hist=[{"role": "system", "content": MEM_CORE}])
    check("C5 approvals.mode=full still bypasses under taint",
          res.get("status") == "executed", res.get("status"))
finally:
    _restore(saved)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
