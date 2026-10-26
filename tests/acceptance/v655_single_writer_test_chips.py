"""v655 — one writer per value, one test button per LLM, chips on every panel.

Operator, on the same Models panel:
  * "ma se i modelli li metto già on top del webui Models settings, a cosa serve
    routing?" — the answer is a CONTRACT, not prose: the table keeps pattern +
    fallbacks, and the two role models that already have a live picker above
    become read-only pointers, so no value has two writers;
  * "test button beside each llm in GUI in settings/models as the embedding
    (one) — don't duplicate code!" — one builder, one handler, three mounts;
  * "live e save li hai messi solo su Models settings e altrove? controlla
    ovunque" — the chips are derived from the DOM for every panel.

What this locks:
  A) routing: summarizer + longrun_agent model cells are read-only (disabled
     but still carrying data-path, so a save round-trips the value instead of
     wiping it); chat/agent keep their editable cells;
  B) probe_model: one REAL chat completion (max_tokens=1) on the ref, reusing
     the same reason mapper as the provider probe; POST /api/models/test;
  C) the UI: ONE test button builder shared by every LLM picker, mounted beside
     compaction / longrunAgent / research, next to the embedding test;
  D) live/save chips are derived from the DOM for EVERY panel, not only Models.

Stdlib only, deterministic, no browser, no network (the probe's offline paths
are tested: unknown ref, @chat, empty ref).
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


ROUTING = _fn(UI, "function _setRoutingFields(box, sec)", "function _setFieldEl")
MARK = _fn(UI, "function _markApplyModes()", "function buildSettingsWin")
BTN = _fn(UI, "function _llmTestBtn(getRef, out)", "function initLlmTestBtns")
INIT = _fn(UI, "function initLlmTestBtns()", "/* v654")

# ---- A. routing keeps ONE writer per value -----------------------------------
check("A1 the model of summarizer/longrun_agent is declared picker-owned",
      # the const lives above the table builder, so it is checked in the whole UI
      "const RT_PICKER_OWNED = {" in UI
      and 'summarizer: "set with the Compaction model picker above' in UI
      and 'longrun_agent: "set with the longrunAgent picker above' in UI)
check("A2 that cell is a DISABLED input that still carries data-path",
      # a bare span would make the save round-trip the value as EMPTY — the
      # disabled input keeps the value and is un-editable.
      "inp.disabled = true;" in ROUTING
      and 'inp.dataset.path = f.path;' in ROUTING
      and 'edit it there; this row keeps pattern + fallbacks' in ROUTING)
check("A3 chat/agent keep an editable model cell (only those two roles are read-only)",
      "key === \"model\" && RT_PICKER_OWNED[r.name]" in ROUTING)
check("A4 the backend still exposes the fields, so the save contract is unchanged",
      open(os.path.join(REPO, "src", "longrun", "core", "settings.py"),
           encoding="utf-8").read().count('roles.%s.model" % name') >= 1)

# ---- B. probe_model — one REAL chat completion -------------------------------
check("B1 probe_model does a real chat completion, max_tokens=1",
      "def probe_model(ref, timeout=25):" in PROV
      and '"max_tokens": 1' in PROV
      and 'messages": [{"role": "user", "content": "ping"}]' in PROV
      and 'base + "/chat/completions"' in PROV or 'endpoint(ref)' in PROV)
check("B2 the failure reasons come from the SAME mapper as the provider probe",
      "def probe_model(ref, timeout=25):" in PROV
      and PROV.count("def _probe_reason(code, body):") == 1
      and PROV.count("_probe_reason(") >= 3)
check("B3 offline paths answer, never raise",
      "unknown model: %s is not in any provider catalogue" in PROV
      and '"@chat follows the active session model' in PROV
      and '"no model selected"' in PROV)
check("B4 the route exists and answers 200 with the verdict",
      'if path == "/api/models/test":' in API
      and "def model_test(body):" in API
      and '_PROVIDERS.probe_model((body or {}).get("ref"))' in API)
check("B5 the probe proves the MODEL answers and reports the latency",
      "latency_ms" in PROV and "time.monotonic()" in PROV)

# ---- C. ONE test button builder, three mounts --------------------------------
check("C1 one builder, one handler — no duplicated wiring",
      "function _llmTestBtn(getRef, out)" in BTN
      and UI.count("function _llmTestBtn(") == 1
      and UI.count('api("POST", "/api/models/test"') == 1)
check("C2 the button is mounted beside compaction, longrunAgent and research",
      '["compactionModel", "longrunAgentModel", "researchModelSettings"]' in INIT
      and 'btn.dataset.llmTest = id' in INIT)
check("C3 the verdict line reads OK with the latency or the reason",
      "async function _modelTestText(ref)" in BTN
      and "function _probeVerdict(ok, okText, errText)" in BTN
      and BTN.count("_probeVerdict(") >= 3)   # v657: one verdict helper for model, provider, embedding probes
check("C4 the research picker has its own result line",
      'id="researchModelSettingsOut"' in UI)
check("C5 settingsCategory mounts the buttons once per render",
      "initLlmTestBtns();" in UI
      and "sel.parentNode.querySelector(\"[data-llm-test=\" + id + \"]\")" in INIT)

# ---- D. live/save chips on EVERY panel ---------------------------------------
check("D1 the chips are derived from the DOM, not from a second list",
      "document.querySelectorAll(\"#swMain .card\").forEach(card =>" in MARK
      and 'card.querySelector("button.config-save")' in MARK
      and 'card.querySelector("[data-change]")' in MARK)
check("D2 a card whose controls carry data-change (no save button) is `live`",
      "chip.className = \"set-chip \" + (save ? \"save\" : \"live\");" in MARK
      and 'applies the moment you change it — there is no save button' in MARK)
check("D3 _markApplyModes runs for every panel (end of settingsCategory)",
      "initLlmTestBtns();\n  _markApplyModes();" in UI)
check("D4 the hand-written Models chips are unchanged",
      'Compaction model <span class="set-chip live"' in UI
      and 'Thinking effort <span class="set-chip live"' in UI)

# ---- E. offline probe behaviour ----------------------------------------------
sys.path.insert(0, os.path.join(REPO, "src"))
os.environ.setdefault("LONGRUN_DATA", os.path.join(REPO, ".agent", "trash", "v655-data"))
try:
    from longrun.model import providers as _p
    r = _p.probe_model("")
    check("E2 an empty ref answers with a reason", r.get("ok") is False
          and "no model selected" in str(r.get("error")), r)
    r = _p.probe_model("@chat")
    check("E3 @chat is refused with a reason", r.get("ok") is False
          and "@chat" in str(r.get("error")), r)
    r = _p.probe_model("no-such-provider:no-such-model")
    check("E4 an unknown ref answers with a reason", r.get("ok") is False
          and "unknown model" in str(r.get("error")), r)
except Exception as e:  # noqa: BLE001
    check("E1 probe_model imports and runs offline", False, repr(e))

print("\n---\nv655: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
