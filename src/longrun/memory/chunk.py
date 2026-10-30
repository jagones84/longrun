"""Shared chunking + file discovery for the indexes (JAG-400) — stdlib only.

Both stores use this: the per-workspace codebase index and the global knowledge
base. Chunks are AST-aware for Python (the ``ast`` module), heading/paragraph-aware
for documents, and a line window is the fallback for other languages.
"""
import ast
import os
import re
import shutil
import subprocess
import tempfile
from fnmatch import fnmatch

from longrun.memory import docio

# direct children of a root never scanned
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".tox", "dist", "build", ".next", ".nuxt", "target", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "vendor", ".idea", ".eggs", "site-packages",
}
CODE_EXT = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript", ".java": "java",
    ".go": "go", ".rs": "rust", ".rb": "ruby", ".c": "c", ".h": "c", ".cpp": "cpp",
    ".cc": "cpp", ".hpp": "cpp", ".cs": "csharp", ".php": "php", ".sh": "bash",
    ".bash": "bash", ".kt": "kotlin", ".kts": "kotlin", ".swift": "swift",
    ".sql": "sql", ".css": "css", ".html": "html", ".htm": "html", ".json": "json",
    ".yml": "yaml", ".yaml": "yaml", ".toml": "toml", ".xml": "xml", ".gradle": "groovy",
    ".scala": "scala", ".pl": "perl", ".lua": "lua", ".r": "r", ".dart": "dart",
    ".vue": "vue", ".svelte": "svelte", ".ex": "elixir", ".exs": "elixir",
    ".clj": "clojure", ".hs": "haskell",
}
DOC_EXT = {".md": "markdown", ".markdown": "markdown", ".rst": "rst", ".txt": "text", ".adoc": "asciidoc"}
# Plain-text DATA formats (JAG-490): these were not indexable at all, so a KB
# built from exports (.csv/.log/.eml/.tex/.ipynb/…) silently missed them.
DATA_EXT = {".csv": "csv", ".tsv": "tsv", ".log": "log", ".eml": "email",
            ".tex": "latex", ".bib": "bibtex", ".ipynb": "notebook",
            ".srt": "subtitle", ".vtt": "subtitle", ".ini": "ini",
            ".cfg": "ini", ".conf": "ini"}
EXTLESS = {"dockerfile": "dockerfile", "makefile": "makefile", "rakefile": "ruby", "procfile": "text"}

#: Folders that hold TESTS of a codebase, not the codebase itself. The codebase
#: index is a map of the product a search is about; a tree of hundreds of test
#: files drowns every real symbol in the top-k. Opt-in per caller (see `walk`),
#: because the KNOWLEDGE base ingests arbitrary folders where a `tests/` file may
#: be exactly the evidence the user wanted.
TEST_DIRS = {"tests", "test", "testing", "__tests__", "spec", "specs", "e2e",
             "integration_tests", "unit_tests", "fixtures", "__mocks__",
             "testdata", "test_data", "test-data", "coverage", "htmlcov"}
TEST_GLOBS = ("test_*.py", "*_test.py", "conftest.py", "tests.py",
              "*.test.js", "*.test.jsx", "*.test.ts", "*.test.tsx",
              "*.test.mjs", "*.test.cjs", "*.spec.js", "*.spec.jsx",
              "*.spec.ts", "*.spec.tsx", "*Test.java", "*Tests.java",
              "*_spec.rb", "*_test.go")


def is_test_path(rel):
    """True when a repo path is a TEST (folder or file name convention)."""
    parts = str(rel or "").replace("\\", "/").split("/")
    if any(p.lower() in TEST_DIRS for p in parts[:-1]):
        return True
    return bool(parts) and any(fnmatch(parts[-1], g) for g in TEST_GLOBS)


def lang_for(rel):
    """(language, kind) for a path, or (None, None) when not indexable."""
    name = os.path.basename(rel).lower()
    ext = os.path.splitext(name)[1]
    if ext in CODE_EXT:
        return CODE_EXT[ext], "code"
    if ext in DOC_EXT:
        return DOC_EXT[ext], "doc"
    if ext in DATA_EXT:
        # JAG-490: data-shaped TEXT is a document, not code (no AST chunking).
        return DATA_EXT[ext], "doc"
    if ext in docio.BINARY_DOC_EXT:
        # JAG-403j: PDF/DOCX/… are extracted to text by ``docio`` (see read_text).
        return "doc", "doc"
    if name in EXTLESS:
        return EXTLESS[name], "code"
    return None, None


