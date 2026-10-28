#!/usr/bin/env python3
"""H2-1 — one execution record per run.

A harness edit is only comparable if a third party can see WHAT the base run did:
the goal, the model, every tool call with its outcome, the files it produced, and
the harness it ran under. Today Longrun keeps the two halves apart — the run
manifest holds digests only (`util/tracing.py:85-112`) and the transcript holds
the `tool_cards` — and nothing ties them together.

This module builds that artifact from already-persisted data. It is read-only:
no hook in the agent loop, no model call, no write to the workspace.

Secrets: tool arguments are **digested**, never copied. The record keeps
`args_keys` (top-level key names), `args_digest` (sha256 of the canonical JSON)
and `args_len`, so two runs can be compared without a bearer token or a file body
ever landing in `data/harness/`.

Reference: `research/papers/harness2/harness2_2610.14224.txt:276-297` (the
Propose step is conditioned on the reference execution, not on a score).
"""
import hashlib
import json
import os

from longrun.memory import skills as skills_mod
from longrun.tools import hooks as hooks_mod
from longrun.util import paths
from longrun.util import tracing

SCHEMA = 1
GOAL_MAX = 400
ERROR_MAX = 200
MAX_DELIVERABLES = 50
MAX_SKILL_FILES = 500
WRITE_TOOLS = ("fs.write", "fs.edit", "fs.append", "fs.replace", "patch")
_HARNESS_TAG = "[harness]"


# ------------------------------------------------------------------ paths ---
def _safe_name(value):
    """Filesystem-safe token for a run id (same policy as `tracing`)."""
    return "".join(c for c in str(value or "") if c.isalnum() or c in "-_.") or "run"


def dir_path():
    """The harness data dir (`LONGRUN_HARNESS_DIR` -> `<DATA_DIR>/harness`)."""
    return os.path.abspath(os.path.expanduser(
        os.environ.get("LONGRUN_HARNESS_DIR") or os.path.join(paths.DATA_DIR, "harness")))


def path_for(run_id):
    """Absolute path of one record artifact."""
    return os.path.join(dir_path(), "runs", _safe_name(run_id) + ".json")


