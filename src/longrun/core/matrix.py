#!/usr/bin/env python3
"""Matrix self-evolution engine — checkpoints, local Git, dynamic tools, prompt hooks & warm restart.

Implements the mutable Matrix half of the Nucleus/Matrix architecture:
  - 3 atomic checkpoint slots (`slot_1`, `slot_2`, `slot_3`) in `.Matrix/checkpoints/`
  - Local Git repository in `src/Matrix/.git` (zero token needed, capped at 20 commits)
  - Scratch test runner & isolated venv in `.Matrix/trash/` and `.Matrix/venv`
  - Fail-open dynamic tool discovery from `src/Matrix/tools/<name>.py`
  - Hardcoded Matrix system prompt instructions + `.Matrix/rules/*.md` addenda hook
  - Optional shadow WebUI (`src/Matrix/webui/index.html`) with automatic fallback to Nucleus
  - Session-preserving warm restart ticket (`.Matrix/resume_ticket.json`)
"""
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback

from longrun.tools import matrix_guard
from longrun.util.fswrite import read_json, write_json
from longrun.util.paths import REPO_ROOT as REPO

SLOT_IDS = (1, 2, 3)
MAX_GIT_COMMITS = 20
HOOK_SUBPACKAGES = (
    "agent", "core", "integrations", "interop", "memory",
    "model", "orbit", "orchestrate", "plan", "research", "util"
)
_LOCK = threading.RLock()
_TOOL_CACHE = {}  # {repo_root: {"stamps": {}, "tools": {}, "errors": []}}
_HOOK_CACHE = {}  # {repo_root: {"stamps": {}, "modules": {}, "errors": [], "runtime_errors": []}}
_ENABLED_OVERRIDE = None  # None = read from config approvals.matrix_enabled (default True)


def is_enabled():
    """True when the live Matrix zone (`src/Matrix` & `.Matrix`) is active."""
    if _ENABLED_OVERRIDE is not None:
        return bool(_ENABLED_OVERRIDE)
    try:
        from longrun.tools import registry
        ap = (registry.load_config().get("approvals") or {})
        return bool(ap.get("matrix_enabled", True))
    except Exception:  # noqa: BLE001
        return True


