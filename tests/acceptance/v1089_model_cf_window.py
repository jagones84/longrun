#!/usr/bin/env python3
"""v1089 — the model replay is BOUNDED to the model's window.

Measured 2026-11-18 on the live store: 138 sessions, max **269 messages /
545k chars**, p90 148 messages / 222k chars. `model_counterfactual_run` sent the
whole stored prefix, so a replay of a long session would exceed the model's
context window and fail at the provider instead of answering.

The bound drops the OLDEST messages (what the harness's own compaction does),
never the target or its recorded successor, and reports how many were dropped —
`fidelity` becomes `transcript-window+live-system` and the caveat says so.

Contract:
  W  modelcf.window drops from the oldest, keeps the prefix under budget
  R  the ONE implementation uses the model's own context budget
  F  a dropped window changes the fidelity string and the reported count
  E  a replacement that cannot fit the budget is refused with a 400
  T  the tool prints the window so the model cannot think it saw everything

Deterministic: the transport is stubbed; no server, no model, no store write.
Run: python3 tests/acceptance/v1089_model_cf_window.py
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S_MOD  # noqa: E402,F401 — import order (agent cycle)
from longrun.agent import agent as A_MOD  # noqa: E402
from longrun.core import api_v02  # noqa: E402
from longrun.harness import modelcf as M  # noqa: E402
from longrun.model import rllm as R  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def patch(mod, **kw):
    old = {}
    for k, v in kw.items():
        old[k] = getattr(mod, k, None)
        setattr(mod, k, v)
    return old


def restore(mod, old):
    for k, v in old.items():
        setattr(mod, k, v)


# ---- W: the window -----------------------------------------------------------
MSGS = [{"role": "user", "content": "x" * 100} for _ in range(10)]

first, dropped = M.window(MSGS, 10, 10000)
check("W1 a prefix that fits is not touched", (first, dropped) == (0, 0),
      (first, dropped))
first, dropped = M.window(MSGS, 10, 350)
check("W2 an over-budget prefix drops from the OLDEST", first == dropped
      and dropped > 0, (first, dropped))
kept = sum(len(m["content"]) + 32 for m in MSGS[first:10])
check("W3 what remains fits the budget", kept <= 350, kept)
first, dropped = M.window(MSGS, 10, 0)
check("W4 a zero budget drops everything before the target",
      first == 10 and dropped == 10, (first, dropped))
first, dropped = M.window(MSGS, 0, 100)
check("W5 no prefix means nothing to drop", (first, dropped) == (0, 0),
      (first, dropped))

# ---- R/F: the implementation uses the model's budget ------------------------
STORED = ([{"role": "user", "content": "brief"}]
          + [{"role": "user", "content": "observation %d " % i + "y" * 900}
             for i in range(20)]
          + [{"role": "assistant", "content": '{"action":"tool","tool":"fs.read",'
                                              '"args":{"path":"a.py"}}'}])
SESS = {"id": "s1", "model": "m1", "workspace": "/tmp", "messages": STORED}
TARGET = len(STORED) - 2      # the last observation, followed by the action


class FakeSrv:
    @staticmethod
    def _system_prompt(sess, tool_ctx, model=None):
        return "SYS"

    @staticmethod
    def _tool_context():
        return {}


sent = []


def fake_stream(msgs, model, on_delta, **kw):
    sent.append(msgs)
    return ('{"action":"tool","tool":"fs.read","args":{"path":"b.py"}}', "")


old = patch(api_v02, _session_ws=lambda sid: ("/tmp", SESS),
            _publish=lambda *a, **k: None)
old2 = patch(S_MOD, _system_prompt=FakeSrv._system_prompt,
             _tool_context=FakeSrv._tool_context)
old3 = patch(A_MOD, _router_stream=fake_stream)
old4 = patch(R, context_budget=lambda alias=None: 2000)  # ~8000 chars
try:
    out = api_v02.model_counterfactual_run("s1", TARGET, {"content": "other"})
    check("R1 a long transcript still answers", out.get("status") == 200, out)
    check("R2 it reports how many messages were dropped",
          out.get("dropped", 0) > 0, out.get("dropped"))
    check("R3 the fidelity says the transcript was windowed",
          out.get("fidelity") == "transcript-window+live-system", out.get("fidelity"))
    check("R4 the caveat names the drop",
          "dropped" in (out.get("caveat") or ""), out.get("caveat"))
    msgs = sent[0]
    check("R5 the system prompt + target are always present",
          msgs[0]["content"] == "SYS" and msgs[-1]["content"] == "other", msgs[:1])
    check("R6 the OLDEST messages are the ones missing",
          "brief" not in [m["content"] for m in msgs], [m["content"][:12] for m in msgs])
    check("R7 the target's predecessor window is what remains",
          len(msgs) < TARGET + 2, len(msgs))

    # ---- E: an unfittable replacement is refused ---------------------------
    out = api_v02.model_counterfactual_run("s1", TARGET, {"content": "z" * 9000})
    check("E1 a replacement larger than the budget is a 400",
          out.get("status") == 400 and "context budget" in (out.get("error") or ""),
          out.get("error"))

    # ---- T: the tool prints the window ------------------------------------
    old5 = patch(T, _may_message=lambda c, t, verb="message": (True, ""), _session_id=lambda v: "s1")
    try:
        r = T._sessions({"action": "model_counterfactual", "session": "s1",
                         "index": TARGET, "change": {"content": "other"}}, "c")
    finally:
        restore(T, old5)
    check("T1 the tool says the replay was windowed",
          "windowed" in (r.get("stdout") or "") and r.get("dropped", 0) > 0,
          (r.get("stdout"), r.get("dropped")))
finally:
    restore(api_v02, old)
    restore(S_MOD, old2)
    restore(A_MOD, old3)
    restore(R, old4)

# ---- no budget: unchanged ------------------------------------------------
plan, why = M.plan(SESS, TARGET, {"content": "other"})
check("B1 without a budget the plan does not window",
      not why and plan.get("dropped") == 0
      and plan.get("fidelity") == "transcript+live-system", plan)

print("\n---\nv1089: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
