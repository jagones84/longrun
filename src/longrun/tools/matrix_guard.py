#!/usr/bin/env python3
"""Matrix scaffold and deterministic Nucleous write-protection guard.

Enforces the strict two-zone architecture:
  1. NUCLEOUS (see `NUCLEOUS_PROTECTED_REL`): fixed and immutable during agent
     self-evolution turns.
  2. MATRIX (`src/Matrix/**`, `.Matrix/**`): live-editable self-evolution zone.

JAG-510 (red-team hardening). The first version of the shell gate matched the RAW
COMMAND TEXT, so it was a spelling check rather than a boundary:
  * C1 `t=$(printf ... | base64 -d); printf x > "$t/f"` wrote into `src/longrun/`;
  * C2 `tests/` and `deploy/` were declared Nucleous but absent from the token list;
  * C3 a file CREATED inside a Nucleous directory survived `restore_*`;
  * C4 the prompt-bearing surfaces (`.longrun/rules`, `AGENTS.md`) were writable;
  * C5 a `SRC/LONGRUN/...` spelling slipped past the case-sensitive compare;
  * C6 the snapshot covered only 131 files (no `deploy/`, `tests/`, `.trae/`);
  * C7 the gate was skipped entirely when `cwd` sat outside the repository.
C1, C2, C4, C5 and C7 are fixed IN the write-target gate below. C3 and C6
belonged to the snapshot/restore machinery, which was REMOVED entirely (see the
paragraph below): with nothing reverting, there is no creation sweep to fool.
The gate judges the write TARGETS (with `cd` tracking) and fails CLOSED on a
target it cannot resolve. NOTHING is ever reverted: enforcement is deny-only,
by operator decision — a post-hoc whole-tree diff cannot attribute a change to
its author, so it destroyed concurrent legitimate work. Everything is
unlocked only by the DANGEROUS `approvals.allow_nucleous_write` operator opt-in.
"""
import ast
import json
import os
import re
import threading

from longrun.util.paths import REPO_ROOT as REPO

# One process-wide critical section for the cooperative Nucleous writers (config
# saves, Matrix promotions). It exists ONLY to serialize those legitimate
# operator writes; the old snapshot/execute/restore transaction is gone and
# nothing is ever reverted (see `run_nucleous_guarded`).
NUCLEOUS_EXEC_LOCK = threading.RLock()

MATRIX_SUBDIRS = (
    "agent", "core", "integrations", "interop", "memory", "model",
    "orbit", "orchestrate", "plan", "research", "tools", "util", "webui"
)
DOT_SUBDIRS = ("trash", "docs", "rules", "skills", "checkpoints")

NUCLEOUS_PROTECTED_REL = (
    os.path.join("src", "longrun"),
    "webui",
    "config",
    "deploy",
    "tests",
    ".trae",
    # JAG-510/C4: the surfaces the system prompt READS. Writing here is not a code
    # change but a persistent prompt injection, so they are part of the Nucleous.
    # JAG-534: project rules moved to the data home, so `.longrun/` is only a
    # LEGACY alias — kept protected in case such a folder reappears in a checkout.
    ".longrun",
    "docs",
    "Global_rules.md",
    "Project_rules.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "README.md",
    "pyproject.toml",
)

MATRIX_ALLOWED_REL = (
    os.path.join("src", "Matrix"),
    os.path.join("skills", "created"),
    # JAG-534: the runtime dir and the data dir are checked ABSOLUTELY in
    # `is_matrix_writable` (they live under the data home, not the checkout), so
    # no repo-relative `data/` or `.Matrix` entry is needed here any more.
)

_DEFAULT_HANDOFF = (
    "# Matrix Self-Evolution — Short-Term Handoff\n\n"
    "## Current Evolution Goal\n"
    "- None active.\n\n"
    "## Recent Changes & Verification\n"
    "- Initialized Matrix layout.\n\n"
    "## Failed Attempts / Do Not Repeat\n"
    "- Never attempt to modify Nucleous files (`src/longrun/`, `webui/`, `config/`, `Global_rules.md` / `Project_rules.md`).\n"
)

