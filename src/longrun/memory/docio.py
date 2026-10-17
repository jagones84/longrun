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
import re
import shutil
import subprocess
import tempfile

# Extensions handled here (binary documents that need extraction, not plain text).
BINARY_DOC_EXT = {".pdf", ".docx", ".doc", ".odt", ".rtf", ".pptx", ".xlsx", ".epub"}
OFFICE_EXT = {".docx", ".doc", ".odt", ".rtf", ".pptx", ".xlsx", ".epub"}
# JAG-430/490: images are extracted by OCR (docling or pdftoppm+tesseract) and,
# when `image_caption_model` is configured, described by a vision model.
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


def _text_quality(text):
    """0..1 share of non-space characters that are LETTERS (script-agnostic).

    JAG-490: a PDF whose embedded font has a broken ToUnicode map yields a full
    text layer of symbol soup (`✁ ✂ ☎`, `$% &0324,5.6`). Every extractor returns
    a NON-empty string, so the old code accepted it and the KB indexed garbage.
    Counting letters (not "words") works for every script (Latin, CJK, Arabic…)
    while symbol/dingbat soup scores near zero.
    """
    t = (text or "")[:50000]
    chars = [c for c in t if not c.isspace()]
    if not chars:
        return 0.0
    return sum(1 for c in chars if c.isalpha()) / len(chars)


# Anything below this is treated as an unusable text layer (not a document).
MIN_TEXT_QUALITY = float(os.environ.get("LONGRUN_DOC_MIN_QUALITY") or 0.45)

# Docling emits a bare placeholder for an image with no recognized content.
_IMAGE_PLACEHOLDER = re.compile(r"<!--\s*image\s*-->|\[\s*image\s*\]", re.I)


def _clean_image_text(text):
    """Drop docling/image placeholders so a placeholder never becomes a chunk."""
    t = _IMAGE_PLACEHOLDER.sub(" ", text or "")
    return re.sub(r"\s+", " ", t).strip()


def _image_caption(path):
    """A vision caption for an image when ``image_caption_model`` is configured.

    JAG-490: OCR is enough for a screenshot or a scanned page, but a photo or an
    unlabelled chart produces almost no text. The KB then indexes the caption
    (visible text + a factual description), so the image becomes retrievable.
    """
    try:
        from longrun.memory import indexcfg
        model = str(indexcfg.load_config().get("image_caption_model") or "").strip()
        if not model:
            return None
        from longrun.model import vision
        return vision.caption(path, model)
    except Exception:  # noqa: BLE001
        return None


