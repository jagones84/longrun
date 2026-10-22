"""Bridge an org agent NAME to its role prompt in the local `agency-agents` clone.

The roster is seeded from `agency-agents` (see ``scripts/seed_teams.py``), but the
seed only carried the short LABEL (``agents.json.role``); the agent's actual role
PROMPT (the ``.md`` body) was never written, so the Bridge prompt and the main-app
``ROLE.md`` were empty (void) for every agent that came from the clone.

This module reads the clone and materialises that body as the session's ROLE.md —
the SAME file both UIs edit/read (`<data home>/roles/<session>.md`). It is
NON-DESTRUCTIVE: it only fills an EMPTY role unless ``force=True``, so a role the
user has already written is never clobbered.

Env:
    LONGRUN_AGENCY_DIR   the clone (default ``~/Repositories/agency-agents``)
"""
import os
import re

# Directories in the clone that are NOT agent sources (mirrors seed_teams.py).
_SKIP_DIRS = {"integrations", "scripts", "strategy", "examples", ".git", ".github"}
# roles.write() refuses >20000 bytes; keep the materialised body within that.
_MAX_ROLE = 20000


def agency_dir():
    """The agency-agents clone path (env override, else the default home clone)."""
    return os.environ.get("LONGRUN_AGENCY_DIR") or os.path.expanduser(
        "~/Repositories/agency-agents")


def available():
    """True when the clone looks present (the divisions.json marker exists)."""
    d = agency_dir()
    return os.path.isdir(d) and os.path.isfile(os.path.join(d, "divisions.json"))


def agent_index():
    """{file stem -> absolute .md path} for every agent file in the clone."""
    root = agency_dir()
    idx = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in _SKIP_DIRS]
        for fn in files:
            if fn.endswith(".md"):
                idx.setdefault(fn[:-3], os.path.join(base, fn))
    return idx


def frontmatter(path):
    """Parse the leading YAML-ish frontmatter (key: value) of an agent file."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    body = m.group(1) if m else ""
    out = {}
    for line in body.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip().lower()] = v.strip().strip('"').strip("'")
    return out


def _body(text):
    """The agent file's text WITHOUT its leading frontmatter block."""
    m = re.match(r"^---\s*\n.*?\n---\s*\n", text, re.S)
    return (text[m.end():] if m else text).strip()


def role_body(path):
    """The role PROMPT body of an agent file (frontmatter stripped, capped)."""
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return _body(f.read())[:_MAX_ROLE]
    except OSError:
        return ""


def by_name():
    """{name.lower() -> absolute .md path} from each agent file's frontmatter name."""
    out = {}
    for _slug, path in agent_index().items():
        nm = (frontmatter(path).get("name") or "").strip().lower()
        if nm:
            out.setdefault(nm, path)
    return out


def role_for(name, index=None):
    """The role PROMPT for an agent NAME ("" when the name is not in the clone)."""
    idx = index if index is not None else by_name()
    return role_body(idx.get(str(name or "").strip().lower()))


def fill_roles(force=False):
    """Write each org agent's ROLE.md from the clone when it is EMPTY (or forced).

    Returns ``{filled, kept, unmatched, failed}`` (lists of A-ids / names).
    Idempotent and non-destructive: an already-set role is left untouched unless
    ``force`` is true.
    """
    from longrun.agent import agents
    from longrun.orchestrate import roles
    names = by_name()
    out = {"filled": [], "kept": [], "unmatched": [], "failed": []}
    for a in agents.REGISTRY.list()["agents"]:
        nm = a.get("name")
        sid = a.get("session")
        path = names.get(str(nm or "").strip().lower())
        if not path:
            out["unmatched"].append(nm)
            continue
        body = role_body(path)
        if not body:
            out["unmatched"].append(nm)
            continue
        if roles.read(sid) and not force:
            out["kept"].append(a.get("id"))
            continue
        r = roles.write(sid, body)
        (out["filled"] if r.get("ok") else out["failed"]).append(a.get("id"))
    return out