def set_enabled(enabled):
    """Enable or disable all live `src/Matrix` and `.Matrix` effects immediately without restart."""
    global _ENABLED_OVERRIDE
    val = bool(enabled)
    _ENABLED_OVERRIDE = val
    try:
        from longrun.tools import registry
        cfg = registry.load_config()
        cfg.setdefault("approvals", {})["matrix_enabled"] = val
        registry.save_config(cfg)
        registry.load_config(reload=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.memory import skills
        skills.list_skills(reload=True)
    except Exception:  # noqa: BLE001
        pass
    _ledger("matrix.toggle", enabled=val)
    return {"ok": True, "enabled": val}

MATRIX_SYSTEM_PROMPT = (
    "## Matrix Self-Evolution (Nucleus vs. Matrix)\n"
    "- **NUCLEUS (Immutable):** `src/longrun/**`, `webui/**`, `config/**`, `tests/**`, `RULES.md` "
    "are hard-protected (`NUCLEUS_PROTECTED`). Import Nucleus functions freely; never edit them.\n"
    "- **MATRIX (`src/Matrix/` & `.Matrix/`):** all 13 subpackages (`agent`, `core`, `integrations`, "
    "`interop`, `memory`, `model`, `orbit`, `orchestrate`, `plan`, `research`, `tools`, `util`, `webui`) "
    "are live-hooked via `src/Matrix/<subpkg>/hooks.py` (fail-open `matrix.call_hook`), "
    "`src/Matrix/tools/<name>.py` (`TOOL_SCHEMA` + `execute`), `/api/matrix/ext/*`, and "
    "`src/Matrix/webui/plugins.js`. Run tests in `.Matrix/trash/`, maintain `.Matrix/docs/HANDOFF.md` "
    "& `MANUAL.md`, put rules in `.Matrix/rules/*.md` and skills in `.Matrix/skills/<name>/SKILL.md`, "
    "and use `checkpoint_save` (slots 1..3), `git_commit` (max 20), `hotload`, or `restart`."
)


def _roots(repo_root=None):
    return matrix_guard._roots(repo_root)


def _ledger(kind, **fields):
    try:
        from longrun.util import improve
        improve.ledger_add(kind, origin="matrix", **fields)
    except Exception:  # noqa: BLE001
        pass


def _format_matrix_error(exc, target_file=None):
    """Extract exact 1-based line number (`line`) and offending source line (`code_line`) from an exception."""
    lineno = getattr(exc, "lineno", None)
    code_line = (getattr(exc, "text", None) or "").strip()
    fname = os.path.basename(str(getattr(exc, "filename", None) or target_file or ""))
    tb_frames = traceback.extract_tb(getattr(exc, "__traceback__", None))
    if tb_frames:
        chosen = tb_frames[-1]
        if target_file:
            t_norm = os.path.normcase(os.path.abspath(target_file))
            for fr in reversed(tb_frames):
                if os.path.normcase(os.path.abspath(fr.filename)) == t_norm:
                    chosen = fr
                    break
        if lineno is None:
            lineno = chosen.lineno
        if not code_line:
            code_line = (chosen.line or "").strip()
        if not fname:
            fname = os.path.basename(chosen.filename)
    loc = ("%s:line %d" % (fname or "matrix", int(lineno))) if lineno else (fname or "matrix")
    msg = "%s at %s: %s" % (type(exc).__name__, loc, exc)
    if code_line:
        msg += " [code: %s]" % code_line[:120]
    return {
        "error": msg,
        "line": int(lineno) if lineno is not None else None,
        "code_line": code_line[:200],
        "traceback": traceback.format_exc()[-1000:],
    }


def _verified_store_path(repo_root=None):
    _root, _msrc, mdot = _roots(repo_root)
    os.makedirs(mdot, exist_ok=True)
    return os.path.join(mdot, "verified_targets.json")


def _file_sha256(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def _resolve_target_path(kind, name, repo_root=None):
    _root, msrc, mdot = _roots(repo_root)
    k = str(kind or "tool").strip().lower()
    nm = str(name or "").strip().replace("\\", "/").strip("/")
    if k == "tool":
        if nm.endswith(".py"):
            nm = nm[:-3]
        return "tool", nm, os.path.join(msrc, "tools", nm + ".py")
    if k == "hook":
        return "hook", nm, os.path.join(msrc, nm, "hooks.py")
    if k == "module":
        if nm.endswith(".py"):
            nm = nm[:-3]
        nm = nm.replace(".", "/")
        parts = [p for p in nm.split("/") if p and p != ".."]
        if len(parts) < 2 or parts[0] not in HOOK_SUBPACKAGES:
            return "module", nm, ""
        return "module", "/".join(parts), os.path.join(msrc, *parts) + ".py"
    if k == "skill":
        return "skill", nm, os.path.join(mdot, "skills", nm, "SKILL.md")
    if k == "rule":
        if not nm.endswith(".md"):
            nm += ".md"
        return "rule", os.path.basename(nm), os.path.join(mdot, "rules", os.path.basename(nm))
    if k == "webui":
        bn = os.path.basename(nm) or "index.html"
        return "webui", bn, os.path.join(msrc, "webui", bn)
    return k, nm, ""


def _record_verified(kind, name, script_name="", repo_root=None):
    k, nm, fpath = _resolve_target_path(kind, name, repo_root)
    if not fpath or not os.path.isfile(fpath):
        return
    sha = _file_sha256(fpath)
    if not sha:
        return
    vp = _verified_store_path(repo_root)
    store = read_json(vp, {})
    if not isinstance(store, dict):
        store = {}
    store["%s:%s" % (k, nm)] = {
        "kind": k,
        "name": nm,
        "sha256": sha,
        "script": script_name,
        "ts": round(time.time(), 3),
    }
    write_json(vp, store)


# ------------------------------------------------ 3-slot atomic checkpoints ---

def _ckpt_dir(repo_root=None):
    _root, _msrc, mdot = _roots(repo_root)
    d = os.path.join(mdot, "checkpoints")
    os.makedirs(d, exist_ok=True)
    return d


def _ckpt_index_path(repo_root=None):
    return os.path.join(_ckpt_dir(repo_root), "index.json")


def checkpoint_list(repo_root=None):
    """Return metadata for the 3 checkpoint slots."""
    idx = read_json(_ckpt_index_path(repo_root), {})
    if not isinstance(idx, dict):
        idx = {}
    out = []
    for s in SLOT_IDS:
        key = "slot_%d" % s
        rec = idx.get(key) or {"slot": s, "empty": True}
        out.append(rec)
    return out


def _copy_tree_clean(src, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst, ignore_errors=True)
    if not os.path.isdir(src):
        os.makedirs(dst, exist_ok=True)
        return
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv"),
    )


def checkpoint_save(slot, label="", repo_root=None):
    """Save `src/Matrix/`, `.Matrix/rules/`, and `.Matrix/skills/` into slot 1, 2, or 3."""
    try:
        slot_num = int(slot)
    except (TypeError, ValueError):
        return {"ok": False, "error": "slot must be an integer in (1, 2, 3)"}
    if slot_num not in SLOT_IDS:
        return {"ok": False, "error": "invalid slot %d: only 3 slots (1, 2, 3) are available" % slot_num}
    matrix_guard.ensure_layout(repo_root)
    root, msrc, mdot = _roots(repo_root)
    cdir = _ckpt_dir(repo_root)
    slot_key = "slot_%d" % slot_num
    sdir = os.path.join(cdir, slot_key)
    with _LOCK:
        try:
            os.makedirs(sdir, exist_ok=True)
            _copy_tree_clean(msrc, os.path.join(sdir, "src_Matrix"))
            _copy_tree_clean(os.path.join(mdot, "rules"), os.path.join(sdir, "dot_rules"))
            _copy_tree_clean(os.path.join(mdot, "skills"), os.path.join(sdir, "dot_skills"))
            _copy_tree_clean(os.path.join(mdot, "docs"), os.path.join(sdir, "dot_docs"))
            idx = read_json(_ckpt_index_path(repo_root), {})
            if not isinstance(idx, dict):
                idx = {}
            meta = {
                "slot": slot_num,
                "empty": False,
                "label": str(label or ("slot %d" % slot_num))[:120],
                "ts": round(time.time(), 3),
            }
            idx[slot_key] = meta
            write_json(_ckpt_index_path(repo_root), idx)
            _ledger("matrix.checkpoint_save", slot=slot_num, label=meta["label"])
            return {"ok": True, **meta}
        except OSError as e:
            return {"ok": False, "error": "checkpoint_save failed: %s" % e}


def _restore_dir_preserving_git(src_snap, target_dir):
    """Restore `target_dir` contents from `src_snap` while keeping `.git` intact."""
    os.makedirs(target_dir, exist_ok=True)
    for name in os.listdir(target_dir):
        if name == ".git":
            continue
        p = os.path.join(target_dir, name)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                os.remove(p)
            except OSError:
                pass
    if not os.path.isdir(src_snap):
        return
    for name in os.listdir(src_snap):
        if name == ".git":
            continue
        sp = os.path.join(src_snap, name)
        dp = os.path.join(target_dir, name)
        if os.path.isdir(sp):
            shutil.copytree(sp, dp)
        else:
            shutil.copy2(sp, dp)


def checkpoint_rollback(slot, repo_root=None):
    """Atomically restore `src/Matrix/`, `.Matrix/rules/`, and `.Matrix/skills/` from slot 1..3."""
    try:
        slot_num = int(slot)
    except (TypeError, ValueError):
        return {"ok": False, "error": "slot must be an integer in (1, 2, 3)"}
    if slot_num not in SLOT_IDS:
        return {"ok": False, "error": "invalid slot %d: must be 1, 2, or 3" % slot_num}
    root, msrc, mdot = _roots(repo_root)
    slot_key = "slot_%d" % slot_num
    sdir = os.path.join(_ckpt_dir(repo_root), slot_key)
    if not os.path.isdir(os.path.join(sdir, "src_Matrix")):
        return {"ok": False, "error": "checkpoint slot %d is empty" % slot_num}
    with _LOCK:
        try:
            _restore_dir_preserving_git(os.path.join(sdir, "src_Matrix"), msrc)
            _restore_dir_preserving_git(os.path.join(sdir, "dot_rules"), os.path.join(mdot, "rules"))
            _restore_dir_preserving_git(os.path.join(sdir, "dot_skills"), os.path.join(mdot, "skills"))
            if os.path.isdir(os.path.join(sdir, "dot_docs")):
                _restore_dir_preserving_git(os.path.join(sdir, "dot_docs"), os.path.join(mdot, "docs"))
            hl = hotload(repo_root)
            _ledger("matrix.checkpoint_rollback", slot=slot_num)
            return {"ok": True, "slot": slot_num, "hotload": hl}
        except OSError as e:
            return {"ok": False, "error": "checkpoint_rollback failed: %s" % e}


# ----------------------------------------- local Git repo (20-commit cap) -----

def _git_paths(repo_root=None):
    _root, msrc, mdot = _roots(repo_root)
    return msrc, os.path.join(mdot, "git")


def _run_git(argv, msrc, git_dir=None):
    cmd = ["git"]
    if git_dir:
        cmd.extend(["--git-dir=" + git_dir, "--work-tree=" + msrc])
    cmd.extend(list(argv))
    p = subprocess.run(
        cmd,
        cwd=msrc,
        capture_output=True,
        text=True,
        timeout=25,
    )
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def git_init_if_needed(repo_root=None):
    """Initialize a standalone local Git repo for `src/Matrix` stored in `.Matrix/git` (no token needed)."""
    matrix_guard.ensure_layout(repo_root)
    msrc, git_dir = _git_paths(repo_root)
    gi = os.path.join(msrc, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8") as f:
            f.write("__pycache__/\n*.pyc\n*.pyo\n")
    if not os.path.isdir(os.path.join(git_dir, "objects")):
        os.makedirs(git_dir, exist_ok=True)
        rc, out, err = _run_git(["init"], msrc, git_dir)
        if rc != 0:
            return {"ok": False, "error": err or out}
        _run_git(["config", "user.name", "Longrun Matrix"], msrc, git_dir)
        _run_git(["config", "user.email", "matrix@longrun.local"], msrc, git_dir)
        _run_git(["add", "-A"], msrc, git_dir)
        _run_git(["commit", "-m", "chore(matrix): initialize Matrix baseline"], msrc, git_dir)
    return {"ok": True, "cwd": msrc, "git_dir": git_dir}


def _prune_git_history(msrc, git_dir, max_commits=MAX_GIT_COMMITS):
    """Keep at most `max_commits` in `.Matrix/git` by grafting the 20th newest commit as root."""
    rc, out, _err = _run_git(["rev-list", "HEAD"], msrc, git_dir)
    if rc != 0 or not out:
        return
    revs = [line.strip() for line in out.splitlines() if line.strip()]
    if len(revs) <= max_commits:
        return
    kept_chronological = list(reversed(revs[:max_commits]))
    prev_new = None
    for sha in kept_chronological:
        rc_t, tree_sha, _ = _run_git(["rev-parse", "%s^{tree}" % sha], msrc, git_dir)
        rc_m, msg, _ = _run_git(["log", "-1", "--format=%B", sha], msrc, git_dir)
        if rc_t != 0 or not tree_sha:
            return
        cmd = ["commit-tree", tree_sha, "-m", msg or "matrix commit"]
        if prev_new:
            cmd.extend(["-p", prev_new])
        rc_c, new_sha, _ = _run_git(cmd, msrc, git_dir)
        if rc_c != 0 or not new_sha:
            return
        prev_new = new_sha
    if prev_new:
        _run_git(["update-ref", "refs/heads/master", prev_new], msrc, git_dir)
        _run_git(["update-ref", "HEAD", prev_new], msrc, git_dir)
        _run_git(["symbolic-ref", "HEAD", "refs/heads/master"], msrc, git_dir)


def git_commit(message, repo_root=None):
    """Stage and commit `src/Matrix/` changes locally (no token needed), capping history at 20."""
    init = git_init_if_needed(repo_root)
    if not init.get("ok"):
        return init
    msrc, git_dir = init["cwd"], init["git_dir"]
    msg = str(message or "matrix evolution step").strip()[:240]
    _run_git(["add", "-A"], msrc, git_dir)
    rc_st, st_out, _ = _run_git(["status", "--porcelain"], msrc, git_dir)
    if rc_st == 0 and not st_out:
        rc_h, head_sha, _ = _run_git(["rev-parse", "--short", "HEAD"], msrc, git_dir)
        return {"ok": True, "commit": head_sha, "noop": True, "message": msg}
    rc, out, err = _run_git(["commit", "-m", msg], msrc, git_dir)
    if rc != 0:
        return {"ok": False, "error": err or out}
    _prune_git_history(msrc, git_dir, MAX_GIT_COMMITS)
    rc_h, head_sha, _ = _run_git(["rev-parse", "--short", "HEAD"], msrc, git_dir)
    _ledger("matrix.git_commit", commit=head_sha, message=msg)
    return {"ok": True, "commit": head_sha, "message": msg}


def git_log(limit=MAX_GIT_COMMITS, repo_root=None):
    """Return up to `limit` (capped at 20) commits from `.Matrix/git`."""
    init = git_init_if_needed(repo_root)
    if not init.get("ok"):
        return init
    msrc, git_dir = init["cwd"], init["git_dir"]
    cap = max(1, min(int(limit or MAX_GIT_COMMITS), MAX_GIT_COMMITS))
    rc, out, err = _run_git(["log", "-n", str(cap), "--pretty=format:%h|%ct|%s"], msrc, git_dir)
    if rc != 0:
        return {"ok": False, "error": err or out, "commits": []}
    commits = []
    for line in out.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append({"sha": parts[0], "ts": int(parts[1] or 0), "subject": parts[2]})
    return {"ok": True, "commits": commits, "count": len(commits)}


def git_diff(rev=None, repo_root=None):
    """Return unified diff in `src/Matrix` against `rev` (or working tree vs HEAD)."""
    init = git_init_if_needed(repo_root)
    if not init.get("ok"):
        return init
    msrc, git_dir = init["cwd"], init["git_dir"]
    argv = ["diff", str(rev)] if rev else ["diff", "HEAD"]
    rc, out, err = _run_git(argv, msrc, git_dir)
    if rc != 0:
        return {"ok": False, "error": err or out}
    return {"ok": True, "diff": out}


def git_reset(rev="HEAD", repo_root=None):
    """Reset `src/Matrix` working tree and index to `rev` and hotload."""
    init = git_init_if_needed(repo_root)
    if not init.get("ok"):
        return init
    msrc, git_dir = init["cwd"], init["git_dir"]
    target = str(rev or "HEAD").strip()
    rc, out, err = _run_git(["reset", "--hard", target], msrc, git_dir)
    if rc != 0:
        return {"ok": False, "error": err or out}
    _run_git(["clean", "-fd"], msrc, git_dir)
    hl = hotload(repo_root)
    _ledger("matrix.git_reset", rev=target)
    return {"ok": True, "rev": target, "hotload": hl}


# ------------------------------------ .Matrix/trash test runner & cleanup -----

def run_test(script_name="test_matrix.py", code=None, install_deps=None,
             timeout_secs=60, target=None, repo_root=None):
    """Execute a test script inside `.Matrix/trash/` (with optional `.Matrix/venv` deps).

    When the test passes (exit_code == 0), records the SHA-256 verification proof
    for `target` (e.g. 'tool:fast_calc' or 'hook:plan') and any Matrix module
    imported by the test script in `.Matrix/verified_targets.json`.
    """
    matrix_guard.ensure_layout(repo_root)
    root, msrc, mdot = _roots(repo_root)
    trash_dir = os.path.join(mdot, "trash")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(str(script_name or "test.py")))
    if not safe_name.endswith(".py"):
        safe_name += ".py"
    script_path = os.path.join(trash_dir, safe_name)
    if code is not None:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(str(code))
    elif not os.path.isfile(script_path):
        return {"ok": False, "error": "script not found in .Matrix/trash: %s" % safe_name}
    try:
        with open(script_path, "r", encoding="utf-8", errors="replace") as f:
            script_src = f.read()
    except OSError:
        script_src = str(code or "")

    py_exe = sys.executable or "python3"
    if install_deps:
        venv_dir = os.path.join(mdot, "venv")
        if not os.path.isdir(venv_dir):
            subprocess.run([py_exe, "-m", "venv", venv_dir], capture_output=True, timeout=60)
        venv_py = (os.path.join(venv_dir, "Scripts", "python.exe")
                   if os.name == "nt" else os.path.join(venv_dir, "bin", "python"))
        if os.path.isfile(venv_py):
            py_exe = venv_py
            deps = [str(d).strip() for d in install_deps if str(d).strip()]
            if deps:
                subprocess.run([py_exe, "-m", "pip", "install", "--quiet"] + deps,
                               capture_output=True, timeout=180)

    env = dict(os.environ)
    src_parent = os.path.dirname(msrc)
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src_parent + (os.pathsep + existing_pp if existing_pp else "")
    t0 = time.time()
    try:
        p = subprocess.run(
            [py_exe, script_path],
            cwd=trash_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=int(timeout_secs or 60),
        )
        ok = p.returncode == 0
        verified_targets = []
        if ok:
            if target and ":" in str(target):
                tk, tn = str(target).split(":", 1)
                _record_verified(tk, tn, safe_name, repo_root)
                verified_targets.append("%s:%s" % (tk.strip(), tn.strip()))
            for m_tool in re.findall(r"Matrix\.tools(?:\s+import\s+|\.)([A-Za-z0-9_]+)", script_src):
                _record_verified("tool", m_tool, safe_name, repo_root)
                verified_targets.append("tool:%s" % m_tool)
            for m_hook in re.findall(r"Matrix\.([A-Za-z0-9_]+)(?:\s+import\s+hooks|\.hooks)", script_src):
                if m_hook in HOOK_SUBPACKAGES:
                    _record_verified("hook", m_hook, safe_name, repo_root)
                    verified_targets.append("hook:%s" % m_hook)
        return {
            "ok": ok,
            "exit_code": p.returncode,
            "stdout": p.stdout or "",
            "stderr": p.stderr or "",
            "path": script_path,
            "verified_targets": sorted(set(verified_targets)),
            "duration_ms": int((time.time() - t0) * 1000),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": 124, "error": "timeout after %ss" % timeout_secs,
                "path": script_path}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "exit_code": 125, "error": str(e), "path": script_path}


