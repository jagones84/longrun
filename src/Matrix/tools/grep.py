"""Matrix tool namespace: grep — fast regex search over workspace files."""
import fnmatch
import os
import re
from longrun.tools import registry

TOOL_SCHEMAS = {
    "grep.search": {
        "description": (
            "Search files under a workspace directory for a regular expression pattern. "
            "Returns matching file paths, line numbers, and line contents."
        ),
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regular expression pattern to search for.",
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
    raw_pat = str(args.get("pattern") or args.get("query") or "")
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
    target, err = registry.resolve_path(str(raw_target), roots)
    if err:
        return {"ok": False, "error": err}
    if not os.path.exists(target):
        return {"ok": False, "error": "path does not exist: %s" % target}

    file_glob = str(args.get("glob") or "").strip()
    limit = max(1, min(int(args.get("limit") or 100), 500))
    matches = []
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
                files_scanned += 1
                rel = os.path.relpath(fpath, target) if os.path.isdir(target) else os.path.basename(fpath)
                for lineno, line in enumerate(f, 1):
                    if rx.search(line):
                        matches.append({
                            "file": rel,
                            "line": lineno,
                            "text": line.rstrip("\r\n")[:300],
                        })
                        if len(matches) >= limit:
                            truncated = True
                            return
        except OSError:
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

    lines = ["%s:%d:%s" % (m["file"], m["line"], m["text"]) for m in matches]
    return {
        "ok": True,
        "pattern": raw_pat,
        "path": target,
        "files_scanned": files_scanned,
        "count": len(matches),
        "truncated": truncated,
        "matches": matches,
        "stdout": "\n".join(lines) if lines else "(no matches)",
    }