def _pdf_page_count(path):
    """Real page count (PyMuPDF, then pdfinfo, then 0)."""
    try:
        import fitz
        doc = fitz.open(path)
        try:
            return int(doc.page_count)
        finally:
            doc.close()
    except Exception:  # noqa: BLE001
        pass
    if shutil.which("pdfinfo"):
        rc, out, _ = _run(["pdfinfo", path], timeout=20)
        if rc == 0:
            for line in out.decode("utf-8", "replace").splitlines():
                if line.lower().startswith("pages:"):
                    try:
                        return int(line.split(":", 1)[1].strip())
                    except (TypeError, ValueError):
                        return 0
    return 0


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
    ext = os.path.splitext(path)[1].lower()
    # JAG-490: a SPREADSHEET needs the Calc CSV filter; the generic Text filter
    # fails with "impl_store … Error Area:Io Class:Write" (an .xlsx yielded 0 chars
    # even though LibreOffice was installed).
    specs = (["csv:Text - txt - csv (StarCalc):44,34,76", "csv"]
             if ext in (".xlsx", ".xls", ".ods")
             else ["txt:Text (encoded):UTF8", "txt:Text"])
    with tempfile.TemporaryDirectory() as td:
        # An isolated profile: a running desktop LibreOffice otherwise holds the
        # default profile lock and the headless conversion can fail silently.
        prof = os.path.join(td, "profile")
        for spec in specs:
            rc, _, _ = _run([soffice, "-env:UserInstallation=file://" + prof,
                             "--headless", "--norestore",
                             "--convert-to", spec, "--outdir", td, path])
            want = ".csv" if "csv" in spec else ".txt"
            outs = [f for f in os.listdir(td) if f.lower().endswith(want)]
            if rc == 0 and outs:
                try:
                    with open(os.path.join(td, outs[0]), encoding="utf-8",
                              errors="replace") as f:
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
         "quality": float, "recommend_visual": bool}

    Never raises. A NON-empty result whose text quality is below
    ``MIN_TEXT_QUALITY`` (a broken font encoding → symbol soup) is NOT accepted
    blindly: the next backend is tried, and the low-quality text is only used as
    a last resort (flagged in ``engine``) so the caller can warn.
    ``recommend_visual=True`` when the body of a PDF/image-only document has no
    readable text AND per-page char density is below
    ``LONGRUN_VISUAL_MIN_CHARS_PER_PAGE`` (default 30).
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

    pages_info = _pdf_pages_diag(path) if ext == ".pdf" else None

    # JAG-490: a normal text PDF is served by the FAST pdftotext path. Running
    # docling (GPU OCR/layout) on every PDF took minutes per book and held the
    # knowledge lock, so ingestion stalled the whole KB.
    low = None
    if ext == ".pdf":
        fast = _pdftotext(path)
        if fast and len(fast) >= 40:
            if _text_quality(fast) >= MIN_TEXT_QUALITY:
                return _cap_and_diagnose(fast, max_kb, "pdftotext", ext,
                                         pages_info=pages_info, path=path)
            low = fast

    text = None
    # A PDF that ALREADY has a low-quality text layer (broken ToUnicode) cannot
    # be fixed by docling/markitdown — they read the same layer. Go to OCR.
    skip_layout = (ext == ".pdf" and low is not None)
    if not skip_layout:
        text = _docling(path)                      # layout + tables + image OCR
        if text:
            if _text_quality(text) >= MIN_TEXT_QUALITY:
                return _cap_and_diagnose(text, max_kb, "docling", ext,
                                         pages_info=pages_info, path=path)
            low = low or text

        text = _markitdown(path)
        if text:
            if _text_quality(text) >= MIN_TEXT_QUALITY:
                return _cap_and_diagnose(text, max_kb, "markitdown", ext,
                                         pages_info=pages_info, path=path)
            low = low or text

    if ext in IMAGE_EXT:                           # images need OCR (docling)
        low = _clean_image_text(low) or None       # "<!-- image -->" is not text
        thin = (not low) or _text_quality(low) < MIN_TEXT_QUALITY
        if not thin:
            try:
                from longrun.memory import indexcfg
                min_chars = int(indexcfg.load_config().get("image_min_chars") or 80)
            except Exception:  # noqa: BLE001
                min_chars = 80
            thin = len((low or "").strip()) < min_chars
        if thin:
            cap = _image_caption(path)
            if cap:
                merged = (((low or "").strip() + "\n\n") if low else "")
                merged += "[image description]\n" + cap
                return _cap_and_diagnose(merged, max_kb,
                                         "ocr+vision" if low else "vision", ext,
                                         pages_info=pages_info, path=path)
        if low:
            return _cap_and_diagnose(low, max_kb, "docling (low-quality OCR)", ext,
                                     pages_info=pages_info, path=path)
        return _result(None, "no text (image has no OCR text; set "
                             "image_caption_model for a vision caption)",
                       0, [], chars=0, recommend_visual=True)

    if ext == ".pdf":
        ocr = _ocr_pdf(path)                        # scanned / broken-font PDF
        if ocr:
            engine = "ocr" if _text_quality(ocr) >= MIN_TEXT_QUALITY else "ocr (low-quality)"
            return _cap_and_diagnose(ocr, max_kb, engine, ext,
                                     pages_info=pages_info, path=path)
        if low:
            return _cap_and_diagnose(low, max_kb, "pdftotext (low-quality)", ext,
                                     pages_info=pages_info, path=path)
        missing = [] if _has_docling() else ["docling", "pdftotext+OCR"]
        return _result(None,
                       "no text (image-only PDF; OCR returned 0%s)" % (
                           "; install " + "/".join(missing) if missing else ""),
                       0, pages_info or [], chars=0, recommend_visual=True)

    if ext in OFFICE_EXT:
        text = _office(path)
        if text:
            return _cap_and_diagnose(text, max_kb, "libreoffice", ext,
                                     pages_info=pages_info, path=path)
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
            "quality": round(_text_quality(text), 3),
            "recommend_visual": extra["recommend_visual"]}


def _cap_and_diagnose(text, max_kb, engine, ext, pages_info=None, path=None):
    """Apply the per-result size cap AND fill in the real page count."""
    text = _cap(text, max_kb)
    if pages_info is None:
        # Light: synthesise a single virtual page for non-PDF paths so the
        # downstream consumer can still inspect `extracted_pages`.
        pages_info = [{"page": 1, "chars": len(text or ""), "images": 0}]
    total = len(pages_info)
    if path and ext == ".pdf":
        real = _pdf_page_count(path)
        if real > total:
            total = real
    return _result(text, engine, total, pages_info)


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
