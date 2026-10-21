#!/usr/bin/env python3
"""v490 — external sources: every file type, real URLs, hybrid retrieval (JAG-490).

Audit found four broken paths in the knowledge pipeline:

  1. a URL to a PDF/image was decoded as UTF-8 text -> the KB indexed "%PDF-1.5…";
  2. Content-Encoding (gzip) was ignored -> compressed bytes were indexed;
  3. a knowledge FOLDER applied the CODE ignore list (*.png/*.svg/*.ipynb) and the
     512 KB cap, and documents were extracted with the same 512 KB cap;
  4. hybrid search only re-ranked the bm25 hits, so a paraphrase with no keyword
     overlap returned NOTHING even though every chunk had a vector.

It also pins the new behaviour: URL metadata + snapshot, data-shaped text formats,
garbage-text detection, image placeholders, and `fs.read` on a binary document.

Deterministic: no live network, no model.

Run: python3 tests/acceptance/v490_kb_external_sources.py
"""
import gzip
import json
import os
import sys
import tempfile
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v490-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_CODEBASE_DIR"] = os.path.join(TMP, "codebase")
os.environ["LONGRUN_KNOWLEDGE_DIR"] = os.path.join(TMP, "knowledge")
os.environ["LONGRUN_EMBEDDING_DIR"] = os.path.join(TMP, "embedding")
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(TMP, "costs")
for d in ("data", "sessions", "codebase", "knowledge", "embedding", "costs"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import chunk  # noqa: E402
from longrun.memory import docio  # noqa: E402
from longrun.memory import knowledge as kb  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A) text/data formats are indexable -------------------------------------
EXPECT = {".csv": "csv", ".tsv": "tsv", ".ipynb": "notebook", ".eml": "email",
          ".log": "log", ".tex": "latex", ".vtt": "subtitle"}
bad = []
for ext, lang in EXPECT.items():
    got, kind = chunk.lang_for("x" + ext)
    if got != lang or kind != "doc":
        bad.append((ext, got, kind))
check("A1 CSV/TSV/IPYNB/EML/LOG/TEX/VTT are documents", not bad, bad)
check("A2 PNG is still a document (docling OCR)", chunk.lang_for("x.png")[0] == "doc")

# ---- B) a broken text layer is detected -------------------------------------
soup = "✁ ✂ ☎ ✝ ✟ ✡ ✌ ✍ ✎ ✏ ✒ ✕ ✖ ✘ ✙ ✜ ✢ ✥ ✧ ✫ ✬ ✮ ✰ ✱ ✳ ✵ ✷ ✼ ✽ ✾ ✿ ❀ ❂"
check("B1 symbol soup scores as garbage", docio._text_quality(soup) < 0.1,
      docio._text_quality(soup))
real = "La dinamica flessionale della trave è descritta dall'equazione differenziale."
check("B2 real prose scores as text", docio._text_quality(real) > 0.6,
      docio._text_quality(real))
check("B3 the docling image placeholder is not text",
      docio._clean_image_text("<!-- image -->") == ""
      and docio._clean_image_text("[image]  hello  world ") == "hello world")
check("B4 MIN_TEXT_QUALITY is a real threshold", 0 < docio.MIN_TEXT_QUALITY < 1,
      docio.MIN_TEXT_QUALITY)

# ---- C) URL fetching: gzip + PDF + image + failure ---------------------------
class _Resp:
    def __init__(self, data, ctype, url, enc=""):
        self._data, self._url = data, url
        self.headers = {"Content-Type": ctype, "Content-Encoding": enc}

    def read(self, n=-1):
        return self._data[:n] if isinstance(n, int) and n >= 0 else self._data

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_orig_urlopen = urllib.request.urlopen
_orig_extract = docio.extract
seen = {}


def _fake_extract(path, max_kb=25600):
    seen["suffix"] = os.path.splitext(path)[1]
    with open(path, "rb") as f:
        seen["bytes"] = f.read(8)
    return {"text": "Extracted document body", "engine": "fake", "ok": True,
            "chars": 23, "pages": 1, "pages_with_text": 1, "pages_empty": 0,
            "avg_chars_per_page": 23, "extracted_pages": [], "quality": 0.9,
            "recommend_visual": False}


