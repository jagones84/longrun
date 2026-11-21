#!/usr/bin/env python3
"""Longrun rules — global (user) + project (workspace) instructions (JAG-114).

Mirrors the AGENTS.md convention: instructions are discovered at two scopes and
concatenated broadest -> most specific (project wins), then injected into the
system prompt of both chat and the agent loop.

  * GLOBAL (user, all sessions):  <config dir>/Global_rules.md  (~/.longrun/config/)
                                  (also loaded, additive: <config dir>/AGENTS.md)
  * PROJECT (the selected workspace): <data>/projects/<ws>-<sha>/Project_rules.md
                                  + rules/*.md beside it
                                  (also loaded, additive: <ws>/AGENTS.md)

Project state is kept OUT of the workspace (never a `.longrun/` in the user's
checkout); a legacy `<ws>/.longrun` is adopted on first use.

The workspace is selectable and persisted in <config dir>/config.json.
No secret ever belongs here.
"""

import os
import re

from longrun.util import paths
from longrun.util.fswrite import write_json
from longrun.util.paths import REPO_ROOT as REPO
# 2026-11-05: the system-prompt rules cap is a CONFIG value (operator: "all in
# config files ... no hardcoding"); `context.rules_prompt_max_bytes` owns it.
from longrun.model import context_limits as ctx_limits
MAX_BYTES = ctx_limits.get("rules_prompt_max_bytes")


def _config_dir():
    return paths.config_dir()


def global_rules_path():
    return os.path.join(_config_dir(), "Global_rules.md")


def global_agents_path():
    return os.path.join(_config_dir(), "AGENTS.md")


def _config_file():
    return paths.config_file()


def _read_config():
    """The config.json dict (empty on any error — never raises)."""
    return paths.read_config()


def _write_config(cfg):
    """Atomically persist config.json."""
    write_json(_config_file(), cfg)


def workspaces_root():
    """The default home for new workspaces (JAG-2.8, JAG-533).

    `paths.WORKSPACES_DIR` — under the USER DATA HOME, never beside the checkout:
    a workspace is the operator's project, and a `git pull` in the harness repo
    must not be able to touch it. Created on demand; `LONGRUN_WORKSPACES_ROOT`
    overrides it (tests point it at a temp dir and never touch the real tree).
    """
    base = paths.WORKSPACES_DIR
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        return ""
    return base if os.path.isdir(base) else ""


def get_workspace():
    """The default project root for a session that has no folder of its own.

    JAG-126: precedence is the EXPLICIT default (config.json `workspace`, set by
    the user) -> `LONGRUN_WORKSPACE` -> the LAST workspace actually used
    (config.json `last_workspace`) -> `workspaces_root()` — the dynamic
    `.longrun/workspaces` beside this checkout (JAG-2.8) -> the user's home. The
    harness repo is never the silent default: opening a folder once makes the NEXT
    new session start there, and a fresh install starts in its own workspaces dir.
    """
    cfg = _read_config()
    ws = cfg.get("workspace")
    if ws and os.path.isdir(ws):
        return ws
    env = os.environ.get("LONGRUN_WORKSPACE")
    if env and os.path.isdir(env):
        return env
    last = cfg.get("last_workspace")
    if last and os.path.isdir(last):
        return last
    base = workspaces_root()
    if base:
        return base
    home = os.path.expanduser("~")
    return home if os.path.isdir(home) else REPO


def remember_workspace(path):
    """JAG-126: remember the folder in use, so the NEXT new session defaults to it."""
    real = check_dir(path)
    if not real:
        return {"ok": False}
    cfg = _read_config()
    if cfg.get("last_workspace") == real:
        return {"ok": True, "unchanged": True}
    cfg["last_workspace"] = real
    try:
        _write_config(cfg)
    except OSError:
        return {"ok": False}
    return {"ok": True, "last_workspace": real}


def _win_to_posix(path):
    """Translate a Windows path copied from Explorer into the DGX path.

    The Windows client drive `Z:` maps to the DGX home (project rule), so
    `Z:\\Repositories\\x` -> `~/Repositories/x`. A bare `\\home\\...` (no drive)
    is also accepted. Anything unrecognised is returned unchanged, so a normal
    Linux path is never altered.
    """
    # JAG-248: `path` is wire data — a non-string crashed `.strip()`.
    if not isinstance(path, str):
        path = "" if path is None else str(path)
    s = path.strip().strip('"').strip("'")
    if not s:
        return s
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", s)
    if m:
        drive, rest = m.group(1).upper(), m.group(2).replace("\\", "/")
        if drive == "Z":
            return os.path.join(os.path.expanduser("~"), rest)
        return s
    if s.startswith("\\"):
        cand = s.replace("\\", "/")
        if cand.startswith("/"):
            return cand
    return s


