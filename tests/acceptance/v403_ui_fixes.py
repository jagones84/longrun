"""v403 — UI/config fixes (JAG-403 follow-up).

Stdlib-only, deterministic. Covers the four points the user raised:

  A) embedding models live in a PERSONAL config file (config/embedding.yaml),
     not a hardcoded Python list; add/remove persist in the overlay
  B) the knowledge sources list renders URLs as hyperlinks, opens files/images/
     PDFs, and is a bounded scrollable window
  C) NO hardcoded fallback chains (routing defaults + config + UI)
  D) thinking effort auto-saves and a non-thinking model that rejects
     `reasoning_effort` is retried WITHOUT the field (never crashes)
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="v403-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(tmp, "costs")
os.environ["LONGRUN_EMBEDDING_DIR"] = os.path.join(tmp, "embedding")
for d in ("cfg", "sessions", "graphs", "edits", "runs", "costs", "embedding"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if (detail and not ok) else ""))


HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

# ------------------------------------------------------------------ A) catalogue
from longrun.memory import embedcfg  # noqa: E402

cat_path = os.path.join(REPO, "config", "embedding.yaml")
check("A1 the catalogue lives in config/embedding.yaml", os.path.isfile(cat_path))
check("A2 the catalogue is loaded (>= 8 models from the file)", len(embedcfg.MODELS) >= 8,
      "n=%d" % len(embedcfg.MODELS))
check("A3 only a SMALL built-in fallback is hardcoded (the basics)",
      len(embedcfg.BASIC) <= 3, "basic=%d" % len(embedcfg.BASIC))

embedcfg.add_model({"id": "custom:v403/8b", "dim": 512, "price_per_mtok": 0.01,
                    "label": "V403 custom"})
check("A4 add_model persists into all_models()",
      any(m["id"] == "custom:v403/8b" for m in embedcfg.all_models()))
embedcfg.remove_model("custom:v403/8b")
check("A5 remove_model drops a personal model",
      not any(m["id"] == "custom:v403/8b" for m in embedcfg.all_models()))

embedcfg.remove_model("openai:text-embedding-3-small")
check("A6 remove_model hides a shipped model (personal override)",
      not any(m["id"] == "openai:text-embedding-3-small" for m in embedcfg.all_models()))
embedcfg.add_model({"id": "openai:text-embedding-3-small", "dim": 1536,
                    "price_per_mtok": 0.02, "label": "re-enabled"})
check("A7 add_model re-enables a hidden shipped model",
      any(m["id"] == "openai:text-embedding-3-small" for m in embedcfg.all_models()))

# ------------------------------------------------------------------ B) sources UI
check("B1 the sources list renders URLs as real hyperlinks",
      'target="_blank" rel="noopener noreferrer"' in HTML and "_kbSourceRow" in HTML)
check("B2 a file/text source opens via kbopen + _kbOpenRef",
      # v653 re-pin: the row keeps `kbopen` as one of its classes (now next to the
      # shared `.kb-main` layout class), so the wiring assertion is the attribute.
      'kbopen" data-ref="' in HTML and "function _kbOpenRef(" in HTML)
check("B3 images open in the image window and PDFs in the viewer",
      "_isImage(ref)" in HTML and "\\.pdf$/i.test(ref)" in HTML)
check("B4 the list is bounded by a row cap, not a nested scroll window",
      # v653 re-pin: the 320px inner window became the panel's single scroll
      # (operator: "vedi che schifo di disordine?"). The DOM is still bounded.
      "const LIMIT = 200" in HTML and ".kb-list { max-height" not in HTML)

# ------------------------------------------------------------------ C) no fallbacks
from longrun.model import routing  # noqa: E402

check("C1 routing defaults have NO hardcoded fallbacks",
      routing.DEFAULT_CONFIG.get("default_fallbacks") == []
      and all(not r.get("fallbacks") for r in routing.DEFAULT_CONFIG.get("roles", {}).values()))
_route_txt = open(os.path.join(REPO, "config", "routing.yaml"), encoding="utf-8").read()
check("C2 config/routing.yaml ships empty fallbacks",
      "default_fallbacks: []" in _route_txt and "fallbacks: []" in _route_txt
      and "- nex" not in _route_txt and "- qwen" not in _route_txt)
check("C3 the WebUI no longer prints an unexplained fallback chain",
      '· fallback: <b>' not in HTML and "no fallback chain" in HTML)

# ------------------------------------------------------------------ D) thinking effort
from longrun.model import rllm  # noqa: E402
from longrun.core import server  # noqa: E402

_orig_re = rllm._reasoning_effort
rllm._reasoning_effort = lambda: "high"
try:
    check("D1 thinking effort ON adds reasoning_effort (no regression)",
          rllm._completion_body("m", [], False).get("reasoning_effort") == "high")
    check("D2 no_reasoning=True omits the field even when effort is ON",
          "reasoning_effort" not in rllm._completion_body("m", [], False, no_reasoning=True))
finally:
    rllm._reasoning_effort = _orig_re

# D3: _router_stream accepts no_reasoning
import inspect  # noqa: E402
check("D3 _router_stream accepts a no_reasoning flag",
      "no_reasoning" in inspect.signature(rllm._router_stream).parameters)

# D4/D5: source wiring for the retry + auto-save UI
srv_src = open(os.path.join(REPO, "src", "longrun", "core", "server.py"), encoding="utf-8").read()
check("D4 stream_with_fallback retries the same model without reasoning_effort",
      "no_reasoning" in srv_src and "attempts = (False, True)" in srv_src)
check("D5 the WebUI auto-saves thinking effort (no manual button)",
      # JAG-425: onchange -> the delegated data-change binding.
      'id="reOn" type="checkbox" data-change="saveReasoning"' in HTML
      and 'id="reEffort" data-change="saveReasoning"' in HTML
      and "save thinking effort" not in HTML)

# D6: behavioural — a model rejecting reasoning_effort must NOT crash the turn.
_calls = []


def _fake_router(messages, model, on_delta, timeout=300, usage=None, guard=None,
                 cancel=None, no_reasoning=False, max_tokens=None):
    _calls.append(no_reasoning)
    if not no_reasoning:
        raise RuntimeError("400: reasoning_effort not supported by this model")
    return "ANSWER", ""


_orig_stream = server._router_stream
_orig_re2 = server._reasoning_effort
server._router_stream = _fake_router
server._reasoning_effort = lambda: "high"
try:
    answer, think, used = server.stream_with_fallback(
        [{"role": "user", "content": "hi"}], "m1", "chat", lambda ch, t: None)
    check("D6 a non-thinking model is retried without the field (never crashes)",
          answer == "ANSWER" and _calls == [False, True], "calls=%s" % _calls)
finally:
    server._router_stream = _orig_stream
    server._reasoning_effort = _orig_re2

# ------------------------------------------------------------------ E) persistence
# The thinking-effort setting must SURVIVE a restart: it is written to the sparse
# tools overlay and merged back on reload. (Regression: `reasoning` was missing
# from the overlay diff/merge key lists, so it silently reset on every restart.)
from longrun.tools import registry as REG  # noqa: E402

_orig_overlay = REG.OVERLAY_YAML
REG.OVERLAY_YAML = os.path.join(tmp, "tools.overlay.yaml")
try:
    REG.save_config({**REG.load_config(), "reasoning": {"enabled": True, "effort": "low"}})
    REG.load_config(reload=True)
    check("E1 thinking effort persists across a reload (survives restart)",
          (REG.load_config().get("reasoning") or {}).get("effort") == "low",
          str(REG.load_config().get("reasoning")))
    check("E2 the persisted effort is used by the request body builder",
          rllm._completion_body("m", [], False).get("reasoning_effort") == "low")
finally:
    REG.OVERLAY_YAML = _orig_overlay
    REG.load_config(reload=True)

# ------------------------------------------------------------------ F) UI polish
# F1: "clear whole knowledge base" ALWAYS asks (force), even with the skip flag set.
check("F1 the whole-KB clear always confirms (force=true)",
      'confirmDelete("Delete the WHOLE knowledge base' in HTML and ", true))) return;" in HTML
      and "function confirmDelete(message, force)" in HTML)
# F2: knowledge headings use the SAME style as every other settings tab.
check("F2 the settings h2 selector is descendant (wrappers don't break it)",
      "#settingsWin .sw-main .sw-cat h2 {" in HTML
      and "#settingsWin .sw-main .sw-cat > h2" not in HTML)
# F3: one merged research bar with an auto/manual checkbox.
check("F3 discover + research merged into ONE topic bar + auto checkbox",
      'id="kbDiscoverQ"' in HTML and 'id="kbAutoMode"' in HTML
      and "function kbResearchGo(" in HTML and 'id="researchQ"' not in HTML)
check("F3b the auto options are revealed only in auto mode",
      'id="kbAutoOpts" hidden' in HTML and "function kbResearchMode(" in HTML)
# F4: the Search card sits right below "Knowledge · global".
check("F4 Search is above Notebooks in the markup order",
      # v653 re-pin: the heading is "Search" now (the tooltip says what it searches;
      # "Search knowledge" inside the Knowledge panel repeated the panel name).
      0 <= HTML.index('>Search</h2>') < HTML.index('<details class="card" id="kbNbBox">'))
# F5: a skill opens in the EDITOR (not a separate modal).
check("F5 skills open in the file editor",
      "function openSkillInEditor(" in HTML and "openInEditor(d.abspath" in HTML
      and "skillView" not in HTML and "closeSkillView" not in HTML)
_skl = open(os.path.join(REPO, "src", "longrun", "memory", "skills.py"), encoding="utf-8").read()
check("F5b the skills API exposes an absolute path for the editor",
      '"abspath": sp' in _skl)
# F6: knowledge search results are clickable (URLs open in a tab, files in the editor).
check("F6 knowledge search results are wired to _kbOpenRef",
      'class="ctxitem kbopen"' in HTML and 'box.querySelectorAll(".kbopen")' in HTML)
# F7: the files list is clickable + bounded like the sources list.
check("F7 the notebook files list is clickable + bounded",
      # v653 re-pin: same row grammar as a source row (kb-main kbopen) and the DOM
      # is bounded by the row cap, not by a second scroll window.
      'class="kb-main kbopen" href="#" data-ref="\' + _attr(f.path)' in HTML
      and "const LIMIT = 200" in HTML)

print("---")
ok = sum(results)
print("%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)