# ------------------------------------------------------------------ utils ---
def _canonical(obj):
    """Canonical JSON text (sorted keys, no whitespace) — the digest input."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(obj):
    """sha256 of the canonical form of `obj` (str, dict, list or None)."""
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def _parse_args(raw):
    """Tool args as a dict: they are a JSON string on the card, a dict sometimes."""
    if isinstance(raw, dict):
        return raw
    try:
        got = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _inside(path, workspace):
    """True when `path` resolves inside `workspace` (no prefix trap, no symlink)."""
    if not workspace:
        return True
    try:
        root = os.path.realpath(workspace)
        got = os.path.realpath(path)
    except (OSError, ValueError):
        return False
    return got == root or got.startswith(root + os.sep)


def _abs(path, workspace):
    """Resolve a tool-supplied path against the workspace (fs tools do the same)."""
    if not path:
        return ""
    p = os.path.expanduser(str(path))
    if not os.path.isabs(p) and workspace:
        p = os.path.join(workspace, p)
    return os.path.normpath(p)


def _goal(session):
    """The task text: the first real user turn, not a harness inject."""
    for msg in session.get("messages") or []:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        if msg.get("internal"):
            continue
        text = str(msg.get("content") or "").strip()
        if not text or text.startswith(_HARNESS_TAG):
            continue
        return text[:GOAL_MAX]
    return ""


# --------------------------------------------------------------- harness ----
def _hooks_digest(reload=True):
    """Digest of the EFFECTIVE hook list (overlay wins, never the raw file).

    A file digest would miss the WebUI overlay (`tools/hooks.py:31-36`), the same
    trap that makes a `config/*.yaml` edit dead at runtime.
    """
    try:
        got = hooks_mod.load(reload=reload) or []
    except Exception:  # noqa: BLE001 — a broken hook file is data, not a crash
        got = []
    return {"count": len(got), "sha256": _digest(got)}


def _skills_digest():
    """Digest of the skills tree: every SKILL.md (path + bytes), bounded."""
    root = getattr(skills_mod, "SKILLS_DIR", "")
    rows = []
    try:
        for base, _dirs, files in os.walk(root):
            for name in sorted(files):
                if name != "SKILL.md" or len(rows) >= MAX_SKILL_FILES:
                    continue
                full = os.path.join(base, name)
                rows.append([os.path.relpath(full, root), tracing.file_digest(full)])
    except OSError:
        rows = []
    rows.sort()
    return {"count": len(rows), "sha256": _digest(rows)}


def _harness(run_id=None):
    """The harness the run executed under, as digests.

    With a `run_id` the stored manifest is the source of truth (it is what was
    actually sent). Without one the live checkout is read, which is the same
    digest by construction — and is recorded as such, never guessed.
    """
    manifest = tracing.read_manifest(run_id) if run_id else None
    manifest = manifest if isinstance(manifest, dict) else {}
    out = {
        "source": "manifest" if manifest else "live",
        "revision": manifest.get("revision") or tracing.git_revision(),
        "config": manifest.get("config") or tracing.config_digests(),
        "overlay": manifest.get("overlay") or tracing.file_digest(
            os.path.join(paths.DATA_DIR, "tools.overlay.yaml")),
        "prompt": manifest.get("prompt"),
        "skills": _skills_digest(),
        "hooks": _hooks_digest(reload=False),
    }
    return out


# ----------------------------------------------------------------- steps ----
def _steps(cards):
    """One entry per executed tool call, in execution order."""
    out = []
    for i, card in enumerate(cards or [], start=1):
        if not isinstance(card, dict):
            continue
        args = _parse_args(card.get("args"))
        out.append({
            "n": i,
            "tool": str(card.get("tool") or ""),
            "node": card.get("node"),
            "ts": card.get("ts"),
            "ok": bool(card.get("ok", True)),
            "exit_code": card.get("exit_code"),
            "error": str(card.get("error") or "")[:ERROR_MAX],
            "backend": card.get("backend") or "",
            "args_keys": sorted(args.keys()),
            "args_len": len(_canonical(args)),
            "args_digest": _digest(args),
            "obs_chars": len(str(card.get("result") or "")),
        })
    return out


def _written(cards, workspace):
    """Workspace files a WRITE tool touched, deduped and sorted."""
    seen = set()
    for card in cards or []:
        if not isinstance(card, dict) or str(card.get("tool") or "") not in WRITE_TOOLS:
            continue
        if not card.get("ok", True):
            continue
        args = _parse_args(card.get("args"))
        path = _abs(args.get("path") or args.get("file"), workspace)
        if path and _inside(path, workspace):
            seen.add(path)
    return sorted(seen)


def _deliverables(files):
    """Existing produced files, with size and content digest (bounded)."""
    out = []
    for path in files[:MAX_DELIVERABLES]:
        try:
            if not os.path.isfile(path):
                continue
            out.append({"path": path, "bytes": os.path.getsize(path),
                        "sha256": tracing.file_digest(path)})
        except OSError:
            continue
    return out


def _tokens(key):
    """Tokens reported for the run, or None (metrics are optional)."""
    try:
        from longrun.model import runmetrics
        got = runmetrics.get(key) or {}
        val = got.get("tokens")
        return int(val) if isinstance(val, (int, float)) else None
    except Exception:  # noqa: BLE001 — a record must never fail on metrics
        return None


# ------------------------------------------------------------------ build ---
def build(session_id, run_id=None, session=None):
    """The execution record of one session (or one run) as a plain dict.

    Args:
        session_id: the session whose transcript holds the tool cards.
        run_id: when given, its manifest supplies revision/config/prompt digests.
        session: an already-loaded session dict (tests, callers holding one).
    Returns:
        {schema, run_id, session_id, goal, ts, model, workspace, harness,
         budget, steps, files_touched, deliverables}
    """
    from longrun.memory import stores
    sess = session if isinstance(session, dict) else (stores.load_session(session_id) or {})
    workspace = str(sess.get("workspace") or "")
    cards = sess.get("tool_cards") or []
    steps = _steps(cards)
    files = _written(cards, workspace)
    stamps = [s["ts"] for s in steps if isinstance(s.get("ts"), (int, float))]
    span = round(max(stamps) - min(stamps), 3) if len(stamps) >= 2 else 0.0
    key = run_id or session_id
    return {
        "schema": SCHEMA,
        "run_id": key,
        "session_id": session_id,
        "goal": _goal(sess),
        "ts": round(float(sess.get("created") or 0.0), 3),
        "model": str(sess.get("model") or ""),
        "workspace": workspace,
        "harness": _harness(run_id),
        "budget": {"steps": len(steps), "seconds": span, "tokens": _tokens(key)},
        "steps": steps,
        "files_touched": files,
        "deliverables": _deliverables(files),
    }


def save(rec):
    """Write one record atomically; returns its path, or None on failure."""
    if not isinstance(rec, dict):
        return None
    path = path_for(rec.get("run_id"))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path
    except Exception:  # noqa: BLE001 — an artifact is never worth a broken run
        return None


def load(run_id):
    """The stored record, or None when absent/corrupt."""
    try:
        with open(path_for(run_id), "r", encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, dict) else None
    except Exception:  # noqa: BLE001
        return None
