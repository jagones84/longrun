#!/usr/bin/env python3
"""Longrun rules — global (user) + project (workspace) instructions (JAG-114).

Mirrors the AGENTS.md convention: instructions are discovered at two scopes and
concatenated broadest -> most specific (project wins), then injected into the
system prompt of both chat and the agent loop.

  * GLOBAL (user, all sessions):  ~/.config/longrun/Global_rules.md
                                  (also loaded, additive: ~/.config/longrun/AGENTS.md)
  * PROJECT (the selected workspace): <ws>/.longrun/Project_rules.md + <ws>/.longrun/rules/*.md
                                  (also loaded, additive: <ws>/AGENTS.md)

The workspace is selectable and persisted in ~/.config/longrun/config.json.
No secret ever belongs here.
"""

import os
import re

from longrun.util import paths
from longrun.util.fswrite import write_json
from longrun.util.paths import REPO_ROOT as REPO
MAX_BYTES = int(os.environ.get("LONGRUN_RULES_MAX", str(32 * 1024)))


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
    return os.path.join(ws or get_workspace(), ".longrun")


def project_rules_path(ws=None):
    return os.path.join(project_dir(ws), "Project_rules.md")


def project_agents_path(ws=None):
    return os.path.join(ws or get_workspace(), "AGENTS.md")


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _collect_scope(native, agents, extra_dir=None):
    """(text, files): the native Global_rules.md / Project_rules.md PLUS the AGENTS.md addendum.

    The scope's AGENTS.md is ADDITIVE, not a mere fallback: when the rules file exists
    its text is composed first and the AGENTS.md content is appended after it, so
    BOTH instruction sources reach the model (JAG-128A).
    """
    files, parts = [], []
    if os.path.isfile(native):
        files.append(native)
        parts.append(_read(native))
        if extra_dir and os.path.isdir(extra_dir):
            for fn in sorted(os.listdir(extra_dir)):
                if fn.endswith(".md"):
                    files.append(os.path.join(extra_dir, fn))
                    parts.append(_read(os.path.join(extra_dir, fn)))
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
                                   extra_dir=os.path.join(project_dir(ws), "rules"))
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
    """The four rule-file locations the model should know (JAG-125).

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
        "project_extra_dir": os.path.join(project_dir(ws), "rules"),
    }


def rules_prompt_block(max_bytes=None, ws=None):
    """Prompt block that ALWAYS carries the rule-file paths (JAG-125).

    Unlike `rules_block` (empty when no rules), this always renders the header
    with the absolute paths of the global + project rule files and their
    AGENTS.md additions (also loaded, additive), so the agent knows WHERE its
    instructions live and can read or edit them with the fs tools. The rules
    text, when present, follows.
    """
    cap = max_bytes or MAX_BYTES
    c = collect(ws)
    pp = prompt_paths(c["workspace"])

    def _scope(title, sc, fallback, extra=None):
        head = ("### %s\n- file: %s\n- AGENTS.md (also loaded, additive): %s\n"
                % (title, sc["path"], fallback))
        if extra:
            head += "- extra: %s/*.md\n" % extra
        head += "- loaded: %s\n" % (", ".join(sc["files"]) or "(none yet)")
        body = (sc["text"] or "").strip()
        return head + (body if body else "_(no rules set here yet)_")

    intro = ("## Rules on disk (global + project)\n"
             "Your standing rules — their text is ALREADY LOADED below, so you do NOT "
             "need to open these files (read them only if you intend to edit). Global "
             "rules apply to every project; project rules win on "
             "conflict. Within each scope Global_rules.md/Project_rules.md and AGENTS.md are BOTH loaded "
             "(additive, not a fallback).\n"
             "- GLOBAL file: %s   (AGENTS.md also loaded, additive: %s)\n"
             "- PROJECT file: %s   (AGENTS.md also loaded, additive: %s)\n"
             "- PROJECT extra: %s/*.md\n"
             % (pp["global_rules"], pp["global_fallback"],
                pp["project_rules"], pp["project_fallback"], pp["project_extra_dir"]))
    chunks = [
        _scope("GLOBAL rules (user, all projects)", c["global"], pp["global_fallback"]),
        _scope("PROJECT rules (workspace: %s)" % c["workspace"], c["project"],
               pp["project_fallback"], pp["project_extra_dir"]),
    ]
    block = intro + "\n" + "\n\n".join(chunks)
    if len(block) > cap:
        keep = max(0, cap - 16)
        block = block[:keep] + "\n… [truncated]"
    return block


def save(scope, content, ws=None):
    """Write the global or project rules file atomically. scope in {global,project}."""
    if scope == "global":
        path = global_rules_path()
    elif scope == "project":
        path = project_rules_path(ws or get_workspace())
    else:
        return {"ok": False, "error": "scope must be 'global' or 'project'"}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        # JAG-251: `content` is wire data; a non-string (int/dict) crashed `write`.
        f.write(content if isinstance(content, str)
                else ("" if content is None else str(content)))
    os.replace(tmp, path)
    text = content if isinstance(content, str) else ("" if content is None else str(content))
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


def status(ws=None):
    """UI-friendly snapshot: paths, existence and sizes for both scopes."""
    c = collect(ws)
    def _scope(key, path, files):
        return {"path": path, "exists": os.path.isfile(path),
                "chars": len(c[key]["text"]), "text": c[key]["text"], "files": files}
    return {
        "workspace": c["workspace"],
        "config_dir": _config_dir(),
        "global": _scope("global", global_rules_path(), c["global"]["files"]),
        "project": _scope("project", c["project"]["path"], c["project"]["files"]),
        "total_chars": c["total_chars"],
    }