def clean_trash(keep_recent=0, repo_root=None):
    """Remove scratch files inside `.Matrix/trash/` keeping `keep_recent` newest files."""
    matrix_guard.ensure_layout(repo_root)
    _root, _msrc, mdot = _roots(repo_root)
    trash_dir = os.path.join(mdot, "trash")
    entries = []
    for name in os.listdir(trash_dir):
        p = os.path.join(trash_dir, name)
        try:
            entries.append((os.stat(p).st_mtime, p))
        except OSError:
            continue
    entries.sort(reverse=True)
    keep = max(0, int(keep_recent or 0))
    removed = 0
    for _mtime, p in entries[keep:]:
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
            removed += 1
        except OSError:
            continue
    return {"ok": True, "removed": removed, "kept": min(len(entries), keep)}


# ------------------------------- Seam 1: Prompt section & .Matrix/rules/ ------

def prompt_section_text(sess=None, ws=None, repo_root=None):
    """Render the Matrix system prompt block: hardcoded instructions + `.Matrix/rules/*.md`."""
    _root, msrc, mdot = _roots(repo_root)
    parts = [MATRIX_SYSTEM_PROMPT]
    if not is_enabled():
        parts.append("[Matrix runtime is currently DISABLED — only immutable Nucleus is active. Call matrix{action:'enable'} to re-enable.]")
        return "\n\n".join(parts)
    rules_dir = os.path.join(mdot, "rules")
    if os.path.isdir(rules_dir):
        rule_texts = []
        for p in sorted(glob.glob(os.path.join(rules_dir, "*.md"))):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    txt = f.read().strip()
                if txt:
                    rule_texts.append("### Matrix rule (%s)\n%s" % (os.path.basename(p), txt[:2000]))
            except OSError:
                continue
        if rule_texts:
            parts.append("## Matrix Dynamic Rules (`.Matrix/rules/`)\n" + "\n\n".join(rule_texts)[:4000])
    hook_py = os.path.join(msrc, "model", "prompt_hook.py")
    for hfile in ("prompt_hook.py", "hooks.py"):
        hook_py = os.path.join(msrc, "model", hfile)
        if os.path.isfile(hook_py):
            try:
                spec = importlib.util.spec_from_file_location("Matrix.model." + hfile[:-3], hook_py)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "extend_prompt"):
                    extra = str(mod.extend_prompt(sess=sess, ws=ws) or "").strip()
                    if extra:
                        parts.append("## Matrix Prompt Hook\n" + extra[:2000])
                        break
            except Exception as e:  # noqa: BLE001 — fail-open
                parts.append("## Matrix Prompt Hook Error (isolated)\n`%s: %s`" % (type(e).__name__, e))
    return "\n\n".join(parts)


