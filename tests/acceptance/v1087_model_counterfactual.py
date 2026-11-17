#!/usr/bin/env python3
"""v1087 — the model-level counterfactual: one changed observation, one re-ask.

Round 11 shipped the STEP-level counterfactual and round 17 widened what it may
replay; both compare an OBSERVATION. HD-1's other half is the decision itself:
*if the model had seen a different observation, would its next action differ?*
A step replay cannot answer that when the step under test was a write (replaying
it duplicates the effect), so this instrument executes NOTHING: it replays the
stored transcript with ONE user message replaced, issues one model call and
compares the parsed action.

Contract:
  P  plan(): the target must be a USER message with a recorded assistant
     successor; a no-op change is refused; -1 addresses the last message
  C  compare(): same-action / different-action / no-action, with moved keys
  R  the ONE implementation: transcript + CURRENT system prompt, one model call,
     the reply parsed by the loop's own `extract_action_json`
  T  the `sessions` action delegates, gates the reporting line and reports
  G  the registry advertises it (required args, enum, guidance, not read-only)

Deterministic: the transport is stubbed; no server, no model, no store write.
Run: python3 tests/acceptance/v1087_model_counterfactual.py
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02  # noqa: E402
from longrun.core import server as S_MOD  # noqa: E402
from longrun.agent import agent as A_MOD  # noqa: E402
from longrun.harness import modelcf as M  # noqa: E402
from longrun.tools import registry  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SESS = {"id": "s1", "model": "m1", "workspace": "/tmp", "messages": [
    {"role": "user", "content": "fix the bug", "ts": 1},
    {"role": "assistant", "content": '{"action":"tool","tool":"shell.exec",'
                                     '"args":{"command":"grep -n x f"}}', "ts": 2},
    {"role": "user", "content": "[harness] Observation for tool shell.exec: no match",
     "ts": 3},
    {"role": "assistant", "content": '{"action":"tool","tool":"fs.read",'
                                     '"args":{"path":"a.py"}}', "ts": 4},
]}


def patch(mod, **kw):
    old = {}
    for k, v in kw.items():
        old[k] = getattr(mod, k, None)
        setattr(mod, k, v)
    return old


def restore(mod, old):
    for k, v in old.items():
        setattr(mod, k, v)


# ---- P: the plan -------------------------------------------------------------
p, why = M.plan(SESS, 2, {"content": "no match (searching a different file)"})
check("P1 a user observation plans cleanly", not why and p.get("index") == 2, why)
check("P2 it names the recorded reply to compare against",
      "fs.read" in str(p.get("recorded_reply")), p.get("recorded_reply"))
check("P3 it states its fidelity and caveat",
      p.get("fidelity") == "transcript+live-system" and bool(p.get("caveat")),
      p.get("fidelity"))
p2, why2 = M.plan(SESS, -2, {"content": "different"})
check("P4 -2 addresses the observation before the last assistant",
      not why2 and p2.get("index") == 2, why2)

refused = [
    ("no messages", {"messages": []}, 0, {"content": "x"}),
    ("index not an int", SESS, "zero", {"content": "x"}),
    ("index out of range", SESS, 99, {"content": "x"}),
    ("the last message has no successor", SESS, 3, {"content": "x"}),
    ("an assistant message is history, not input", SESS, 1, {"content": "x"}),
    ("a no-op change", SESS, 2, {"content": "[harness] Observation for tool "
                                            "shell.exec: no match"}),
    ("no content", SESS, 2, {"replacement": "x"}),
    ("empty content", SESS, 2, {"content": "   "}),
    ("change not an object", SESS, 2, "x"),
]
for name, sess, idx, ch in refused:
    _, w = M.plan(sess, idx, ch)
    check("P5 refused: %s" % name, bool(w), w)

structured = dict(SESS, messages=[
    {"role": "user", "content": [{"type": "text", "text": "x"}], "ts": 1},
    {"role": "assistant", "content": "a", "ts": 2}])
_, w = M.plan(structured, 0, {"content": "y"})
check("P6 structured (image-block) content is refused", "structured" in w, w)

# ---- C: the comparison -------------------------------------------------------
same = M.compare({"action": "tool", "tool": "fs.read", "args": {"path": "a.py"}},
                 {"action": "tool", "tool": "fs.read", "args": {"path": "a.py"}})
check("C1 identical actions are same-action",
      same["verdict"] == "same-action" and not same["moved"], same)
diff = M.compare({"action": "tool", "tool": "fs.read", "args": {"path": "a.py"}},
                 {"action": "tool", "tool": "fs.read", "args": {"path": "b.py"}})
check("C2 a changed argument is different-action", diff["verdict"] == "different-action", diff)
check("C3 it names what moved", diff["moved"] == ["args"], diff["moved"])
tool = M.compare({"action": "tool", "tool": "fs.read", "args": {}},
                 {"action": "tool", "tool": "shell.exec", "args": {}})
check("C4 a changed tool is different-action", tool["verdict"] == "different-action", tool)
none = M.compare({}, {})
check("C5 two plain answers are no-action", none["verdict"] == "no-action", none)
one = M.compare({"action": "tool", "tool": "x", "args": {}}, {})
check("C6 an action that vanishes is different-action with action moved",
      one["verdict"] == "different-action" and one["moved"] == ["action"], one)
check("C7 one_line renders a tool action",
      "fs.read" in M.one_line({"action": "tool", "tool": "fs.read",
                               "args": {"path": "a.py"}}),
      M.one_line({"action": "tool", "tool": "fs.read", "args": {"path": "a.py"}}))

# ---- R: the ONE implementation ----------------------------------------------
class FakeSrv:
    @staticmethod
    def _system_prompt(sess, tool_ctx, model=None):
        return "SYSTEM(%s)" % model

    @staticmethod
    def _tool_context():
        return {"fake": True}


sent = []
published = []


def fake_stream(msgs, model, on_delta, **kw):
    sent.append({"msgs": msgs, "model": model, "kw": kw})
    return ('{"action":"tool","tool":"fs.read","args":{"path":"b.py"}}', "think")

old = patch(api_v02, _session_ws=lambda sid: ("/tmp", SESS if sid == "s1" else None),
            _publish=lambda kind, **d: published.append((kind, d)))
old2 = patch(S_MOD, _system_prompt=FakeSrv._system_prompt,
             _tool_context=FakeSrv._tool_context)
old3 = patch(A_MOD, _router_stream=fake_stream)
try:
    out = api_v02.model_counterfactual_run("nope", 2, {"content": "x"})
    check("R1 an unknown session is a 404", out.get("status") == 404, out)
    out = api_v02.model_counterfactual_run("s1", 3, {"content": "x"})
    check("R2 a refused plan is a 400", out.get("status") == 400
          and "no recorded next action" in (out.get("error") or ""), out)

    out = api_v02.model_counterfactual_run("s1", 2, {"content": "no match elsewhere"})
    check("R3 the happy path answers 200", out.get("status") == 200, out)
    check("R4 it asked the session's own model", out.get("model") == "m1", out.get("model"))
    check("R5 exactly one model call was made", len(sent) == 1, sent)
    msgs = sent[0]["msgs"]
    check("R6 the system prompt leads", msgs[0]["role"] == "system"
          and msgs[0]["content"] == "SYSTEM(m1)", msgs[0])
    check("R7 the transcript up to the target is replayed in order",
          [m["role"] for m in msgs[1:]] == ["user", "assistant", "user"], msgs[1:])
    check("R8 the target message was REPLACED",
          msgs[-1]["content"] == "no match elsewhere", msgs[-1])
    check("R9 the reply is compared with the recorded action",
          out["compare"]["verdict"] == "different-action"
          and out["compare"]["moved"] == ["args"], out["compare"])
    check("R10 the usage dict was handed to the transport",
          isinstance(sent[0]["kw"].get("usage"), dict), sent[0]["kw"])
    check("R11 the event names the session, index and verdict",
          published and published[-1][0] == "model_counterfactual.run"
          and published[-1][1].get("index") == 2, published[-1:])
    check("R12 the answer carries its fidelity caveat",
          out.get("fidelity") == "transcript+live-system" and bool(out.get("caveat")),
          out.get("fidelity"))

    def boom(*a, **k):
        raise RuntimeError("provider down")

    patch(A_MOD, _router_stream=boom)
    out = api_v02.model_counterfactual_run("s1", 2, {"content": "different"})
    check("R13 a provider failure is a 502 naming the cause",
          out.get("status") == 502 and "provider down" in (out.get("error") or ""), out)
finally:
    restore(api_v02, old)
    restore(S_MOD, old2)
    restore(A_MOD, old3)

# ---- T: the tool action ------------------------------------------------------
r = T._sessions({"action": "model_counterfactual"}, None)
check("T1 missing arguments are exit 64 with a teaching message",
      r.get("exit_code") == 64 and "index" in (r.get("error") or ""), r.get("error"))
r = T._sessions({"action": "model_counterfactual", "session": "s1", "index": 2,
                 "change": "{not json"}, None)
check("T2 broken change JSON is exit 64", r.get("exit_code") == 64
      and "JSON" in (r.get("error") or ""), r.get("error"))

old = patch(T, _may_message=lambda caller, target: (False, "sideways"))
try:
    r = T._sessions({"action": "model_counterfactual", "session": "s1", "index": 2,
                     "change": {"content": "x"}}, "caller")
finally:
    restore(T, old)
check("T3 the reporting line refuses it (exit 126)",
      r.get("exit_code") == 126 and r.get("permission_denied") is True, r)

seen = []


def fake_run(sid, index, change, model=None, by="model-counterfactual"):
    seen.append({"sid": sid, "index": index, "change": change, "by": by})
    return {"ok": True, "status": 200, "session": sid, "index": 2, "model": "m1",
            "fidelity": "transcript+live-system", "caveat": "x",
            "compare": {"verdict": "different-action", "moved": ["args"]},
            "recorded_action": {"action": "tool"}, "replayed_action": {"action": "tool"},
            "usage": {"prompt_tokens": 10}}


old = patch(T, _may_message=lambda caller, target: (True, ""), _session_id=lambda v: "s1")
old2 = patch(api_v02, model_counterfactual_run=fake_run)
try:
    r = T._sessions({"action": "model_counterfactual", "session": "s1", "index": 2,
                     "change": "{\"content\": \"different\"}"}, "caller")
    r2 = T._sessions({"action": "model_cf", "session": "s1", "index": -2,
                      "change": {"content": "different"}}, "caller")
finally:
    restore(T, old)
    restore(api_v02, old2)
check("T4 the tool calls the ONE implementation (by=tool)",
      len(seen) == 2 and seen[0]["by"] == "tool", seen)
check("T5 a JSON-string change is parsed before delegating",
      seen[0]["change"] == {"content": "different"}, seen)
check("T6 -2 is handed through unchanged", seen[1]["index"] == -2, seen[1])
check("T7 the verdict and the model are in stdout",
      r.get("ok") is True and "different-action" in (r.get("stdout") or "")
      and "m1" in (r.get("stdout") or ""), r.get("stdout"))

# ---- G: the registry ---------------------------------------------------------
spec = (registry.tool_spec("sessions.model_counterfactual") or {}).get("schema") or {}
check("G1 required args are session, index, change",
      spec.get("required") == ["session", "index", "change"], spec.get("required"))
check("G2 index is an integer in the schema",
      (spec.get("properties") or {}).get("index", {}).get("type") == "integer",
      (spec.get("properties") or {}).get("index"))
_enum = ((registry.TOOL_SCHEMAS.get("sessions") or {}).get("properties") or {}) \
    .get("action", {}).get("enum") or []
check("G3 the action is in the namespace enum", "model_counterfactual" in _enum, _enum)
check("G4 it spends a model call, so it is NOT plan-read-only",
      "sessions.model_counterfactual" not in registry.PLAN_READ_ONLY_TOOLS)

print("\n---\nv1087: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
