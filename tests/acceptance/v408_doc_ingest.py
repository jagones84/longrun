"""v408 — document ingestion (PDF/Office/OCR), flat composer, notebooks menu (JAG-403j).

Stdlib-only, deterministic, no browser. Covers:

  1) the ingestion pipeline turns PDF/DOCX/… into text (docio + chunk.read_text),
     and the active embedding model now DEFAULTS to cohere (a fresh clone is not
     left with an empty field);
  2) the composer toolbar is a flat strip (no per-button frames);
  3) the Notebooks list is a collapsible <details> menu;
  4) the knowledge status reports which document extractors are installed.
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="v408-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_CODECODE_DIR"] = os.path.join(tmp, "codebase")
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
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if (detail and not ok) else ""))


HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

# ------------------------------------------------------------------ 1) ingestion
from longrun.memory import chunk, docio          # noqa: E402
from longrun.memory import indexcfg              # noqa: E402
from longrun.memory import embedcfg              # noqa: E402

check("1a docio recognises the common binary documents",
      docio.supported("a.pdf") and docio.supported("b.docx") and docio.supported("c.pptx")
      and docio.supported("d.xlsx") and not docio.supported("e.md"))
check("1b the chunker classifies a PDF as a document",
      chunk.lang_for("paper.PDF") == ("doc", "doc") and chunk.lang_for("a.md") == ("markdown", "doc"))
check("1c chunk.read_text delegates binary documents to docio",
      "if docio.supported(abspath):" in open(os.path.join(REPO, "src", "longrun", "memory", "chunk.py"),
                                             encoding="utf-8").read())
check("1d a non-document is rejected by extract()",
      (lambda r: r.get("text") is None and r.get("engine") == "not a binary document"
                 and r.get("ok") is False)(docio.extract(str(os.path.join(tmp, "x.md")))))
check("1e extract() reports availability of the backends",
      set(docio.available().keys()) >= {"markitdown", "pdftotext", "tesseract", "libreoffice"})
check("1f docs get a larger size budget than code files",
      indexcfg.DEFAULT_CONFIG.get("doc_max_kb", 0) > indexcfg.DEFAULT_CONFIG.get("max_file_kb", 0))

# The shipped default embedding model (fresh clone is not left empty).
check("1g a default embedding model ships (cohere) so a clone is not empty",
      indexcfg.DEFAULT_CONFIG.get("embed_model") == "cohere:embed-multilingual-v3.0"
      and embedcfg.active_model() == "cohere:embed-multilingual-v3.0", embedcfg.active_model())
check("1h the embedding build degrades to bm25 if the embedder fails (records, never raises)",
      'except Exception as e:  # noqa: BLE001\n                    embed_err = "%s: %s"' in open(
          os.path.join(REPO, "src", "longrun", "memory", "codeindex.py"), encoding="utf-8").read())

# requirements documents the optional ingestion dependency.
_reqs = open(os.path.join(REPO, "requirements.txt"), encoding="utf-8").read() if os.path.isfile(
    os.path.join(REPO, "requirements.txt")) else ""
check("1i requirements.txt lists the document-ingestion dependency",
      "PyYAML" in _reqs and "markitdown" in _reqs)

# Behavioural: a real PDF with a text layer is extracted (guarded by pdftotext).
if shutil.which("pdftotext"):
    def _mini_pdf(text):
        objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
                b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R "
                b"/Resources << /Font << /F1 5 0 R >> >> >>",
                None,
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
        stream = ("BT /F1 18 Tf 20 100 Td (" + text + ") Tj ET").encode()
        objs[3] = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        out = bytearray(b"%PDF-1.4\n")
        offs = []
        for i, o in enumerate(objs, 1):
            offs.append(len(out))
            out += str(i).encode() + b" 0 obj\n" + o + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
        for off in offs:
            out += ("%010d 00000 n \n" % off).encode()
        out += (b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root 1 0 R >>\nstartxref\n"
                + str(xref).encode() + b"\n%%EOF")
        return bytes(out)

    pdfp = os.path.join(tmp, "doc.pdf")
    with open(pdfp, "wb") as f:
        f.write(_mini_pdf("LONGRUNDOCMARKER alpha beta gamma delta epsilon zeta"))
    txt = chunk.read_text(pdfp, 512)
    check("1j a PDF is extracted through the pipeline (marker text present)",
          bool(txt) and "LONGRUNDOCMARKER" in txt, (txt or "")[:80])
else:
    check("1j a PDF is extracted through the pipeline [skipped: pdftotext missing]", True)

# ------------------------------------------------------------------ 2) composer
check("2 the composer toolbar is a flat strip (no per-button frames)",
      "#composerBar .cb-left > button, #composerBar .cb-right > button," in HTML
      and "background: transparent; border: 0; box-shadow: none; color: var(--dim);" in HTML)

# ------------------------------------------------------------------ 3) notebooks
check("3 the notebooks list is a collapsible <details> menu",
      '<details class="card" id="kbNbBox">' in HTML and 'id="kbNbActive"' in HTML)
check("3b the collapsed summary shows the active notebook",
      '$("kbNbActive").textContent = act ?' in HTML)

# ------------------------------------------------------------------ 4) UI text + status
check("4a the sources help mentions PDF/DOCX extraction + embedding",
      "PDF / DOCX / PPTX / XLSX / ODT" in HTML)
check("4b the knowledge status reports the installed document extractors",
      "doc extractors: <b>" in HTML and '"extractors": _docio.available()' in open(
          os.path.join(REPO, "src", "longrun", "memory", "knowledge.py"), encoding="utf-8").read())

print("---")
ok = sum(results)
print("%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
