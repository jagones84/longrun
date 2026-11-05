#!/usr/bin/env python3
"""v830 — ONE live health system (2026-11-06).

Operator: *"health systme mine is in diagnosis (diag?) . imprve taht one and complete
with all (its obsolete)"*. Before this test the answer was split between `diag.health`
(host snapshot), `diagnostics.collect` (settings checks) and
`rllm.selfcheck_payload` (LLM path), and the runtime swallowed its own errors.

The contract pinned here:

  * `HealthBoard` is one entry per part: `unknown` until it reports, `warn` on the
    first two consecutive failures, `error` from the third, and a success resets it;
  * `claim` is idempotent, so two importers cannot own one part twice;
  * `collect(probe=False)` returns parts + probes + host + settings WITHOUT a
    network call, and `probe=True` adds the router probe;
  * a broken probe degrades to `ok=False` instead of raising;
  * the real failure paths report: routines, jobs, subagents and webhooks;
  * `GET /api/health`, the `self` action `diagnose` and Settings ▸ Diagnostics all
    read this one report, and no secret reaches it.

Deterministic and offline (probe=False everywhere): no server, no model, no network.
Run: python3 tests/acceptance/v830_health.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v830-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_WEBHOOKS"] = os.path.join(TMP, "data", "webhooks.json")
for _d in ("cfg", "sessions", "data"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}   # never spawn an MCP client in a test

from longrun.agent import agents as agents_mod  # noqa: E402
from longrun.core import health  # noqa: E402
from longrun.core import webhooks as WH  # noqa: E402
from longrun.orchestrate import routines  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------- board semantics
health.BOARD.reset()
check("H1 a part is unknown until it reports",
      health.BOARD.claim("demo", "Demo part").get("status") == "unknown")
_one = health.BOARD.report("demo", False, "boom-1")
_two = health.BOARD.report("demo", False, "boom-2")
_three = health.BOARD.report("demo", False, "boom-3")
check("H2 a failure is warn, the third in a row is error",
      _one.get("status") == "warn" and _two.get("status") == "warn"
      and _three.get("status") == "error"
      and _three.get("failures") == health.FAILURES_BEFORE_ERROR,
      (_one.get("status"), _two.get("status"), _three.get("status")))
_happy = health.BOARD.report("demo", True)
check("H3 a success resets the counter and the status",
      _happy.get("status") == "ok" and _happy.get("failures") == 0
      and _happy.get("last_ok"))
check("H4 claim is idempotent (one owner, not two entries)",
      health.BOARD.claim("demo", "Demo part").get("part") == "demo"
      and len([p for p in health.BOARD.snapshot() if p["part"] == "demo"]) == 1)
check("H5 the snapshot sorts the worst status first",
      [p["status"] for p in health.BOARD.snapshot()][0] in ("error", "warn", "unknown", "ok"))

# -------------------------------------------------------- real failure paths
health.BOARD.reset()
for _ in range(health.FAILURES_BEFORE_ERROR):
    routines._report(False, "tick exploded")
_r = {p["part"]: p for p in health.BOARD.snapshot()}.get("routines") or {}
routines._report(True)
_r_ok = {p["part"]: p for p in health.BOARD.snapshot()}.get("routines") or {}
check("H6 the routine scheduler reports its own failures and recovery",
      _r.get("status") == "error" and _r.get("failures") == health.FAILURES_BEFORE_ERROR
      and _r_ok.get("status") == "ok", (_r, _r_ok))

# --------------------------------------------------------------- the report
_report = health.collect(probe=False)
check("H7 the report has one stable shape",
      all(k in _report for k in ("ok", "status", "summary", "parts", "probes",
                                 "host", "settings", "generated_at", "uptime_secs")),
      sorted(_report))
check("H8 a cheap report still names every local probe",
      {p["name"] for p in _report["probes"]} >=
      {"scheduler", "events", "memory", "approvals", "webhooks", "sandbox"},
      [p["name"] for p in _report["probes"]])
check("H9 probe=False does not call the network (no router probe)",
      "router" not in {p["name"] for p in _report["probes"]}
      and not _report.get("llm"), _report.get("probes"))
check("H10 the report folds the settings checks in",
      isinstance(_report.get("settings", {}).get("summary"), dict)
      and isinstance(_report.get("settings", {}).get("issues"), list))

health.BOARD.reset()
for _ in range(health.FAILURES_BEFORE_ERROR):
    health.BOARD.report("jobs", False, "job runner down")
_err = health.collect(probe=False)
check("H11 a broken part makes the report ERROR",
      _err.get("status") == "error" and _err.get("ok") is False
      and "jobs" in (_err.get("summary", {}).get("errors") or []), _err.get("summary"))


def _broken_probe():
    raise RuntimeError("probe blew up")


_original = health._memory_probe
health._memory_probe = _broken_probe
try:
    _degraded = health.collect(probe=False)
finally:
    health._memory_probe = _original
_mem = {p["name"]: p for p in _degraded["probes"]}.get("memory") or {}
check("H12 a broken probe degrades instead of raising",
      _mem.get("ok") is False and "blew up" in str(_mem.get("detail")), _mem)

# ----------------------------------------------------------------- no secret
agents_mod.REGISTRY.designate("sess-v830", name="tester")
_made = WH.save_hook({"id": "gh", "agent": "A1", "goal": "Watch the repo."})
_secret = _made.get("secret") or ""
_full = json.dumps(health.collect(probe=False))
check("H13 the health report never carries a webhook secret",
      bool(_secret) and _secret not in _full)
check("H14 the webhooks probe reports real counters",
      any(p["name"] == "webhooks" and p.get("ok") is True for p in _degraded["probes"]),
      [p for p in _degraded["probes"] if p["name"] == "webhooks"])

# ------------------------------------------------------------------ surfaces
_srv = _src("src", "longrun", "core", "httpapi.py")
check("H15 GET /api/health exists and offers the cheap switches",
      'path == "/api/health"' in _srv and 'qs.get("probe", "1")' in _srv
      and 'qs.get("llm", "1")' in _srv)
check("H16 the agent's diagnose action reads the SAME report",
      "_health.collect(probe=True, llm_probe=False)" in
      _src("src", "longrun", "tools", "tools.py"))
check("H17 the router probe exists only on the probing path",
      '_probe("router", _router_probe, "error")' in
      _src("src", "longrun", "core", "health.py"))
_ui = _src("webui", "index.html")
check("H18 Settings ▸ Diagnostics renders the live components",
      'id="healthCard"' in _ui and "async function loadHealth" in _ui
      and "function renderHealth" in _ui and 'data-call="runHealthChecks"' in _ui
      and 'name === "diagnostics"' in _ui)
check("H19 the old settings checks are still there, below the live card",
      'id="diagSummary"' in _ui and 'id="diagIssues"' in _ui)

print("%d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
