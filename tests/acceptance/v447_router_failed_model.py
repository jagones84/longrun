#!/usr/bin/env python3
"""v447 — routing must never select a FAILED router model (JAG-447r).

Observed live: a "Master" session delegated a repo-audit subagent and got
``{"ok": false, "error": "subagent timeout"}``. Root cause: the `subagent` role
pattern is `glm`, the router reported `glm-5.3-flash-iq2` as FAILED (exit_code 1),
`router_models()` discarded that signal, so `pick('subagent')` selected the broken
model and `ensure_model()` polled for up to MODEL_LOAD_TIMEOUT (900s) for a load
that could never happen — while the parent gave up after SUBAGENT_WAIT (180s).

This pins the fix:
  A) the roster exposes `failed`;
  B) `_match`/`pick` never return a failed model;
  C) `default_model()` skips failed models;
  D) `ensure_model()` fails FAST on a failed model (no poll, no load call).

Deterministic, no model, no network. Run: python3 tests/acceptance/v447_router_failed_model.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v447-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for d in ("cfg", "sessions"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import rllm, routing          # noqa: E402
import longrun.model.providers as providers      # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: the roster exposes the FAILED signal --------------------------------
DATA = {"data": [
    {"id": "glm-5.3-flash-iq2",
     "status": {"value": "unloaded", "exit_code": 1, "failed": True}},
    {"id": "nex-n25-mini-uncensored-q8", "status": {"value": "loaded"}},
    {"id": "qwen-3.8-27b-uncensored-q8",
     "status": {"value": "unloaded", "args": ["--ctx-size", "262144"]}},
]}
roster = rllm._parse_roster(DATA)
by = {m["alias"]: m for m in roster}
check("A1 a router-failed model is flagged failed",
      by["glm-5.3-flash-iq2"]["failed"] is True)
check("A2 a healthy model is not flagged failed",
      by["nex-n25-mini-uncensored-q8"]["failed"] is False)
check("A3 n_ctx is parsed from --ctx-size",
      by["qwen-3.8-27b-uncensored-q8"]["n_ctx"] == 262144)
check("A4 loaded reflects status.value", by["nex-n25-mini-uncensored-q8"]["loaded"] is True)

# ---- B: _match / pick never return a failed model ---------------------------
check("B1 _match skips a FAILED alias (returns None)",
      routing._match(["glm"], roster) is None)
check("B2 _match still finds a healthy alias",
      routing._match(["qwen"], roster) == "qwen-3.8-27b-uncensored-q8")
check("B3 _match prefers a LOADED alias",
      routing._match(["nex", "qwen"], roster) == "nex-n25-mini-uncensored-q8")
roster2 = roster + [{"alias": "glm-ok", "status": "unloaded", "loaded": False,
                     "failed": False, "n_ctx": 0}]
check("B4 a healthy glm alias is still selected when one exists",
      routing._match(["glm"], roster2) == "glm-ok")

routing.CONFIG_PATH = os.path.join(TMP, "routing.yaml")
routing.save_config({"roles": {"subagent": {"pattern": "glm", "fallbacks": []}},
                     "default_fallbacks": []})
routing._roster = lambda: roster
check("B5 pick('subagent') does NOT return the FAILED glm (returns None)",
      routing.pick("subagent") is None)

# ---- C: default_model skips failed -----------------------------------------
rllm.router_models = lambda: roster
providers.default_ref = lambda: ""            # force the roster path
check("C1 default_model skips a FAILED model and takes the loaded one",
      rllm.default_model() == "nex-n25-mini-uncensored-q8")
rllm.router_models = lambda: [by["glm-5.3-flash-iq2"]]
check("C2 default_model returns None when every model is FAILED",
      rllm.default_model() is None)

# ---- D: ensure_model fails FAST on a failed model ---------------------------
calls = {"load": 0}
rllm.model_loaded = lambda alias: (False, by["glm-5.3-flash-iq2"])
rllm._router_load = lambda *a, **k: calls.__setitem__("load", calls["load"] + 1)
t0 = time.time()
res = rllm.ensure_model("glm-5.3-flash-iq2", timeout=900)
dt = time.time() - t0
check("D1 ensure_model reports the FAILED model immediately",
      res.get("action") == "failed" and res.get("loaded") is False, res)
check("D2 ensure_model neither loads nor polls (fast fail)",
      calls["load"] == 0 and dt < 2.0, "load=%d dt=%.2f" % (calls["load"], dt))

print("---")
ok = sum(results)
print("\nv447: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)