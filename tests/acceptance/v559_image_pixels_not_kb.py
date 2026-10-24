#!/usr/bin/env python3
"""v559 — JAG-565: images go to the model as PIXELS, not through the KB.

Operator report (2026-10-24): two attached images made the agent invent an OCR
story, then fail twice on `knowledge.read_source`. Root causes pinned here:

  A) `deepseek:deepseek-flash` IS vision-capable (verified live: a 64x64 solid
     red PNG came back as "red") but the catalogue had no flag, so the harness
     told the model it could not see.
  B) an uploaded IMAGE was auto-routed into the session knowledge base, adding
     one noisy chunk and a false "read it with knowledge.search" instruction.
  C) when the model genuinely cannot see, the harness note must forbid a KB/OCR
     detour instead of only saying "switch model".
  D) `read_source` only matched the absolute path/id, while `search` shows the
     title/filename — the agent's honest follow-up failed.
  E) the WebUI must warn BEFORE sending an image to a text-only model.

Deterministic: no model, server, network or browser.
"""
import base64
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="v559-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_CODEBASE_DIR"] = os.path.join(tmp, "codebase")
os.environ["LONGRUN_KNOWLEDGE_DIR"] = os.path.join(tmp, "knowledge")
os.environ["LONGRUN_EMBEDDING_DIR"] = os.path.join(tmp, "embedding")
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(tmp, "costs")
for d in ("data", "cfg", "sessions", "codebase", "knowledge", "embedding", "costs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (("  :: " + str(detail)) if detail and not ok else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = read("webui", "index.html")
API = read("src", "longrun", "core", "api_v02.py")
AGENT = read("src", "longrun", "agent", "agent.py")
PROVIDERS_YAML = read("config", "providers.yaml")

# ------------------------------------------------------- A: deepseek vision --
from longrun.model import providers as P  # noqa: E402
from longrun.model import rllm  # noqa: E402

_line = [ln for ln in PROVIDERS_YAML.splitlines() if "id: deepseek-flash" in ln]
check("A1 deepseek-flash is declared vision-capable",
      bool(_line) and "vision: true" in _line[0], _line)
_hit = P.resolve("deepseek:deepseek-flash")
check("A2 the provider resolver finds the declared model",
      _hit is not None and _hit[1] == "deepseek-flash", _hit)
check("A3 model_supports_vision trusts the catalogue flag (no network needed)",
      rllm.model_supports_vision("deepseek:deepseek-flash") is True)

# ------------------------------------------------- B: attach returns visual --
from longrun.core import api_v02 as A  # noqa: E402
from longrun.memory import docio  # noqa: E402

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_r = A.attach_save(PNG, name="shot.png", session="s1")
check("B1 an image is NOT knowledge-indexable", _r.get("indexable") is False, _r)
check("B2 an image is flagged visual", _r.get("visual") is True, _r)
_t = A.attach_save(b"# note\nhello", name="note.md", session="s1")
check("B3 a document still reports indexable + not visual",
      _t.get("indexable") is True and _t.get("visual") is False, _t)
check("B4 IMAGE_EXT covers the formats the composer accepts",
      {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"} <= set(docio.IMAGE_EXT))
check("B5 attach_save derives `visual` from docio.IMAGE_EXT and gates indexable",
      'in _docio.IMAGE_EXT' in API and "and not visual" in API)

# ------------------------------------------- C: pixels, or an honest note ----
from longrun.agent import agent  # noqa: E402

_img = os.path.join(tmp, "shot.png")
with open(_img, "wb") as f:
    f.write(PNG)
_msgs = [{"role": "user", "content": "- file: %s\n\ndescribe this" % _img}]
_orig_vision = agent.model_supports_vision
try:
    agent.model_supports_vision = lambda _m: True
    _out = agent._inject_vision_blocks(_msgs, "deepseek:deepseek-flash")
    _content = _out[-1].get("content")
    check("C1 a vision model receives an image_url data block",
          isinstance(_content, list) and any(
              b.get("type") == "image_url" and str(b.get("image_url", {}).get("url", "")).startswith("data:image/")
              for b in _content), _content)
    check("C2 the original message list is not mutated",
          isinstance(_msgs[-1].get("content"), str))

    agent.model_supports_vision = lambda _m: False
    _out = agent._inject_vision_blocks(_msgs, "text:only")
    _txt = _out[-1].get("content")
    check("C3 a text-only model gets an explicit cannot-see note",
          isinstance(_txt, str) and "You CANNOT see these images" in _txt, _txt)
    check("C4 the note forbids the knowledge-base/OCR detour",
          "Do NOT search the knowledge base" in AGENT and "OCR" in AGENT)
finally:
    agent.model_supports_vision = _orig_vision

# ------------------------------------------------ D: read_source by title ----
from longrun.memory import knowledge as K  # noqa: E402

_seed = K.add_source_text("default", "https://example.com/costs-panel",
                          "The cost panel reports attempts, failures and latency.",
                          title="shot.png")
_nb = _seed.get("notebook") or "default"
_by_title = K.read_source("shot.png", notebook=_nb)
check("D1 read_source resolves a source by its TITLE",
      _by_title.get("ok") is True, _by_title)
_seed2 = K.add_source_text(_nb, "/tmp/imports/image-1792836976.png",
                           "A screenshot of the WebUI terminal and feed.",
                           title="screenshot-one")
_by_base = K.read_source("image-1792836976.png", notebook=_nb)
check("D2 read_source resolves a source by the BASENAME of its path",
      _by_base.get("ok") is True, _by_base)
_missing = K.read_source("definitely-not-there.png", notebook=_nb)
check("D3 an unknown ref still fails honestly",
      _missing.get("ok") is False and "not found" in str(_missing.get("error")), _missing)

# --------------------------------------------------------- E: WebUI wiring --
check("E1 the catalogue exposes the declared vision flag",
      '"vision": bool(m.get("vision"))' in read("src", "longrun", "model", "providers.py"))
check("E2 the model cache carries vision / the UI has a capability helper",
      "loaded: !!m.loaded, vision: m.vision" in HTML and "function _modelVision(ref)" in HTML)
check("E3 attaching an image warns when the pinned model cannot see",
      "_vision === false" in HTML and "this model cannot see images" in HTML)
check("E4 an image attachment is branded visual in the composer",
      "visual: !!r.visual" in HTML)
check("E5 the attachment preamble sends images to pixels, never to the KB",
      "IMAGE attachment" in HTML and "Do NOT search the knowledge base for these images" in HTML)
check("E6 images are excluded from the binary-document knowledge hint",
      r"/\.(pdf|docx?|odt|rtf|pptx|xlsx|epub)\b/i.test(a.label" in HTML)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