_DEFAULT_MANUAL = (
    "# Matrix Self-Evolution — Architecture & Operations Manual\n\n"
    "## Directory Layout (All 13 Subpackages Live-Hooked)\n"
    "- `src/Matrix/`: live-editable Python packages mirroring `src/longrun/` (`agent`, `core`, "
    "`integrations`, `interop`, `memory`, `model`, `orbit`, `orchestrate`, `plan`, `research`, "
    "`tools`, `util`, `webui`).\n"
    "- The Matrix RUNTIME dir (reported by `matrix.status.matrix_dot`, default `~/.longrun/matrix`; "
    "`.Matrix/` is only its pre-JAG-533 name) holds:\n"
    "  - `trash/`: temporary test scripts and sandbox experiments (clean up after use).\n"
    "  - `docs/`: `HANDOFF.md` (short-term state) and `MANUAL.md` (verified recipes); "
    "included in `checkpoint_save` / `checkpoint_rollback`.\n"
    "  - `rules/`: `<NN>-<section>.md` system prompt addenda automatically hooked into the prompt.\n"
    "  - `skills/`: `<name>/SKILL.md` auto-created skills segregated from external skills.\n"
    "  - `checkpoints/`: 3 atomic rollback slots (`slot_1`, `slot_2`, `slot_3`).\n\n"
    "## 13 Live Seams into Nucleous (Fail-Open Isolated)\n"
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
    "13. `src/Matrix/webui/plugins.js` — the ONE browser seam, auto-loaded at "
    "`/api/matrix/plugins.js` (no shadow SPA: nothing else under `webui/` is served, "
    "so a plugin written under another name is never loaded).\n"
)


def _roots(repo_root=None):
    """(repo root, Matrix nucleous dir, Matrix RUNTIME dir).

    JAG-533: the runtime dir (a rewritten git checkout) is NOT part of the
    repository any more — it lives under the user data home. An explicit
    `repo_root` (tests) still gets `<root>/.Matrix`, so a fixture stays a fixture.
    """
    root = os.path.abspath(repo_root or REPO)
    if repo_root is None and os.environ.get("LONGRUN_MATRIX_SRC"):
        msrc = os.path.abspath(os.environ["LONGRUN_MATRIX_SRC"])
    else:
        msrc = os.path.abspath(os.path.join(root, "src", "Matrix"))
    if repo_root is None and os.environ.get("LONGRUN_MATRIX_DOT"):
        mdot = os.path.abspath(os.environ["LONGRUN_MATRIX_DOT"])
    elif repo_root is None:
        from longrun.util import paths
        mdot = os.path.abspath(paths.MATRIX_DOT_DIR)
    else:
        mdot = os.path.abspath(os.path.join(root, ".Matrix"))
    return root, msrc, mdot


from longrun.util.fswrite import path_under as _under


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
    """True when `path` resolves inside `src/Matrix/`, the Matrix runtime dir,
    the app data dir, or `skills/created/`."""
    from longrun.util import paths
    root, msrc, mdot = _roots(repo_root)
    p = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))
    if _under(p, msrc) or _under(p, mdot) or _under(p, paths.DATA_DIR):
        return True
    for rel in MATRIX_ALLOWED_REL:
        if _under(p, os.path.join(root, rel)):
            return True
    return False


