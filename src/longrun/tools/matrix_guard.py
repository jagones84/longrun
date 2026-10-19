#!/usr/bin/env python3
"""Matrix scaffold and deterministic Nucleus write-protection guard.

Enforces the strict two-zone architecture:
  1. NUCLEUS (`src/longrun/**`, `webui/**`, `config/**`, `deploy/**`, `tests/**`,
     `RULES.md`, `README.md`, `pyproject.toml`): fixed and immutable during agent
     self-evolution turns.
  2. MATRIX (`src/Matrix/**`, `.Matrix/**`): live-editable self-evolution zone.
"""
import hashlib
import json
import os
import re

from longrun.util.paths import REPO_ROOT as REPO

MATRIX_SUBDIRS = ("agent", "core", "memory", "model", "plan", "tools", "util", "webui")
DOT_SUBDIRS = ("trash", "docs", "rules", "skills", "checkpoints")

NUCLEUS_PROTECTED_REL = (
    os.path.join("src", "longrun"),
    "webui",
    "config",
    "deploy",
    "tests",
    ".trae",
    "RULES.md",
    "README.md",
    "pyproject.toml",
)

MATRIX_ALLOWED_REL = (
    os.path.join("src", "Matrix"),
    ".Matrix",
    "data",
    os.path.join("skills", "created"),
)

_DEFAULT_HANDOFF = (
    "# Matrix Self-Evolution — Short-Term Handoff\n\n"
    "## Current Evolution Goal\n"
    "- None active.\n\n"
    "## Recent Changes & Verification\n"
    "- Initialized Matrix layout.\n\n"
    "## Failed Attempts / Do Not Repeat\n"
    "- Never attempt to modify Nucleus files (`src/longrun/`, `webui/`, `config/`, `RULES.md`).\n"
)

_DEFAULT_MANUAL = (
    "# Matrix Self-Evolution — Architecture & Operations Manual\n\n"
    "## Directory Layout\n"
    "- `src/Matrix/`: live-editable Python packages mirroring `src/longrun/` (`agent`, `core`, "
    "`memory`, `model`, `plan`, `tools`, `util`, `webui`).\n"
    "- `.Matrix/trash/`: temporary test scripts and sandbox experiments (clean up after use).\n"
    "- `.Matrix/docs/`: `HANDOFF.md` (short-term state) and `MANUAL.md` (verified recipes).\n"
    "- `.Matrix/rules/`: `<NN>-<section>.md` system prompt addenda automatically hooked into the prompt.\n"
    "- `.Matrix/skills/`: `<name>/SKILL.md` auto-created skills segregated from external skills.\n"
    "- `.Matrix/checkpoints/`: 3 atomic rollback slots (`slot_1`, `slot_2`, `slot_3`).\n\n"
    "## Adding a Dynamic Tool\n"
    "Create `src/Matrix/tools/<name>.py` defining `TOOL_SCHEMA = {...}` and "
    "`def execute(args, run_id=None) -> dict:`. Call `matrix{action:\"hotload\"}` to validate.\n"
)


def _roots(repo_root=None):
    root = os.path.abspath(repo_root or REPO)
    if repo_root is None and os.environ.get("LONGRUN_MATRIX_SRC"):
        msrc = os.path.abspath(os.environ["LONGRUN_MATRIX_SRC"])
    else:
        msrc = os.path.abspath(os.path.join(root, "src", "Matrix"))
    if repo_root is None and os.environ.get("LONGRUN_MATRIX_DOT"):
        mdot = os.path.abspath(os.environ["LONGRUN_MATRIX_DOT"])
    else:
        mdot = os.path.abspath(os.path.join(root, ".Matrix"))
    return root, msrc, mdot


def _under(path, parent):
    try:
        p = os.path.realpath(path)
        r = os.path.realpath(parent)
        return p == r or p.startswith(r + os.sep)
    except OSError:
        return False


def ensure_layout(repo_root=None):
    """Create the mirrored `src/Matrix/` and `.Matrix/` directory trees if missing."""
    root, msrc, mdot = _roots(repo_root)
    try:
        os.makedirs(msrc, exist_ok=True)
        init_py = os.path.join(msrc, "__init__.py")
        if not os.path.exists(init_py):
            with open(init_py, "w", encoding="utf-8") as f:
                f.write('"""Matrix self-evolving codebase package."""\n')
        manifest = os.path.join(msrc, "manifest.json")
        if not os.path.exists(manifest):
            with open(manifest, "w", encoding="utf-8") as f:
                json.dump({"version": "1.0", "subdirs": list(MATRIX_SUBDIRS)}, f, indent=2)
        for sub in MATRIX_SUBDIRS:
            d = os.path.join(msrc, sub)
            os.makedirs(d, exist_ok=True)
            if sub != "webui":
                sub_init = os.path.join(d, "__init__.py")
                if not os.path.exists(sub_init):
                    with open(sub_init, "w", encoding="utf-8") as f:
                        f.write('"""Matrix %s subpackage."""\n' % sub)
        for sub in DOT_SUBDIRS:
            os.makedirs(os.path.join(mdot, sub), exist_ok=True)
        handoff = os.path.join(mdot, "docs", "HANDOFF.md")
        if not os.path.exists(handoff):
            with open(handoff, "w", encoding="utf-8") as f:
                f.write(_DEFAULT_HANDOFF)
        manual = os.path.join(mdot, "docs", "MANUAL.md")
        if not os.path.exists(manual):
            with open(manual, "w", encoding="utf-8") as f:
                f.write(_DEFAULT_MANUAL)
        return {"ok": True, "matrix_src": msrc, "matrix_dot": mdot}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def is_matrix_writable(path, repo_root=None):
    """True when `path` resolves inside `src/Matrix/`, `.Matrix/`, `data/`, or `skills/created/`."""
    root, msrc, mdot = _roots(repo_root)
    p = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))
    if _under(p, msrc) or _under(p, mdot):
        return True
    for rel in MATRIX_ALLOWED_REL:
        if _under(p, os.path.join(root, rel)):
            return True
    return False


