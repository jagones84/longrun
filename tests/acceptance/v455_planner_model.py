#!/usr/bin/env python3
"""v455 — a session pinned to a CLOUD model must not burn the LOCAL GPU (JAG-455).

Reported symptom: benchmark sessions whose model reads `deepseek-reasoner` while the
DGX GPU was busy. Root cause (one): the sync `/api/chat` path passed
`routing.pick("planner")` to the planner call UNCONDITIONALLY. `config/routing.yaml`
resolves the `planner` role by `pattern: qwen` -> the LOCAL DGX model, so every turn of
a cloud-pinned session still made one local-GPU model call. The turn's own model is now
authoritative and the role pattern is only the fallback.

Deterministic: no model, no network, no server.
Run: python3 tests/acceptance/v455_planner_model.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-455-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server    # noqa: E402 — must precede httpapi (circular import)
from longrun.core import httpapi  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


real_pick = httpapi.routing.pick
try:
    # ---- A: _planner_model — the turn's model wins ---------------------------
    httpapi.routing.pick = lambda role, preferred=None: "local-qwen-alias"
    try:
        got = httpapi._planner_model({"model": "openrouter:deepseek/deepseek-reasoner"},
                                     "openrouter:deepseek/deepseek-reasoner")
        check("A1 an explicit request model wins over the role pattern",
              got == "openrouter:deepseek/deepseek-reasoner", got)
        got = httpapi._planner_model({"model": "deepseek:deepseek-reasoner"}, None)
        check("A2 the session pin is used when the request has no model",
              got == "deepseek:deepseek-reasoner", got)
        got = httpapi._planner_model({"model": "deepseek:deepseek-reasoner"}, "explicit:model")
        check("A3 the explicit request model beats the session pin",
              got == "explicit:model", got)
        got = httpapi._planner_model({}, None)
        check("A4 no pin at all falls back to the planner ROLE pattern",
              got == "local-qwen-alias", got)
        got = httpapi._planner_model(None, None)
        check("A5 a missing session does not blow up", got == "local-qwen-alias", got)

        def _boom(role, preferred=None):
            raise RuntimeError("router unreachable")

        httpapi.routing.pick = _boom
        check("A6 an unroutable role returns None instead of raising",
              httpapi._planner_model({}, None) is None)
    finally:
        httpapi.routing.pick = real_pick

    # ---- B: the sync chat path is WIRED to the helper ------------------------
    src = _read("src", "longrun", "core", "httpapi.py")
    check("B1 the sync /api/chat planner call uses _planner_model",
          '_planner_model(sess, body.get("model"))' in src)
    check("B2 no bare routing.pick(\"planner\") is passed to start_run_graph",
          'sess["id"], routing.pick("planner")' not in src)
    check("B3 the helper documents the local-GPU root cause", "LOCAL DGX model" in src)
    check("B4 the sync chat TURN also honours the session pin, not just the planner",
          src.count('body.get("model") or sess.get("model")') >= 2)

    # ---- C: the benchmark arm pins EVERY routing role ------------------------
    la = _read("benchmarks", "longrun_adapter.py")
    check("C1 setup() pins all five roles to the arm's model",
          'roles = ("chat", "planner", "agent", "subagent", "summarizer")' in la
          and 'POST", "/api/routing"' in la)
    check("C2 the pin is conditional on the arm actually having a model",
          "if self.model:" in la and "{r: {\"model\": self.model} for r in roles}" in la)
    check("C3 teardown() restores the previous role pins (clears ours)",
          "self._routing = dict((rstatus or {}).get(\"config\") or {})" in la
          and 'roles[role] = {"model": entry.get("model") or ""}' in la)
    check("C4 the pin's stated purpose is an equal-conditions run",
          "burned the local" in la and "GPU for the planner call" in la)
finally:
    httpapi.routing.pick = real_pick

print("---")
okc = sum(results)
print("\nv455: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)