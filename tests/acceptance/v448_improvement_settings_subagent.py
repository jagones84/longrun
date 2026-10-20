#!/usr/bin/env python3
"""v448 — improvement panel moved to Settings (and shows what changed) + the
subagent LLM is config-driven (no hardcoded model) with a real failover chain.

Two fixes from operator feedback:

  0) the old Improvement inspector panel was global-but-tucked-away and only
     showed counts; it did not answer "what exactly did the harness change —
     which files, which memory, which prompts?". It now lives in Settings >
     Improvement with collapsible sections and the AUTO-WRITTEN memory records.

  1) the subagent LLM was resolved by a local pattern (`glm`) that pointed at a
     router model flagged FAILED; the model came from config, but there was no
     way to pin a cloud model from the WebUI and no failover. The subagent role
     is now an explicit `openrouter:...` model + a literal `provider:model`
     fallback, everything in config/routing.yaml, editable in Settings > Models.

Deterministic, no model, no server. Run: python3 tests/acceptance/v448_*.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v448-")
for k, v in {
    "LONGRUN_CONFIG_DIR": os.path.join(TMP, "cfg"),
    "LONGRUN_DATA_DIR": os.path.join(TMP, "data"),
    "LONGRUN_SESSIONS_DIR": os.path.join(TMP, "sessions"),
    "LONGRUN_DB": os.path.join(TMP, "events.db"),
    "LONGRUN_GRAPH_DIR": os.path.join(TMP, "graphs"),
    "LONGRUN_EDITS_DIR": os.path.join(TMP, "edits"),
    "LONGRUN_RUNS_DIR": os.path.join(TMP, "runs"),
    "LONGRUN_REQUIRE_HELDOUT": "0",
}.items():
    os.environ[k] = v
for d in ("cfg", "data", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import routing, providers   # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A) providers config lists the requested cloud models -----------------
openrouter_models = []
for p in providers.load().get("providers", []):
    if p.get("id") == "openrouter":
        openrouter_models = [m.get("id") if isinstance(m, dict) else m
                             for m in p.get("models", [])]
check("A1 providers lists z-ai/glm-5.3-flash:batch",
      "z-ai/glm-5.3-flash:batch" in openrouter_models)
check("A2 providers lists meta/muse-spark-1.3-contributor",
      "meta/muse-spark-1.3-contributor" in openrouter_models)
check("A3 the synchronous z-ai/glm-5.3-flash is present",
      "z-ai/glm-5.3-flash" in openrouter_models)

# ---- B) routing config: subagent role is explicit, nothing hardcoded ------
# JAG-451: the operator CHANGES the subagent model in Settings ▸ Subagents (it
# writes routing.yaml ▸ roles.subagent), so assert the CONTRACT — the resolved
# model mirrors the config and the chain preserves the configured fallbacks — NOT
# a specific model id (a hardcoded id here would fail every legitimate edit).
import yaml  # noqa: E402
_rr = yaml.safe_load(open(os.path.join(REPO, "config", "routing.yaml"), encoding="utf-8")) or {}
_sub = ((_rr.get("roles") or {}).get("subagent") or {})
chain = routing.model_chain("subagent")
rm = routing.role_model("subagent")
check("B1 role_model('subagent') mirrors config/routing.yaml (explicit, not a pattern)",
      bool(rm) and ":" in rm and (not _sub.get("model") or rm == _sub.get("model")),
      {"role_model": rm, "config": _sub.get("model")})
check("B2 the resolved chain leads with that model",
      bool(chain) and chain[0] == rm, chain)
check("B3 every configured fallback is preserved in the chain",
      all(f in chain for f in (_sub.get("fallbacks") or [])),
      {"chain": chain, "fallbacks": _sub.get("fallbacks")})

# ---- C) the spawn/loop wire the failover chain ----------------------------
sa = open(os.path.join(REPO, "src", "longrun", "agent", "subagent.py"),
          encoding="utf-8").read()
av = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
          encoding="utf-8").read()
check("C1 spawn honours the subagent role model (kept)",
      'routing.role_model("subagent") or routing.pick("subagent")' in sa)
check("C2 spawn computes the config failover chain",
      "model_chain" in sa and "fallbacks =" in sa)
check("C3 agent_run_v2 accepts fallbacks", "fallbacks=None" in av)
check("C4 agent_run_v2 walks the candidate chain on failure",
      "candidates" in av and "model.failover" in av)

# ---- D) WebUI: subagent model is settable in Settings > Subagents ----------
# v505: the picker was duplicated in Models and Subagents. Subagents is now the
# single owner (one source of truth for roles.subagent).
idx = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("D1 Settings > Subagents has a subagent model picker",
      'id="subModel"' in idx and 'data-cat="subagents"' in idx)
check("D2 the subagent picker is listed in the settings nav",
      '["subagents", "Subagents"]' in idx)

# ---- E) WebUI: improvement moved from inspector to Settings ---------------
check("E1 the improvement panel is a Settings category",
      'data-cat="improvement"' in idx and "impRecords" in idx)
check("E2 the old inspector 'improvement' section is gone",
      'data-insp="improvement"' not in idx)
check("E3 proposals/lessons are collapsible (details/summary)",
      "imp-s" in idx and "<details" in idx)
check("E4 the panel renders the auto-written memory path",
      "impRecords" in idx)

print("---")
ok = sum(results)
print("\nv448: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)