# ----------- Seam 2 & 3: Universal Subpackage Hooks & Dynamic Tools -----------

def _hotload_hooks(msrc):
    """Scan and reload `src/Matrix/<subpkg>/hooks.py` across all 11 Python subpackages."""
    modules = {}
    active = {}
    errors = []
    stamps = {}
    for sub in HOOK_SUBPACKAGES:
        hp = os.path.join(msrc, sub, "hooks.py")
        if not os.path.isfile(hp):
            continue
        try:
            stamps[sub] = os.stat(hp).st_mtime_ns
        except OSError:
            continue
        try:
            mod_name = "Matrix.%s.hooks" % sub
            spec = importlib.util.spec_from_file_location(mod_name, hp)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            fns = sorted(
                k for k, v in vars(mod).items()
                if not k.startswith("_") and callable(v)
            )
            modules[sub] = mod
            active[sub] = fns
        except Exception as e:  # noqa: BLE001 — isolate syntax/import error
            err_info = _format_matrix_error(e, hp)
            errors.append({
                "subpackage": sub,
                "file": "%s/hooks.py" % sub,
                **err_info,
            })
    prev_rt = (_HOOK_CACHE.get(msrc) or {}).get("runtime_errors") or []
    _HOOK_CACHE[msrc] = {
        "stamps": stamps,
        "modules": modules,
        "active": active,
        "errors": errors,
        "runtime_errors": prev_rt[-20:],
    }
    return active, errors


def discover_hooks(repo_root=None):
    """Return `{subpackage: [callable_names]}` for all `src/Matrix/<subpkg>/hooks.py`, mtime-cached."""
    if not is_enabled():
        return {}
    _root, msrc, _mdot = _roots(repo_root)
    cur_stamps = {}
    for sub in HOOK_SUBPACKAGES:
        hp = os.path.join(msrc, sub, "hooks.py")
        if os.path.isfile(hp):
            try:
                cur_stamps[sub] = os.stat(hp).st_mtime_ns
            except OSError:
                pass
    with _LOCK:
        cached = _HOOK_CACHE.get(msrc)
        if not cached or cached.get("stamps") != cur_stamps:
            _hotload_hooks(msrc)
            cached = _HOOK_CACHE.get(msrc) or {}
        return dict(cached.get("active") or {})


