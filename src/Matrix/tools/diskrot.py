"""Matrix experimental tool: diskrot -- read-only disk rot auditor.

Finds reclaimable junk (caches, build artifacts, backups) under an explicit root
and reports bytes per category. IT NEVER DELETES ANYTHING: the caller decides.

Design constraints (learned the hard way on this host):
  - the root must be passed explicitly (default: cwd); no unbounded walk of $HOME
  - depth and file count are capped, so a slow network mount cannot hang the loop
  - symlinks are not followed, so a cycle cannot trap the walk
"""

import os

TOOL_SCHEMA = {
    "description": (
        "[MATRIX experimental] Read-only disk rot audit: report reclaimable bytes for "
        "caches, build artifacts and backups under an explicit root. Never deletes."
    ),
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Root to audit (default: cwd)."},
        "max_depth": {"type": "integer", "default": 6, "description": "Directory depth cap."},
        "max_files": {"type": "integer", "default": 200000, "description": "File count cap."},
        "top": {"type": "integer", "default": 6, "description": "How many top entries to return."},
    },
    "required": [],
    "approval": "auto",
}

# category -> predicate on (name, path parts)
_DIR_JUNK = {
    "__pycache__": "python bytecode cache",
    ".pytest_cache": "pytest cache",
    ".ruff_cache": "ruff cache",
    ".mypy_cache": "mypy cache",
    ".hypothesis": "hypothesis DB",
    "node_modules": "node dependency tree",
    ".archify-preview": "archify transient preview",
}
_FILE_JUNK = {
    ".pyc": "compiled python",
    ".pyo": "compiled python",
    ".bak": "editor backup",
    ".orig": "merge leftover",
    ".tmp": "temp file",
    ".swp": "vim swap",
}
_FILE_PREFIX_JUNK = (".bak-",)


def _walk_junk(root, max_depth, max_files):
    """Yield (category, size_bytes, path) for junk entries. Read-only, capped."""
    found = []
    files = 0
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth >= max_depth:
            dirnames[:] = []
        # a junk dir: measure it whole, then do not descend again
        keep = []
        for d in dirnames:
            full = os.path.join(dirpath, d)
            cat = _DIR_JUNK.get(d)
            if cat:
                size = 0
                n = 0
                for dp, _dn, fns in os.walk(full, followlinks=False):
                    for fn in fns:
                        try:
                            size += os.path.getsize(os.path.join(dp, fn))
                        except OSError:
                            pass
                        n += 1
                        files += 1
                        if files > max_files:
                            break
                    if files > max_files:
                        break
                found.append({"category": cat, "bytes": size, "files": n, "path": full})
            else:
                keep.append(d)
        dirnames[:] = keep
        for fn in filenames:
            files += 1
            if files > max_files:
                return found, True
            ext = os.path.splitext(fn)[1].lower()
            cat = _FILE_JUNK.get(ext)
            if cat is None and fn.startswith(_FILE_PREFIX_JUNK):
                cat = "dated backup"
            if cat is None and fn in ("nohup.out",):
                cat = "nohup log"
            if cat:
                full = os.path.join(dirpath, fn)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                found.append({"category": cat, "bytes": size, "files": 1, "path": full})
    return found, files > max_files


def _fmt(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0 or unit == "TB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0


def execute(args, run_id=None):
    """Audit a root and aggregate reclaimable bytes by category. Never deletes."""
    args = args or {}
    root = os.path.abspath(os.path.expanduser(str(args.get("path") or os.getcwd())))
    if not os.path.isdir(root):
        return {"ok": False, "error": "not a directory: %s" % root}
    try:
        max_depth = max(1, min(int(args.get("max_depth") or 6), 20))
        max_files = max(1000, min(int(args.get("max_files") or 200000), 2000000))
        top = max(1, min(int(args.get("top") or 6), 50))
    except (TypeError, ValueError) as e:
        return {"ok": False, "error": "bad numeric argument: %s" % e}

    try:
        found, truncated = _walk_junk(root, max_depth, max_files)
    except Exception as e:  # noqa: BLE001 - a probe must never break the tool loop
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "path": root}

    by_cat = {}
    total = 0
    for f in found:
        c = by_cat.setdefault(f["category"], {"bytes": 0, "files": 0, "entries": 0})
        c["bytes"] += f["bytes"]
        c["files"] += f["files"]
        c["entries"] += 1
        total += f["bytes"]
    cats = sorted(by_cat.items(), key=lambda kv: kv[1]["bytes"], reverse=True)
    biggest = sorted(found, key=lambda f: f["bytes"], reverse=True)[:top]
    return {
        "ok": True,
        "path": root,
        "reclaimable_bytes": total,
        "reclaimable_human": _fmt(total),
        "truncated": truncated,
        "max_depth": max_depth,
        "categories": [
            {"category": k, "human": _fmt(v["bytes"]), "bytes": v["bytes"],
             "files": v["files"], "entries": v["entries"]}
            for k, v in cats
        ],
        "biggest": [
            {"human": _fmt(f["bytes"]), "bytes": f["bytes"],
             "category": f["category"], "path": f["path"]}
            for f in biggest
        ],
        "note": "read-only audit: nothing was deleted",
    }
