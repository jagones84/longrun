#!/usr/bin/env python3
"""Longrun rules — GLOBAL (harness default + user) and PROJECT (workspace).

Instructions are discovered at two scopes and concatenated broadest -> most
specific (project wins), then injected into the system prompt of both chat and the
agent loop.

  * GLOBAL (every project, in this order):
      1. <repo>/AGENTS.md          the HARNESS DEFAULT that ships with Longrun
      2. <config>/Global_rules.md  the USER's own general rules — OPTIONAL, absent
                                   by default and created by the operator
  * PROJECT (the selected workspace): <ws>/.longrun/rules/*.md — ONLY this folder.
                                  `AGENTS.md` is never a project source.

Project instructions are workspace-local by contract: no project rules are read
from Longrun's external data home, `.trae/rules`, or other workspace paths.
Non-instruction project state remains in the external data home.

The workspace is selectable and persisted in <config dir>/config.json.
No secret ever belongs here.
"""

import os
import re

from longrun.util import paths
from longrun.util.fswrite import read_json, write_json
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
    """The HARNESS DEFAULT general rule: the shipped `<repo>/AGENTS.md`.

    2026-11-24 (operator): `AGENTS.md` is not a workspace file — it is Longrun's
    own default rule, applied to every project, and the user's general rules live
    beside it in `Global_rules.md` (optional, absent by default).
    """
    return os.path.join(REPO, "AGENTS.md")


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
    return os.path.join(workspace_rules_dir(ws), "Project_rules.md")


def workspace_rules_dir(ws=None):
    """The ONLY project-rules folder: `<workspace>/.longrun/rules`."""
    return os.path.join(os.path.realpath(ws or get_workspace()), ".longrun", "rules")


def project_rules_dirs(ws=None):
    """The only folder source for project rules: `<workspace>/.longrun/rules`."""
    return [workspace_rules_dir(ws)]


def project_rules_state_path(ws=None):
    """Where the per-file ALWAYS-APPLY switches of the project rules live.

    ROUND 179 (operator, Trae parity): *"posso selezionare se applicarla ad ogni
    messaggio always apply o no?"* — one JSON map in the harness state, never a
    second `.md` in the operator's checkout. Absent entry = ON, which is the
    behaviour every file had before the switch existed.
    """
    return os.path.join(project_dir(ws), "rules_state.json")


def always_apply_map(ws=None):
    """{abs path: False} for the rules the operator turned OFF (ON is the default)."""
    d = read_json(project_rules_state_path(ws), {}) or {}
    m = d.get("always_apply") if isinstance(d, dict) else None
    return m if isinstance(m, dict) else {}


def set_always_apply(path, always, ws=None):
    """Turn ONE project rule file on/off for the prompt. Only loaded files are valid.

    `AGENTS.md` is a GLOBAL rule (harness default), never a project file — the switch
    applies only to `<workspace>/.longrun/rules/*.md`.
    """
    ws = ws or get_workspace()
    real = os.path.abspath(str(path or ""))
    allowed = set()
    for d in project_rules_dirs(ws):
        if not _canonical_path(d) or not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            p = os.path.join(d, fn)
            if fn.endswith(".md") and _canonical_path(p):
                allowed.add(os.path.abspath(p))
    if real not in allowed or not os.path.isfile(real):
        return {"ok": False, "error": "not a project rule file: %s" % (path or "(empty)")}
    m = always_apply_map(ws)
    m[real] = bool(always)
    write_json(project_rules_state_path(ws), {"always_apply": m})
    return {"ok": True, "path": real, "always_apply": bool(always)}


def _canonical_path(path):
    """True only when a path resolves to itself (no symlink escape)."""
    return os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.realpath(path))


def project_rules_path_is_local(ws=None):
    """Whether the editable project rules path stays inside the workspace."""
    return _canonical_path(project_rules_path(ws))


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def read_project_rules(ws=None):
    """Read the editable project rules file only when it resolves locally."""
    path = project_rules_path(ws)
    return _read(path) if project_rules_path_is_local(ws) else ""


