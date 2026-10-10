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
      '<section data-insp="rules"' in HTML and 'data-insp="role"' not in HTML
      and "toggleInsp('rules')" in HTML, "")
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
check("A6 the panel is role-only (global/project rules moved to Settings)",
      '"global rules (all projects)"' not in HTML
      and '"project rules (this workspace)"' not in HTML, "")

# --- C: my duplicate-id regression + the interface polish --------------------
check("C1 the topbar element no longer shadows the inspector #ctxPct",
      'id="ctxPctTop"' in HTML and '<span id="ctxPct" class="ctxpct">' in HTML, "")
check("C2 the polish guards hold",
      "#nowbar[hidden] { display: none; }" in HTML and "a.ghost {" in HTML
      and "button:disabled {" in HTML and "#dotrail button:focus-visible" in HTML, "")
check("C3 the undefined border token and the forced-dark popup are gone",
      "var(--line2)" not in HTML and "#qmode { color-scheme: inherit; }" in HTML, "")

# --- B: REAL per-call cost ---------------------------------------------------
TMP = tempfile.mkdtemp(prefix="sf-v361-")
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(TMP, "costs")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
os.environ["LONGRUN_PRICES"] = json.dumps({
    "m/x": {"in": 2.0, "out": 8.0, "cache_read": 0.5, "request": 0.01}})
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
      r3 and r3["usd"] is None and r3["src"] is None, r3)
check("B4 the richer rate set parses (cache_read + request)",
      C.rates_for("m/x") == {"in": 2.0, "out": 8.0, "cache_read": 0.5,
                             "cache_write": None, "request": 0.01}, C.rates_for("m/x"))
check("B5 price_for still returns the (in, out) pair",
      C.price_for("m/x") == (2.0, 8.0), C.price_for("m/x"))
_fx = os.path.join(TMP, "openrouter_models.json")
with open(_fx, "w", encoding="utf-8") as f:
    json.dump({"data": [{"id": "fx/only", "pricing": {
        "prompt": "0.000002", "completion": "0.000008",
        "input_cache_read": "0.0000009", "request": "0.01"}}]}, f)
_ref = C.refresh_openrouter(url="file://" + _fx)
check("B6 the refresh caches the richer rate set (cache_read + request)",
      _ref.get("ok") and C.rates_for("fx/only") == {"in": 2.0, "out": 8.0, "cache_read": 0.9,
                                                    "cache_write": None, "request": 0.01},
      (_ref, C.rates_for("fx/only")))
check("B7 the UI marks an estimated row and names exact vs estimated",
      'r.src === "estimate" ? "\\u2248"' in HTML and '\\u00b7 exact' in HTML
      and "charged by the provider" in HTML, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

