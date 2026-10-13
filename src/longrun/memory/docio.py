"""Document text extraction for the indexes (JAG-403j / JAG-430) — PDF / Office / images.

The knowledge base and the codebase index both chunk PLAIN TEXT. This module turns
the common BINARY documents into text/markdown so they can be chunked + embedded.

Layered, best-available backend (no import-time hard dependency):

  0. ``docling`` (IBM, MIT) when installed -> layout-aware reading order + real
     TABLE structure (TableFormer) for PDF/DOCX/PPTX/XLSX/HTML/EPUB **and native
     images** (PNG/JPEG/TIFF…). This is the richest path (JAG-430).
  1. ``markitdown`` (Microsoft, MIT) when installed -> PDF, DOCX, PPTX, XLSX, HTML…
     converts to Markdown (headings + tables preserved).
  2. PDF fallback -> ``pdftotext`` (poppler); when the page has no text layer
     (a SCAN) -> OCR via ``pdftoppm`` + ``tesseract``.
  3. Office fallback -> ``libreoffice --headless --convert-to txt``.

Everything is stdlib + optional external binaries. ``available()`` reports which
backends are present so the UI/CLI can explain what is missing.

LANG: OCR language comes from ``LONGRUN_OCR_LANGS`` (default ``eng+ita``).
"""
import os
import shutil
import subprocess
import tempfile

# Extensions handled here (binary documents that need extraction, not plain text).
BINARY_DOC_EXT = {".pdf", ".docx", ".doc", ".odt", ".rtf", ".pptx", ".xlsx", ".epub"}
OFFICE_EXT = {".docx", ".doc", ".odt", ".rtf", ".pptx", ".xlsx", ".epub"}
# JAG-430: images reach the KB only through docling (OCR/vision); other backends
# cannot read them, so they are a docling-only extension set.
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
BINARY_DOC_EXT |= IMAGE_EXT

_TIMEOUT = int(os.environ.get("LONGRUN_DOC_TIMEOUT") or 300)


def supported(path):
    """True when this path is a binary document this module can extract."""
    return os.path.splitext(str(path or ""))[1].lower() in BINARY_DOC_EXT


def available():
    """Which backends exist on this host (for status / diagnostics)."""
    return {
        "docling": _has_docling(),
        "markitdown": _has_markitdown(),
        "pdftotext": bool(shutil.which("pdftotext")),
        "tesseract": bool(shutil.which("tesseract")),
        "pdftoppm": bool(shutil.which("pdftoppm")),
        "libreoffice": bool(shutil.which("libreoffice") or shutil.which("soffice")),
    }


def _has_module(name):
    try:
        import importlib.util
        return importlib.util.find_spec(name) is not None
    except Exception:  # noqa: BLE001
        return False


def _has_docling():
    # docling's public entry point lives in `docling.document_converter`.
    return _has_module("docling")


def _has_markitdown():
    return _has_module("markitdown")


_MAX_OUTPUT = int(os.environ.get("LONGRUN_DOC_MAX_OUTPUT") or (64 * 1024 * 1024))


def _run(cmd, timeout=None):
    """Run a helper binary, capturing stdout/stderr to TEMP FILES (JAG-413): a
    runaway converter cannot exhaust memory — we read back at most _MAX_OUTPUT."""
    out_f = tempfile.TemporaryFile()
    err_f = tempfile.TemporaryFile()
    try:
        p = subprocess.Popen(cmd, stdout=out_f, stderr=err_f)
        try:
            p.communicate(timeout=timeout or _TIMEOUT)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
        out_f.seek(0)
        err_f.seek(0)
        return p.returncode, out_f.read(_MAX_OUTPUT), err_f.read(_MAX_OUTPUT)
    except Exception as e:  # noqa: BLE001
        return 1, b"", str(e).encode("utf-8", "replace")
    finally:
        out_f.close()
        err_f.close()


def _cap(text, max_kb):
    text = (text or "").strip()
    if not text:
        return None
    return text[: int(max_kb) * 1024]


# ----------------------------------------------------------------- backends ---
_DOCLING_CONVERTER = None