def _collect_scope(native, agents, extra_dirs=None, always_map=None,
                   reject_symlinks=False):
    """(text, files): the native scope file, every allowed rule-folder `.md`,
    and the AGENTS.md addendum.

    The scope's AGENTS.md is ADDITIVE, not a mere fallback: when the rules file exists
    its text is composed first and the AGENTS.md content is appended after it, so
    BOTH instruction sources reach the model (JAG-128A). The project's sole
    `.longrun/rules/` folder is additive and deduped by path.

    ROUND 179: `always_map` is the operator's per-file switch (Trae's "Always Apply").
    A file explicitly mapped to False is skipped everywhere — text, file list and
    audit — while an absent entry keeps the historical behaviour (loaded).
    """
    amap = always_map or {}
    files, parts = [], []
    texts = {}   # 2026-11-25: per-source text. A capped consumer (the per-turn
                 # reference copy) must be able to keep the operator's file while it
                 # shortens the harness default — the composed text cannot tell them apart.
    canonical = (lambda p: not reject_symlinks or _canonical_path(p))
    if (canonical(native) and os.path.isfile(native)
            and amap.get(os.path.abspath(native), True) is not False):
        files.append(native)
        _t = _read(native)
        parts.append(_t)
        texts[os.path.abspath(native)] = _t
    # Folder files load even when the native file is absent.
    for extra_dir in (extra_dirs or []):
        if (not extra_dir or not canonical(extra_dir)
                or not os.path.isdir(extra_dir)):
            continue
        for fn in sorted(os.listdir(extra_dir)):
            if not fn.endswith(".md"):
                continue
            p = os.path.join(extra_dir, fn)
            if (not canonical(p) or p in files
                    or amap.get(os.path.abspath(p), True) is False):
                continue
            files.append(p)
            _t = _read(p)
            parts.append(_t)
            texts[os.path.abspath(p)] = _t
    if not agents:
        agents = ""
    if (canonical(agents) and os.path.isfile(agents) and agents not in files
            and amap.get(os.path.abspath(agents), True) is not False):
        agents_text = _read(agents)
        if agents_text.strip():
            files.append(agents)
            parts.append(agents_text)
            texts[os.path.abspath(agents)] = agents_text
    text = "\n\n".join(p.strip() for p in parts if p and p.strip())
    return text, files, texts


def collect(ws=None):
    """Everything the model would see: global + project rules and their files.

    GLOBAL = the harness default `<repo>/AGENTS.md` FOLLOWED BY the user's optional
    `<config>/Global_rules.md` (more specific, so it wins on a conflict).
    PROJECT = `<ws>/.longrun/rules/*.md`, the only project source, and it honours the
    per-file always-apply switches (ROUND 179). `ws` selects the project root.
    """
    gtext, gfiles, gtexts = _collect_scope(global_agents_path(), global_rules_path())
    ws = ws or get_workspace()
    ptext, pfiles, _ = _collect_scope(project_rules_path(ws), None,
                                      extra_dirs=project_rules_dirs(ws),
                                      always_map=always_apply_map(ws),
                                      reject_symlinks=True)
    return {
        "workspace": ws,
        # 2026-11-25: the two GLOBAL sources are ALSO exposed one by one
        # (`agents_text` = the harness default, `user_text` = the operator's own
        # file). `text` stays their composition, AGENTS.md first — but a capped
        # consumer must be able to shorten the harness default without dropping the
        # operator's file, which is what the per-turn reference copy does.
        "global": {"text": gtext, "files": gfiles, "path": global_rules_path(),
                   "agents_text": (gtexts.get(os.path.abspath(global_agents_path())) or "").strip(),
                   "user_text": (gtexts.get(os.path.abspath(global_rules_path())) or "").strip()},
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
        "global_agents": global_agents_path(),   # harness default (shipped)
        "global_rules": global_rules_path(),     # user, OPTIONAL (absent by default)
        "project_rules": project_rules_path(ws),
        "project_extra_dirs": project_rules_dirs(ws),
    }