def is_nucleous_path(path, repo_root=None):
    """True when `path` resolves inside a protected Nucleous directory or file.

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
    for prot in NUCLEOUS_PROTECTED_REL:
        rel_prot = prot.replace("\\", "/").lower()
        if rel == rel_prot or rel.startswith(rel_prot + "/"):
            return True
    return False


def nucleous_write_unlocked():
    """True only when the operator flipped the DANGEROUS `allow_nucleous_write` opt-in.

    Read dynamically from the live config (like `allow_matrix_promote`) so the
    Settings checkbox applies without a restart. Anything unreadable => LOCKED.
    """
    try:
        from longrun.tools import registry
        approvals = (registry.load_config() or {}).get("approvals") or {}
        return bool(approvals.get("allow_nucleous_write", False))
    except Exception:  # noqa: BLE001
        return False



def check_write_allowed(path, repo_root=None):
    """Deterministic write gate for `fs.write` and `fs.edit`.

    Paths outside `repo_root` (e.g. a separate user workspace or scratch dir)
    are governed by the normal workspace policy. Paths inside `repo_root` that
    belong to Nucleous are hard-blocked, unless the operator enabled the DANGEROUS
    `approvals.allow_nucleous_write` opt-in (JAG-510).
    """
    if not path:
        return False, "empty path"
    if nucleous_write_unlocked():
        return True, ""
    root, msrc, mdot = _roots(repo_root)
    p = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))
    if not _under(p, root):
        return True, ""
    if is_matrix_writable(p, root):
        return True, ""
    if is_nucleous_path(p, root):
        try:
            rel = os.path.relpath(os.path.realpath(p), os.path.realpath(root)).replace("\\", "/")
        except ValueError:
            rel = str(path)
        return False, (
            "NUCLEOUS_PROTECTED: '%s' belongs to the immutable Nucleous. "
            "Agent self-evolution writes are restricted to `src/Matrix/` (code) and "
            "the Matrix runtime dir (`matrix.status.matrix_dot`, default ~/.longrun/matrix)." % rel
        )
    return True, ""


def _store_targets():
    """Absolute paths of the harness's own RECORD (trace tampering, 2609.30266).

    The `fs.*`/`shell` denies in `config/tools.yaml` are REPO-relative patterns.
    This list is the LIVE store (data home), resolved through `paths` so the
    guard never re-derives a mutable path from the repository.
    """
    out = []
    try:
        from longrun.util import paths as _p
        data = getattr(_p, "DATA_DIR", "") or ""
        for _name in ("SESSIONS_DIR", "THREADS_DIR"):
            _v = getattr(_p, _name, None)
            if isinstance(_v, str) and _v:
                out.append(_v)
        out.append(os.environ.get("LONGRUN_RUNS_DIR") or os.path.join(data, "runs"))
        out.append(os.environ.get("LONGRUN_HELDOUT_DIR") or os.path.join(data, "heldout"))
        out.append(os.environ.get("LONGRUN_DB") or os.path.join(data, "events.db"))
        # Round 13: the IMPROVEMENT record is evidence too. Proved live 2026-11-18:
        # a write to `~/.longrun/data/proposals/<id>/proposal.json` was allowed by
        # both guards, so an agent could rewrite its own verdict and case table.
        _prop = getattr(_p, "PROPOSALS_DIR", "")
        if isinstance(_prop, str) and _prop:
            out.append(_prop)
        # Round 14: the improvement LEDGER is the record the proposals are judged
        # in. Proved live 2026-11-18: all five routes (`shell >>`, `truncate`,
        # `python -c`, `fs.write`, `fs.edit`) to `data/improvement/ledger.jsonl`
        # classified `auto`, so the agent the ledger records could rewrite it —
        # and a hash chain nobody can forge is worthless if the file is writable.
        _imp = getattr(_p, "IMPROVEMENT_DIR", "")
        if isinstance(_imp, str) and _imp:
            out.append(_imp)
    except Exception:  # noqa: BLE001 — the guard must not break on an import
        pass
    # The in-repo spelling needs no entry of its own: `paths.DATA_DIR` IS the
    # checkout's `data/` while a legacy in-repo home is still being served, and
    # `config/tools.yaml` keeps the repo-relative fs/shell deny for the rest.
    return [os.path.realpath(p) for p in out if p]


def _is_store(path):
    """True when `path` IS or is INSIDE the run/session/event/held-out record."""
    if not path:
        return False
    rp = os.path.realpath(path)
    for root in _store_targets():
        if rp == root or rp.startswith(root + os.sep):
            return True
    return False


def _fold_path(node):
    """Fold a CONSTANT path expression to a string, else None (round 58).

    Measured live 2026-11-18: the literal-only rule let ONE rewrite through —
    `open(os.path.expanduser("~/.longrun/data/events.db"), "a")` and
    `open(os.path.join("~/.longrun/data", "events.db"), "a")` both reached the
    record, while the same path written literally was refused. Those are not the
    indirection `v1072` P7 protects: the value is a CONSTANT, so it is folded and
    judged exactly like a literal. A NAME is deliberately NOT folded — a target
    behind a variable stays the documented fail-open limit.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold_path(node.left), _fold_path(node.right)
        if left is not None and right is not None:
            return left + right
        return None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        attr = node.func.attr
        if attr in ("expanduser", "expandvars", "normpath", "abspath") and node.args:
            value = _fold_path(node.args[0])
            if value is None:
                return None
            try:
                return getattr(os.path, attr)(value)
            except (TypeError, ValueError, OSError):
                return None
        if attr == "join":
            vals = [_fold_path(a) for a in node.args]
            if vals and all(v is not None for v in vals):
                try:
                    # `join("~/.longrun/data", "events.db")` keeps the `~`, and
                    # `_resolve_literal` refuses a `~` target — expand it here so
                    # the joined constant is judged like the same absolute path.
                    return os.path.expanduser(os.path.join(*vals))
                except (TypeError, ValueError):
                    return None
    return None


