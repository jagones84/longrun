#!/usr/bin/env python3
"""v1085 — the agent can run the causal instrument, not only the operator.

Rounds 10–15 built a chain the AGENT could not use: the compacted manifest prints
`#<handle>` (round 10), the counterfactual replays one recorded step with one fact
changed (round 11), and round 15 made the cards agents actually produce eligible
(436/1076 pure). But the instrument was reachable only from the HTTP route and
`forge.py` — measured 2026-11-18: `grep -rn counterfactual src/` found the route,
the CLI and the harness module, and NO tool action. So an agent asked "why did
that step fail?" could still only correlate.

Round 16 gives the agent the two missing actions and keeps ONE implementation:
`api_v02.counterfactual_run` serves the route, the CLI and the tool, so the purity
gate, the `gated_call` door and the comparison cannot drift apart.

Contract:
  A  counterfactual_run: 400 no handle · 404 no session · 404 no card · 400 impure
     · 200 on a pure replay, with the call it made and the comparison it returned
  B  sessions action=counterfactual: 64 on bad arguments (teaching text), 126 when
     the reporting line refuses, ok on the happy path — and it DELEGATES
  C  the registry advertises both actions; `card` is exploration, `counterfactual`
     is not (it executes)

Deterministic: no server, no model, no real replay (the door is stubbed).
Run: python3 tests/acceptance/v1085_agent_counterfactual.py
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02  # noqa: E402
from longrun.tools import registry  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


CARD = {"id": "ab12cd34", "tool": "shell", "ok": True,
        "args": json.dumps({"command": "cat a.py"}),
        "result": "line 1\nline 2"}


class FakeSrv:
    def __init__(self, card):
        self._card = card

    def card_by_handle(self, sess, handle):
        return self._card


def patch(mod, **kw):
    """Set attributes and return the originals (restored by the caller)."""
    old = {}
    for k, v in kw.items():
        old[k] = getattr(mod, k, None)
        setattr(mod, k, v)
    return old


def restore(mod, old):
    for k, v in old.items():
        setattr(mod, k, v)


# ---- A: the ONE implementation ----------------------------------------------
out = api_v02.counterfactual_run("s1", "", {"command": "cat b"})
check("A1 no handle is a 400", out.get("status") == 400
      and "handle" in (out.get("error") or ""), out)

old = patch(api_v02, _session_ws=lambda sid: ("/tmp", None))
try:
    out = api_v02.counterfactual_run("s1", "ab12cd34", {"command": "cat b"})
finally:
    restore(api_v02, old)
check("A2 an unknown session is a 404",
      out.get("status") == 404 and "session" in (out.get("error") or ""), out)

old = patch(api_v02, _session_ws=lambda sid: ("/tmp", {"id": sid}),
            _srv=lambda: FakeSrv(None))
try:
    out = api_v02.counterfactual_run("s1", "nope", {"command": "cat b"})
finally:
    restore(api_v02, old)
check("A3 an unknown handle is a 404",
      out.get("status") == 404 and "card" in (out.get("error") or ""), out)

calls = []


def fake_gated(tool, args, **kw):
    calls.append({"tool": tool, "args": args, **kw})
    return {"result": {"ok": True, "stdout": "line 3\nline 4"},
            "observation": "line 3\nline 4"}


old = patch(api_v02, _session_ws=lambda sid: ("/tmp", {"id": sid}),
            _srv=lambda: FakeSrv(CARD), gated_call=fake_gated,
            _publish=lambda *a, **k: None, _chat_obs_full=lambda: 1600)
try:
    out = api_v02.counterfactual_run("s1", "ab12cd34", {"command": "rm -rf build"})
    check("A4 an impure recorded/commanded step is a 400 before executing",
          out.get("status") == 400 and "not pure" in (out.get("error") or "")
          and not calls, out)

    out = api_v02.counterfactual_run("s1", "ab12cd34", {"command": "cat b.py"})
    check("A5 a pure step replays and returns 200", out.get("status") == 200, out)
    check("A6 the replay went through the ONE gated door",
          len(calls) == 1 and calls[0]["tool"] == "shell"
          and calls[0]["args"].get("command") == "cat b.py"
          and calls[0].get("by") == "counterfactual", calls)
    check("A7 the comparison is reported",
          (out.get("compare") or {}).get("verdict") == "different-observation",
          out.get("compare"))
    check("A8 the answer carries the live-tree caveat",
          out.get("fidelity") == "live-tree" and "caveat" in out, out.get("fidelity"))
    check("A9 it names the purity it relied on",
          "shell command" in ((out.get("plan") or {}).get("purity") or ""),
          out.get("plan"))
finally:
    restore(api_v02, old)


# ---- B: the tool action ------------------------------------------------------
r = T._sessions({"action": "counterfactual"}, None)
check("B1 missing session/handle is exit 64 with a teaching message",
      r.get("exit_code") == 64 and "handle" in (r.get("error") or ""), r.get("error"))

r = T._sessions({"action": "counterfactual", "session": "s1", "handle": "h1"}, None)
check("B2 a missing change is exit 64 and says what to send",
      r.get("exit_code") == 64 and "change" in (r.get("error") or ""), r.get("error"))

r = T._sessions({"action": "counterfactual", "session": "s1", "handle": "h1",
                 "change": "{not json"}, None)
check("B3 a broken change JSON is exit 64, not a crash",
      r.get("exit_code") == 64 and "JSON" in (r.get("error") or ""), r.get("error"))

old = patch(T, _may_message=lambda caller, target, verb="message": (False, "sideways across teams"),
            _session_id=lambda v: "s1")
try:
    r = T._sessions({"action": "counterfactual", "session": "s1", "handle": "h1",
                     "change": {"command": "cat b"}}, "caller-1")
finally:
    restore(T, old)
check("B4 the reporting line refuses it (exit 126)",
      r.get("exit_code") == 126 and r.get("permission_denied") is True
      and "sideways" in (r.get("error") or ""), r.get("error"))

seen = []


def fake_run(sid, handle, change, wait=True, by="counterfactual"):
    seen.append({"sid": sid, "handle": handle, "change": change, "by": by})
    return {"ok": True, "status": 200, "fidelity": "live-tree", "caveat": "x",
            "plan": {"tool": "shell", "changed": ["command"],
                     "purity": "read-only shell command"},
            "compare": {"verdict": "different-observation", "changed": ["result"]}}


old = patch(T, _may_message=lambda caller, target, verb="message": (True, ""),
            _session_id=lambda v: "s1")
old2 = patch(api_v02, counterfactual_run=fake_run)
try:
    r = T._sessions({"action": "counterfactual", "session": "s1", "handle": "#ab12",
                     "change": {"command": "cat b"}}, "caller-1")
    r2 = T._sessions({"action": "cf", "session": "s1", "handle": "#ab12",
                      "change": "{\"command\": \"cat c\"}"}, "caller-1")
finally:
    restore(T, old)
    restore(api_v02, old2)
check("B5 the tool calls the ONE implementation", len(seen) == 2 and seen[0]["by"] == "tool",
      seen)
check("B6 it hands the handle and the change through unchanged",
      seen[0]["handle"] == "#ab12" and seen[0]["change"] == {"command": "cat b"}, seen)
check("B7 a JSON-string change is parsed before delegating",
      seen[1]["change"] == {"command": "cat c"}, seen)
check("B8 the verdict is in the answer and in stdout",
      r.get("ok") is True and r.get("verdict") == "different-observation"
      and "different-observation" in (r.get("stdout") or ""), r)
check("B9 the purity and the caveat reach the model",
      r.get("purity") == "read-only shell command" and bool(r.get("caveat")), r)

# ---- C: the registry advertises them ----------------------------------------
spec_cf = (registry.tool_spec("sessions.counterfactual") or {}).get("schema") or {}
spec_card = (registry.tool_spec("sessions.card") or {}).get("schema") or {}
check("C1 sessions.counterfactual exists with its required args",
      spec_cf.get("required") == ["session", "handle", "change"], spec_cf.get("required"))
check("C2 sessions.card exists with its required args",
      spec_card.get("required") == ["session", "handle"], spec_card.get("required"))
check("C3 change is an object in the declared schema",
      (spec_cf.get("properties") or {}).get("change", {}).get("type") == "object",
      (spec_cf.get("properties") or {}).get("change"))
check("C4 reading a card is exploration; replaying is not",
      "sessions.card" in registry.PLAN_READ_ONLY_TOOLS
      and "sessions.counterfactual" not in registry.PLAN_READ_ONLY_TOOLS)
_enum = ((registry.TOOL_SCHEMAS.get("sessions") or {}).get("properties") or {}) \
    .get("action", {}).get("enum") or []
check("C5 the actions are in the namespace enum",
      "card" in _enum and "counterfactual" in _enum, _enum)

print("\n---\nv1085: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
