"""Shared chunking + file discovery for the indexes (JAG-400) — stdlib only.

Both stores use this: the per-workspace codebase index and the global knowledge
base. Chunks are AST-aware for Python (the ``ast`` module), heading/paragraph-aware
for documents, and a line window is the fallback for other languages.
"""
import ast
import os
import re
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
EXTLESS = {"dockerfile": "dockerfile", "makefile": "makefile", "rakefile": "ruby", "procfile": "text"}


def lang_for(rel):
    """(language, kind) for a path, or (None, None) when not indexable."""
    name = os.path.basename(rel).lower()
    ext = os.path.splitext(name)[1]
    if ext in CODE_EXT:
        return CODE_EXT[ext], "code"
    if ext in DOC_EXT:
        return DOC_EXT[ext], "doc"
    if ext in docio.BINARY_DOC_EXT:
        # JAG-403j: PDF/DOCX/… are extracted to text by ``docio`` (see read_text).
        return "doc", "doc"
    if name in EXTLESS:
        return EXTLESS[name], "code"
    return None, None


# ---------------------------------------------------------------- gitignore ---
def load_gitignore(root):
    rules = []
    try:
        with open(os.path.join(root, ".gitignore"), encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or line.startswith("!"):
                    continue
                rules.append({"pat": line.strip("/"), "dir": line.endswith("/"),
                              "anchored": line.startswith("/")})
    except Exception:  # noqa: BLE001
        pass
    return rules


def _git_ignored(rel, name, is_dir, rules):
    for r in rules:
        pat = r["pat"]
        if r["anchored"] or "/" in pat:
            if rel == pat or rel.startswith(pat + "/") or fnmatch(rel, pat):
                return True
        elif fnmatch(name, pat):
            return True
        if r["dir"] and is_dir and fnmatch(name, pat):
            return True
    return False


def extra_ignored(name, rel, globs):
    return any(fnmatch(name, g) or fnmatch(rel, g) for g in (globs or []))


def walk(root, cfg):
    """Yield (rel, abspath, lang, kind) for indexable files under `root`."""
    gi = load_gitignore(root)
    globs = cfg.get("ignore") or []
    maxb = int(cfg.get("max_file_kb") or 512) * 1024
    docmax = int(cfg.get("doc_max_kb") or 25600) * 1024   # JAG-403j: docs are bigger
    root = os.path.realpath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        rel_dir = os.path.relpath(dirpath, root)
        keep = []
        for d in dirnames:
            rd = d if rel_dir == "." else os.path.join(rel_dir, d)
            if _git_ignored(rd, d, True, gi) or extra_ignored(d, rd, globs):
                continue
            keep.append(d)
        dirnames[:] = keep
        for fn in filenames:
            rel = fn if rel_dir == "." else os.path.join(rel_dir, fn)
            lang, kind = lang_for(rel)
            if not lang:
                continue
            if _git_ignored(rel, fn, False, gi) or extra_ignored(fn, rel, globs):
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
    """Readable text from a URL (public internet). HTML is stripped to text."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "longrun-index/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        data = resp.read(2 * 1024 * 1024)
    text = data.decode("utf-8", "replace")
    if "html" in ctype or "<html" in text[:400].lower():
        return strip_html(text)
    return text