def call_hook(subpkg, fn_name, *args, default=None, repo_root=None, **kwargs):
    """Invoke promoted Nucleus hook (`src/longrun/<subpkg>/matrix_promoted_hooks.py`) then Matrix hook (`src/Matrix/<subpkg>/hooks.py`).

    Returns `default` when no hook is present, returns `None`, or raises any exception.
    Records any runtime exception with exact line number in `_HOOK_CACHE[msrc]["runtime_errors"]`.
    """
    root, msrc, _mdot = _roots(repo_root)
    cur_default = default
    # 1. Promoted Nucleus baseline hook (if previously promoted via promote_to_nucleus)
    prom_hp = os.path.join(root, "src", "longrun", subpkg, "matrix_promoted_hooks.py")
    if os.path.isfile(prom_hp):
        try:
            spec = importlib.util.spec_from_file_location("longrun.%s.matrix_promoted_hooks" % subpkg, prom_hp)
            pmod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pmod)
            pfn = getattr(pmod, fn_name, None)
            if callable(pfn):
                pres = pfn(*args, **kwargs)
                if pres is not None:
                    cur_default = pres
        except Exception:  # noqa: BLE001
            pass
    # 2. Live Matrix overlay hook (skipped when Matrix is disabled)
    if not is_enabled():
        return cur_default
    discover_hooks(repo_root)
    with _LOCK:
        cached = _HOOK_CACHE.get(msrc) or {}
        mod = (cached.get("modules") or {}).get(subpkg)
    if mod is None:
        return cur_default
    fn = getattr(mod, fn_name, None)
    if not callable(fn):
        return cur_default
    hp = os.path.join(msrc, subpkg, "hooks.py")
    try:
        res = fn(*args, **kwargs)
        return cur_default if res is None else res
    except Exception as e:  # noqa: BLE001 — fail-open back to Nucleus default
        err_info = _format_matrix_error(e, hp)
        with _LOCK:
            hc = _HOOK_CACHE.setdefault(msrc, {"stamps": {}, "modules": {}, "active": {},
                                               "errors": [], "runtime_errors": []})
            rt = hc.setdefault("runtime_errors", [])
            rt.append({
                "subpackage": subpkg,
                "hook": "%s.hooks.%s" % (subpkg, fn_name),
                "ts": round(time.time(), 3),
                **err_info,
            })
            hc["runtime_errors"] = rt[-20:]
        return cur_default

def _builtin_tool_names():
    try:
        from longrun.tools import registry
        return set(registry.TOOL_SCHEMAS.keys())
    except Exception:  # noqa: BLE001
        return set()


def hotload(repo_root=None):
    """Scan and reload all `src/Matrix/tools/*.py` modules with fail-open isolation."""
    matrix_guard.ensure_layout(repo_root)
    root, msrc, _mdot = _roots(repo_root)
    src_parent = os.path.dirname(msrc)
    if src_parent not in sys.path:
        sys.path.insert(0, src_parent)
    tdir = os.path.join(msrc, "tools")
    builtins = _builtin_tool_names()
    loaded = {}
    errors = []
    stamps = {}
    if os.path.isdir(tdir):
        for p in sorted(glob.glob(os.path.join(tdir, "*.py"))):
            bn = os.path.basename(p)
            if bn.startswith("_"):
                continue
            tname = bn[:-3]
            try:
                stamps[bn] = os.stat(p).st_mtime_ns
            except OSError:
                continue
            if tname in builtins or tname == "matrix":
                errors.append({
                    "file": bn,
                    "tool": tname,
                    "error": "collision with built-in Nucleus tool %r is forbidden" % tname,
                })
                continue
            try:
                mod_name = "Matrix.tools.%s" % tname
                spec = importlib.util.spec_from_file_location(mod_name, p)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                schema = getattr(mod, "TOOL_SCHEMA", None)
                exec_fn = getattr(mod, "execute", None)
                if not isinstance(schema, dict) or not callable(exec_fn):
                    errors.append({
                        "file": bn,
                        "tool": tname,
                        "error": "module must define dict TOOL_SCHEMA and callable execute(args, run_id=None)",
                    })
                    continue
                loaded[tname] = {
                    "name": tname,
                    "origin": "matrix",
                    "file": p,
                    "schema": {
                        "description": "[MATRIX] " + str(schema.get("description") or tname),
                        "type": schema.get("type", "object"),
                        "properties": schema.get("properties", {}),
                        "required": schema.get("required", []),
                    },
                    "approval": str(schema.get("approval") or "auto"),
                    "execute": exec_fn,
                }
            except Exception as e:  # noqa: BLE001 — isolate broken tool module
                err_info = _format_matrix_error(e, p)
                errors.append({
                    "file": bn,
                    "tool": tname,
                    **err_info,
                })
    with _LOCK:
        _TOOL_CACHE[msrc] = {"stamps": stamps, "tools": loaded, "errors": errors}
        active_hooks, hook_errors = _hotload_hooks(msrc)
        if msrc in _HOOK_CACHE:
            _HOOK_CACHE[msrc]["runtime_errors"] = []
    return {
        "ok": len(errors) == 0 and len(hook_errors) == 0,
        "loaded_tools": sorted(loaded.keys()),
        "active_hooks": active_hooks,
        "errors": errors,
        "hook_errors": hook_errors,
    }


def discover_tools(repo_root=None):
    """Return `{name: spec_dict}` for valid Matrix tools, auto-reloading when mtimes change."""
    if not is_enabled():
        return {}
    _root, msrc, _mdot = _roots(repo_root)
    tdir = os.path.join(msrc, "tools")
    cur_stamps = {}
    if os.path.isdir(tdir):
        for p in sorted(glob.glob(os.path.join(tdir, "*.py"))):
            bn = os.path.basename(p)
            if not bn.startswith("_"):
                try:
                    cur_stamps[bn] = os.stat(p).st_mtime_ns
                except OSError:
                    pass
    with _LOCK:
        cached = _TOOL_CACHE.get(msrc)
        if not cached or cached.get("stamps") != cur_stamps:
            hotload(repo_root)
            cached = _TOOL_CACHE.get(msrc) or {"tools": {}}
        return dict(cached.get("tools") or {})


def execute_tool(name, args, run_id=None, repo_root=None):
    """Execute a discovered Matrix tool inside a fail-open try/except boundary."""
    tools_map = discover_tools(repo_root)
    entry = tools_map.get(name)
    if not entry:
        return {"ok": False, "tool": name, "origin": "matrix",
                "error": "unknown or broken Matrix tool %r" % name, "exit_code": 127}
    t0 = time.time()
    snap = matrix_guard.snapshot_nucleus_digests(repo_root)
    try:
        res = entry["execute"](args or {}, run_id)
        if not isinstance(res, dict):
            res = {"ok": True, "stdout": str(res)}
    except Exception as e:  # noqa: BLE001
        err_info = _format_matrix_error(e, entry.get("file"))
        res = {
            "ok": False,
            "error": "Matrix tool %r failed — %s" % (name, err_info["error"]),
            "line": err_info["line"],
            "code_line": err_info["code_line"],
            "stderr": err_info["traceback"],
            "exit_code": 1,
        }
    reverted = matrix_guard.restore_if_nucleus_tampered(snap, repo_root)
    if reverted:
        res = {
            "ok": False,
            "error": "NUCLEUS_PROTECTED: Matrix tool attempted to modify Nucleus files (reverted: %d)" % len(reverted),
            "exit_code": 126,
        }
    res.setdefault("ok", res.get("exit_code", 0) == 0)
    res.setdefault("exit_code", 0 if res.get("ok") else 1)
    res["tool"] = name
    res["origin"] = "matrix"
    res["backend"] = "matrix"
    res["sandboxed"] = False
    res.setdefault("duration_ms", int((time.time() - t0) * 1000))
    return res