# ---------------------------------------------------------------- gitignore ---
def _read_gitignore(path, base=""):
    """Rules from ONE .gitignore, with the directory they apply to.

    Negations (`!pattern`) are kept: git evaluates rules in order and the LAST
    match wins, so a re-included file must override an earlier ignore.
    """
    rules = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                neg = line.startswith("!")
                if neg:
                    line = line[1:].strip()
                if not line:
                    continue
                rules.append({"base": base, "pat": line.strip("/"),
                              "dir": line.endswith("/"),
                              "anchored": line.startswith("/"), "neg": neg})
    except Exception:  # noqa: BLE001
        pass
    return rules


def load_gitignore(root):
    return _read_gitignore(os.path.join(root, ".gitignore"))


def _git_ignored(rel, name, is_dir, rules):
    """True when git-ignore `rules` exclude this path (last match wins)."""
    rel = str(rel or "").replace("\\", "/")
    ignored = False
    for r in rules:
        base = str(r["base"] or "").replace("\\", "/")
        if base:
            if not (rel == base or rel.startswith(base + "/")):
                continue
            sub = rel[len(base) + 1:]
        else:
            sub = rel
        if not sub:
            continue
        pat = r["pat"]
        if r["anchored"] or "/" in pat:
            matched = (fnmatch(sub, pat) or sub == pat
                       or (is_dir and sub.startswith(pat + "/")))
        else:
            matched = fnmatch(name, pat)
        if matched:
            ignored = not r["neg"]
    return ignored


def extra_ignored(name, rel, globs):
    return any(fnmatch(name, g) or fnmatch(rel, g) for g in (globs or []))


def _git_listed_files(root):
    """Paths git considers part of this work tree, or None when git cannot say.

    `git ls-files --cached --others --exclude-standard` is the AUTHORITATIVE
    definition of "not ignored": it applies every nested .gitignore, negation
    rules, `.git/info/exclude` and the user's global excludes. The fallback walk
    below approximates only the workspace-root file.
    """
    exe = shutil.which("git")
    if not exe:
        return None
    try:
        probe = subprocess.run([exe, "-C", root, "rev-parse", "--is-inside-work-tree"],
                               capture_output=True, text=True, timeout=5)
        if probe.returncode != 0 or probe.stdout.strip().lower() != "true":
            return None
        out = subprocess.run([exe, "-C", root, "ls-files", "-z", "--cached",
                              "--others", "--exclude-standard"],
                             capture_output=True, timeout=30)
        if out.returncode != 0:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    rows = out.stdout.decode("utf-8", "replace").split("\0")
    return sorted({row for row in rows if row})


def _rel_dir(root, dirpath):
    rel = os.path.relpath(dirpath, root)
    return "" if rel == "." else rel