def check_python_write(code, workspace=None, repo_root=None):
    """Refuse a Python snippet whose LITERAL write target is inside the Nucleous.

    The shell gate cannot see what Python code does (`open("src/longrun/x",
    "w")` sails through target parsing), so without this `python.run` was the
    open front door \u2014 previously "covered" only by the post-hoc restore, which
    is now gone by operator decision. Only string-literal paths are judged;
    dynamic paths (variables, f-strings, joins) are allowed through: refusing
    them would break legitimate code, and nothing reverts anything anymore, so
    a miss only means "not blocked", never "data destroyed". Non-literal and
    unparseable snippets fail OPEN here; a SyntaxError fails at runtime anyway.
    `workspace` is the snippet's cwd (relative targets resolve against it);
    `repo_root` defaults to the harness checkout.
    """
    src = str(code or "")
    if not src.strip():
        return True, ""
    if nucleous_write_unlocked():
        return True, ""
    try:
        tree = ast.parse(src, mode="exec")
    except SyntaxError:
        return True, ""
    root, _msrc, _mdot = _roots(repo_root)
    base = os.path.realpath(workspace) if workspace else os.path.realpath(root)

    def _resolve_literal(lit):
        t = str(lit or "").strip()
        if not t or "$" in t or "`" in t or "{" in t:
            return None
        if t.startswith("~"):
            return None
        p = t if os.path.isabs(t) else os.path.join(base, t)
        try:
            return os.path.normpath(os.path.realpath(p))
        except OSError:
            return None

    def _deny(resolved, what):
        try:
            rel = os.path.relpath(resolved, os.path.realpath(root)).replace("\\", "/")
        except ValueError:
            rel = what
        return (False,
                "NUCLEOUS_PROTECTED: python snippet %s inside the immutable "
                "Nucleous (%s). Modify only `src/Matrix/` or the Matrix runtime dir "
                "(`matrix.status.matrix_dot`)." % (what, rel))

    def _is_nucleous(resolved):
        return (resolved is not None and _under(resolved, os.path.realpath(root))
                and is_nucleous_path(resolved, root))

    def _deny_store(resolved, what):
        """The record is not a workspace file, so it has its own message."""
        try:
            shown = os.path.relpath(resolved, os.path.realpath(root)).replace("\\", "/")
        except ValueError:
            shown = str(resolved)
        return (False,
                "STORE_PROTECTED: python snippet %s inside the harness record (%s). "
                "The runs, transcripts, thread ledger, event log, held-out suite, "
                "improvement proposals and the improvement ledger are not writable "
                "by the agent they record; write your own outputs under the workspace."
                % (what, shown))

    def _refuse(resolved, what):
        """The one write-target verdict this guard can return (None = allow)."""
        if _is_nucleous(resolved):
            return _deny(resolved, what)
        if _is_store(resolved):
            return _deny_store(resolved, what)
        return None

    _WRITE_MODES = ("w", "a", "x", "+")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # open(path, mode) / io.open / os.fdopen / pathlib.Path.open
        if isinstance(func, ast.Name) and func.id in ("open",):
            if not node.args:
                continue
            mode = ""
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value or "")
            for kw in node.keywords or []:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = str(kw.value.value or "")
            if not any(m in mode for m in _WRITE_MODES):
                continue
            folded = _fold_path(node.args[0])
            if folded is not None:
                resolved = _resolve_literal(folded)
                _v = _refuse(resolved, "writes")
                if _v:
                    return _v
            continue
        if not isinstance(func, ast.Attribute):
            continue
        attr = func.attr
        # os.remove/unlink/rmdir/.../replace/rename/symlink, os.makedirs/mkdir
        if isinstance(func.value, ast.Name) and func.value.id == "os":
            if attr in ("remove", "unlink", "rmdir", "removedirs", "replace",
                        "rename", "renames", "symlink", "makedirs", "mkdir",
                        "mknod", "mkfifo", "truncate"):
                for arg in list(node.args or [])[:2]:
                    folded = _fold_path(arg)
                    if folded is not None:
                        resolved = _resolve_literal(folded)
                        _v = _refuse(resolved, "writes")
                        if _v:
                            return _v
            continue
        # shutil.copy/copy2/copytree/move/rmtree(dst, ...)
        if isinstance(func.value, ast.Name) and func.value.id == "shutil":
            idx = 1 if attr in ("copy", "copy2", "copytree", "move") else 0
            if attr in ("copy", "copy2", "copytree", "move", "rmtree"):
                if len(node.args or []) > idx:
                    folded = _fold_path(node.args[idx])
                    if folded is not None:
                        resolved = _resolve_literal(folded)
                        _v = _refuse(resolved, "writes")
                        if _v:
                            return _v
            continue
        # pathlib: Path("...").write_text/write_bytes/unlink/mkdir/touch/...,
        # or Path("...").open(mode) with a write mode.
        if attr in ("write_text", "write_bytes", "unlink", "mkdir", "touch",
                    "rename", "replace", "symlink_to", "hardlink_to", "rmdir",
                    "open"):
            recv = func.value
            lit = None
            if attr == "open":
                mode = ""
                if len(node.args) >= 1 and isinstance(node.args[0], ast.Constant):
                    mode = str(node.args[0].value or "")
                if not any(m in mode for m in _WRITE_MODES):
                    continue
            if (isinstance(recv, ast.Call) and isinstance(recv.func, ast.Name)
                    and recv.func.id == "Path"):
                if recv.args:
                    lit = _fold_path(recv.args[0])
            if lit is not None:
                resolved = _resolve_literal(lit)
                _v = _refuse(resolved, "writes")
                if _v:
                    return _v
            continue
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


