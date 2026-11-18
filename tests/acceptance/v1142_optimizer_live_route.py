#!/usr/bin/env python3
"""v1142 — the optimizer has its own live model route (round 77).

`_optimizer_model()` used `pick("agent")` alone. `pick()` reads `pattern` and
`fallbacks` only — never `roles.<role>.model` — and returns None while the local
roster is empty, so the operator's exact-model pin was ignored and every run fell
through to `default_model()`. Measured 2026-11-18: that key answers HTTP 403
(limit exceeded) and 95 of 170 runs were logged as "unparseable model reply" with
no reply at all. Every other role consumer already uses `role_model(role) or
pick(role)`; the optimizer was the one that did not.

Contract:
  A precedence: roles.optimizer.model -> roles.agent.model -> pick -> default
  B the shipped config gives the optimizer its own exact, non-default ref
  C the role is visible where the operator edits routing (no hidden key)

Deterministic: the routing/rllm functions are stubbed, no network.
Run: python3 tests/acceptance/v1142_optimizer_live_route.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.evolve import optimizer as O       # noqa: E402
from longrun.model import routing as RT         # noqa: E402
from longrun.model import rllm as RL            # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


_orig = (RT.role_model, RT.pick, RL.default_model)


def stub(role_map=None, pick_ret=None, default="d:default", boom=False):
    def _role_model(role):
        if boom:
            raise RuntimeError("routing unavailable")
        return (role_map or {}).get(role)
    RT.role_model = _role_model
    RT.pick = lambda role: None if boom else pick_ret
    RL.default_model = lambda: default


try:
    stub({"optimizer": "o:live", "agent": "a:cfg"}, pick_ret="p:roster")
    check("A1 roles.optimizer.model wins", O._optimizer_model() == "o:live",
          O._optimizer_model())

    stub({"agent": "a:cfg"}, pick_ret="p:roster")
    check("A2 without it, the agent PIN beats pick and the default (the fixed idiom)",
          O._optimizer_model() == "a:cfg", O._optimizer_model())

    stub({}, pick_ret="p:roster")
    check("A3 with no pin, the roster pick is used", O._optimizer_model() == "p:roster",
          O._optimizer_model())

    stub({}, pick_ret=None, default="d:default")
    check("A4 nothing configured falls back to the harness default",
          O._optimizer_model() == "d:default", O._optimizer_model())

    stub(boom=True, default="d:default")
    check("A5 a broken routing module still yields the default", O._optimizer_model() == "d:default",
          O._optimizer_model())
finally:
    RT.role_model, RT.pick, RL.default_model = _orig


# ---- B) the shipped config ---------------------------------------------------
_ref = RT.role_model("optimizer")
check("B1 config/routing.yaml gives the optimizer an exact model", bool(_ref), _ref)
check("B2 it is a provider:model ref, not a local roster alias",
      isinstance(_ref, str) and ":" in _ref, _ref)
check("B3 the optimizer no longer runs on the harness default",
      _ref and _ref != RL.default_model(), (_ref, RL.default_model()))
check("B4 _optimizer_model() resolves to it", O._optimizer_model() == _ref,
      O._optimizer_model())


# ---- C) the role is where the operator edits routing -------------------------
_cfg = RT.load_config()
check("C1 the role is in the live routing config",
      "optimizer" in ((_cfg.get("roles") or {})), sorted((_cfg.get("roles") or {})))
_st = RT.status()
check("C2 /api/routing lists it with its model",
      ((_st.get("roles") or {}).get("optimizer") or {}).get("model") == _ref,
      (_st.get("roles") or {}).get("optimizer"))
check("C2b /api/routing names the pin as the SELECTED model (not null)",
      ((_st.get("roles") or {}).get("optimizer") or {}).get("selected") == _ref,
      (_st.get("roles") or {}).get("optimizer"))

from longrun.core import settings as ST   # noqa: E402
_sec = next(s for s in ST._sections() if s.get("id") == "routing")
_paths = [f.get("path") for f in (_sec.get("fields") or [])]
check("C3 the Settings form renders the role (schema is role-derived)",
      "roles.optimizer.model" in _paths, [p for p in _paths if "optimizer" in p])

print("---")
passed = sum(RESULTS)
print("%d/%d PASS" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
