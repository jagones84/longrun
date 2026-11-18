#!/usr/bin/env python3
"""v1153 — one `tool.result` per call, and a failure that explains itself (round 88).

Measured on the live store: 1,836 recent `tool.result` events for ~950 tool calls.
`gated_call` publishes one (stdout only, 2,000 chars, no `stderr`, no `error`) and
the chat loop publishes a second, richer one right after it, so every chat call
stores a duplicate. On a failure whose reason lives in `result["error"]` — a
`python.run` that died with an empty stdout, a `shell.exec` with a missing
argument — the `gated_call` record says `ok: false` and NOTHING else
(54 such rows in the same window). The audit cannot say why the call failed.

Contract:
  A gated_call publishes exactly one tool.result by default
  B announce=False suppresses ONLY the result (the approval event stays)
  C a failure whose reason is in `error` still carries it in the event
  D a failure whose reason is the observation carries that
  E a success still carries stdout (no regression)
  F both chat call sites pass announce=False
  G the other gated_call callers keep the default (they publish)

Deterministic: stub publisher, stub registry.classify, stub toolmod.execute,
isolated data dir; no model, no network, no server.
Run: python3 tests/acceptance/v1153_tool_result_single_event.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1153-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_APPROVALS"] = os.path.join(TMP, "approvals.json")
for _d in ("cfg", "data"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02                      # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- the stub publisher: records what gated_call actually publishes ---------
EVENTS = []


class _Srv:
    def publish(self, kind, **data):
        EVENTS.append((kind, data))
        return None


api_v02._srv = lambda: _Srv()

# Policy and execution are not what this test measures: classify -> auto,
# execute -> a controlled result dict.
api_v02.registry.classify = lambda *a, **k: ("auto", "test")
api_v02.registry.canonical_name = lambda tool, args: tool
api_v02.registry.tool_spec = lambda tool: {"enabled": True}

_RESULT = {}


def _execute(tool, args, run_id=None):
    return dict(_RESULT)


api_v02.toolmod.execute = _execute


def _call(**kw):
    EVENTS.clear()
    return api_v02.gated_call("fs.read", {"path": "x.md"}, run_id="v1153",
                              obs_max=1600, **kw)


def _results():
    return [d for k, d in EVENTS if k == "tool.result"]


# A — one result by default, naming the approval
_RESULT.clear()
_RESULT.update({"ok": True, "stdout": "alpha\nbeta", "exit_code": 0})
r = _call()
check("A1 executed", r.get("status") == "executed", r)
check("A2 exactly one tool.result", len(_results()) == 1, [k for k, _ in EVENTS])
ev = _results()[0] if _results() else {}
check("A3 the result names tool, ok and approval",
      ev.get("tool") == "fs.read" and ev.get("ok") is True and bool(ev.get("approval")), ev)
check("A4 the payload is stdout", ev.get("stdout") == "alpha\nbeta", ev)

# B — announce=False suppresses only the result
_RESULT.clear()
_RESULT.update({"ok": True, "stdout": "gamma", "exit_code": 0})
r = _call(announce=False)
kinds = [k for k, _ in EVENTS]
check("B1 announce=False publishes no tool.result", "tool.result" not in kinds, kinds)
check("B2 the approval event survives announce=False",
      "approval.auto" in kinds, kinds)
check("B3 the call still executes and answers", r.get("status") == "executed"
      and (r.get("result") or {}).get("stdout") == "gamma", r)

# C — a failure whose reason is only in `error`
_RESULT.clear()
_RESULT.update({"ok": False, "exit_code": 1, "stdout": "",
                "error": "missing REQUIRED argument(s) 'command'", "stderr": ""})
_call()
ev = _results()[0] if _results() else {}
check("C1 one result", len(_results()) == 1, [k for k, _ in EVENTS])
check("C2 the event carries the failure reason",
      "missing REQUIRED argument" in (ev.get("stdout") or ""), ev)
check("C3 ok is false", ev.get("ok") is False, ev)

# D — a failure whose reason is the observation
_RESULT.clear()
_RESULT.update({"ok": False, "exit_code": 0, "stdout": "", "stderr": "",
                "observation": "tool fs.read refused: outside the workspace"})
_call()
ev = _results()[0] if _results() else {}
check("D1 the observation reaches the event",
      "outside the workspace" in (ev.get("stdout") or ""), ev)

# E — success keeps stdout and now also carries stderr (empty is fine)
_RESULT.clear()
_RESULT.update({"ok": True, "stdout": "ok-out", "stderr": "warn-line", "exit_code": 0})
_call()
ev = _results()[0] if _results() else {}
check("E1 stdout unchanged on success", ev.get("stdout") == "ok-out", ev)
check("E2 stderr is carried", ev.get("stderr") == "warn-line", ev)

# F/G — the call sites: chat suppresses, the external doors keep publishing
src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
           encoding="utf-8").read()
chat = src.count("gated_call(tool, args, run_id=sess[\"id\"]")
quiet = src.count("announce=False")
check("F1 both chat call sites exist", chat == 2, chat)
check("F2 both chat call sites suppress the duplicate", quiet == 2, quiet)
check("F3 no chat call site left publishing", src.count("announce=True") == 0,
      src.count("announce=True"))

api_src = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
               encoding="utf-8").read()
check("G1 gated_call defaults to announce=True",
      "announce=True" in api_src.split("def gated_call")[1].split(")")[0], "signature")

print("---")
print("%d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
