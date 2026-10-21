#!/usr/bin/env python3
"""Matrix scaffold and deterministic Nucleus write-protection guard.

Enforces the strict two-zone architecture:
  1. NUCLEUS (see `NUCLEUS_PROTECTED_REL`): fixed and immutable during agent
     self-evolution turns.
  2. MATRIX (`src/Matrix/**`, `.Matrix/**`): live-editable self-evolution zone.

JAG-510 (red-team hardening). The first version of the shell gate matched the RAW
COMMAND TEXT, so it was a spelling check rather than a boundary:
  * C1 `t=$(printf ... | base64 -d); printf x > "$t/f"` wrote into `src/longrun/`;
  * C2 `tests/` and `deploy/` were declared Nucleus but absent from the token list;
  * C3 a file CREATED inside a Nucleus directory survived `restore_*`;
  * C4 the prompt-bearing surfaces (`.longrun/rules`, `AGENTS.md`) were writable;
  * C5 a `SRC/LONGRUN/...` spelling slipped past the case-sensitive compare;
  * C6 the snapshot covered only 131 files (no `deploy/`, `tests/`, `.trae/`);
  * C7 the gate was skipped entirely when `cwd` sat outside the repository.
The gate now judges the write TARGETS (with `cd` tracking) and fails CLOSED on a
target it cannot resolve, and the restore also removes creations. Everything is
unlocked only by the DANGEROUS `approvals.allow_nucleus_write` operator opt-in.
"""
import hashlib
import json
import os
import re
import threading

from longrun.util.paths import REPO_ROOT as REPO

# Snapshot/execute/restore must be one process-wide critical section. Otherwise
# concurrent sessions can each snapshot the same source tree and one command's
# legitimate Nucleus write is misattributed to another command, which then
# restores it. Model generation stays parallel; only host-side guarded executions
# serialize for the short interval where their mutations are attributed.
NUCLEUS_EXEC_LOCK = threading.RLock()

MATRIX_SUBDIRS = (
    "agent", "core", "integrations", "interop", "memory", "model",
    "orbit", "orchestrate", "plan", "research", "tools", "util", "webui"
)
DOT_SUBDIRS = ("trash", "docs", "rules", "skills", "checkpoints")

NUCLEUS_PROTECTED_REL = (
    os.path.join("src", "longrun"),
    "webui",
    "config",
    "deploy",
    "tests",
    ".trae",
    # JAG-510/C4: the surfaces the system prompt READS. Writing here is not a code
    # change but a persistent prompt injection, so they are part of the Nucleus.
    ".longrun",
    "docs",
    "RULES.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "README.md",
    "pyproject.toml",
)

