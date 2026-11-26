#!/usr/bin/env python3
"""v1316 — the cost lock: only the two AUTHORIZED models may be spent on.

The operator authorized exactly `deepseek:deepseek-flash` and
`openrouter:z-ai/glm-5.3-flash`; everything else costs too much. `allowed_models`
in `config/routing.yaml` is enforced at every point a model is chosen
(`role_model` / `pick` / `model_chain` / `turn_model`) and at the one point a call
is dispatched (`server.stream_with_fallback`). A LOCAL provider and an UNRESOLVED
ref (a llama.cpp alias, or a test's synthetic id) are never blocked — neither can
spend money at a cloud provider.

  A  the shipped config only names authorized models (roles, fallbacks, default);
  B  `model_allowed` blocks a paid outsider and allows the two + local + synthetic;
  C  `turn_model` coerces an unauthorized pin and keeps an authorized/synthetic one;
  D  `role_model` / `model_chain` drop an unauthorized pin written into routing;
  E  `stream_with_fallback` never dispatches an unauthorized paid model.

Deterministic: no model, no network, no server turn. Run:
    python3 tests/acceptance/v1316_model_cost_lock.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

_TMP = tempfile.mkdtemp(prefix="sf-v1316-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "RUNS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(_TMP, _k)
    os.makedirs(os.path.join(_TMP, _k), exist_ok=True)
os.environ["LONGRUN_DATA_HOME"] = _TMP

from longrun.model import routing, providers, rllm  # noqa: E402
from longrun.util.dataio import load_yaml  # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


AUTH = ["deepseek:deepseek-flash", "openrouter:z-ai/glm-5.3-flash"]

# ── A · the shipped config only names authorized models ─────────────────────
_cfg = routing.load_config(reload=True)
check("A1 allowed_models is exactly the two authorized refs",
      routing.allowed_models() == AUTH, routing.allowed_models())
_roles = _cfg.get("roles") or {}
_bad = []
for _role, _e in _roles.items():
    for _ref in [_e.get("model")] + list(_e.get("fallbacks") or []):
        if _ref and _ref not in AUTH:
            _bad.append("%s=%s" % (_role, _ref))
check("A2 every role model and fallback is authorized", not _bad, _bad)
check("A3 default_fallbacks is empty (no implicit extra spend)",
      not (_cfg.get("default_fallbacks") or []), _cfg.get("default_fallbacks"))
with open(os.path.join(REPO, "config", "providers.yaml"), encoding="utf-8") as _f:
    _prov_default = str((load_yaml(_f.read(), default={}) or {}).get("default") or "")
check("A4 the providers default is an authorized model",
      _prov_default in AUTH, _prov_default)
check("A5 the runtime default resolves to an authorized model",
      rllm.default_model() in AUTH, rllm.default_model())
PRODUCERS = ("chat", "agent", "subagent", "architect")
check("A6 the reviewer differs from every producing role (v796 kept)",
      all(routing.role_model(r) != routing.role_model("reviewer") for r in PRODUCERS),
      [(r, routing.role_model(r)) for r in PRODUCERS] + [("reviewer", routing.role_model("reviewer"))])

# ── B · model_allowed semantics ─────────────────────────────────────────────
check("B1 both authorized refs are allowed", all(routing.model_allowed(a) for a in AUTH))
check("B2 the bare id form of an authorized model is allowed",
      routing.model_allowed("deepseek-flash") and routing.model_allowed("z-ai/glm-5.3-flash"))
check("B3 a paid outsider is blocked",
      not routing.model_allowed("openai:gpt-6-astra")
      and not routing.model_allowed("anthropic:claude-sonnet-5")
      and not routing.model_allowed("openrouter:meta/muse-spark-1.3-contributor"))
check("B4 a LOCAL roster alias is never blocked (it cannot cost anything)",
      routing.model_allowed("qwen-3.8-27b-uncensored-q8"))
check("B5 an unresolved synthetic id is never blocked (tests, local aliases)",
      routing.model_allowed("m1") and routing.model_allowed("x"))
check("B6 the @chat sentinel is not a model and passes",
      routing.model_allowed("@chat"))

# ── C · turn_model coerces a non-authorized pin ─────────────────────────────
check("C1 an unauthorized session pin is coerced to the default",
      routing.turn_model({"model": "openai:gpt-6-astra"}) == rllm.default_model())
check("C2 an authorized pin is kept verbatim",
      routing.turn_model({"model": "openrouter:z-ai/glm-5.3-flash"})
      == "openrouter:z-ai/glm-5.3-flash")
check("C3 a synthetic pin is kept verbatim (local alias behaviour)",
      routing.turn_model({"model": "x"}) == "x")

# ── D · an unauthorized pin written into routing is dropped ─────────────────
_real_load = routing.load_config
routing.load_config = lambda reload=False: {
    "allowed_models": AUTH,
    "roles": {"chat": {"model": "openai:gpt-6-astra",
                       "fallbacks": ["openrouter:meta/muse-spark-1.3-contributor",
                                     "deepseek:deepseek-flash"]}},
    "default_fallbacks": [],
}
try:
    check("D1 role_model drops an unauthorized model pin",
          routing.role_model("chat") is None, routing.role_model("chat"))
    check("D2 model_chain drops the unauthorized refs and keeps the authorized one",
          routing.model_chain("chat") == ["deepseek:deepseek-flash"],
          routing.model_chain("chat"))
finally:
    routing.load_config = _real_load

# ── E · dispatch never calls an unauthorized paid model ─────────────────────
from longrun.core import server as S  # noqa: E402

_attempts = []
_orig_stream = S._router_stream
_orig_chain = routing.model_chain
_orig_default = rllm.default_model


def _stub(messages, alias, on_delta, timeout, usage, guard, cancel,
          no_reasoning=False, max_tokens=None, temperature=None, seed=None):
    _attempts.append(alias)
    return "ok:" + alias, ""


S._router_stream = _stub
routing.model_chain = lambda role: []
rllm.default_model = lambda: "deepseek:deepseek-flash"
try:
    answer, _think, used = S.stream_with_fallback(
        [{"role": "user", "content": "x"}], "openai:gpt-6-astra", "chat", lambda *a: None)
finally:
    S._router_stream = _orig_stream
    routing.model_chain = _orig_chain
    rllm.default_model = _orig_default
check("E1 the unauthorized model never reaches the transport",
      "openai:gpt-6-astra" not in _attempts, _attempts)
check("E2 the turn runs on the authorized default instead",
      used == "deepseek:deepseek-flash" and answer == "ok:deepseek:deepseek-flash", used)

print()
if FAILED:
    print("FAILED %d/%d: %s" % (len(FAILED), len(CHECKS), ", ".join(FAILED)))
    sys.exit(1)
print("OK %d/%d" % (len(CHECKS), len(CHECKS)))