def _split_redirects(segment):
    """Insert spaces around `>`/`>>` only where the SHELL would see them.

    Round 55: a `>` inside single or double quotes is a literal character
    (`echo "$f -> $(cat $f)"`, `printf '%s -> %s'`), but the old
    `re.sub(r">>?", …)` rewrote it everywhere — the token after the arrow
    (`$`, `` ` ``, `$(cat`) then read as an unresolvable write target and six
    measured READ-ONLY commands were refused as Nucleous writes.
    """
    out = []
    quote = ""
    i, n = 0, len(segment)
    while i < n:
        ch = segment[i]
        if quote:
            out.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                out.append(segment[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            out.append(segment[i:i + 2])
            i += 2
            continue
        if ch == ">":
            j = i + 1
            while j < n and segment[j] == ">":
                j += 1
            out.append(" " + segment[i:j] + " ")
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _backticks_as_subshell(cmd):
    """Spell backticks as `$( … )` so the segment splitter descends into them.

    A backtick substitution inside double quotes still runs (and can redirect),
    so a quote-aware redirect scan alone would lose `echo "`echo x > p`"`.
    An unbalanced backtick leaves an open `$(`, which the splitter treats as a
    segment boundary — the fail-closed direction.
    """
    out, opening = [], True
    for ch in str(cmd or ""):
        if ch == "`":
            out.append("$(" if opening else ")")
            opening = not opening
        else:
            out.append(ch)
    return "".join(out)


def _shell_tokens(segment):
    """Tokens of one command segment: fd duplications dropped, redirections apart."""
    s = re.sub(r"\d*>&\d+", " ", segment)
    s = _split_redirects(s)  # `>>` stays one token, `>` its own, outside quotes only
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
    `ln -sfn <nucleous>/tools /tmp/nl && echo probe > /tmp/nl/_p.txt` therefore
    PASSED (at check time `/tmp/nl` did not exist, so it resolved to itself) and
    the shell then wrote THROUGH the link into the Nucleous. A symlink whose
    source is inside the Nucleous is a write channel, so creating one is refused.
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
    """Reject shell commands that could write inside the immutable Nucleous.

    The decision is made on the write TARGETS, never on the raw text, and an
    unresolvable target fails CLOSED. Reading (`cat`, `grep`, `pytest > /tmp/log`)
    and writing outside the repository stay allowed.
    """
    cmd = str(command or "")
    if not cmd.strip():
        return True, ""
    if nucleous_write_unlocked():
        return True, ""
    cmd = _backticks_as_subshell(cmd)
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
            if is_nucleous_path(resolved, root):
                try:
                    rel = os.path.relpath(resolved, os.path.realpath(root)).replace("\\", "/")
                except ValueError:
                    rel = source
                return False, (
                    "NUCLEOUS_PROTECTED: a symlink whose SOURCE is inside the immutable "
                    "Nucleous (%s) is a write channel — a later write through the link "
                    "would land in the Nucleous. Copy or import the content instead."
                    % rel
                )
        for target in targets:
            resolved = _resolve_target(target, whence)
            if resolved is None:
                return False, (
                    "NUCLEOUS_PROTECTED: shell command writes to the unresolvable target %r. "
                    "Use an explicit path (the guard fails closed on variables and "
                    "command substitutions)." % target
                )
            if not resolved or resolved in _SAFE_DEVICES:
                continue
            if not _under(resolved, root):
                continue  # outside the repository: normal workspace policy applies
            if is_nucleous_path(resolved, root):
                try:
                    rel = os.path.relpath(resolved, os.path.realpath(root)).replace("\\", "/")
                except ValueError:
                    rel = target
                return False, (
                    "NUCLEOUS_PROTECTED: shell command targets immutable Nucleous path (%s). "
                    "Modify only `src/Matrix/` or the Matrix runtime dir "
                    "(`matrix.status.matrix_dot`)." % rel
                )
    return True, ""


def run_nucleous_guarded(operation, repo_root=None):
    """Run one operation holding the Nucleous mutex. NEVER snapshots, NEVER reverts.

    Policy (operator decision): the harness must NEVER auto-revert files — a
    whole-tree before/after diff cannot attribute a change to the calling
    command, so a concurrent legitimate edit (another agent, the operator) was
    silently destroyed. Protection is DENY-AT-THE-BOUNDARY only
    (`check_write_allowed`, `check_shell_command`, `check_python_write`): a
    command that targets the Nucleous is refused BEFORE it runs. What already
    passed the gates runs untouched, and whatever is on disk stays on disk.
    The lock only serializes legitimate operator writers (config saves).
    Returns `(result, [])`; the empty list keeps the call shape stable.
    """
    with NUCLEOUS_EXEC_LOCK:
        return operation(), []