def is_nucleus_path(path, repo_root=None):
    """True when `path` resolves inside a protected Nucleus directory or file."""
    root, msrc, mdot = _roots(repo_root)
    p = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))
    if _under(p, msrc) or _under(p, mdot):
        return False
    for rel in NUCLEUS_PROTECTED_REL:
        if _under(p, os.path.join(root, rel)):
            return True
    return False


def check_write_allowed(path, repo_root=None):
    """Deterministic write gate for `fs.write` and `fs.edit`.

    Paths outside `repo_root` (e.g. a separate user workspace or scratch dir)
    are governed by the normal workspace policy. Paths inside `repo_root` that
    belong to Nucleus are hard-blocked.
    """
    if not path:
        return False, "empty path"
    root, msrc, mdot = _roots(repo_root)
    p = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))
    if not _under(p, root):
        return True, ""
    if is_matrix_writable(p, root):
        return True, ""
    if is_nucleus_path(p, root):
        try:
            rel = os.path.relpath(os.path.realpath(p), os.path.realpath(root)).replace("\\", "/")
        except ValueError:
            rel = str(path)
        return False, (
            "NUCLEUS_PROTECTED: '%s' belongs to the immutable Nucleus. "
            "Agent self-evolution writes inside the harness repository are strictly "
            "restricted to src/Matrix/ and .Matrix/." % rel
        )
    return True, ""


_WRITE_OP_RE = re.compile(
    r"(?:>>?|\btee\b|\bsed\s+-i\b|\brm\b|\bmv\b|\bcp\b|\bchmod\b|\btruncate\b|"
    r"shutil\.|open\s*\([^)]*['\"][wa+])"
)
_NUCLEUS_TOKEN_RE = re.compile(
    r"(?:^|[\s'\"=/\\])(src[/\\]longrun|webui[/\\]|config[/\\]|deploy[/\\]|RULES\.md|pyproject\.toml)"
)


def check_shell_command(command, cwd=None, repo_root=None):
    """Reject shell commands that attempt to write/delete protected Nucleus paths."""
    cmd = str(command or "")
    if not cmd.strip():
        return True, ""
    root, _msrc, _mdot = _roots(repo_root)
    eff_cwd = os.path.realpath(cwd or root)
    if _under(eff_cwd, root):
        hit = _NUCLEUS_TOKEN_RE.search(cmd)
        if hit and _WRITE_OP_RE.search(cmd):
            # Allow if the only match is actually src/Matrix/webui
            if "src/Matrix" in cmd or "src\\Matrix" in cmd:
                cleaned = cmd.replace("src/Matrix/webui", "").replace("src\\Matrix\\webui", "")
                if not _NUCLEUS_TOKEN_RE.search(cleaned):
                    return True, ""
            return False, (
                "NUCLEUS_PROTECTED: shell command targets immutable Nucleus path (%s). "
                "Modify only src/Matrix/ or .Matrix/." % hit.group(1)
            )
    return True, ""


def _iter_nucleus_files(repo_root=None):
    root, _msrc, _mdot = _roots(repo_root)
    for rel in ("src/longrun", "webui", "config", "RULES.md", "README.md", "pyproject.toml"):
        target = os.path.join(root, *rel.split("/"))
        if os.path.isfile(target):
            yield target
        elif os.path.isdir(target):
            for dirpath, dirnames, filenames in os.walk(target):
                dirnames[:] = [d for d in dirnames if d != "__pycache__"]
                for fn in filenames:
                    if fn.endswith((".py", ".yaml", ".json", ".html", ".js", ".css", ".md")):
                        p = os.path.join(dirpath, fn)
                        try:
                            if os.path.getsize(p) <= 2_000_000:
                                yield p
                        except OSError:
                            continue


def snapshot_nucleus_digests(repo_root=None):
    """Capture content snapshots of Nucleus files before an untrusted command runs."""
    snap = {}
    for p in _iter_nucleus_files(repo_root):
        try:
            with open(p, "rb") as f:
                data = f.read()
            snap[p] = (hashlib.sha256(data).hexdigest(), data)
        except OSError:
            continue
    return snap


def restore_if_nucleus_tampered(before_digests, repo_root=None):
    """Compare current Nucleus files against `before_digests` and revert any modifications."""
    if not before_digests:
        return []
    reverted = []
    for p, (digest, raw) in before_digests.items():
        try:
            if not os.path.isfile(p):
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(raw)
                reverted.append(p)
                continue
            with open(p, "rb") as f:
                cur = f.read()
            if hashlib.sha256(cur).hexdigest() != digest:
                with open(p, "wb") as f:
                    f.write(raw)
                reverted.append(p)
        except OSError:
            continue
    return reverted