# JAG-510/C6: what the snapshot protects (content revert + creation removal).
# `docs/` and `.longrun/` stay in the WRITE gate above but out of the snapshot:
# both receive machine-written artefacts (archify diagrams, `.longrun/prompt.d/`
# promotions) that a restore must not mistake for tampering.
NUCLEUS_SNAPSHOT_REL = (
    os.path.join("src", "longrun"),
    "webui",
    "config",
    "deploy",
    "tests",
    ".trae",
    "RULES.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "README.md",
    "pyproject.toml",
)
NUCLEUS_SNAPSHOT_EXTS = (
    ".py", ".yaml", ".yml", ".json", ".html", ".js", ".css", ".md", ".sh",
    ".toml", ".cfg", ".ini", ".ts", ".mjs", ".service", ".webmanifest", ".svg",
)
_SNAPSHOT_MAX_BYTES = 2_000_000
_SKIP_DIRS = frozenset({"__pycache__", "node_modules", "venv"})
# Runtime-written config overlays (WebUI auto-save, not an agent command): a
# concurrent save must survive the creation sweep.
_KEEP_REL = (
    "config/compaction.local.yaml",
    "config/providers.local.yaml",
    "config/mcp_clients.local.yaml",
    "config/mcp_clients.local.json",
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
    "## Directory Layout (All 13 Subpackages Live-Hooked)\n"
    "- `src/Matrix/`: live-editable Python packages mirroring `src/longrun/` (`agent`, `core`, "
    "`integrations`, `interop`, `memory`, `model`, `orbit`, `orchestrate`, `plan`, `research`, "
    "`tools`, `util`, `webui`).\n"
    "- `.Matrix/trash/`: temporary test scripts and sandbox experiments (clean up after use).\n"
    "- `.Matrix/docs/`: `HANDOFF.md` (short-term state) and `MANUAL.md` (verified recipes); "
    "included in `checkpoint_save` / `checkpoint_rollback`.\n"
    "- `.Matrix/rules/`: `<NN>-<section>.md` system prompt addenda automatically hooked into the prompt.\n"
    "- `.Matrix/skills/`: `<name>/SKILL.md` auto-created skills segregated from external skills.\n"
    "- `.Matrix/checkpoints/`: 3 atomic rollback slots (`slot_1`, `slot_2`, `slot_3`).\n\n"
    "## 13 Live Seams into Nucleus (Fail-Open Isolated)\n"
    "1. `src/Matrix/tools/<namespace>.py`: define `TOOL_SCHEMAS = {'<namespace>.<subtool>': {...}}` "
    "+ `def execute(args, run_id=None, subtool=None) -> dict` (every tool MUST be namespaced `<namespace>.<subtool>`, never plain).\n"
    "2. `src/Matrix/agent/hooks.py`: `transform_turn(sess, msgs, message)`.\n"
    "3. `src/Matrix/core/hooks.py`: `on_event(event_dict)` & `handle_http(method, sub_path, qs, body)` "
    "(serves `/api/matrix/ext/<sub_path>`).\n"
    "4. `src/Matrix/memory/hooks.py`: `augment_recall(kind, results, limit)`.\n"
    "5. `src/Matrix/model/hooks.py` (or `prompt_hook.py`): `extend_prompt(sess, ws)` & "
    "`pick_model(role, default_model)`.\n"
    "6. `src/Matrix/plan/hooks.py`: `score_candidate(text, base_score)` & "
    "`decide_keepgoing(decision, open_nodes, rounds)`.\n"
    "7. `src/Matrix/orchestrate/hooks.py`: `on_job_change(jobs_payload, event)`.\n"
    "8. `src/Matrix/research/hooks.py`: `augment_research(query, report)`.\n"
    "9. `src/Matrix/interop/hooks.py`: `extra_mcp_tools()`.\n"
    "10. `src/Matrix/orbit/hooks.py`: `augment_orbit(payload)`.\n"
    "11. `src/Matrix/integrations/hooks.py`: `transform_bridge_payload(payload)`.\n"
    "12. `src/Matrix/util/hooks.py`: `on_ledger_add(entry)` + shared `Matrix.util.*` modules.\n"
    "13. `src/Matrix/webui/index.html` (shadow SPA) & `src/Matrix/webui/plugins.js` "
    "(auto-loaded at `/api/matrix/plugins.js`).\n"
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
    """True when `path` resolves inside a protected Nucleus directory or file.

    JAG-510/C5: the comparison is case-insensitive so a `SRC/LONGRUN/...` spelling
    cannot slip past on a case-insensitive filesystem. The Matrix zone still wins.
    """
    root, msrc, mdot = _roots(repo_root)
    p = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))
    if _under(p, msrc) or _under(p, mdot):
        return False
    try:
        rel = os.path.relpath(p, os.path.realpath(root)).replace("\\", "/").lower()
    except ValueError:
        return False
    if rel == ".." or rel.startswith("../"):
        return False
    for prot in NUCLEUS_PROTECTED_REL:
        rel_prot = prot.replace("\\", "/").lower()
        if rel == rel_prot or rel.startswith(rel_prot + "/"):
            return True
    return False