# ------------------------------- Seam 4: Shadow WebUI & Warm Restart ----------

def webui_init(repo_root=None):
    """Copy Nucleus `webui/index.html` into `src/Matrix/webui/index.html` (zero LLM tokens)."""
    matrix_guard.ensure_layout(repo_root)
    root, msrc, _mdot = _roots(repo_root)
    src_html = os.path.join(root, "webui", "index.html")
    if not os.path.isfile(src_html):
        return {"ok": False, "error": "Nucleus webui/index.html not found"}
    dst_dir = os.path.join(msrc, "webui")
    os.makedirs(dst_dir, exist_ok=True)
    dst_html = os.path.join(dst_dir, "index.html")
    shutil.copy2(src_html, dst_html)
    _ledger("matrix.webui_init", path=dst_html)
    return {"ok": True, "path": dst_html}


def webui_reset(repo_root=None):
    """Remove the shadow `src/Matrix/webui/index.html` so HTTP `/` serves Nucleus WebUI."""
    _root, msrc, _mdot = _roots(repo_root)
    dst_html = os.path.join(msrc, "webui", "index.html")
    removed = False
    if os.path.isfile(dst_html):
        try:
            os.remove(dst_html)
            removed = True
        except OSError as e:
            return {"ok": False, "error": str(e)}
    _ledger("matrix.webui_reset", removed=removed)
    return {"ok": True, "removed": removed}


def webui_index_path(repo_root=None, prefer_nucleus=False):
    """Return the valid `index.html` path to serve on `/` (Matrix shadow if healthy, else Nucleus)."""
    root, msrc, _mdot = _roots(repo_root)
    nuc_html = os.path.join(root, "webui", "index.html")
    if prefer_nucleus or not is_enabled():
        return nuc_html
    shadow_html = os.path.join(msrc, "webui", "index.html")
    if os.path.isfile(shadow_html):
        try:
            with open(shadow_html, "r", encoding="utf-8", errors="replace") as f:
                head = f.read(250_000)
            if 'id="app"' in head and "<html" in head.lower():
                return shadow_html
        except OSError:
            pass
    return nuc_html


def webui_plugins_js(repo_root=None):
    """Return a fail-open JavaScript wrapper around `src/Matrix/webui/plugins.js` (plus promoted plugins)."""
    root, msrc, _mdot = _roots(repo_root)
    chunks = []
    prom_js = os.path.join(root, "webui", "assets", "matrix_promoted_plugins.js")
    if os.path.isfile(prom_js):
        try:
            with open(prom_js, "r", encoding="utf-8", errors="replace") as f:
                chunks.append("try {\n" + f.read(500_000) + "\n} catch (_e) {}\n")
        except OSError:
            pass
    if not is_enabled():
        chunks.append("/* Matrix live plugins disabled */\n")
        return "\n".join(chunks)
    p = os.path.join(msrc, "webui", "plugins.js")
    if not os.path.isfile(p):
        chunks.append("/* Matrix webui/plugins.js: not present */\n")
        return "\n".join(chunks)
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            body = f.read(500_000)
        chunks.append(
            "/* Matrix live WebUI plugin (fail-open isolated) */\n"
            "try {\n" + body + "\n} catch (_mtxErr) {\n"
            "  console.warn('[Matrix plugin error]', _mtxErr);\n"
            "}\n"
        )
    except OSError:
        chunks.append("/* Matrix webui/plugins.js: unreadable */\n")
    return "\n".join(chunks)


def call_ext_http(method, path, qs=None, body=None, repo_root=None):
    """Invoke `src/Matrix/core/hooks.py::handle_http(method, sub_path, qs, body)` for `/api/matrix/ext/*`."""
    prefix = "/api/matrix/ext"
    sub = path[len(prefix):].lstrip("/") if str(path or "").startswith(prefix) else str(path or "")
    res = call_hook("core", "handle_http", str(method or "GET").upper(), sub,
                    qs or {}, body, default=None, repo_root=repo_root)
    if not isinstance(res, dict):
        return {"status": 404, "body": {"ok": False, "error": "no Matrix HTTP handler for %r" % sub}}
    return {
        "status": int(res.get("status") or 200),
        "body": res.get("body") if "body" in res else res,
    }


def handle_ext_http(handler, method, path, qs=None, body=None, repo_root=None):
    """HTTP route dispatcher for `/api/matrix/ext/*` inside `httpapi.py`."""
    if not str(path or "").startswith("/api/matrix/ext"):
        return False
    out = call_ext_http(method, path, qs=qs, body=body, repo_root=repo_root)
    handler._send(out["status"], out["body"])
    return True


def _resume_ticket_path(repo_root=None):
    _root, _msrc, mdot = _roots(repo_root)
    os.makedirs(mdot, exist_ok=True)
    return os.path.join(mdot, "resume_ticket.json")


def schedule_restart(session_id=None, reason="", repo_root=None, dry_run=False):
    """Write a durable session continuation ticket and optionally trigger a graceful restart."""
    matrix_guard.ensure_layout(repo_root)
    ticket = {
        "session_id": str(session_id or "").strip(),
        "reason": str(reason or "Matrix evolution restart").strip()[:300],
        "ts": round(time.time(), 3),
    }
    write_json(_resume_ticket_path(repo_root), ticket)
    _ledger("matrix.restart_scheduled", session=ticket["session_id"], reason=ticket["reason"])
    if not dry_run:
        def _delayed_restart():
            time.sleep(0.6)
            os._exit(0)
        threading.Thread(target=_delayed_restart, daemon=True).start()
    return {"ok": True, "ticket": ticket, "dry_run": bool(dry_run)}


def consume_resume_ticket(repo_root=None):
    """Read and atomically delete `.Matrix/resume_ticket.json` if present."""
    p = _resume_ticket_path(repo_root)
    if not os.path.isfile(p):
        return None
    data = read_json(p, None)
    try:
        os.remove(p)
    except OSError:
        pass
    return data if isinstance(data, dict) else None