try:
    docio.extract = _fake_extract
    urllib.request.urlopen = lambda req, timeout=None: _Resp(
        b"%PDF-1.5 fake bytes", "application/pdf", "https://x/final/report.pdf")
    snapdir = os.path.join(TMP, "raw")
    info = chunk.fetch_url_info("https://x/r.pdf", snapshot_dir=snapdir)
    check("C1 a PDF URL is extracted, not decoded as text",
          info["kind"] == "pdf-url" and info["text"] == "Extracted document body",
          info)
    check("C2 the PDF bytes reached the extractor",
          seen.get("suffix") == ".pdf" and seen.get("bytes", b"").startswith(b"%PDF-"),
          seen)
    check("C3 the redirect target is recorded",
          info["final_url"] == "https://x/final/report.pdf", info["final_url"])
    check("C4 the binary source is snapshotted",
          info["snapshot"] and os.path.isfile(info["snapshot"])
          and os.path.getsize(info["snapshot"]) > 0, info["snapshot"])

    urllib.request.urlopen = lambda req, timeout=None: _Resp(
        gzip.compress(b"<html><body><p>Hello gzip world</p></body></html>"),
        "text/html; charset=utf-8", "https://x/page", "gzip")
    info = chunk.fetch_url_info("https://x/page")
    check("C5 a gzip HTML response is decompressed and stripped",
          info["engine"] == "html" and "Hello gzip world" in info["text"]
          and "<p>" not in info["text"], info["text"][:80])

    urllib.request.urlopen = lambda req, timeout=None: _Resp(
        b"\x89PNG\r\n\x1a\nfake", "image/png", "https://x/i.png")
    info = chunk.fetch_url_info("https://x/i.png")
    check("C6 an image URL is OCR/extracted, not decoded",
          info["kind"] == "image-url" and info["text"] == "Extracted document body",
          info)

    def _boom(req, timeout=None):
        raise OSError("network down")
    urllib.request.urlopen = _boom
    info = chunk.fetch_url_info("https://x/dead")
    check("C7 a fetch failure is reported, never raised",
          "error" in info and info["text"] == "", info)
finally:
    urllib.request.urlopen = _orig_urlopen
    docio.extract = _orig_extract

# ---- D) knowledge.add_source records URL metadata ---------------------------
_orig_fetch_info = kb.fetch_info
_orig_embed_model = kb._cfg.embed_model
try:
    kb._cfg.embed_model = lambda: ""      # offline: lexical-only ingest
    kb.fetch_info = lambda url, **kw: {
        "text": "Quarterly revenue was 42 million euro.",
        "kind": "pdf-url", "content_type": "application/pdf",
        "final_url": "https://cdn.example/final.pdf",
        "snapshot": "/tmp/snap.pdf", "engine": "pdftotext",
        "diagnostic": {"engine": "pdftotext", "quality": 0.9,
                       "recommend_visual": False},
    }
    r = kb.add_source("default", "https://example/report.pdf")
finally:
    kb.fetch_info = _orig_fetch_info
    kb._cfg.embed_model = _orig_embed_model
check("D1 a URL source ingests the extracted text",
      r.get("ok") and r.get("chunks", 0) >= 1, r)
check("D2 content type / final URL / snapshot are stored",
      r.get("content_type") == "application/pdf"
      and r.get("final_url") == "https://cdn.example/final.pdf"
      and r.get("snapshot") == "/tmp/snap.pdf", r)
db = kb._connect()
row = db.execute("SELECT kind, content_type, final_url, snapshot FROM sources "
                 "WHERE ref=?", ("https://example/report.pdf",)).fetchone()
db.close()
check("D3 the sources ROW carries the metadata",
      row and row["kind"] == "pdf-url" and row["content_type"] == "application/pdf"
      and row["final_url"].endswith("final.pdf"), dict(row) if row else None)

# ---- E) the knowledge folder config is its own ------------------------------
cfg = kb._kb_cfg()
check("E1 the code ignore globs do not hide knowledge files",
      cfg["ignore"] == [] and cfg["max_file_kb"] >= 1024, cfg)
check("E2 documents keep the doc cap", int(cfg["doc_max_kb"]) >= 1024, cfg["doc_max_kb"])

# ---- F) semantic-only hits (no lexical overlap) -----------------------------
import array  # noqa: E402

_orig_qv = kb._embed_texts_query
_orig_sem = kb._vec.semantic_hits
try:
    kb._embed_texts_query = lambda ref, q: [0.1, 0.2, 0.3]
    db = kb._connect()
    row = db.execute("SELECT id FROM chunks LIMIT 1").fetchone()
    ids = [row["id"]] if row else []
    if ids:  # give the hit a real vector so the RRF fusion runs
        db.execute("UPDATE chunks SET vec=? WHERE id=?",
                   (array.array("f", [1.0, 0.0, 0.0]).tobytes(), ids[0]))
        db.commit()
    db.close()
    kb._vec.semantic_hits = lambda db, qv, where_sql="", where_args=(), limit=20, cap=None: (
        ids, {}) if ids else ([], {})
    res = kb.search("zzzznonexistentterm", None, k=3)
finally:
    kb._embed_texts_query = _orig_qv
    kb._vec.semantic_hits = _orig_sem
check("F1 a query with ZERO lexical overlap still returns a semantic hit",
      bool(res.get("results")) and res.get("mode") == "hybrid",
      {"mode": res.get("mode"), "n": len(res.get("results") or [])})

# ---- G) orphaned FTS rows must not block the next indexed chunk -------------
orphan_pdf = os.path.join(TMP, "orphan.pdf")
with open(orphan_pdf, "wb") as f:
    f.write(b"%PDF-1.4 test upload")
