#!/usr/bin/env python3
"""v666 — R3: the run token ceiling has an ENTRY, not just helpers.

`_budget_exceeded` and `token_budget=` were correct and covered by v561, but every
production call site passed `None` and no config key existed, so the ceiling
could never fire. This test pins the entry:

* `budget.max_tokens_per_run` (config/tools.yaml) is read by `agent_run_v2` when
  the caller passes no budget; 0 / negative / garbage = off;
* an explicit argument still wins;
* a run whose tree spend reaches the configured ceiling stops with
  `termination="budget"`.

Deterministic: the router is stubbed, no model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v666-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(TMP, "costs")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as A             # noqa: E402
from longrun.tools import registry                # noqa: E402

registry._external_tools = lambda: {}
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _budget_cfg(value):
    cfg = registry.load_config()
    block = cfg.setdefault("budget", {})
    saved = block.get("max_tokens_per_run")
    block["max_tokens_per_run"] = value
    return saved


def _restore(saved):
    block = registry.load_config().setdefault("budget", {})
    block["max_tokens_per_run"] = saved


_eff = getattr(A, "_effective_budget", None)
check("A0 api_v02._effective_budget exists", callable(_eff))
if callable(_eff):
    saved = _budget_cfg(0)
    try:
        check("A1 a zero config means OFF", _eff(None) is None, _eff(None))
    finally:
        _restore(saved)
    saved = _budget_cfg(1000)
    try:
        check("A2 the config value reaches the loop with no caller passing it",
              _eff(None) == 1000, _eff(None))
        check("A3 an explicit argument wins over the config", _eff(50) == 50, _eff(50))
    finally:
        _restore(saved)
    saved = _budget_cfg(-5)
    try:
        check("A4 a negative config is OFF, not an instant trip", _eff(None) is None)
    finally:
        _restore(saved)
    saved = _budget_cfg("not-a-number")
    try:
        check("A5 garbage is OFF, never a raise", _eff(None) is None)
    finally:
        _restore(saved)


# ---- B. the entry is really in the loop ------------------------------------
with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
          encoding="utf-8") as f:
    _src = f.read()
check("B1 agent_run_v2 resolves the budget through the entry",
      "token_budget = _effective_budget(token_budget)" in _src)
check("B2 a budget block in tools.yaml survives the config merge",
      ((registry._merged({"budget": {"max_tokens_per_run": 42}}) or {}).get("budget")
       or {}).get("max_tokens_per_run") == 42,
      (registry._merged({"budget": {"max_tokens_per_run": 42}}) or {}).get("budget"))


# ---- C. a run stops at the configured ceiling -------------------------------
from longrun.core import server as srv_mod          # noqa: E402

_orig_router = getattr(srv_mod, "_router_stream", None)


def _fake_router(msgs, model, on_delta, usage=None, **kw):
    if usage is not None:
        usage.update({"prompt_tokens": 8, "completion_tokens": 2})
    return '{"thought":"x","action":"finish","summary":"done"}', ""


srv_mod._router_stream = _fake_router
A._srv = lambda: srv_mod
_events = []


def _ev(kind, **data):
    _events.append((kind, data))


try:
    saved = _budget_cfg(0)
    try:
        out = A.agent_run_v2("v666 no budget", max_steps=2, model="m", on_event=_ev)
        check("C1 with no budget the run completes as today",
              out.get("termination") == "completed", out)
    finally:
        _restore(saved)

    saved = _budget_cfg(5)
    try:
        out = A.agent_run_v2("v666 budget", max_steps=2, model="m", on_event=_ev)
        check("C2 the configured ceiling stops the run as 'budget'",
              out.get("termination") == "budget", out)
        check("C3 the stop is announced with budget_capped",
              any(k == "agent.finish" and d.get("budget_capped")
                  for k, d in _events), _events[-4:])
        check("C4 the run stops at the first iteration, it does not wander",
              len(out.get("trace") or []) == 1
              and (out.get("trace") or [{}])[-1].get("budget_capped") is True,
              out.get("trace"))

        out = A.agent_run_v2("v666 explicit", max_steps=2, model="m", on_event=_ev,
                             token_budget=100000)
        check("C5 an explicit large budget overrides the config",
              out.get("termination") == "completed", out)
    finally:
        _restore(saved)
finally:
    if _orig_router is not None:
        srv_mod._router_stream = _orig_router

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