def _docling(path):
    """Richest backend (JAG-430): layout-aware Markdown + real table structure."""
    if not _has_docling():
        return None
    global _DOCLING_CONVERTER
    try:
        if _DOCLING_CONVERTER is None:
            from docling.document_converter import DocumentConverter
            _DOCLING_CONVERTER = DocumentConverter()
        res = _DOCLING_CONVERTER.convert(path)
        doc = getattr(res, "document", None)
        if doc is None:
            return None
        text = doc.export_to_markdown()
        return (text or "").strip() or None
    except Exception:  # noqa: BLE001 — any docling failure falls through to the next backend
        return None


def _markitdown(path):
    if not _has_markitdown():
        return None
    try:
        from markitdown import MarkItDown
        res = MarkItDown().convert(path)
        return (getattr(res, "text_content", "") or "").strip() or None
    except Exception:  # noqa: BLE001
        return None


def _pdftotext(path):
    if not shutil.which("pdftotext"):
        return None
    rc, out, _ = _run(["pdftotext", "-layout", "-q", path, "-"])
    if rc == 0:
        return out.decode("utf-8", "replace").strip() or None
    return None


def _page_index(name):
    """Numeric page index for a pdftoppm output file (page-1.png -> 1) so pages
    sort naturally (page-2 < page-10) instead of lexicographically (JAG-413)."""
    stem = name.rsplit(".", 1)[0]
    tail = stem.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _ocr_pdf(path, max_pages=40):
    if not (shutil.which("pdftoppm") and shutil.which("tesseract")):
        return None
    langs = os.environ.get("LONGRUN_OCR_LANGS") or "eng+ita"
    with tempfile.TemporaryDirectory() as td:
        rc, _, _ = _run(["pdftoppm", "-r", "200", "-png", "-l", str(max_pages),
                         path, os.path.join(td, "page")])
        if rc != 0:
            return None
        parts = []
        for img in sorted(os.listdir(td), key=_page_index):
            if not img.endswith(".png"):
                continue
            rc2, out2, _ = _run(["tesseract", os.path.join(td, img), "stdout", "-l", langs])
            if rc2 != 0 and "eng" not in langs:
                rc2, out2, _ = _run(["tesseract", os.path.join(td, img), "stdout", "-l", "eng"])
            if rc2 == 0 and out2.strip():
                parts.append(out2.decode("utf-8", "replace"))
        return ("\n\n".join(parts).strip() or None)


def _office(path):
    soffice = shutil.which("libreoffice") or shutil.which("soffice")
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as td:
        for spec in ("txt:Text (encoded):UTF8", "txt:Text"):
            rc, _, _ = _run([soffice, "--headless", "--norestore",
                             "--convert-to", spec, "--outdir", td, path])
            outs = [f for f in os.listdir(td) if f.lower().endswith(".txt")]
            if rc == 0 and outs:
                try:
                    with open(os.path.join(td, outs[0]), encoding="utf-8", errors="replace") as f:
                        text = f.read().strip()
                    if text:
                        return text
                except OSError:
                    pass
    return None


# ------------------------------------------------------------------ public ---
def extract(path, max_kb=25600):
    """Extract text from a binary document.

    Returns a dict::

        {"text": <str|None>, "engine": <str|reason>, "ok": bool,
         "chars": int, "pages": int, "pages_with_text": int,
         "pages_empty": int, "avg_chars_per_page": float,
         "extracted_pages": <list of {page, chars, images}>,
         "recommend_visual": bool}

    Never raises. ``recommend_visual=True`` when the body of a PDF/image-only
    document has no readable text AND per-page char density is below
    ``LONGRUN_VISUAL_MIN_CHARS_PER_PAGE`` (default 30) — a hint that
    visual-embedding backends (ColPali / SigLIP / open_clip) would be needed
    to make the document searchable.
    """
    path = str(path or "")
    ext = os.path.splitext(path)[1].lower()
    if ext not in BINARY_DOC_EXT:
        return _result(None, "not a binary document", 0, [])
    if not os.path.isfile(path):
        return _result(None, "not a file", 0, [])
    path = os.path.abspath(path)  # JAG-413: a "-x.pdf" name must not read as a flag
    if os.path.getsize(path) == 0:
        return _result(None, "empty file", 0, [])

    text = _docling(path)                          # JAG-430: richest (layout + tables + images)
    if text:
        return _cap_and_diagnose(text, max_kb, "docling", ext)

    text = _markitdown(path)                       # richest output when available
    if text:
        return _cap_and_diagnose(text, max_kb, "markitdown", ext)

    if ext in IMAGE_EXT:                           # images need docling (OCR/vision)
        return _result(None, "no text (install docling to OCR/describe images)",
                       0, [], chars=0)

    pages_info = _pdf_pages_diag(path)

    if ext == ".pdf":
        text = _pdftotext(path)
        if text and len(text) >= 40:
            return _cap_and_diagnose(text, max_kb, "pdftotext", ext,
                                     pages_info=pages_info)
        ocr = _ocr_pdf(path)                        # scanned PDF -> OCR
        if ocr:
            return _cap_and_diagnose(ocr, max_kb, "ocr", ext, pages_info=pages_info)
        if text:
            return _cap_and_diagnose(text, max_kb, "pdftotext", ext,
                                     pages_info=pages_info)
        # JAG-431r5: surfaced as `recommend_visual` so add_source/auto-route
        # can hint that an atlas / image-only PDF needs SigLIP / ColPali.
        return _result(None,
                       "no text (image-only PDF; pdftotext+OCR returned 0; "
                       "install a visual embedder)",
                       0, pages_info, chars=0, recommend_visual=True)

    if ext in OFFICE_EXT:
        text = _office(path)
        if text:
            return _cap_and_diagnose(text, max_kb, "libreoffice", ext)
        return _result(None, "no converter (install markitdown or libreoffice)",
                       0, [], chars=0)

    return _result(None, "no extractor for %s" % ext, 0, [], chars=0)