def nucleus_write_unlocked():
    """True only when the operator flipped the DANGEROUS `allow_nucleus_write` opt-in.

    Read dynamically from the live config (like `allow_matrix_promote`) so the
    Settings checkbox applies without a restart. Anything unreadable => LOCKED.
    """
    try:
        from longrun.tools import registry
        approvals = (registry.load_config() or {}).get("approvals") or {}
        return bool(approvals.get("allow_nucleus_write", False))
    except Exception:  # noqa: BLE001
        return False



def check_write_allowed(path, repo_root=None):
    """Deterministic write gate for `fs.write` and `fs.edit`.

    Paths outside `repo_root` (e.g. a separate user workspace or scratch dir)
    are governed by the normal workspace policy. Paths inside `repo_root` that
    belong to Nucleus are hard-blocked, unless the operator enabled the DANGEROUS
    `approvals.allow_nucleus_write` opt-in (JAG-510).
    """
    if not path:
        return False, "empty path"
    if nucleus_write_unlocked():
        return True, ""
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


_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;|&()\n]")
# Every argument is a write target.
_WRITE_ALL_ARGS = frozenset({
    "tee", "rm", "rmdir", "unlink", "touch", "truncate", "dd", "shred",
    "chmod", "chown", "chgrp", "mkfifo", "mknod", "sponge",
})
# Only the LAST argument is written (the earlier ones are sources).
_WRITE_LAST_ARG = frozenset({"cp", "mv", "ln", "install", "rsync", "scp"})
_GIT_WRITE_SUBCMDS = frozenset({
    "rm", "mv", "checkout", "restore", "clean", "reset", "apply", "stash", "switch",
})
_SAFE_DEVICES = frozenset({
    "-", "/dev/null", "/dev/stdout", "/dev/stderr", "/dev/zero",
    "/dev/random", "/dev/urandom", "/dev/tty",
})


def _shell_tokens(segment):
    """Tokens of one command segment: fd duplications dropped, redirections apart."""
    s = re.sub(r"\d*>&\d+", " ", segment)
    s = re.sub(r">>?", r" \g<0> ", s)  # `>>` stays one token, `>` its own
    s = s.replace("<", " < ")
    out = []
    for raw in s.split():
        tok = raw.strip("'\"")
        if tok:
            out.append(tok)
    return out


def _resolve_target(target, whence):
    """Absolute path for a shell write target, or None when it cannot be resolved.

    None is the fail-CLOSED answer (JAG-510/C1): a target built from a variable or
    a command substitution must never be assumed harmless.
    """
    t = str(target or "").strip()
    if not t:
        return ""
    if "$" in t or "`" in t:
        return None
    if t.startswith("~"):
        t = os.path.expanduser(t)
        if t.startswith("~"):
            return None
    if not os.path.isabs(t):
        if whence is None:
            return None
        t = os.path.join(whence, t)
    return os.path.normpath(os.path.realpath(t))


def _segment_link_sources(toks):
    """Sources of symlink-creating commands in one command segment.

    JAG-531: the target gate judges a path AS WRITTEN, before the command runs.
    `ln -sfn <nucleus>/tools /tmp/nl && echo probe > /tmp/nl/_p.txt` therefore
    PASSED (at check time `/tmp/nl` did not exist, so it resolved to itself) and
    the shell then wrote THROUGH the link into the Nucleus. A symlink whose
    source is inside the Nucleus is a write channel, so creating one is refused.
    """
    out = []
    for i, tok in enumerate(toks):
        base = os.path.basename(tok).lower()
        if base == "ln":
            pass
        elif base == "cp":
            flags = [t for t in toks[i + 1:] if t.startswith("-")]
            if not any("s" in f.lstrip("-") for f in flags):
                continue
        else:
            continue
        args = [t for t in toks[i + 1:] if not t.startswith("-")]
        out.extend(args[:-1])  # the LAST argument is the link itself
    return out


