#!/usr/bin/env python3
"""v854 — the context METER must not pay the memory re-ranker.

Operator report (2026-11-07): "the WebUI is very slow now, even expanding a team or
switching session". Profiled on the DGX (`.agent/trash/prof_switch.py`, 288-message
session): `context_usage` cost 435 ms and 508 ms of it was ONE HTTPS call to the
OpenRouter cross-encoder (`context_engine.retrieve` -> `rerank.rerank`, the shipped
`config/rerank.yaml` has `enabled: true`), and `context_items` cost 758 ms of which
603 ms was a SECOND identical call — because it calls `context_usage` to fill
`used_tokens` / `cached_tokens`. So EVERY session switch paid the paid re-ranker
TWICE for `compacted_tokens`, a field no client reads (it is assigned in
`httpapi.context_usage` and nowhere else).

What this pins:
  A) the meter (`context_usage`) and the panel (`context_items`) never call
     `context_engine.retrieve` — proven by arming it to explode;
  B) what the UI actually renders is unchanged: `tokens_used` is still the system
     prompt + the full stored transcript + the pending message, and `display`
     still describes it;
  C) the FEATURE is intact — a real turn build (`retrieve_memory=True`) still
     retrieves exactly once, so the fix narrowed the meter, not the harness.

Deterministic, no model, no network.

Run:  python3 tests/acceptance/v854_context_meter_no_rerank.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v854-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S  # noqa: E402
from longrun.model import context_engine as CE  # noqa: E402
from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}

os.makedirs(S.SESSIONS_DIR, exist_ok=True)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


sid = "t854"
S.save_session({"id": sid, "title": sid, "messages": [
    {"role": "user", "content": "please restart the service"},
    {"role": "assistant", "content": "restarting the longrun service now"},
    {"role": "user", "content": "and verify the new code is loaded"},
]})

# ---- arm the retrieval: any call is a defect for the meter ----
calls = []
_real_retrieve = CE.retrieve


def _armed(*a, **k):
    calls.append(a)
    raise AssertionError("retrieve() was called: %r %r" % (a, k))


CE.retrieve = _armed
try:
    try:
        u = S.context_usage(sid, "a pending question")
    except AssertionError as e:
        u = {"error": str(e)}
    check("A1 the meter does not retrieve", u.get("error") is None,
          str(u.get("error") or ""))
    try:
        ci = S.context_items(sid)
    except AssertionError as e:
        ci = {"error": str(e)}
    check("A2 the panel does not retrieve (it calls the meter)", ci.get("error") is None,
          str(ci.get("error") or ""))
    check("A3 not one retrieval call left in the meter path", calls == [],
          "calls=%d" % len(calls))
finally:
    CE.retrieve = _real_retrieve

# ---- B: the number the UI renders is the one the meter already defined ----
sess = S.load_session(sid) or {}
sysp = S._system_prompt(sess)
aug = "a pending question" + "\n\n" + S.state_block(session_id=sid)
want = (CE.count_tokens(sysp)
        + sum(CE.count_tokens(m.get("content", "")) for m in sess.get("messages", []))
        + CE.count_tokens(aug))
check("B1 tokens_used = system prompt + transcript + pending message",
      u.get("tokens_used") == want, "got=%s want=%s" % (u.get("tokens_used"), want))
check("B2 the display block still describes it",
      isinstance(u.get("display"), dict) and u["display"].get("state") in
      ("normal", "near", "over"), str(u.get("display")))
# The panel reads the meter with NO pending message (it describes a session, not a
# draft), so its own expectation is the same sum without the message.
want_ci = (CE.count_tokens(sysp)
           + sum(CE.count_tokens(m.get("content", "")) for m in sess.get("messages", []))
           + CE.count_tokens(S.state_block(session_id=sid)))
check("B3 the panel still ties to the meter",
      ci.get("used_tokens") == want_ci,
      "got=%s want=%s" % (ci.get("used_tokens"), want_ci))

# ---- C: the feature itself still retrieves, once, on a real turn build ----
CE.retrieve = _armed
try:
    try:
        CE.build("sys", [{"role": "user", "content": "restart the service"}],
                 "restart the service", retrieve_memory=True)
        n = len(calls)
    except AssertionError:
        n = len(calls)
finally:
    CE.retrieve = _real_retrieve
check("C1 a real turn build still retrieves, exactly once", n == 1, "calls=%d" % n)

print("")
print("%d/%d GREEN" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