def check_dir(path):
    """Normalise + validate an existing directory; returns the abs path or None.

    Windows paths copied from the client are translated first (`Z:` = DGX home),
    so a `Z:\\Repositories\\...` folder resolves to its real Linux path instead
    of being silently rejected.
    """
    raw = _win_to_posix(path).strip()
    if not raw:
        return None
    p = os.path.abspath(os.path.expanduser(raw))
    return p if os.path.isdir(p) else None


def ensure_dir(path):
    """Normalise a directory path and CREATE it (`mkdir -p`) when missing.

    JAG-429: naming a not-yet-existing workspace for a new session used to be a
    hard error ("no such folder"); the intent is obviously to use that folder, so
    create it (with parents) instead of refusing. Returns the abs path, or None
    when the path is empty/uncreatable. Same Windows->POSIX translation as
    ``check_dir`` so `Z:\\...` works too.
    """
    raw = _win_to_posix(path).strip()
    if not raw:
        return None
    p = os.path.abspath(os.path.expanduser(raw))
    if os.path.isdir(p):
        return p
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        return None
    return p if os.path.isdir(p) else None


def resolve_workspace(sess=None):
    """The workspace for a turn: a session's own folder, else the global default.

    Precedence: session["workspace"] (if it still exists) -> config.json -> env -> repo.
    """
    if isinstance(sess, dict):
        ws = check_dir(sess.get("workspace"))
        if ws:
            return ws
    return get_workspace()


def set_workspace(path):
    """Persist the GLOBAL default workspace (must be an existing directory)."""
    # JAG-248: coerce the wire value before `.strip()`.
    if not isinstance(path, str):
        path = "" if path is None else str(path)
    raw = path.strip()
    real = check_dir(raw)
    if not real:
        return {"ok": False, "error": "no such folder: %s" % (raw or "(empty)")}
    path = real
    cfg = _read_config()
    cfg["workspace"] = path
    _write_config(cfg)
    return {"ok": True, "workspace": path}


def project_dir(ws=None):
    """JAG-534: the workspace's harness state, under the DATA HOME — never a
    `.longrun/` inside the operator's checkout."""
    return paths.workspace_state_dir(ws or get_workspace())


def project_rules_path(ws=None):
    return os.path.join(project_dir(ws), "Project_rules.md")


def workspace_rules_dir(ws=None):
    """The OPERATOR's own rules folder for the workspace: `<ws>/.trae/rules`.

    2026-11-22 ROUND 177 (operator: *"anche longrun deve farlo per le rules che stanno
    nella cartella (vengono caricate tutte, non solo project_rules … proprio come fa
    trae)"*). Every `.md` inside is a project rule, exactly like Trae's Reference list.
    """
    return os.path.join(ws or get_workspace(), ".trae", "rules")


def project_rules_dirs(ws=None):
    """Both project rules FOLDERS: the operator's `<ws>/.trae/rules` first (their own
    files, the Trae convention), then the harness-owned `<state>/rules`."""
    ws = ws or get_workspace()
    return [workspace_rules_dir(ws), os.path.join(project_dir(ws), "rules")]


def project_agents_path(ws=None):
    return os.path.join(ws or get_workspace(), "AGENTS.md")


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _collect_scope(native, agents, extra_dirs=None):
    """(text, files): the native Global_rules.md / Project_rules.md PLUS every `.md`
    of the scope's rule FOLDERS and the AGENTS.md addendum.

    The scope's AGENTS.md is ADDITIVE, not a mere fallback: when the rules file exists
    its text is composed first and the AGENTS.md content is appended after it, so
    BOTH instruction sources reach the model (JAG-128A). The folders (ROUND 177) are
    additive too and deduped by path, so a file listed twice is loaded once.
    """
    files, parts = [], []
    if os.path.isfile(native):
        files.append(native)
        parts.append(_read(native))
    # folders load even when the native file is absent: Trae parity is the folder
    for extra_dir in (extra_dirs or []):
        if not extra_dir or not os.path.isdir(extra_dir):
            continue
        for fn in sorted(os.listdir(extra_dir)):
            if not fn.endswith(".md"):
                continue
            p = os.path.join(extra_dir, fn)
            if p in files:
                continue
            files.append(p)
            parts.append(_read(p))
    if os.path.isfile(agents) and agents not in files:
        agents_text = _read(agents)
        if agents_text.strip():
            files.append(agents)
            parts.append(agents_text)
    text = "\n\n".join(p.strip() for p in parts if p and p.strip())
    return text, files


