"""v654 — how a control applies, a readable Routing table, and a provider that
must prove it works.

Operator, on the Models panel:
  * "guarda che schifo mettilo affianco ad effort, il box medium etcetera"
    (Thinking effort rendered `enabled ☑effort` then a stray select below);
  * "quando aggiunge un provider deve fare il TEST in automatico; se non va deve
    dare messaggio OK che error con il motivo";
  * "guarda che schifo, routing è disordinatissima e non si capisce niente";
  * "perché scrivi active: se già è nel menu a tendina … elenca invece quelli che
    necessitano cliccare SAVE".

What this locks:
  A) thinking effort is ONE row (no bare `.hrow` with no gap);
  B) every control says HOW it applies — `live` (writes on change) vs `save`
     (needs the button) — and no picker repeats its own value on a second line;
  C) Routing renders as a role · model · pattern · fallbacks table, with the
     subagent row pointing at its owner instead of duplicating it;
  D) adding/saving a provider probes it (GET /models) and reports OK with the
     model count, or the reason it failed.

Stdlib only, deterministic, no browser, no network.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
PROV = open(os.path.join(REPO, "src", "longrun", "model", "providers.py"),
            encoding="utf-8").read()
API = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
           encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name +
          ((" :: " + str(detail)) if (detail and not ok) else ""))


def _fn(src, name, next_name):
    i = src.find(name)
    j = src.find(next_name, i + len(name)) if i >= 0 else -1
    return src[i:j] if i >= 0 and j > i else ""


MODELS = UI[UI.index('data-cat="models"'):UI.index('data-cat="subagents"')]
SECTION = _fn(UI, "function _setSectionEl(sec)", "function _setFieldEl")
ROUTING = _fn(UI, "function _setRoutingFields(box, sec)", "function _setFieldEl")
README = _fn(UI, "function _setReadField(root, f)", "async function saveSettingsSection")
SAVE_PROV = _fn(UI, "async function saveProvider()", "function _saveProviderDraft")
PROV_ROWS = _fn(UI, "async function loadProviders()", "function editProvider(p)")

# ---- A. thinking effort is ONE row -------------------------------------------
check("A1 effort sits next to its checkbox in one row",
      '<div class="u-df u-g12 u-aic u-fww">' in MODELS
      and 'id="reOn" type="checkbox" data-change="saveReasoning"' in MODELS
      and 'id="reEffort" data-change="saveReasoning"' in MODELS)
check("A2 the bare .hrow wrapper is gone from that card",
      '<div class="hrow">' not in MODELS)
check("A3 .hrow has a real gap, so generated fields never touch",
      ".hrow { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; }" in UI)

# ---- B. how a control applies ------------------------------------------------
check("B1 every instant picker carries the live chip",
      MODELS.count('class="set-chip live"') >= 5
      and 'title="applies the moment you pick a model — no save button"' in MODELS)
check("B2 a value is never repeated under its own picker",
      "active: <b" not in UI and "#emActive" not in UI
      and '$("researchActive")' not in UI)
check("B3 generated cards say they need the save button",
      'class="set-chip save" title="writes ' in SECTION)
check("B4 hand-written save cards are marked from the DOM they ship",
      "function _markApplyModes()" in UI
      and "button.config-save" in _fn(UI, "function _markApplyModes()", "function buildSettingsWin")
      and "_markApplyModes();" in _fn(UI, "function settingsCategory(name)", "function _markApplyModes"))
check("B5 the two words are explained once, in the window header",
      "sw-legend" in UI and "applies on change" in UI
      and "needs the save button" in UI)

# ---- C. routing is a table ---------------------------------------------------
check("C1 the routing section renders through its own row grammar",
      'if (sec.id === "routing") _setRoutingFields(box, sec);' in SECTION)
check("C2 the table names its four columns",
      '<span class="rt-hd">role</span>' in ROUTING
      and '<span class="rt-hd">model</span>' in ROUTING
      and '<span class="rt-hd">pattern</span>' in ROUTING
      and '<span class="rt-hd">fallbacks</span>' in ROUTING)
check("C3 a role with no fields did not die: subagent points at its owner",
      'roles\\.([^.]+)\\.([^.]+)' in ROUTING
      and "Settings ▸ Subagents" in ROUTING
      and "one value, one place" in ROUTING)
check("C4 fallbacks are one comma line, not a 3-row textarea",
      'inp.dataset.sep = ","' in ROUTING and "rows=\"3\"" not in ROUTING)
check("C5 the reader honours the one-line separator",
      "el.dataset.sep" in README and 'split(sep)' in README)
check("C6 the table is one grid with a real column template",
      "#swMain .rt-grid { display: grid;" in UI
      and "grid-template-columns: 96px minmax(0, 1.7fr) minmax(0, .9fr) minmax(0, 1.7fr);" in UI)
check("C7 every routing control has an id derived from its config path",
      'inp.id = "rt-" + f.path.replace(/\\./g, "-");' in ROUTING
      and 'inp.id = "rt-default-fallbacks";' in ROUTING)

# ---- D. a provider must prove it works --------------------------------------
check("D1 the backend probes the provider with one real GET /models",
      "def probe(spec, timeout=10):" in PROV and '+ "/models"' in PROV
      and "urllib.request.urlopen(req, timeout=timeout)" in PROV)
check("D2 the failure names the reason, not just a code",
      "def _probe_reason(code, body):" in PROV
      and "key rejected (HTTP %d)" in PROV
      and "no /models endpoint (HTTP 404)" in PROV
      and "cannot reach the host" in PROV)
check("D3 the route exists and answers 200 with the verdict",
      # a failed probe is a RESULT, not a bad request: 200 + {ok:false, error}
      # keeps the browser console clean.
      'if path == "/api/providers/test":' in API
      and "def provider_test(body):" in API
      and "_PROVIDERS.probe(body or {})" in API
      and 'return _r(handler, 200, provider_test(body))' in API)
check("D4 saving a provider tests it automatically",
      "await _provTestText(r.id)" in SAVE_PROV
      and '"saved: " + r.id + " · testing…"' in SAVE_PROV)
check("D5 OK carries the model count, FAIL carries the reason",
      'return "OK · " + (t.models || 0) + " models";' in UI
      and 'return "FAIL · " + ((t && t.error) || "no answer");' in UI)
check("D6 each saved provider can be re-tested from its row",
      'test.textContent = "test"' in PROV_ROWS and "await _provTestText(p.id)" in PROV_ROWS)

# ---- E. the probe itself, offline -------------------------------------------
sys.path.insert(0, os.path.join(REPO, "src"))
os.environ.setdefault("LONGRUN_DATA", os.path.join(REPO, ".agent", "trash", "v654-data"))
try:
    from longrun.model import providers as _p
    r = _p.probe("definitely-not-a-provider")
    check("E1 an unknown id is a clear failure, never an exception",
          r.get("ok") is False and "unknown provider" in str(r.get("error")), r)
    r2 = _p.probe({"id": "v654fresh"})
    check("E2 a new provider without base_url fails before any request",
          r2.get("ok") is False and "unknown provider" in str(r2.get("error")), r2)
    r3 = _p.probe({"id": "v654fresh2", "base_url": "https://example.invalid/v1",
                   "api_key_env": "V654_NO_SUCH_KEY"})
    check("E3 a missing key is reported as such (no network attempted)",
          r3.get("ok") is False and "missing key" in str(r3.get("error")), r3)
    check("E4 the reason mapper speaks human",
          _p._probe_reason(401, "") .startswith("key rejected")
          and _p._probe_reason(404, "").startswith("no /models endpoint")
          and _p._probe_reason(None, "timed out").startswith("cannot reach the host"))
except Exception as e:  # noqa: BLE001 — a broken import is the failure
    check("E5 probe imports and runs offline", False, repr(e))

print("\n---\nv654: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