def _segment_writes(toks, whence):
    """Return `(write targets, resulting cwd)` for one command segment."""
    targets = []
    i, n = 0, len(toks)
    while i < n:
        base = os.path.basename(toks[i]).lower()
        if base in ("cd", "pushd"):
            j = i + 1
            while j < n and (toks[j].startswith("-") or os.path.basename(toks[j]).lower() == "cd"):
                j += 1
            if j < n:
                nxt = _resolve_target(toks[j], whence)
                whence = nxt if (nxt and os.path.isdir(nxt)) else None
            i = j + 1
            continue
        if toks[i] in (">", ">>"):
            if i + 1 < n:
                targets.append(toks[i + 1])
            i += 2
            continue
        if base == "sed":
            rest = [t for t in toks[i + 1:] if t != "<"]
            if any(t == "-i" or t.startswith("-i") for t in rest):
                files = [t for t in rest if not t.startswith("-")]
                targets.extend(files[1:])  # files[0] is the sed script
            i = n
            continue
        if base == "git":
            sub = next((t for t in toks[i + 1:] if not t.startswith("-")), "")
            if sub.lower() in _GIT_WRITE_SUBCMDS:
                targets.extend(t for t in toks[i + 1:] if not t.startswith("-"))
            i = n
            continue
        if base in _WRITE_ALL_ARGS or base in _WRITE_LAST_ARG:
            args = []
            j = i + 1
            while j < n and toks[j] not in (">", ">>", "<", "|"):
                if not toks[j].startswith("-"):
                    args.append(toks[j])
                j += 1
            if base in _WRITE_LAST_ARG:
                targets.extend(args[-1:])
            else:
                targets.extend(args)
            i = j
            continue
        i += 1
    return targets, whence


def check_shell_command(command, cwd=None, repo_root=None):
    """Reject shell commands that could write inside the immutable Nucleus.

    The decision is made on the write TARGETS, never on the raw text, and an
    unresolvable target fails CLOSED. Reading (`cat`, `grep`, `pytest > /tmp/log`)
    and writing outside the repository stay allowed.
    """
    cmd = str(command or "")
    if not cmd.strip():
        return True, ""
    if nucleus_write_unlocked():
        return True, ""
    root, _msrc, _mdot = _roots(repo_root)
    whence = os.path.realpath(cwd or root)
    for segment in _SEGMENT_SPLIT_RE.split(cmd):
        toks = _shell_tokens(segment)
        if not toks:
            continue
        targets, whence = _segment_writes(toks, whence)
        for source in _segment_link_sources(toks):
            resolved = _resolve_target(source, whence)
            if not resolved or not _under(resolved, root):
                continue
            if is_nucleus_path(resolved, root):
                try:
                    rel = os.path.relpath(resolved, os.path.realpath(root)).replace("\\", "/")
                except ValueError:
                    rel = source
                return False, (
                    "NUCLEUS_PROTECTED: a symlink whose SOURCE is inside the immutable "
                    "Nucleus (%s) is a write channel — a later write through the link "
                    "would land in the Nucleus. Copy or import the content instead."
                    % rel
                )
        for target in targets:
            resolved = _resolve_target(target, whence)
            if resolved is None:
                return False, (
                    "NUCLEUS_PROTECTED: shell command writes to the unresolvable target %r. "
                    "Use an explicit path (the guard fails closed on variables and "
                    "command substitutions)." % target
                )
            if not resolved or resolved in _SAFE_DEVICES:
                continue
            if not _under(resolved, root):
                continue  # outside the repository: normal workspace policy applies
            if is_nucleus_path(resolved, root):
                try:
                    rel = os.path.relpath(resolved, os.path.realpath(root)).replace("\\", "/")
                except ValueError:
                    rel = target
                return False, (
                    "NUCLEUS_PROTECTED: shell command targets immutable Nucleus path (%s). "
                    "Modify only src/Matrix/ or .Matrix/." % rel
                )
    return True, ""