def collect(ws=None):
    """Everything the model would see: global + project rules and their files.

    `ws` selects the project root (defaults to the global workspace).
    """
    gtext, gfiles = _collect_scope(global_rules_path(), global_agents_path())
    ws = ws or get_workspace()
    ptext, pfiles = _collect_scope(project_rules_path(ws), project_agents_path(ws),
                                   extra_dirs=project_rules_dirs(ws))
    return {
        "workspace": ws,
        "global": {"text": gtext, "files": gfiles, "path": global_rules_path()},
        "project": {"text": ptext, "files": pfiles, "path": project_rules_path(ws)},
        "total_chars": len(gtext) + len(ptext),
    }


def rules_block(max_bytes=None, ws=None):
    """The prompt block (global then project, capped). Empty string when none."""
    cap = max_bytes or MAX_BYTES
    c = collect(ws)
    chunks = []
    if c["global"]["text"]:
        chunks.append("### GLOBAL rules (user, all projects)\n" + c["global"]["text"])
    if c["project"]["text"]:
        chunks.append("### PROJECT rules (workspace: %s)\n" % c["workspace"]
                      + c["project"]["text"])
    if not chunks:
        return ""
    block = "\n\n".join(chunks)
    if len(block) > cap:
        keep = max(0, cap - 16)
        block = block[:keep] + "\n… [truncated]"
    return block


def prompt_paths(ws=None):
    """The rule files and FOLDERS the model should know (JAG-125, ROUND 177).

    Any value shown to the model must be an ABSOLUTE path so it can `cat`/edit
    the file directly, instead of guessing where its own rules live.
    """
    ws = ws or get_workspace()
    return {
        "workspace": ws,
        "global_rules": global_rules_path(),
        "global_fallback": global_agents_path(),
        "project_rules": project_rules_path(ws),
        "project_fallback": project_agents_path(ws),
        "project_extra_dirs": project_rules_dirs(ws),
    }


def rules_prompt_block(max_bytes=None, ws=None):
    """Prompt block that ALWAYS carries the rule-file paths (JAG-125).

    Unlike `rules_block` (empty when no rules), this always renders the header
    with the absolute paths of the global + project rule files, their AGENTS.md
    additions (also loaded, additive) and the project rules FOLDERS — every `.md`
    inside them is loaded (ROUND 177: "vengono caricate tutte, non solo
    project_rules"). The rules text, when present, follows.
    """
    cap = max_bytes or MAX_BYTES
    c = collect(ws)
    pp = prompt_paths(c["workspace"])

    def _scope(title, sc, fallback, extra=None):
        head = ("### %s\n- file: %s\n- AGENTS.md (also loaded, additive): %s\n"
                % (title, sc["path"], fallback))
        if extra:
            head += "- folders (every .md loaded): %s\n" % ", ".join(
                d + "/*.md" for d in extra)
        head += "- loaded: %s\n" % (", ".join(sc["files"]) or "(none yet)")
        body = (sc["text"] or "").strip()
        return head + (body if body else "_(no rules set here yet)_")

    intro = ("## Rules on disk (global + project)\n"
             "Your standing rules — their text is ALREADY LOADED below, so you do NOT "
             "need to open these files (read them only if you intend to edit). Global "
             "rules apply to every project; project rules win on "
             "conflict. Within each scope Global_rules.md/Project_rules.md and AGENTS.md are BOTH loaded "
             "(additive, not a fallback), and EVERY `.md` of the project rules folders "
             "is loaded too (additive).\n"
             "- GLOBAL file: %s   (AGENTS.md also loaded, additive: %s)\n"
             "- PROJECT file: %s   (AGENTS.md also loaded, additive: %s)\n"
             "- PROJECT folders: %s\n"
             % (pp["global_rules"], pp["global_fallback"],
                pp["project_rules"], pp["project_fallback"],
                ", ".join(d + "/*.md" for d in pp["project_extra_dirs"])))
    chunks = [
        _scope("GLOBAL rules (user, all projects)", c["global"], pp["global_fallback"]),
        _scope("PROJECT rules (workspace: %s)" % c["workspace"], c["project"],
               pp["project_fallback"], pp["project_extra_dirs"]),
    ]
    block = intro + "\n" + "\n\n".join(chunks)
    if len(block) > cap:
        keep = max(0, cap - 16)
        block = block[:keep] + "\n… [truncated]"
    return block


