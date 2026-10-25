#!/usr/bin/env python3
"""v361 — one complete Rules panel, REAL per-call cost, UI polish (JAG-361).

  A) the side inspector has ONE "Rules" section (the old Role-only pane is gone)
     that lists EVERY prompt source with its real path and saves it in place;
  B) the cost ledger uses the provider's OWN charge when it reports one (EXACT,
     `src: "provider"`) and otherwise prices the real token counts with the full
     rate set — cache-read rate for cached tokens + the fixed per-request fee;
  C) my duplicate `#ctxPct` id is fixed (the topbar uses `#ctxPctTop`, so the
     inspector meter works again) and the interface-polish guards hold.

Run: python3 tests/acceptance/v361_rules_cost_polish.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()

results = []


def check(name, cond, extra=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(extra)) if extra else ""))


# --- A: ONE complete Rules panel --------------------------------------------
check("A1 the inspector Rules section replaces the Role-only pane",
      # JAG-425: the toggle moved from an inline onclick to a delegated data-call attr.
      '<section data-insp="rules"' in HTML and 'data-insp="role"' not in HTML
      and ("toggleInsp('rules')" in HTML
           or 'data-call="toggleInsp" data-args=\'["rules"]\'' in HTML), "")
check("A2 it lists the per-session role it can edit",
      'id="rulesList"' in HTML and "function loadRulesPanel" in HTML
      and '"session role"' in HTML, "")
check("A3 every row shows the real path + a save handler",
      '"rpath"' in HTML and "function _rulesRow" in HTML and "function saveRuleSource" in HTML, "")
check("A4 saving writes the right backend (roles vs rules) for the scope",
      'api("POST", "/api/roles", { session: sessionId, text: text })' in HTML
      and 'api("POST", "/api/rules", { scope: kind, content: text, session: sessionId })' in HTML, "")
check("A5 the panel reads both APIs and keeps loadRole as an alias",
      'api("GET", "/api/rules?" + params.toString())' in HTML
      and 'api("GET", "/api/roles?session="' in HTML
      and "async function loadRole() { return loadRulesPanel(); }" in HTML, "")
_rules_loader = HTML.split("async function loadRulesPanel() {", 1)[1].split(
    "\nfunction _rulesRow", 1)[0]
check("A5b the Rules request never puts the browser token in its URL",
      'params.set("token", TOKEN)' not in _rules_loader
      and 'params.set("session", sessionId)' in _rules_loader, "")
check("A6 the panel is role-only (global/project rules moved to Settings)",
      '"global rules (all projects)"' not in HTML
      and '"project rules (this workspace)"' not in HTML, "")
check("A7 the session inspector identifies ROLE.md and links global rules to Settings",
      'data-args=\'["rules"]\'>Rules<' in HTML
      and "ROLE.md" in HTML
      and "Global_rules.md" in HTML, "")
check("A8 global and project Global_rules.md / Project_rules.md editors remain in Settings",
      'data-cat="rules"' in HTML and 'id="rulesGlobalText"' in HTML
      and 'id="rulesProjectText"' in HTML, "")
check("A9 Settings includes a diagnostics category and panel",
      '["diagnostics", "Diagnostics"]' in HTML
      and 'data-cat="diagnostics"' in HTML
      and 'api("GET", "/api/diagnostics' in HTML, "")
check("A10 the header diagnostics control exposes its issue summary",
      'id="settingsDiagBadge"' in HTML and 'aria-label="settings diagnostics"' in HTML
      and 'function renderDiagnostics' in HTML, "")
check("A11 diagnostics presents unauthorized responses as an auth issue",
      'const unauthorized = /401|unauthorized/i.test(String(report.error))' in HTML
      and '"auth.browser_unauthorized"' in HTML
      and "Longrun rejected this browser token" in HTML, "")

# --- C: my duplicate-id regression + the interface polish --------------------
check("C1 the topbar element no longer shadows the inspector #ctxPct",
      'id="ctxPctTop"' in HTML and '<span id="ctxPct" class="ctxpct">' in HTML, "")
check("C2 the polish guards hold",
      "#nowbar[hidden] { display: none; }" in HTML and "a.ghost {" in HTML
      and "button:disabled {" in HTML and "#dotrail button:focus-visible" in HTML, "")
check("C3 the undefined border token and the forced-dark popup are gone",
      "var(--line2)" not in HTML and "#qmode { color-scheme: inherit; }" in HTML, "")
check("C4 chat dots exclude delegated user turns",
      '.msg.user:not(.deleg)' in HTML and "only operator-authored prompts get dots" in HTML, "")
_dot_rail = HTML.split("function buildDotRail()")[1].split("function _dotRailCur()")[0]
check("C5 bookmark click aligns its exact prompt to the chat top",
      '_alignChatNodeTop(log, m);' in _dot_rail and "m.scrollIntoView" not in _dot_rail)

# --- B: REAL per-call cost ---------------------------------------------------
TMP = tempfile.mkdtemp(prefix="sf-v361-")
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(TMP, "costs")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
os.environ["LONGRUN_PRICES"] = json.dumps({
    "m/x": {"in": 2.0, "out": 8.0, "cache_read": 0.5, "request": 0.01},
    "mistral:mistralai/shared-name": {"in": 7.0, "out": 14.0}})
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import costs as C  # noqa: E402

S = "v361"
# 1) the provider reports the charge itself -> EXACT, used verbatim
r1 = C.record(S, "m/x", {"prompt_tokens": 1000, "completion_tokens": 500, "cost": 0.4242})
check("B1 a provider-reported cost is used verbatim (exact)",
      r1 and r1["usd"] == 0.4242 and r1["src"] == "provider", r1)
# 2) no provider cost -> priced from the real tokens with the FULL rate set
r2 = C.record(S, "m/x", {"prompt_tokens": 2000, "completion_tokens": 1000,
                         "prompt_tokens_details": {"cached_tokens": 1000}})
check("B2 estimated from tokens: cache-read rate + output rate + request fee",
      r2 and r2["usd"] == 0.0205 and r2["src"] == "estimate", r2)
# 3) an unpriced model stays unknown (never a fake zero)
r3 = C.record(S, "nowhere/unknown", {"prompt_tokens": 10, "completion_tokens": 10})
check("B3 an unpriced model is usd null / src null",
      r3 and r3["usd"] is None and r3["src"] is None
      and r3["cached"] == 0 and r3["tokens_cached"] == 1000, r3)
check("B4 the richer rate set parses (cache_read + request)",
      C.rates_for("m/x") == {"in": 2.0, "out": 8.0, "cache_read": 0.5,
                             "cache_write": None, "request": 0.01}, C.rates_for("m/x"))
check("B5 price_for still returns the (in, out) pair",
      C.price_for("m/x") == (2.0, 8.0), C.price_for("m/x"))
_summary = C.summary(S)
check("B6 session summary counts exact, estimated, and unpriced calls separately",
      _summary.get("provider_calls") == 1
      and _summary.get("estimated_calls") == 1
      and _summary.get("unknown_calls") == 1, _summary)
_fx = os.path.join(TMP, "openrouter_models.json")
with open(_fx, "w", encoding="utf-8") as f:
    json.dump({"data": [
        {"id": "fx/only", "pricing": {
            "prompt": "0.000002", "completion": "0.000008",
            "input_cache_read": "0.0000009", "request": "0.01"}},
        {"id": "mistralai/shared-name", "pricing": {
            "prompt": "0.000002", "completion": "0.000008"}}
    ]}, f)
_ref = C.refresh_openrouter(url=Path(_fx).as_uri())
check("B7 the refresh caches the richer rate set (cache_read + request)",
      _ref.get("ok") and C.rates_for("fx/only") == {"in": 2.0, "out": 8.0, "cache_read": 0.9,
                                                    "cache_write": None, "request": 0.01},
      (_ref, C.rates_for("fx/only")))
check("B8 provider-specific rates never inherit a same-name OpenRouter price",
      C.rates_for("openrouter:mistralai/shared-name") == {
          "in": 2.0, "out": 8.0, "cache_read": None, "cache_write": None, "request": None}
      and C.rates_for("mistral:mistralai/shared-name") == {
          "in": 7.0, "out": 14.0, "cache_read": None, "cache_write": None, "request": None}
      and C.rates_for("openai:mistralai/shared-name") is None,
      (C.rates_for("openrouter:mistralai/shared-name"),
       C.rates_for("mistral:mistralai/shared-name"),
       C.rates_for("openai:mistralai/shared-name")))
check("B9 official direct-provider rates are stored under exact provider/model refs",
      C.rates_for("deepseek:deepseek-flash") == {
          "in": 0.3, "out": 1.2, "cache_read": 0.006,
          "cache_write": None, "request": None}
      and C.rates_for("deepseek:deepseek-reasoner") is None
      and C.rates_for("deepseek:deepseek-chat") is None
      and C.rates_for("mistral:mistral-large-4-0") == {
          "in": 1.36, "out": 4.18, "cache_read": 0.14,
          "cache_write": None, "request": None}
      and C.rates_for("anthropic:claude-opus-4-8") == {
          "in": 5.0, "out": 25.0, "cache_read": 0.5,
          "cache_write": 10.0, "request": None}
      and C.rates_for("google:gemini-3.1-pro-preview") == {
          "in": 4.0, "out": 18.0, "cache_read": 0.4,
          "cache_write": None, "request": None}
      and C.rates_for("openai:gpt-6-astra") is None
      and C.rates_for("anthropic:claude-fable-5.1") is None
      and C.rates_for("google:gemini-3.8-flash") is None,
      (C.rates_for("deepseek:deepseek-flash"),
       C.rates_for("deepseek:deepseek-reasoner"),
       C.rates_for("deepseek:deepseek-chat"),
       C.rates_for("mistral:mistral-large-4-0"),
       C.rates_for("anthropic:claude-opus-4-8"),
       C.rates_for("google:gemini-3.1-pro-preview"),
       C.rates_for("openai:gpt-6-astra"),
       C.rates_for("anthropic:claude-fable-5.1"),
       C.rates_for("google:gemini-3.8-flash")))
check("B10 the Cost panel labels estimates and displays cached input usage",
      'data-args=\'["cost"]\'' in HTML and ">Cost · harness only" in HTML
      # v633: the peak/off-peak rule moved from a three-clause line in the panel body
      # to the section-header tooltip (the panel itself is data, not an essay).
      and "peak/off-peak by UTC" in HTML
      and 'id="costCached"' in HTML
      and 'c.provider_calls' in HTML and 'c.estimated_calls' in HTML
      and 'c.cached' in HTML
      and 'Number(c.priced_calls || 0) > 0' in HTML
      and 'call.tokens_cached' in HTML, "")
check("B11 the UI marks an estimated row and names exact vs estimated",
      'r.src === "estimate" ? "\\u2248"' in HTML
      and 'c.provider_calls + " exact"' in HTML
      and "charged by the provider" in HTML, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