def walk(root, cfg, exclude_tests=False):
    """Yield (rel, abspath, lang, kind) for indexable files under `root`.

    Git-ignored content is NEVER indexed: when `root` is a git work tree the
    exact `git ls-files` roster decides (nested .gitignore, negations, global
    excludes); otherwise the workspace-root .gitignore plus any nested
    .gitignore found while descending are applied.

    `exclude_tests=True` drops the TEST tree (see `TEST_DIRS`/`TEST_GLOBS`): the
    codebase index maps the code, and a repo with hundreds of test files makes
    every real symbol lose the top-k to a fixture. The knowledge base leaves it
    off — a folder someone points a notebook at must be indexed as given.
    """
    globs = cfg.get("ignore") or []
    maxb = int(cfg.get("max_file_kb") or 512) * 1024
    docmax = int(cfg.get("doc_max_kb") or 25600) * 1024   # JAG-403j: docs are bigger
    root = os.path.realpath(root)

    listed = _git_listed_files(root)
    if listed is not None:
        for rel in listed:
            parts = rel.replace("\\", "/").split("/")
            if any(p in SKIP_DIRS or p.startswith(".") for p in parts[:-1]):
                continue
            if exclude_tests and is_test_path(rel):
                continue
            lang, kind = lang_for(rel)
            if not lang:
                continue
            fn = parts[-1]
            if extra_ignored(fn, rel, globs):
                continue
            abspath = os.path.join(root, *parts)
            try:
                if os.path.getsize(abspath) > (docmax if docio.supported(fn) else maxb):
                    continue
            except OSError:
                continue
            yield rel, abspath, lang, kind
        return

    rules = load_gitignore(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = _rel_dir(root, dirpath)
        if rel_dir:
            # Nested rules apply only under their own directory (the base filter
            # in _git_ignored enforces that, so siblings are unaffected).
            rules = rules + _read_gitignore(
                os.path.join(dirpath, ".gitignore"), rel_dir)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        keep = []
        for d in dirnames:
            rd = d if not rel_dir else os.path.join(rel_dir, d)
            if _git_ignored(rd, d, True, rules) or extra_ignored(d, rd, globs):
                continue
            if exclude_tests and d.lower() in TEST_DIRS:
                continue
            keep.append(d)
        dirnames[:] = keep
        for fn in filenames:
            rel = fn if not rel_dir else os.path.join(rel_dir, fn)
            if exclude_tests and is_test_path(rel):
                continue
            lang, kind = lang_for(rel)
            if not lang:
                continue
            if _git_ignored(rel, fn, False, rules) or extra_ignored(fn, rel, globs):
                continue
            abspath = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(abspath) > (docmax if docio.supported(fn) else maxb):
                    continue
            except OSError:
                continue
            yield rel, abspath, lang, kind



def read_text(abspath, max_kb):
    """Decoded text, or None for binary/unreadable files.

    JAG-403j: binary DOCUMENTS (PDF/DOCX/PPTX/…) are extracted to text/markdown
    via ``docio`` so they can be chunked + embedded like any other source.
    """
    if docio.supported(abspath):
        # JAG-431r5: docio.extract now returns a diagnostic dict (text + engine +
        # per-page metrics + recommend_visual). We only consume the text.
        res = docio.extract(abspath, max_kb=max(1024, int(max_kb or 512)))
        return res.get("text") if isinstance(res, dict) else (res[0] if res else None)
    try:
        with open(abspath, "rb") as f:
            data = f.read(int(max_kb) * 1024 + 1)
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", "replace")


# ----------------------------------------------------------------- chunkers ---
def _emit_range(out, lines, s, e, name, chunk_lines, overlap):
    overlap = max(0, min(overlap, chunk_lines - 1))
    while s < e:
        end = min(s + chunk_lines, e)
        body = "\n".join(lines[s:end]).strip()
        if body:
            out.append({"name": name, "start": s + 1, "end": end, "text": body})
        if end >= e:
            break
        s = end - overlap


def chunk_python(text, chunk_lines, overlap):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    lines = text.splitlines()
    out = []
    tops = [n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    first = min([n.lineno for n in tops], default=len(lines) + 1)
    if first > 1:
        head = "\n".join(lines[:first - 1]).strip()
        if head:
            out.append({"name": "<module>", "start": 1, "end": first - 1, "text": head})

    def add(name, node):
        s = max(getattr(node, "lineno", 1) - 1, 0)
        e = getattr(node, "end_lineno", None) or (s + 1)
        body = "\n".join(lines[s:e]).strip()
        if body:
            out.append({"name": name, "start": s + 1, "end": e, "text": body})

    for n in tops:
        if isinstance(n, ast.ClassDef):
            add(n.name, n)
            for m in n.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add(n.name + "." + m.name, m)
        else:
            add(n.name, n)
    return out or None


def chunk_doc(text, chunk_lines, overlap):
    lines = text.splitlines()
    n = len(lines)
    heads = [(i, re.sub(r"^#{1,6}\s+", "", lines[i]).strip()[:120])
             for i in range(n) if re.match(r"^#{1,6}\s+\S", lines[i])]
    out = []
    if not heads:
        _emit_range(out, lines, 0, n, "<doc>", chunk_lines, overlap)
        return out
    if heads[0][0] > 0:
        _emit_range(out, lines, 0, heads[0][0], "<intro>", chunk_lines, overlap)
    bounds = [h[0] for h in heads] + [n]
    for idx, (s, name) in enumerate(heads):
        _emit_range(out, lines, s, bounds[idx + 1], name, chunk_lines, overlap)
    return out


def chunk_file(text, lang, kind, cfg):
    cl = int(cfg.get("chunk_lines") or 60)
    ov = int(cfg.get("overlap_lines") or 8)
    if lang == "python":
        got = chunk_python(text, cl, ov)
        if got is not None:
            return got
    if kind == "doc":
        return chunk_doc(text, cl, ov)
    out = []
    _emit_range(out, text.splitlines(), 0, len(text.splitlines()), "<file>", cl, ov)
    return out


# --------------------------------------------------------------------- html ---
def strip_html(html):
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def fetch_url(url, timeout=20):
    """Readable text from a URL (public internet). HTML is stripped to text.

    Back-compat string wrapper around :func:`fetch_url_info`. Binary documents
    (PDF / Office / images) are extracted with ``docio`` instead of being
    decoded as text.
    """
    return (fetch_url_info(url, timeout=timeout) or {}).get("text") or ""


# JAG-490: what a URL actually IS. Before this, a PDF/image URL was read as
# bytes and decoded as UTF-8 ("%PDF-1.5 …"), so the KB indexed garbage.
_IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"), (b"GIF89a", ".gif"), (b"BM", ".bmp"),
    (b"II*\x00", ".tiff"), (b"MM\x00*", ".tiff"),
)
_CTYPE_SUFFIX = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/epub+zip": ".epub",
    "application/rtf": ".rtf",
    "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
    "image/bmp": ".bmp", "image/webp": ".webp", "image/tiff": ".tiff",
}


