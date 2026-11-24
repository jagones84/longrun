#!/usr/bin/env python3
"""v1297 — the rail's per-session saturation is measured against the SESSION's model.

Reported (operator, 2026-11-24): *"the context ring and number in the sessions do
not show correctly when the session is NOT selected; if I change session focus the
context in the OTHER session changes."*

Root cause (measured live): the rail rows are filled by the context BACKFILL
worker (`stores._ctx_backfill_loop`), which calls `httpapi.context_usage(sid)`
with **no model**. `context_usage` computed the budget with `context_budget(None)`,
which falls back to the model the LOCAL ROUTER happened to have LOADED — not the
session's own model. A session on `openrouter:z-ai/glm-5.3-flash` (1,044,480 tok)
therefore read `6.7%` (17651/262144, the local router window) in the rail while
the live meter read `1.7%` (17651/1044480). The ACTIVE row is painted from
`context_usage` (with the resolved model) and the others from the stored/backfilled
value, so the number JUMPED the moment focus moved.

Fix (JAG-258, applied to the backfill path): `context_usage` now resolves the
model with the SAME rule the live HTTP path already uses — ONE owner,
`resolve_ctx_model`: explicit > the session's own model > the default.

Stdlib-only, deterministic, no network, no model (windows + default are stubbed).

Run: python3 tests/acceptance/v1297_rail_ctx_uses_session_model.py
"""
import inspect
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1297-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_OFFLINE"] = "1"
for d in ("cfg", "data", "sessions", "edits", "runs"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import providers as P          # noqa: E402
from longrun.model import rllm                     # noqa: E402
from longrun.core import server                    # noqa: E402,F401 — breaks the cycle
from longrun.core import httpapi                   # noqa: E402
from longrun.memory import stores                  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail else ""))


WIDE, NARROW, DEF = "fake:wide", "fake:narrow", "fake:default"
WIN = {WIDE: 1048576, NARROW: 262144, DEF: 524288}

_orig = (P.context_length, rllm.ctx_limits.limit_set, httpapi.default_model)
try:
    # deterministic: declared windows, no flat budget, no router, no network
    P.context_length = lambda alias: WIN.get(alias or "", 0)
    rllm.ctx_limits.limit_set = lambda key: False   # force the model-aware branch
    httpapi.default_model = lambda: DEF

    server.save_session({"id": "rail1", "model": WIDE, "created": 1.0,
                         "messages": [{"role": "user", "content": "hello"}]})
    server.save_session({"id": "rail2", "created": 1.0,
                         "messages": [{"role": "user", "content": "hi"}]})

    # A — the rail/backfill call (NO model) measures against the SESSION's model
    u = httpapi.context_usage("rail1")
    check("A1 a model-less call resolves the session's own model",
          u.get("model") == WIDE, u.get("model"))
    check("A2 the budget is the session model's window (not the router's)",
          u.get("budget_tokens") == httpapi.context_budget(WIDE), u.get("budget_tokens"))
    check("A3 it is NOT the narrow window",
          u.get("budget_tokens") != httpapi.context_budget(NARROW), u.get("budget_tokens"))

    # B — the rail value equals the LIVE meter value for the same session, so the
    #     number cannot jump when focus moves away
    live = httpapi.context_usage("rail1", model=WIDE)
    check("B1 rail (no model) and live (explicit model) agree on budget + pct",
          (u.get("budget_tokens"), u.get("pct")) == (live.get("budget_tokens"), live.get("pct")),
          (u.get("budget_tokens"), u.get("pct"), live.get("budget_tokens"), live.get("pct")))

    # C — an explicit model still wins (the HTTP path already resolves one)
    u2 = httpapi.context_usage("rail1", model=NARROW)
    check("C1 explicit model wins over the session's own",
          u2.get("model") == NARROW
          and u2.get("budget_tokens") == httpapi.context_budget(NARROW),
          (u2.get("model"), u2.get("budget_tokens")))

    # D — a session with no model resolves the DEFAULT (the rule the meter uses)
    u3 = httpapi.context_usage("rail2")
    check("D1 a session with no model resolves the default",
          u3.get("model") == DEF, u3.get("model"))

    # E — the SOURCE is pinned: the backfill worker still calls it WITHOUT a model,
    #     which is exactly why the resolution above must live inside context_usage
    src = inspect.getsource(stores._ctx_backfill_loop)
    check("E1 the backfill worker calls context_usage(sid) with no model",
          "context_usage(sid)" in src, src[:160])
finally:
    P.context_length, rllm.ctx_limits.limit_set, httpapi.default_model = _orig

print("---")
ok = sum(results)
print("v1297: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