def save(scope, content, ws=None):
    """Write the global or project rules file atomically. scope in {global,project}."""
    from longrun.util.fswrite import write_text
    if scope == "global":
        path = global_rules_path()
    elif scope == "project":
        path = project_rules_path(ws or get_workspace())
    else:
        return {"ok": False, "error": "scope must be 'global' or 'project'"}
    text = content if isinstance(content, str) else ("" if content is None else str(content))
    write_text(path, text)
    return {"ok": True, "scope": scope, "path": path, "chars": len(text)}


def append(scope, content, ws=None):
    """Aggiunge testo alle regole (global|project) in modo additivo."""
    path = global_rules_path() if scope == "global" else project_rules_path(ws or get_workspace())
    cur = ""
    try:
        with open(path, encoding="utf-8") as f:
            cur = f.read()
    except OSError:
        cur = ""
    sep = "" if cur.endswith("\n") or not cur else "\n"
    return save(scope, cur + sep + (content or ""), ws=ws)


def _file_rows(paths):
    """[{path, name, chars}] for the panel's link list — the SAME files the prompt loads."""
    out = []
    for p in paths or []:
        try:
            n = os.path.getsize(p)
        except OSError:
            n = 0
        out.append({"path": p, "name": os.path.basename(p), "chars": n})
    return out


def status(ws=None):
    """UI-friendly snapshot: paths, existence, sizes and the loaded FILE LIST.

    ROUND 177: `file_rows` is what the RH panel renders as one link per `.md` — the
    project scope is no longer a single editable file but every `.md` of the rules
    folders (`project_rules_dirs`), so the panel must be able to name each of them.

    ROUND 178: `text` is the COMPOSED corpus (native file + every folder `.md` +
    AGENTS.md) because that is what the model reads; `file_text` is the native
    file's OWN bytes, and it is what an editor must load and save. Showing the
    composed corpus in an editor that writes a single file would duplicate every
    other file's rules into it on the first save.
    """
    c = collect(ws)

    def _scope(key, path, files):
        return {"path": path, "exists": os.path.isfile(path),
                "chars": len(c[key]["text"]), "text": c[key]["text"],
                "file_text": _read(path), "files": files,
                "file_rows": _file_rows(files), "prompt_cap": MAX_BYTES}
    proj = _scope("project", project_rules_path(ws), c["project"]["files"])
    proj["dirs"] = project_rules_dirs(ws)   # the folder model the panel renders
    return {
        "workspace": c["workspace"],
        "config_dir": _config_dir(),
        "global": _scope("global", global_rules_path(), c["global"]["files"]),
        "project": proj,
        "total_chars": c["total_chars"],
        "prompt_cap": MAX_BYTES,
    }


# ---------------------------------------------------------------- audit -------
#: Words that only ever carry emphasis (they inflate a line without changing it),
#: so the duplicate/contradiction comparison ignores them.
_AUDIT_STOP = {
    "the", "and", "for", "with", "you", "are", "not", "this", "that", "its",
    "from", "into", "your", "our", "all", "any", "must", "should", "always",
    "please", "when", "then", "than", "have", "has", "had", "will", "can",
    "che", "gli", "dei", "delle", "della", "per", "con", "una", "uno", "sono",
    "sempre", "tutti", "tutte", "deve", "puo", "anche", "come", "questo",
}
#: A negation marker makes two otherwise identical rules contradict each other.
_AUDIT_NEG = {"never", "not", "no", "non", "mai", "without", "senza", "dont", "avoid"}
#: Only paths with a known file extension are checked: a bare `/` token is a
#: command or a number far too often, and a false "stale file" costs more than a
#: missed one.
_AUDIT_PATH = re.compile(
    r"(?<![A-Za-z0-9_./~-])(?:~|/)[A-Za-z0-9_./~-]+\.(?:md|py|json|yaml|yml|sh|txt)\b")
_AUDIT_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def _audit_tokens(line):
    """Content words of one rule line, negation markers separated out."""
    words = re.findall(r"[a-z0-9_]{3,}", str(line or "").lower())
    neg = {w for w in words if w in _AUDIT_NEG}
    content = {w for w in words if w not in _AUDIT_NEG and w not in _AUDIT_STOP}
    return content, bool(neg)