def rules_prompt_block(max_bytes=None, ws=None):
    """Prompt block that ALWAYS carries the rule-file paths (JAG-125).

    GLOBAL = the harness default `AGENTS.md` + the user's optional `Global_rules.md`;
    PROJECT = the workspace `.longrun/rules/` folder (its every `.md` is loaded).
    The rules text, when present, follows. Never empty, so the model always knows
    where its own rules live.
    """
    cap = max_bytes or MAX_BYTES
    c = collect(ws)
    pp = prompt_paths(c["workspace"])

    def _scope(title, sc, extra=None):
        head = "### %s\n- loaded: %s\n" % (
            title, ", ".join(sc["files"]) or "(none yet)")
        if extra:
            head += "- folder (every .md with always-apply on): %s\n" % ", ".join(
                d + "/*.md" for d in extra)
        body = (sc["text"] or "").strip()
        return head + (body if body else "_(no rules set here yet)_")

    intro = ("## Rules on disk (global + project)\n"
             "Your standing rules — their text is ALREADY LOADED below, so you do NOT "
             "need to open these files (read them only if you intend to edit). GLOBAL "
             "rules apply to EVERY project, broadest first: the harness default "
             "`AGENTS.md`, then the user's `Global_rules.md` when it exists. PROJECT "
             "rules come ONLY from the workspace `.longrun/rules/` folder (every `.md` "
             "whose always-apply switch is on, the default) and win on conflict.\n"
             "- GLOBAL harness default: %s\n"
             "- GLOBAL user rules (optional, may not exist): %s\n"
             "- PROJECT folder (the only project source): %s\n"
             % (pp["global_agents"], pp["global_rules"],
                ", ".join(d + "/*.md" for d in pp["project_extra_dirs"])))
    chunks = [
        _scope("GLOBAL rules (harness default + user, all projects)", c["global"]),
        _scope("PROJECT rules (workspace: %s)" % c["workspace"], c["project"],
               pp["project_extra_dirs"]),
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
        if not project_rules_path_is_local(ws or get_workspace()):
            return {"ok": False, "error": "project rules path resolves outside workspace"}
    else:
        return {"ok": False, "error": "scope must be 'global' or 'project'"}
    text = content if isinstance(content, str) else ("" if content is None else str(content))
    write_text(path, text)
    return {"ok": True, "scope": scope, "path": path, "chars": len(text)}


def append(scope, content, ws=None):
    """Aggiunge testo alle regole (global|project) in modo additivo."""
    if scope not in ("global", "project"):
        return {"ok": False, "error": "scope must be 'global' or 'project'"}
    if scope == "project":
        path = project_rules_path(ws or get_workspace())
        if not project_rules_path_is_local(ws or get_workspace()):
            return {"ok": False, "error": "project rules path resolves outside workspace"}
        cur = read_project_rules(ws)
    else:
        path = global_rules_path()
        cur = _read(path)
    sep = "" if cur.endswith("\n") or not cur else "\n"
    return save(scope, cur + sep + (content or ""), ws=ws)


def _file_rows(paths):
    """[{path, name, chars, dir}] for the panel's link list — the SAME files the prompt loads.

    Each file row carries its own parent folder for the Settings and inspector links.
    """
    out = []
    for p in paths or []:
        try:
            n = os.path.getsize(p)
        except OSError:
            n = 0
        out.append({"path": p, "name": os.path.basename(p), "chars": n,
                    "dir": os.path.dirname(p)})
    return out


def _project_rows(ws=None):
    """EVERY project rule file with its always-apply switch (the Settings list).

    ROUND 179: `file_rows` (the RH panel) stays the LOADED set; this inventory also
    names the files the operator turned OFF, so the switch can be turned back on.
    """
    ws = ws or get_workspace()
    amap = always_apply_map(ws)
    seen, out = set(), []

    def _add(p, fixed=False):
        ap = os.path.abspath(p)
        if ap in seen:
            return
        seen.add(ap)
        try:
            n = os.path.getsize(ap)
        except OSError:
            n = 0
        on = amap.get(ap, True) is not False
        out.append({"path": ap, "name": os.path.basename(ap), "chars": n,
                    "always_apply": on, "loaded": on, "fixed": bool(fixed),
                    "dir": os.path.dirname(ap)})

    native = project_rules_path(ws)
    if _canonical_path(native) and os.path.isfile(native):
        _add(native, fixed=True)          # harness overlay: always loaded, no switch
    for d in project_rules_dirs(ws):
        if not _canonical_path(d) or not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            p = os.path.join(d, fn)
            if fn.endswith(".md") and _canonical_path(p):
                _add(p)
    return out


def status(ws=None):
    """UI-friendly snapshot: paths, existence, sizes and the loaded FILE LIST.

    `file_rows` is what the RH panel renders as one link per `.md` from the sole
    workspace-local `.longrun/rules/` source.

    `text` is the COMPOSED corpus (global: harness `AGENTS.md` + user
    `Global_rules.md`; project: the `.longrun/rules/` files) because that is what the
    model reads; `file_text` is the native file's OWN bytes, and it is what an editor
    must load and save.

    `rules_dir` is the sole allowed workspace folder; `all_rows` carries each rule
    file with its always-apply switch.
    """
    c = collect(ws)

    def _scope(key, path, files):
        safe_project_path = key != "project" or _canonical_path(path)
        return {"path": path, "exists": safe_project_path and os.path.isfile(path),
                "chars": len(c[key]["text"]), "text": c[key]["text"],
                "file_text": _read(path) if safe_project_path else "", "files": files,
                "file_rows": _file_rows(files), "prompt_cap": MAX_BYTES}
    proj = _scope("project", project_rules_path(ws), c["project"]["files"])
    proj["dirs"] = project_rules_dirs(ws)   # the folder model the panel renders
    proj["rules_dir"] = workspace_rules_dir(ws)
    proj["all_rows"] = _project_rows(ws)
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