def _sniff_suffix(data, ctype, url):
    """The document suffix implied by the bytes/content-type/URL (or None)."""
    ctype = (ctype or "").split(";")[0].strip().lower()
    if ctype in _CTYPE_SUFFIX:
        return _CTYPE_SUFFIX[ctype]
    head = data[:8]
    if head.startswith(b"%PDF-"):
        return ".pdf"
    for magic, suffix in _IMAGE_MAGIC:
        if head.startswith(magic):
            return suffix
    # Office formats are ZIP containers: [Content_Types].xml near the start.
    if head.startswith(b"PK\x03\x04") and b"[Content_Types].xml" in data[:4096]:
        ext = os.path.splitext(url.split("?", 1)[0])[1].lower()
        if ext in (".docx", ".pptx", ".xlsx", ".epub"):
            return ext
        return ".docx"
    ext = os.path.splitext(url.split("?", 1)[0])[1].lower()
    if ext in docio.BINARY_DOC_EXT:
        return ext
    return None


#: A page whose payload is a VIDEO, not text. Fetched as HTML it yields the
#: chrome — title, description, comments — and the words are never indexed.
#: Measured 2026-10-30: a YouTube URL added to a notebook became a source of page
#: furniture that answered nothing. The transcript comes from a transcriber; when
#: none is installed the add must FAIL loudly instead of storing the furniture.
MEDIA_URL_RE = re.compile(
    r"^https?://(?:www\.|m\.|music\.)?"
    r"(?:youtube\.com/(?:watch\?|shorts/|embed/|live/|v/)|youtu\.be/)", re.I)

#: Where a transcriber usually lives on a workstation. Only a DISCOVERY order —
#: the config keys below always win, and nothing here is required.
DEFAULT_TRANSCRIBERS = (
    ("~/mcp/yt-whisper/venv/bin/python", "~/mcp/yt-whisper/transcribe.py"),
)


def is_media_url(url):
    """True when the URL addresses a video we must TRANSCRIBE, not read."""
    return bool(MEDIA_URL_RE.match(str(url or "").strip()))


def _transcriber(cfg):
    """(python, script) of the transcriber to use, or ("", "") when none exists."""
    py = str((cfg or {}).get("media_transcriber_python") or "").strip()
    sc = str((cfg or {}).get("media_transcriber_script") or "").strip()
    if py and sc:
        return os.path.expanduser(py), os.path.expanduser(sc)
    for py, sc in DEFAULT_TRANSCRIBERS:
        py, sc = os.path.expanduser(py), os.path.expanduser(sc)
        if os.path.isfile(py) and os.path.isfile(sc):
            return py, sc
    return "", ""