def _result(text, engine, pages, pages_info, **extra):
    """Build the standardized diagnostic envelope for extract()."""
    chars = len(text or "")
    pages_with_text = sum(1 for p in pages_info if p.get("chars", 0) > 0)
    pages_empty = max(0, pages - pages_with_text)
    avg = round(chars / max(1, pages), 2) if pages else 0.0
    if "recommend_visual" not in extra:
        min_cpp = float(os.environ.get("LONGRUN_VISUAL_MIN_CHARS_PER_PAGE") or 30)
        extra["recommend_visual"] = (
            (pages or 0) > 5 and pages_empty >= max(1, int(0.6 * (pages or 1)))
            and avg < min_cpp)
    return {"text": text, "engine": engine, "ok": bool(text),
            "chars": chars, "pages": pages, "pages_with_text": pages_with_text,
            "pages_empty": pages_empty, "avg_chars_per_page": avg,
            "extracted_pages": pages_info,
            "recommend_visual": extra["recommend_visual"]}


def _cap_and_diagnose(text, max_kb, engine, ext, pages_info=None):
    """Apply the per-result size cap AND fill in per-page diagnostic."""
    if pages_info is None:
        # Light: synthesise a single virtual page for non-PDF paths so the
        # downstream consumer can still inspect `extracted_pages`.
        pages_info = [{"page": 1, "chars": len(text or ""), "images": 0}]
    return _result(_cap(text, max_kb), engine, len(pages_info), pages_info)


def _pdf_pages_diag(path, probe_pages=12):
    """Sample `probe_pages` of a PDF to estimate how many are image-only.

    A page is "text-bearing" if pdftotext returns ≥ 4 non-space chars for it.
    The returned list has at most `probe_pages` rows (small + fast); the rest
    of the document is counted in `pages` via PyMuPDF.
    """
    try:
        import fitz  # PyMuPDF
    except Exception:  # pragma: no cover — fallback when PyMuPDF is absent
        return _pdf_pages_diag_fallback(path)
    out = []
    try:
        doc = fitz.open(path)
        total = doc.page_count
        step = max(1, total // probe_pages)
        sample_indices = list(range(0, total, step))[:probe_pages]
        for i in sample_indices:
            page = doc[i]
            t = page.get_text("text") or ""
            images = len(page.get_images(full=True))
            out.append({"page": i + 1, "chars": len(t.strip()),
                        "images": images})
        return out
    except Exception:  # noqa: BLE001
        return _pdf_pages_diag_fallback(path)


def _pdf_pages_diag_fallback(path):
    """pdftotext probe when PyMuPDF is not available (rough, slow)."""
    if not shutil.which("pdftotext"):
        return []
    out = []
    rc, out_bytes, _ = _run(["pdfinfo", path])
    total = 0
    if rc == 0:
        for line in out_bytes.decode("utf-8", "replace").splitlines():
            if line.lower().startswith("pages:"):
                try:
                    total = int(line.split(":", 1)[1].strip())
                except (TypeError, ValueError):
                    total = 0
                break
    return out
