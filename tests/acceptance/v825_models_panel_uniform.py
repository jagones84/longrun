#!/usr/bin/env python3
"""v825 — Settings ▸ Models is ONE uniform sheet (2026-11-05).

Why: the panel had grown three different shapes for the same job. The re-ranker —
a MODEL choice — was a bare text input inside the generic config form, rendered at
the very END of the panel (below Providers and Available models), while every other
model was a live picker at the top. The provider editor was its own "Add / edit
provider" section ABOVE the list it edits, which read as if the list could not be
edited at all. And each provider row was itself a `.card` inside the Providers
card, so eight providers looked like eight nested boxes.

What this pins:
  A  the panel ORDER and the uniform ANATOMY of the model pickers;
  B  the provider EDITOR lives inside the Providers card, above the list;
  C  the provider LIST is a sheet (divided rows, no nested cards);
  D  the wiring: the picker is live, one writer per value, a real test;
  E  the backend contract behind it (roster, one-writer, rerank probe).

Deterministic: temp data dir, no network, no model, no server.
Run: python3 tests/acceptance/v825_models_panel_uniform.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="lr-models-ui-v825-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
for _d in ("data", "cfg", "sessions"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
# The slice is the Models category ALONE: it ends where the next category starts.
SEC = HTML[HTML.index('data-cat="models"'):HTML.index('data-cat="subagents"')]

from longrun.core import settings as settings_mod       # noqa: E402
from longrun.model import providers, rerank            # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ------------------------------------------------------ A) order + anatomy ----
_pick = ["Thinking effort", "Compaction model", "longrunAgent · VEO automation model",
         "Research model · web → notebook", "Embedding · knowledge index",
         "Re-ranker model", ">Providers</h2>"]
_pos = [SEC.find(h) for h in _pick]
check("A1 the model pickers come first, in order, and end with Providers",
      all(p >= 0 for p in _pos) and _pos == sorted(_pos), str(_pos))
check("A2 the re-ranker is a live MODEL picker, styled like its siblings",
      'id="rerankModel" data-change="saveRerankModel"' in SEC
      and 'id="rerankResult"' in SEC
      and 'data-call="rerankTest"' in SEC
      and "Re-ranker model" in SEC
      and 'set-chip live' in SEC[SEC.index("Re-ranker model"):SEC.index("Re-ranker model") + 400])
check("A3 its knobs render INSIDE its own card, not at the end of the panel",
      '<div class="setFormsHost" data-for="rerank" data-merged="1"></div>' in SEC
      and SEC.index('id="rerankResult"') < SEC.index('data-for="rerank"')
      and SEC.index('data-for="rerank"') < SEC.index(">Providers</h2>"))
# The re-ranker is the SECOND stage of the retrieval the embedding feeds.
check("A4 the re-ranker picker sits next to the embedding picker",
      SEC.index("Embedding · knowledge index") < SEC.index("Re-ranker model"))
check("A5 the panel has no stray 'Retrieval re-ranker' heading any more",
      "Retrieval re-ranker" not in SEC)

# ------------------------------------------------------- B) provider editor ---
check("B1 the editor is INSIDE the Providers card (no section of its own)",
      '<h2>Add / edit provider</h2>' not in HTML
      and '<details id="provCard">' in SEC
      and '<details class="card" id="provCard">' not in HTML)
_prov_card = SEC[SEC.index('<h2 title="Where the models come from'):]
check("B2 it sits ABOVE the list it edits",
      _prov_card.index('id="provId"') < _prov_card.index('id="provList"'))
check("B3 the summary line + the fallback line share the card header",
      'class="prov-head"' in HTML and 'class="remaining prov-sum" id="provSummary"' in HTML
      and 'class="remaining u-mt4" id="modelsList"' in HTML)
check("B4 the retired 'Available models' heading is gone, its element is not",
      "<h2>Available models</h2>" not in HTML
      and 'id="modelsList"' in HTML and 'id="modelsList" class="card"' not in HTML)
check("B5 editing a row REVEALS the editor (a collapsed form looked inert)",
      "card.open = true;" in HTML and 'edit.title = "edit this provider' in HTML)
check("B6 every row action is named (no bare glyph)",
      'aria-label", "edit provider ' in HTML and 'aria-label", "remove provider ' in HTML)

# ------------------------------------------------------------ C) the sheet ----
_pf = HTML[HTML.index("async function loadProviders()"):HTML.index("function editProvider(p)")]
check("C1 rows are NOT cards any more (they were a card inside a card)",
      'row.className = "prov-row";' in _pf and 'row.className = "card";' not in _pf)
check("C2 one CSS rule divides them, and the first row has no top border",
      "#provList .prov-row {" in HTML and "#provList .prov-row:first-child { border-top: 0; }" in HTML)
check("C3 the model list of a row is indented under it",
      'modelsBox.className = "prov-models";' in HTML and "#provList .prov-models {" in HTML)
check("C4 the editor is not a card inside a card",
      "#provCard { border: 1px dashed" in HTML)

# --------------------------------------------------------------- D) wiring ---
check("D1 loadRerankModel takes the roster from the API, never from memory",
      "async function loadRerankModel()" in HTML
      and '(d && d.rerank_models)' in HTML
      and 'api("GET", "/api/providers")' in HTML)
check("D2 the current value is read from the settings section it writes",
      'find(x => x.id === "rerank")' in HTML)
check("D3 the picker writes the SECTION (one writer), and only the model",
      'api("POST", "/api/settings", { file: "rerank.yaml", values: { model: v } })' in HTML)
check("D4 the test is a REAL probe with the same verdict shape as its siblings",
      'api("POST", "/api/models/test", { ref })' in HTML
      and "t.ranked_first" in HTML and "_probeVerdict(" in HTML)
check("D5 the model row of the config card is a POINTER, not a second input",
      "if (f.owned) {" in HTML and 'setAttribute("data-owned", "1")' in HTML
      and 'hasAttribute("data-owned")' in HTML)
check("D6 the knobs are ONE sheet: no second header, no second save chip, no repeated value",
      # 2026-11-05: the form used to render its own card ("Re-ranker · tuning ·
      # config/rerank.yaml" + a SAVE chip + a read-only copy of the model ref) under
      # the picker that already said all three. A merged form is a divider + fields
      # + ONE save; the value the picker owns is never repeated.
      'card.className = merged ? "set-merged" : "card"' in HTML
      and '? \'<div class="hrow" data-fields></div>\'' in HTML
      and '"set-acts set-foot"' in HTML
      and "_refreshRerankPointer" not in HTML
      and "#swMain .set-merged .set-owned { display: none; }" in HTML)
check("D7 the picker is loaded when the Models panel opens",
      "loadRerankModel();   // 2026-11-05: re-ranker picker" in HTML)
check("D8 a panel can declare a second home for a section",
      "function _settingsSectionHost(panel, id)" in HTML
      and "'.setFormsHost[data-for=\"' + id + '\"]'" in HTML
      and "_settingsSectionHost(sec.panel, sec.id)" in HTML)
check("D9 the chat picker is untouched: no rerank entry in the model menu",
      "_modelsCache.forEach" in HTML and 'rerank_models' in HTML)

# -------------------------------------------------------------- E) backend ----
rr = providers.rerank_models()
check("E1 the roster is the `rerank: true` entries",
      len(rr) >= 1 and all({"ref", "id", "provider", "name", "available"} <= set(m) for m in rr), rr[:2])
_chat = {x["ref"] for p in providers.catalog()["providers"] for x in p["models"]}
check("E2 none of them leaks into the CHAT catalogue",
      not any(m["ref"] in _chat for m in rr), sorted(_chat & {m["ref"] for m in rr}))

_sec = next((s for s in settings_mod.view()["sections"] if s["id"] == "rerank"), None)
_mf = next((f for f in (_sec or {}).get("fields", []) if f["path"] == "model"), None)
check("E3 the rerank form lives on the models panel and its model is owned",
      bool(_sec) and _sec.get("panel") == "models" and bool(_mf) and _mf.get("owned") is True, _mf)

_before = dict(settings_mod._effective("rerank.yaml"))
_res = settings_mod.update({"file": "rerank.yaml", "values": {"model": "openrouter:cohere/rerank-5-fast"}})
_after = rerank.cfg(reload=True)
check("E4 a partial save writes the model WITHOUT dropping the keys it does not own",
      _res.get("ok") is True and _after.get("model") == "openrouter:cohere/rerank-5-fast"
      and all(_after.get(k) == _before.get(k)
              for k in ("top_n", "candidates", "enabled", "timeout_secs")),
      {k: (_before.get(k), _after.get(k)) for k in ("top_n", "candidates", "enabled")})

# The test button must reach /rerank, never /chat/completions (a cross-encoder
# cannot answer a chat call, so the probe would report a false FAIL).
_calls = {"rerank": 0, "urlopen": 0}
_orig_rerank = rerank.rerank
import urllib.request  # noqa: E402
_orig_open = urllib.request.urlopen


def _fake_rerank(query, documents, model=None, top_n=None, timeout=None, transport=None):
    _calls["rerank"] += 1
    return {"ok": True, "results": [{"index": 0, "score": 0.91}], "model": model or "?",
            "ms": 210, "cost_usd": None, "tokens": 12}


def _no_net(*a, **k):
    _calls["urlopen"] += 1
    raise AssertionError("a rerank ref must not go through the chat path")


rerank.rerank = _fake_rerank
urllib.request.urlopen = _no_net
try:
    _pr = providers.probe_model("openrouter:voyageai/rerank-2.5-lite")
    _unknown = providers.probe_model("no-such-provider:no-such-model")
finally:
    rerank.rerank = _orig_rerank
    urllib.request.urlopen = _orig_open
check("E5 probe_model routes a rerank ref to /rerank and reports the ranking",
      _pr.get("ok") is True and _pr.get("ranked_first") is True and _pr.get("latency_ms") == 210
      and _calls["rerank"] == 1 and _calls["urlopen"] == 0, (_pr, _calls))
check("E6 an unknown ref still fails without touching the network",
      _unknown.get("ok") is False and "unknown model" in str(_unknown.get("error"))
      and _calls["urlopen"] == 0, _unknown)

print("---")
_ok = sum(results)
print("%d/%d checks passed" % (_ok, len(results)))
sys.exit(0 if _ok == len(results) else 1)
