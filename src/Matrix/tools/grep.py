"""Matrix tool namespace: grep — fast regex search over workspace files."""
import fnmatch
import os
import re
from longrun.tools import registry

TOOL_SCHEMAS = {
    "grep.search": {
        "description": (
            "Search files under a workspace directory for a REGULAR EXPRESSION and "
            "return matching file paths, line numbers and line contents. The regex "
            "goes in `pattern` (not a natural-language `query`); `context` adds the "
            "lines around each hit (ripgrep style)."
        ),
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regular expression to search for (e.g. 'TODO|FIXME', 'def main\\(').",
            },
            "path": {
                "type": "string",
                "description": "Directory or file path to search in (defaults to workspace).",
            },
            "glob": {
                "type": "string",
                "description": "Optional filename glob filter (e.g. '*.py', '*.js').",
            },
            "ignore_case": {
                "type": "boolean",
                "description": "Case-insensitive matching (default false).",
                "default": False,
            },
            "context": {
                "type": "integer",
                "description": ("Lines of context before and after each match (0-5, "
                                "default 0). Context lines are printed as 'file-line-text'."),
                "default": 0,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of matching lines to return (default 100).",
                "default": 100,
            },
        },
        "required": ["pattern"],
        "approval": "auto",
    },
}

_SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache",
    ".pytest_cache", ".tox", "dist", "build", ".next", ".nuxt",
})


def execute(args, run_id=None, subtool=None):
    args = args or {}
    raw_pat = str(args.get("pattern") or "")
    if not raw_pat:
        return {"ok": False, "error": "missing required argument: pattern"}

    flags = re.IGNORECASE if args.get("ignore_case") else 0
    try:
        rx = re.compile(raw_pat, flags)
    except re.error as exc:
        return {"ok": False, "error": "invalid regex %r: %s" % (raw_pat, exc)}

    ws = args.get("workspace") or os.getcwd()
    raw_target = args.get("path") or ws
    spec = registry.tool_spec("fs.read") or {}
    roots = list(spec.get("roots") or [ws])
    if ws and ws not in roots:
        roots.append(ws)
    # v834: a RELATIVE `path` means "relative to the session workspace", exactly
    # as `fs.read`/`fs.write` resolve it (JAG-191). Without `base=ws` this fell
    # back to the harness checkout, so a session whose workspace is another
    # repository answered "path does not exist" for a directory that is right
    # there — measured 2026-11-06 on the SWE slice (two search rounds lost).
    target, err = registry.resolve_path(str(raw_target), roots, base=ws)
    if err:
        return {"ok": False, "error": err}
    if not os.path.exists(target):
        return {"ok": False, "error": "path does not exist: %s" % target}

    file_glob = str(args.get("glob") or "").strip()
    limit = max(1, min(int(args.get("limit") or 100), 500))
    context = max(0, min(int(args.get("context") or 0), 5))
    matches = []
    out_lines = []
    files_scanned = 0
    truncated = False

    def _scan_file(fpath):
        nonlocal files_scanned, truncated
        if file_glob and not fnmatch.fnmatch(os.path.basename(fpath), file_glob):
            return
        try:
            if os.path.getsize(fpath) > 2 * 1024 * 1024:
                return
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                # Skip binary files quickly
                sample = f.read(4096)
                if "\x00" in sample:
                    return
                f.seek(0)
                text_lines = f.read().splitlines()
        except OSError:
            return
        files_scanned += 1
        rel = os.path.relpath(fpath, target) if os.path.isdir(target) else os.path.basename(fpath)
        hits = [n for n, line in enumerate(text_lines, 1) if rx.search(line)]
        if not hits:
            return
        room = limit - len(matches)
        if len(hits) > room:
            hits = hits[:max(0, room)]
            truncated = True
        for lineno in hits:
            matches.append({
                "file": rel,
                "line": lineno,
                "text": text_lines[lineno - 1][:300],
            })
        # ripgrep convention: `file:line:text` for a hit, `file-line-text` for context.
        printed = set()
        for lineno in hits:
            lo = max(1, lineno - context)
            hi = min(len(text_lines), lineno + context)
            for n in range(lo, hi + 1):
                if n in printed:
                    continue
                printed.add(n)
                sep = ":" if n == lineno else "-"
                out_lines.append("%s%s%d%s%s"
                                 % (rel, sep, n, sep, text_lines[n - 1][:300]))
        if truncated:
            return

    if os.path.isfile(target):
        _scan_file(target)
    else:
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".git"))
            for fn in sorted(filenames):
                _scan_file(os.path.join(dirpath, fn))
                if truncated:
                    break
            if truncated:
                break

    return {
        "ok": True,
        "pattern": raw_pat,
        "path": target,
        "files_scanned": files_scanned,
        "count": len(matches),
        "truncated": truncated,
        "matches": matches,
        "stdout": "\n".join(out_lines) if out_lines else "(no matches)",
    }