def _audit_lines(files, scope):
    """(scope, file, lineno, raw) for every non-empty content line of a scope."""
    out = []
    for path in files or []:
        text = _read(path)
        for i, raw in enumerate(text.splitlines(), 1):
            if raw.strip():
                out.append((scope, path, i, raw.strip()))
    return out


def _audit_norm(raw):
    """A line's identity for duplicate detection: lowercased, bullet-free, spaced."""
    line = _AUDIT_BULLET.sub("", str(raw or ""))
    return " ".join(line.lower().split()).rstrip(".").strip()


def audit(ws=None, max_bytes=None):
    """Read-only audit of the assembled rules corpus (HA-1, lot H).

    Finds what the byte cap cannot see: two rules that contradict each other, a
    rule pointing at a path that no longer exists, the same line pasted into more
    than one scope, and a scope over its context budget. It never edits anything —
    every finding names the file and line so the operator can delete it.

    Deterministic, no model, no network. Conservative on purpose: a negation is
    compared on the SAME content words (so "always use X" vs "never use X" is a
    contradiction, while two different `never` rules are not), and only paths with
    a known extension are checked.
    """
    cap = int(max_bytes or MAX_BYTES)
    c = collect(ws)
    rows = _audit_lines(c["global"]["files"], "global") + \
        _audit_lines(c["project"]["files"], "project")
    findings = []

    def _add(code, severity, scope, path, line, message, evidence, **extra):
        item = {"code": code, "severity": severity, "scope": scope,
                "file": path, "line": line, "message": message,
                "evidence": evidence}
        item.update(extra)
        findings.append(item)

    # (a) contradictions: identical content words, exactly one side negated.
    parsed = [(scope, path, ln, raw) + _audit_tokens(_audit_norm(raw))
              for scope, path, ln, raw in rows]
    seen_pairs = set()
    for i in range(len(parsed)):
        s_a, f_a, l_a, raw_a, content_a, neg_a = parsed[i]
        if len(content_a) < 3:
            continue
        for j in range(i + 1, len(parsed)):
            s_b, f_b, l_b, raw_b, content_b, neg_b = parsed[j]
            if content_a != content_b or neg_a == neg_b or len(content_b) < 3:
                continue
            key = tuple(sorted([(f_a, l_a), (f_b, l_b)]))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            _add("rules.contradiction", "error", s_b, f_b, l_b,
                 "Two rules say the same thing and one of them is negated — the "
                 "model may follow either one.",
                 "%s :: %s" % (raw_a, raw_b))

    # (b) stale paths: a rule that names a file which does not exist.
    for scope, path, ln, raw in rows:
        for cand in _AUDIT_PATH.findall(raw):
            real = os.path.expanduser(cand)
            if os.path.isabs(real) and not os.path.exists(real):
                _add("rules.stale_path", "warning", scope, path, ln,
                     "This rule points at a path that does not exist.", cand)

    # (c) duplicates: the same normalized line in more than one place.
    where = {}
    for scope, path, ln, raw in rows:
        norm = _audit_norm(raw)
        if len(norm) < 25:
            continue
        where.setdefault(norm, []).append((scope, path, ln, raw))
    for norm, places in where.items():
        scopes = sorted({p[0] for p in places})
        if len(places) < 2 or (len(scopes) < 2 and len({p[1] for p in places}) < 2):
            continue
        scope, path, ln, raw = places[0]
        _add("rules.duplicate", "warning", scope, path, ln,
             "The same rule appears %d times (%s) — keep one copy."
             % (len(places), ", ".join(scopes)),
             raw, scopes=scopes)

    # (d) over budget: the prompt cap is per scope, and the audit says by how much.
    for scope, key in (("global", "global"), ("project", "project")):
        chars = len(c[key]["text"])
        if chars > cap:
            _add("rules.over_budget", "warning", scope, c[key]["path"], 0,
                 "This scope exceeds the rules prompt budget and is TRUNCATED "
                 "before the model sees it.", "%d chars > %d" % (chars, cap),
                 chars=chars, max_bytes=cap)

    findings.sort(key=lambda f: (f["code"], f["file"] or "", f["line"]))
    counts = {}
    for f in findings:
        counts[f["code"]] = counts.get(f["code"], 0) + 1
    return {
        "workspace": c["workspace"],
        "max_bytes": cap,
        "findings": findings,
        "counts": {
            "contradiction": counts.get("rules.contradiction", 0),
            "stale_path": counts.get("rules.stale_path", 0),
            "duplicate": counts.get("rules.duplicate", 0),
            "over_budget": counts.get("rules.over_budget", 0),
        },
        "total": len(findings),
    }