db = kb._connect()
next_id = db.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM chunks").fetchone()[0]
orphan_ids = range(next_id, next_id + 5)
for rowid in orphan_ids:
    db.execute("INSERT INTO chunks_fts(rowid, text, name, path) VALUES(?,?,?,?)",
               (rowid, "stale orphan marker", "", "stale.txt"))
db.commit()
db.close()
_orig_orphan_extract = docio.extract


def _fake_orphan_extract(path, max_kb=25600):
    result = _fake_extract(path, max_kb=max_kb)
    result["text"] = "\n".join("FTS orphan recovery line %d." % i for i in range(900))
    result["chars"] = len(result["text"])
    return result


try:
    docio.extract = _fake_orphan_extract
    orphan_ingest = kb.add_source("auto", orphan_pdf, session_id="sid-fts-orphan")
except Exception as e:
    orphan_ingest = {"ok": False, "error": str(e)}
finally:
    docio.extract = _orig_orphan_extract
db = kb._connect()
orphan_count = db.execute(
    "SELECT count(*) FROM chunks_fts WHERE rowid NOT IN (SELECT id FROM chunks)"
).fetchone()[0]
db.close()
check("G1 a PDF is indexed into its session notebook despite an orphan FTS row",
      orphan_ingest.get("ok") and orphan_ingest.get("notebook", "").startswith("sess-")
      and orphan_ingest.get("chunks", 0) > len(orphan_ids) and orphan_count == 0, {
          "ingest": orphan_ingest, "orphan_fts_rows": orphan_count,
      })

# ---- H) fs.read extracts a binary document instead of decoding it -----------
from longrun.tools import tools as toolmod  # noqa: E402

pdf = os.path.join(TMP, "attached.pdf")
with open(pdf, "wb") as f:
    f.write(b"%PDF-1.4 binary-bytes")
_orig_read_extract = docio.extract
_orig_spec = toolmod.registry.tool_spec
try:
    docio.extract = _fake_extract
    # the temp dir is outside the shipped fs.read roots; allow it for this check
    toolmod.registry.tool_spec = lambda name: ({"roots": [TMP]} if name == "fs.read"
                                               else _orig_spec(name))
    got = toolmod._fs_read({"path": pdf, "max_bytes": 4096}, "run-v490")
finally:
    docio.extract = _orig_read_extract
    toolmod.registry.tool_spec = _orig_spec
check("H1 fs.read returns the EXTRACTED text of a PDF",
      got.get("ok") and got.get("content") == "Extracted document body"
      and got.get("engine") == "fake", got)

# ---- I) the WebUI attaches images too --------------------------------------
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
RX = ("pdf|docx?|odt|rtf|pptx|xlsx|epub|png|jpe?g|gif|bmp|webp|tiff?")
check("I1 the composer auto-ingests images as well as documents", RX in UI)
check("I2 the attach hint knows images are documents", RX in UI)
IDXCFG = open(os.path.join(REPO, "config", "index.yaml"), encoding="utf-8").read()
check("I3 index.yaml documents the knowledge knobs",
      all(k in IDXCFG for k in ("knowledge_ignore", "url_max_kb",
                                "image_caption_model", "image_min_chars")))

# ---- J) a cloud vision model is detected from live vendor metadata ----------
from longrun.model import providers, rllm  # noqa: E402

_orig_resolve = providers.resolve
_orig_modal = dict(providers._OPENROUTER_MODAL)
_orig_ctx = providers._OPENROUTER_CTX.get("map")
try:
    providers._OPENROUTER_MODAL.update({"vendor/vision-model": ["text", "image"],
                                        "vendor/text-model": ["text"]})
    providers._OPENROUTER_CTX["map"] = {"vendor/vision-model": 128000}
    providers.resolve = lambda ref: ({"id": "openrouter", "kind": "openrouter",
                                      "local": False, "models": []},
                                     ref.split(":", 1)[-1])
    check("J1 an OpenRouter model with an image input modality is vision-capable",
          rllm.model_supports_vision("openrouter:vendor/vision-model") is True)
    check("J2 an OpenRouter text-only model stays text-only",
          rllm.model_supports_vision("openrouter:vendor/text-model") is False)
    providers.resolve = lambda ref: ({"id": "deepseek", "kind": "deepseek",
                                      "local": False, "models": []},
                                     ref.split(":", 1)[-1])
    check("J3 a non-OpenRouter remote provider is never granted vision implicitly",
          rllm.model_supports_vision("deepseek:vendor/vision-model") is False)
finally:
    providers.resolve = _orig_resolve
    providers._OPENROUTER_MODAL.clear()
    providers._OPENROUTER_MODAL.update(_orig_modal)
    providers._OPENROUTER_CTX["map"] = _orig_ctx
check("J4 both vendor modality spellings are understood",
      providers._normalise_modalities("text+image->text") == ["text", "image"]
      and providers._normalise_modalities(["text", "image"]) == ["text", "image"])

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
