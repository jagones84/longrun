"""Document text extraction for the indexes (JAG-403j) — PDF / Office / OCR.

The knowledge base and the codebase index both chunk PLAIN TEXT. This module turns
the common BINARY documents into text/markdown so they can be chunked + embedded.

Layered, best-available backend (no import-time hard dependency):

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

_TIMEOUT = int(os.environ.get("LONGRUN_DOC_TIMEOUT") or 300)


def supported(path):
    """True when this path is a binary document this module can extract."""
    return os.path.splitext(str(path or ""))[1].lower() in BINARY_DOC_EXT


def available():
    """Which backends exist on this host (for status / diagnostics)."""
    return {
        "markitdown": _has_markitdown(),
        "pdftotext": bool(shutil.which("pdftotext")),
        "tesseract": bool(shutil.which("tesseract")),
        "pdftoppm": bool(shutil.which("pdftoppm")),
        "libreoffice": bool(shutil.which("libreoffice") or shutil.which("soffice")),
    }


def _has_markitdown():
    try:
        import importlib.util
        return importlib.util.find_spec("markitdown") is not None
    except Exception:  # noqa: BLE001
        return False


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

    Returns ``(text, engine)`` on success, ``(None, reason)`` when nothing could
    be extracted. Never raises.
    """
    path = str(path or "")
    ext = os.path.splitext(path)[1].lower()
    if ext not in BINARY_DOC_EXT:
        return None, "not a binary document"
    if not os.path.isfile(path):
        return None, "not a file"
    path = os.path.abspath(path)  # JAG-413: a "-x.pdf" name must not read as a flag
    if os.path.getsize(path) == 0:
        return None, "empty file"

    text = _markitdown(path)                       # richest output when available
    if text:
        return _cap(text, max_kb), "markitdown"

    if ext == ".pdf":
        text = _pdftotext(path)
        if text and len(text) >= 40:
            return _cap(text, max_kb), "pdftotext"
        ocr = _ocr_pdf(path)                        # scanned PDF -> OCR
        if ocr:
            return _cap(ocr, max_kb), "ocr"
        if text:
            return _cap(text, max_kb), "pdftotext"
        return None, "no text (scan? install tesseract)"

    if ext in OFFICE_EXT:
        text = _office(path)
        if text:
            return _cap(text, max_kb), "libreoffice"
        return None, "no converter (install markitdown or libreoffice)"

    return None, "no extractor for %s" % ext