def _walk_nucleus(repo_root=None, exts=None):
    """Yield `(path, size)` for every file under the snapshot roots.

    `exts=None` means EVERY extension: that is the EXISTENCE set the restore
    judges creations against (JAG-531). `exts=NUCLEUS_SNAPSHOT_EXTS` is the
    CONTENT set whose bytes are restored. Realpath is used so a symlinked
    directory cannot hide files from either set.
    """
    root, _msrc, _mdot = _roots(repo_root)
    for rel in NUCLEUS_SNAPSHOT_REL:
        target = os.path.join(root, *rel.split("/"))
        if os.path.isfile(target):
            try:
                size = os.path.getsize(target)
            except OSError:
                continue
            if exts is None or os.path.splitext(target)[1].lower() in exts:
                yield target, size
            continue
        if not os.path.isdir(target):
            continue
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d not in _SKIP_DIRS]
            for fn in filenames:
                if fn.startswith("."):
                    continue
                if exts is not None and os.path.splitext(fn)[1].lower() not in exts:
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    yield p, os.path.getsize(p)
                except OSError:
                    continue


def _iter_nucleus_files(repo_root=None):
    """Yield every Nucleus artefact whose CONTENT the snapshot tracks."""
    for p, size in _walk_nucleus(repo_root, NUCLEUS_SNAPSHOT_EXTS):
        if size <= _SNAPSHOT_MAX_BYTES:
            yield p


def snapshot_nucleus_digests(repo_root=None):
    """Capture the Nucleus before an untrusted command runs.

    Every file is recorded, whatever its extension, as ``(None, None)`` when its
    bytes are not tracked; tracked files carry ``(sha256, bytes)``. The existence
    set is what the creation sweep uses, so a created `_probe.txt` cannot survive
    just because `.txt` is not a content extension (JAG-531).
    """
    snap = {}
    for p, size in _walk_nucleus(repo_root):
        if size > _SNAPSHOT_MAX_BYTES or os.path.splitext(p)[1].lower() not in NUCLEUS_SNAPSHOT_EXTS:
            snap[p] = (None, None)
            continue
        try:
            with open(p, "rb") as f:
                data = f.read()
            snap[p] = (hashlib.sha256(data).hexdigest(), data)
        except OSError:
            snap.setdefault(p, (None, None))
    return snap


def run_nucleus_guarded(operation, repo_root=None):
    """Run one operation with an exclusive Nucleus snapshot/restore transaction.

    The lock prevents a parallel session's guarded command from changing the
    baseline while this operation runs. On exceptions, restore is still attempted
    before the original exception is re-raised.
    """
    with NUCLEUS_EXEC_LOCK:
        before = snapshot_nucleus_digests(repo_root)
        try:
            result = operation()
        except BaseException:
            restore_if_nucleus_tampered(before, repo_root)
            raise
        reverted = restore_if_nucleus_tampered(before, repo_root)
        return result, reverted


def restore_if_nucleus_tampered(before_digests, repo_root=None):
    """Revert every Nucleus change a command made: edits, deletions AND creations.

    JAG-510/C3: the previous version iterated only the snapshot, so a file created
    *ex novo* inside `src/longrun/`, `tests/` or `deploy/` survived untouched.
    """
    if not before_digests or nucleus_write_unlocked():
        return []
    root, _msrc, _mdot = _roots(repo_root)
    reverted = []
    for p, (digest, raw) in before_digests.items():
        if digest is None or raw is None:
            continue  # existence-only entry: nothing to restore, nothing to compare
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
    keep = {os.path.normpath(os.path.join(root, *rel.split("/"))) for rel in _KEEP_REL}
    for p, _size in _walk_nucleus(repo_root):
        if p in before_digests or os.path.normpath(p) in keep:
            continue
        try:
            os.remove(p)
            reverted.append(p)
        except OSError:
            continue
    return reverted