def resume_after_restart(repo_root=None, spawn_turn=True):
    """Called on server startup after `reconcile_orphan_turns`: resumes the interrupted session."""
    ticket = consume_resume_ticket(repo_root)
    if not ticket or not ticket.get("session_id"):
        return {"resumed": False}
    sid = ticket["session_id"]
    reason = ticket.get("reason") or "Matrix self-evolution update"
    try:
        from longrun.memory import stores
        sess = stores.load_session(sid)
        if sess is not None:
            msgs = sess.get("messages") or []
            if msgs and (msgs[-1].get("meta") or {}).get("error_detail") == "interrupted-by-restart":
                msgs.pop()
            stores.append_message(
                sess,
                "assistant",
                "[Matrix Warm Restart] Service restarted cleanly (%s). Continuing session." % reason,
                meta={"matrix_resumed": True, "reason": reason},
            )
            cont_msg = (
                "[Harness Matrix Continuation] Warm restart complete (%s). "
                "Verify your Matrix changes and continue the active run." % reason
            )
            if spawn_turn:
                stores.append_message(
                    sess,
                    "user",
                    cont_msg,
                    meta={"matrix_continuation": True, "reason": reason},
                )
                def _run_cont():
                    try:
                        from longrun.agent import agent as _ag
                        s2 = stores.load_session(sid)
                        if s2 is not None:
                            _ag.chat_once(s2, cont_msg, model=s2.get("model"), autonomous=True)
                    except Exception:  # noqa: BLE001
                        pass
                threading.Thread(target=_run_cont, daemon=True).start()
            return {"resumed": True, "session_id": sid, "reason": reason}
    except Exception:  # noqa: BLE001
        pass
    return {"resumed": False, "session_id": sid}


def status(repo_root=None):
    """Complete health and inventory report for `src/Matrix` and `.Matrix`."""
    matrix_guard.ensure_layout(repo_root)
    root, msrc, mdot = _roots(repo_root)
    tools_map = discover_tools(repo_root)
    hooks_map = discover_hooks(repo_root)
    cached = _TOOL_CACHE.get(msrc) or {}
    hcached = _HOOK_CACHE.get(msrc) or {}
    glog = git_log(limit=5, repo_root=repo_root)
    shadow = os.path.join(msrc, "webui", "index.html")
    plugins_p = os.path.join(msrc, "webui", "plugins.js")
    active_webui = webui_index_path(repo_root)
    skills_dir = os.path.join(mdot, "skills")
    m_skills = []
    if os.path.isdir(skills_dir):
        m_skills = sorted(
            d for d in os.listdir(skills_dir)
            if os.path.isfile(os.path.join(skills_dir, d, "SKILL.md"))
        )
    hook_errs = list(hcached.get("errors") or []) + list(hcached.get("runtime_errors") or [])
    vstore = read_json(_verified_store_path(repo_root), {})
    return {
        "ok": True,
        "enabled": is_enabled(),
        "matrix_src": msrc,
        "matrix_dot": mdot,
        "subpackages": list(matrix_guard.MATRIX_SUBDIRS),
        "tools": sorted(tools_map.keys()),
        "promoted_tools": sorted(discover_promoted_tools(repo_root).keys()),
        "tool_errors": cached.get("errors") or [],
        "active_hooks": hooks_map,
        "hook_errors": hook_errs,
        "verified_targets": sorted(vstore.keys()) if isinstance(vstore, dict) else [],
        "skills": m_skills,
        "checkpoints": checkpoint_list(repo_root),
        "git_commits": glog.get("commits", []),
        "webui_shadow_active": active_webui == shadow,
        "webui_plugins_active": os.path.isfile(plugins_p),
        "webui_active_path": active_webui,
    }


# ------ PT3: Deterministic Matrix -> Nucleus Promotion & Promoted Loader ------