def transcribe_media_url(url, cfg=None, timeout=None):
    """(text, error) — the spoken words of a video URL.

    Runs the transcriber OUT of process: loading a whisper model is seconds to
    minutes and must not live inside the indexer. A failure is returned, never
    raised — `knowledge.add_source` turns it into the error the operator sees.
    """
    cfg = cfg or {}
    py, script = _transcriber(cfg)
    if not script:
        return "", ("no transcriber for a video URL: install yt-dlp + whisper, or "
                    "set index.media_transcriber_python and "
                    "index.media_transcriber_script in Settings ▸ Knowledge")
    model = str(cfg.get("media_transcriber_model") or "small").strip()
    lang = str(cfg.get("media_transcriber_language") or "").strip()
    tmpdir = tempfile.mkdtemp(prefix="longrun-media-")
    out_txt = os.path.join(tmpdir, "transcript.txt")
    cmd = [py, script, url,
           "--output_audio", os.path.join(tmpdir, "audio.m4a"),
           "--output_text", out_txt, "--model", model]
    if lang:
        cmd += ["--language", lang]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=float(timeout or 1800))
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return "", "transcription timed out after %ss" % (timeout or 1800)
    except OSError as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return "", "transcriber could not start (%s): %s" % (script, exc)
    text = ""
    try:
        if os.path.isfile(out_txt):
            with open(out_txt, encoding="utf-8", errors="replace") as f:
                text = f.read().strip()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    if proc.returncode != 0 or not text:
        tail = [x for x in (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]]
        return "", ("transcription failed (exit %s): %s"
                    % (proc.returncode, " / ".join(tail) or "no transcript produced"))
    return text, ""


def fetch_url_info(url, timeout=20, max_kb=None, snapshot_dir=None):
    """Fetch a URL and return ``{text, engine, content_type, final_url, kind,
    bytes, truncated, snapshot, diagnostic}``.

    Handles gzip/deflate/brotli, redirects (``final_url``), HTML, plain text and
    binary documents. A binary document can be snapshotted verbatim into
    ``snapshot_dir`` so the KB keeps a local copy of an online pointer.
    Never raises: network/parse failures return ``{"error": ...}``.
    """
    import gzip
    import shutil
    import tempfile
    import urllib.request
    import zlib

    max_bytes = int(max_kb or os.environ.get("LONGRUN_URL_MAX_KB") or 51200) * 1024
    info = {"text": "", "engine": "", "content_type": "", "final_url": url,
            "kind": "url", "bytes": 0, "truncated": False, "snapshot": None,
            "diagnostic": None}
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "longrun-index/1.0",
            "Accept": ("text/html,application/xhtml+xml,application/pdf,"
                       "image/*,text/plain;q=0.9,*/*;q=0.5"),
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type") or ""
            enc = (resp.headers.get("Content-Encoding") or "").lower()
            raw = resp.read(max_bytes + 1)
            final = resp.geturl() or url
        info["content_type"] = ctype.split(";")[0].strip().lower()
        info["final_url"] = final
        info["bytes"] = len(raw)
        if len(raw) > max_bytes:
            raw, info["truncated"] = raw[:max_bytes], True
        try:
            if "gzip" in enc:
                raw = gzip.decompress(raw)
            elif "deflate" in enc:
                raw = zlib.decompress(raw)
            elif "br" in enc:
                try:
                    import brotli  # optional
                    raw = brotli.decompress(raw)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001 — a truncated stream: use what we have
            pass
        raw = raw[: max_bytes * 4]
        suffix = _sniff_suffix(raw, info["content_type"], final)
        if suffix:
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            try:
                tmp.write(raw)
                tmp.close()
                if snapshot_dir:
                    try:
                        os.makedirs(snapshot_dir, exist_ok=True)
                        import hashlib
                        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:14]
                        snap = os.path.join(snapshot_dir, digest + suffix)
                        shutil.copyfile(tmp.name, snap)
                        info["snapshot"] = snap
                    except OSError:
                        pass
                res = docio.extract(tmp.name, max_kb=int(
                    os.environ.get("LONGRUN_URL_DOC_MAX_KB") or 25600))
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
            info["diagnostic"] = res
            info["engine"] = res.get("engine")
            info["text"] = res.get("text") or ""
            if suffix == ".pdf":
                info["kind"] = "pdf-url"
            elif suffix in docio.IMAGE_EXT:
                info["kind"] = "image-url"
            else:
                info["kind"] = "doc-url"
            if not info["text"]:
                info["error"] = "no text in %s (%s)" % (suffix, res.get("engine"))
            return info
        text = raw.decode("utf-8", "replace")
        if "html" in info["content_type"] or "<html" in text[:400].lower():
            info["engine"] = "html"
            info["text"] = strip_html(text)
        else:
            info["engine"] = info["content_type"] or "text"
            info["text"] = text
        return info
    except Exception as e:  # noqa: BLE001 — a fetch failure is data, not a crash
        info["error"] = "%s: %s" % (type(e).__name__, e)
        return info