def discover_promoted_tools(repo_root=None):
    """Discover tools permanently promoted into Nucleus (`src/longrun/tools/promoted/*.py`)."""
    root, _msrc, _mdot = _roots(repo_root)
    pdir = os.path.join(root, "src", "longrun", "tools", "promoted")
    out = {}
    if not os.path.isdir(pdir):
        return out
    for p in sorted(glob.glob(os.path.join(pdir, "*.py"))):
        bn = os.path.basename(p)
        if bn.startswith("_"):
            continue
        tname = bn[:-3]
        try:
            spec = importlib.util.spec_from_file_location("longrun.tools.promoted.%s" % tname, p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            schema = getattr(mod, "TOOL_SCHEMA", None)
            exec_fn = getattr(mod, "execute", None)
            if isinstance(schema, dict) and callable(exec_fn):
                out[tname] = {
                    "name": tname,
                    "origin": "nucleus",
                    "file": p,
                    "schema": {
                        "description": str(schema.get("description") or tname),
                        "type": schema.get("type", "object"),
                        "properties": schema.get("properties", {}),
                        "required": schema.get("required", []),
                    },
                    "approval": str(schema.get("approval") or "auto"),
                    "execute": exec_fn,
                }
        except Exception:  # noqa: BLE001
            continue
    return out


def execute_promoted_tool(name, args, run_id=None, repo_root=None):
    """Execute a tool permanently promoted to `src/longrun/tools/promoted/<name>.py`."""
    pmap = discover_promoted_tools(repo_root)
    entry = pmap.get(name)
    if not entry:
        return {"ok": False, "tool": name, "origin": "nucleus",
                "error": "unknown promoted Nucleus tool %r" % name, "exit_code": 127}
    t0 = time.time()
    try:
        res = entry["execute"](args or {}, run_id)
        if not isinstance(res, dict):
            res = {"ok": True, "stdout": str(res)}
    except Exception as e:  # noqa: BLE001
        err_info = _format_matrix_error(e, entry.get("file"))
        res = {"ok": False, "error": err_info["error"], "line": err_info["line"],
               "code_line": err_info["code_line"], "exit_code": 1}
    res.setdefault("ok", res.get("exit_code", 0) == 0)
    res.setdefault("exit_code", 0 if res.get("ok") else 1)
    res["tool"] = name
    res["origin"] = "nucleus"
    res["backend"] = "nucleus(promoted)"
    res["sandboxed"] = False
    res.setdefault("duration_ms", int((time.time() - t0) * 1000))
    return res


def verify_target(kind, name, repo_root=None):
    """Deterministically verify that a Matrix artifact is tested, valid, and safe to promote into Nucleus."""
    k, nm, fpath = _resolve_target_path(kind, name, repo_root)
    if k not in ("tool", "hook", "module", "skill", "rule", "webui") or not nm:
        return {"ok": False, "error": "kind must be 'tool', 'hook', 'module', 'skill', 'rule', or 'webui' and name is required"}
    if not fpath or not os.path.isfile(fpath):
        return {"ok": False, "error": "Matrix artifact not found at %s" % fpath}
    cur_sha = _file_sha256(fpath)
    vstore = read_json(_verified_store_path(repo_root), {})
    rec = (vstore if isinstance(vstore, dict) else {}).get("%s:%s" % (k, nm))
    if not rec or rec.get("sha256") != cur_sha:
        return {
            "ok": False,
            "error": (
                "PROMOTE_UNVERIFIED: '%s:%s' has not been tested with its current content. "
                "You MUST first run matrix{action:'test', target:'%s:%s', ...} in .Matrix/trash/ "
                "and verify it passes with exit_code=0 before promoting to Nucleus." % (k, nm, k, nm)
            ),
        }
    if k in ("tool", "hook", "module"):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                src = f.read()
            compile(src, fpath, "exec")
            spec = importlib.util.spec_from_file_location("_verify_%s_%s" % (k, nm.replace("/", "_")), fpath)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if k == "tool":
                if not isinstance(getattr(mod, "TOOL_SCHEMA", None), dict) or not callable(getattr(mod, "execute", None)):
                    return {"ok": False, "error": "PROMOTE_UNVERIFIED: tool %r must define dict TOOL_SCHEMA and callable execute" % nm}
            elif k == "hook":
                fns = [fn for fn, v in vars(mod).items() if not fn.startswith("_") and callable(v)]
                if not fns:
                    return {"ok": False, "error": "PROMOTE_UNVERIFIED: hook %r defines no callable hook functions" % nm}
        except Exception as e:  # noqa: BLE001
            err_info = _format_matrix_error(e, fpath)
            return {
                "ok": False,
                "error": "PROMOTE_UNVERIFIED: %s" % err_info["error"],
                "line": err_info["line"],
                "code_line": err_info["code_line"],
            }
    elif k in ("skill", "rule"):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                txt = f.read().strip()
            if not txt:
                return {"ok": False, "error": "PROMOTE_UNVERIFIED: %s %r is empty" % (k, nm)}
        except OSError as e:
            return {"ok": False, "error": "PROMOTE_UNVERIFIED: %s" % e}
    elif k == "webui":
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                txt = f.read()
            if nm == "index.html" and ('id="app"' not in txt or "<html" not in txt.lower()):
                return {"ok": False, "error": "PROMOTE_UNVERIFIED: shadow webui/index.html is missing id=\"app\" or <html>"}
            if not txt.strip():
                return {"ok": False, "error": "PROMOTE_UNVERIFIED: webui artifact %r is empty" % nm}
        except OSError as e:
            return {"ok": False, "error": "PROMOTE_UNVERIFIED: %s" % e}
    return {"ok": True, "kind": k, "name": nm, "path": fpath, "sha256": cur_sha}


def promote_to_nucleus(kind, name, repo_root=None):
    """Deterministically import a tested Matrix artifact into Legacy Nucleus and delete it from Matrix.

    Enforces:
      1. Dedicated checkbox `approvals.allow_matrix_promote == True` (even `approvals.mode == 'full'` does NOT unlock it).
      2. Mandatory pre-promotion test & syntax/contract verification (`verify_target`).
      3. Automatic pre-promotion checkpoint + Git commit before modifying Nucleus.
      4. Atomic copy into Nucleus + deletion from Matrix.
    """
    try:
        from longrun.tools import registry
        ap = (registry.load_config().get("approvals") or {})
        allowed = bool(ap.get("allow_matrix_promote", False))
    except Exception:  # noqa: BLE001
        allowed = False
    if not allowed:
        return {
            "ok": False,
            "error": (
                "PROMOTE_DENIED: Matrix -> Nucleus permanent promotion requires the dedicated "
                "'allow_matrix_promote' checkbox in Settings > Tools & approvals (even FULL approval "
                "mode does not authorize it)."
            ),
        }
    v = verify_target(kind, name, repo_root=repo_root)
    if not v.get("ok"):
        return v
    k, nm, src_path = v["kind"], v["name"], v["path"]
    root, msrc, mdot = _roots(repo_root)

    # Automatic pre-promotion checkpoint & commit (both .Matrix/git and root .git when present)
    checkpoint_save(1, label="pre-promote:%s:%s" % (k, nm), repo_root=repo_root)
    pre_msg = "chore(matrix): pre-promote snapshot before importing %s:%s to Nucleus" % (k, nm)
    pre_c = git_commit(pre_msg, repo_root=repo_root)
    pre_sha = pre_c.get("commit") or "checkpoint_slot_1"
    if os.path.isdir(os.path.join(root, ".git")):
        try:
            subprocess.run(["git", "add", "--", src_path], cwd=root, capture_output=True, timeout=15)
            subprocess.run(["git", "commit", "-m", pre_msg, "--", src_path],
                           cwd=root, capture_output=True, timeout=15)
        except Exception:  # noqa: BLE001
            pass

    try:
        if k == "tool":
            pdir = os.path.join(root, "src", "longrun", "tools", "promoted")
            os.makedirs(pdir, exist_ok=True)
            init_p = os.path.join(pdir, "__init__.py")
            if not os.path.exists(init_p):
                with open(init_p, "w", encoding="utf-8") as f:
                    f.write('"""Tools permanently promoted from Matrix into Nucleus."""\n')
            dst_path = os.path.join(pdir, nm + ".py")
            shutil.copy2(src_path, dst_path)
            os.remove(src_path)
        elif k == "hook":
            sub_dir = os.path.join(root, "src", "longrun", nm)
            os.makedirs(sub_dir, exist_ok=True)
            dst_path = os.path.join(sub_dir, "matrix_promoted_hooks.py")
            shutil.copy2(src_path, dst_path)
            os.remove(src_path)
        elif k == "module":
            parts = nm.split("/")
            dst_path = os.path.join(root, "src", "longrun", *parts) + ".py"
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)
            os.remove(src_path)
        elif k == "skill":
            src_sdir = os.path.dirname(src_path)
            dst_pdir = os.path.join(root, "skills", "created", nm)
            os.makedirs(os.path.dirname(dst_pdir), exist_ok=True)
            if os.path.exists(dst_pdir):
                shutil.rmtree(dst_pdir, ignore_errors=True)
            shutil.copytree(src_sdir, dst_pdir)
            shutil.rmtree(src_sdir, ignore_errors=True)
            dst_path = os.path.join(dst_pdir, "SKILL.md")
        elif k == "rule":
            pddir = os.path.join(root, ".longrun", "prompt.d")
            os.makedirs(pddir, exist_ok=True)
            dst_path = os.path.join(pddir, nm)
            shutil.copy2(src_path, dst_path)
            os.remove(src_path)
        elif k == "webui":
            if nm == "index.html":
                dst_path = os.path.join(root, "webui", "index.html")
            else:
                adir = os.path.join(root, "webui", "assets")
                os.makedirs(adir, exist_ok=True)
                dst_path = os.path.join(adir, "matrix_promoted_" + nm)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)
            os.remove(src_path)
        else:
            return {"ok": False, "error": "unsupported kind %r" % k}
    except OSError as e:
        return {"ok": False, "error": "promotion file move failed: %s" % e}

    post_msg = "chore(matrix): promoted %s:%s to Nucleus and removed from Matrix" % (k, nm)
    git_commit(post_msg, repo_root=repo_root)
    if os.path.isdir(os.path.join(root, ".git")):
        try:
            subprocess.run(["git", "add", "--", dst_path, src_path], cwd=root, capture_output=True, timeout=15)
            subprocess.run(["git", "commit", "-m", post_msg, "--", dst_path, src_path],
                           cwd=root, capture_output=True, timeout=15)
        except Exception:  # noqa: BLE001
            pass
    hl = hotload(repo_root)
    _ledger("matrix.promote_to_nucleus", artifact_kind=k, name=nm, promoted_to=dst_path, pre_commit=pre_sha)
    return {
        "ok": True,
        "kind": k,
        "name": nm,
        "promoted_to": dst_path,
        "deleted_from_matrix": True,
        "pre_commit": pre_sha,
        "hotload": hl,
    }
