#!/usr/bin/env python3
"""Longrun skills loader (v0.7.1) — discover and read agent skills.

A skill is any directory containing a SKILL.md under `skills/<category>/<name>`.
The `skills/` tree holds symlinks into the user's skill distribution
(skills-autodist-skill), so every category is live without copying files.

API:
  list_skills()            -> [{name, category, path, title, description}]
  get_skill(name)          -> full SKILL.md text (or None)
  skills_context()         -> compact block for the agent system prompt
"""

import io
import os
import re
import shutil
import stat
import tempfile
import zipfile

from longrun.util.paths import REPO_ROOT as REPO
SKILLS_DIR = os.path.join(REPO, "skills")

LOCAL_CATEGORY = "local"

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _local_dir():
    """Directory of user-uploaded skills (gitignored)."""
    return os.environ.get("LONGRUN_SKILLS_LOCAL_DIR") or \
        os.path.join(SKILLS_DIR, LOCAL_CATEGORY)


def _max_zip():
    return int(os.environ.get("LONGRUN_SKILL_MAX_ZIP", str(20 * 1024 * 1024)))


def _max_unzip():
    return int(os.environ.get("LONGRUN_SKILL_MAX_UNZIP", str(60 * 1024 * 1024)))


def _max_files():
    return int(os.environ.get("LONGRUN_SKILL_MAX_FILES", "500"))


def _safe_name(name):
    name = (name or "").strip().lower()
    return name if _NAME_RE.match(name) else None


def _frontmatter_name(text):
    fm = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.S)
    if fm:
        m = re.search(r"^name:\s*(.+?)\s*$", fm.group(1), re.M)
        if m:
            return m.group(1).strip()
    return None


_cache = {"sig": None, "skills": []}


def _skills_sig():
    """Signature of the skills tree: mtimes of SKILLS_DIR + each category dir.

    The category dirs are symlinks into the autodist store, so adding a skill
    inside a category changes the CATEGORY mtime but NOT the top-level dir
    mtime. Keying the cache on the top-level mtime alone made a freshly adopted
    skill invisible until a server restart.
    """
    if not os.path.exists(SKILLS_DIR):
        return None
    parts = [os.stat(SKILLS_DIR).st_mtime_ns]
    try:
        for cat in sorted(os.listdir(SKILLS_DIR)):
            cd = os.path.join(SKILLS_DIR, cat)
            try:
                if not os.path.isdir(cd):
                    continue
                parts.append((cat, os.stat(cd).st_mtime_ns))
                for name in sorted(os.listdir(cd)):
                    sd = os.path.join(cd, name)
                    try:
                        parts.append((cat, name, os.stat(sd).st_mtime_ns))
                    except OSError:
                        continue
            except OSError:
                continue
    except OSError:
        pass
    return tuple(parts)


def _parse_skill_md(text, fallback_name):
    """Extract (title, description) from a SKILL.md (YAML frontmatter or headings)."""
    title, desc = fallback_name, ""
    body = text
    fm = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.S)
    if fm:
        body = text[fm.end():]
        m = re.search(r"^name:\s*(.+?)\s*$", fm.group(1), re.M)
        if m:
            title = m.group(1).strip()
        m = re.search(r"^description:\s*(.+?)\s*$", fm.group(1), re.M | re.S)
        if m:
            desc = re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.match(r"\s*#\s+(.+?)\s*$", body, re.M)
    if m and title == fallback_name:
        title = m.group(1)
    if not desc:
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                desc = re.sub(r"\s+", " ", line)[:200]
                break
    return title, desc


def list_skills(reload=False):
    """Scan skills/<category>/<name>/SKILL.md; returns cached entries."""
    sig = _skills_sig()
    if not reload and _cache["skills"] and _cache["sig"] == sig:
        return _cache["skills"]
    skills = []
    if os.path.isdir(SKILLS_DIR):
        for cat in sorted(os.listdir(SKILLS_DIR)):
            cat_dir = os.path.join(SKILLS_DIR, cat)
            if not os.path.isdir(cat_dir):
                continue
            for name in sorted(os.listdir(cat_dir)):
                sd = os.path.join(cat_dir, name)
                sp = os.path.join(sd, "SKILL.md")
                if os.path.isfile(sp):
                    try:
                        with open(sp, "r", encoding="utf-8", errors="replace") as f:
                            text = f.read(8192)
                    except OSError:
                        continue
                    title, desc = _parse_skill_md(text, name)
                    skills.append({"name": name, "category": cat,
                                   "path": os.path.relpath(sp, REPO),
                                   "abspath": sp,
                                   "title": title, "description": desc,
                                   # JAG-451: `auto` marks MACHINE-generated skills
                                   # (the skills/created box); `local` = user-uploaded.
                                   "auto": cat == "created",
                                   "local": cat == LOCAL_CATEGORY})
    _cache.update(sig=sig, skills=skills)
    return skills


def install_zip(data, name=None, overwrite=False):
    """Extract a skill zip into _local_dir()/<name>. Returns {ok,...} or {error}."""
    if not data:
        return {"error": "empty zip body"}
    if len(data) > _max_zip():
        return {"error": "zip too large (max %d bytes)" % _max_zip()}
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return {"error": "not a valid zip archive"}
    with zf:
        infos = zf.infolist()
        if len(infos) > _max_files():
            return {"error": "too many files (max %d)" % _max_files()}
        if sum(i.file_size for i in infos) > _max_unzip():
            return {"error": "uncompressed too large (max %d bytes)" % _max_unzip()}
        for i in infos:
            if (i.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
                return {"error": "zip contains a symlink: %s" % i.filename}
        raw_names = [i.filename.replace("\\", "/").strip("/")
                     for i in infos if i.filename.strip("/")]
        tops = {n.split("/")[0] for n in raw_names}
        strip = None
        if len(tops) == 1:
            only = next(iter(tops))
            if only not in raw_names:  # compare only as a directory prefix
                strip = only
        local = _local_dir()
        os.makedirs(local, exist_ok=True)
        stage = tempfile.mkdtemp(prefix=".install-", dir=local)
        try:
            root = os.path.realpath(stage)
            for i in infos:
                parts = [p for p in i.filename.replace("\\", "/").split("/")
                         if p not in ("", ".")]
                if any(p == ".." for p in parts):
                    return {"error": "path traversal in zip: %s" % i.filename}
                if strip and parts and parts[0] == strip:
                    parts = parts[1:]
                if not parts:
                    continue
                dest = os.path.join(stage, *parts)
                real = os.path.realpath(dest)
                if real != root and not real.startswith(root + os.sep):
                    return {"error": "unsafe path in zip: %s" % i.filename}
                if i.is_dir():
                    os.makedirs(dest, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(i) as src, open(dest, "wb") as out:
                        shutil.copyfileobj(src, out)
            if not os.path.isfile(os.path.join(stage, "SKILL.md")):
                return {"error": "SKILL.md not found at skill root"}
            if name is None:
                with open(os.path.join(stage, "SKILL.md"), "r",
                          encoding="utf-8", errors="replace") as f:
                    name = _frontmatter_name(f.read())
            safe = _safe_name(name)
            if not safe:
                return {"error": "invalid skill name: %r" % name}
            target = os.path.join(local, safe)
            if os.path.exists(target):
                if not overwrite:
                    return {"error": "skill '%s' already exists (use overwrite)" % safe}
                shutil.rmtree(target)
            os.replace(stage, target)
            stage = None
            list_skills(reload=True)
            return {"ok": True, "name": safe, "category": LOCAL_CATEGORY,
                    "path": os.path.relpath(target, REPO)}
        finally:
            if stage and os.path.isdir(stage):
                shutil.rmtree(stage, ignore_errors=True)


def is_local(name):
    """True if a user-uploaded skill with this name exists."""
    safe = _safe_name(name)
    return bool(safe) and os.path.isdir(os.path.join(_local_dir(), safe))


def remove(name):
    """Remove a LOCAL skill. It never touches system skills."""
    safe = _safe_name(name)
    if not safe:
        return {"error": "invalid name: %r" % name}
    target = os.path.join(_local_dir(), safe)
    if not os.path.isdir(target):
        return {"error": "local skill not found: %s" % safe}
    shutil.rmtree(target)
    list_skills(reload=True)
    return {"ok": True, "name": safe}


def get_skill(name):
    """Full SKILL.md content for a skill (matched by directory name)."""
    for s in list_skills():
        if s["name"] == name:
            with open(os.path.join(REPO, s["path"]), "r",
                      encoding="utf-8", errors="replace") as f:
                return {"ok": True, **s, "content": f.read(65536)}
    return None


def skills_context(max_chars=2200):
    """Compact skills block injected into the agent's system prompt.

    JAG-163: mirrors the frontier pattern (Claude Code / openclaw / hermes) — the
    model always sees every installed skill as NAME + a one-line description, so
    it knows what it has WITHOUT a discovery round-trip (previously only bare
    names were preloaded, and only into the chat loop). The full SKILL.md body is
    still loaded on demand with the `skills` tool, keeping the prompt bounded.
    """
    skills = list_skills()
    if not skills:
        return "Skills: none found in %s." % SKILLS_DIR
    cats = {}
    for s in skills:
        cats.setdefault(s["category"], []).append(s)
    lines = ["Skills: %d installed. The `skills` tool: "
             '{"action":"read","name":"<name>"} loads one and you FOLLOW its '
             'instructions; {"action":"search","query":"..."} finds one by keyword; '
             '{"action":"list"} shows all. Index:"' % len(skills)]
    for cat in sorted(cats):
        lines.append("- %s:" % cat)
        for s in sorted(cats[cat], key=lambda x: x["name"]):
            d = (s.get("description") or "").strip().replace("\n", " ")
            if len(d) > 80:
                d = d[:77].rstrip() + "\u2026"
            lines.append(("    %s \u2014 %s" % (s["name"], d)) if d else ("    %s" % s["name"]))
    out = "\n".join(lines)
    if len(out) <= max_chars:
        return out
    return out[:max_chars] + \
        '\n…[index truncated — find the rest with {"action":"search","query":"..."}]'


_SKILL_STOP = {
    "the", "and", "for", "with", "you", "are", "not", "this", "that", "error",
    "failed", "unknown", "command", "tool", "run", "get", "set", "use", "using",
    "how", "can", "help", "skill", "skills", "want", "need", "make", "does",
}


def search_skills(query, limit=10):
    """Rank installed skills against `query` (JAG-198).

    Progressive discovery (Claude Code / ScaleMCP pattern): the model can find
    the ONE relevant skill without loading the whole library into context. A hit
    in the name/title weighs 3x a hit in the description. Returns a list of
    {name, category, title, description, score}, best first.
    """
    words = set(re.findall(r"[a-z]{3,}", str(query or "").lower())) - _SKILL_STOP
    if not words:
        return []
    scored = []
    for s in list_skills():
        strong = (str(s.get("name") or "") + " " + str(s.get("title") or "")).lower()
        weak = str(s.get("description") or "").lower()
        score = sum(3 for w in words if w in strong) + sum(1 for w in words if w in weak)
        if score:
            scored.append((score, s))
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))
    out = []
    for score, s in scored[:max(1, int(limit))]:
        out.append({"name": s["name"], "category": s["category"],
                    "title": s.get("title"), "description": s.get("description"),
                    "score": score})
    return out


def _name_tokens(name):
    return {t for t in re.split(r"[^a-z0-9]+", str(name or "").lower()) if t}


def audit_skills():
    """Non-destructive health report of the skill library (JAG-203).

    A large library develops duplicates (two skills with the SAME description, or
    near-identical names) which confuse selection and bloat the prompt. This only
    REPORTS — it never deletes. Read-only.
    """
    sk = list_skills()
    dup_desc = {}
    for s in sk:
        d = re.sub(r"\s+", " ", (s.get("description") or "").strip().lower())
        if len(d) >= 40:
            dup_desc.setdefault(d, []).append(s["name"])
    dup_desc = {k: v for k, v in dup_desc.items() if len(v) > 1}
    toks = {s["name"]: _name_tokens(s["name"]) for s in sk}
    names = list(toks)
    near = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = toks[names[i]], toks[names[j]]
            if len(a) < 2 or len(b) < 2:
                continue
            inter = len(a & b)
            union = len(a | b)
            if union and inter >= 2 and (inter / union) >= 0.5:
                near.append(sorted([names[i], names[j]]))
    no_desc = [s["name"] for s in sk if not (s.get("description") or "").strip()]
    oversized = []
    for s in sk:
        try:
            n = os.path.getsize(os.path.join(REPO, s["path"]))
        except OSError:
            continue
        if n > 20000:
            oversized.append({"name": s["name"], "bytes": n})
    return {"count": len(sk), "duplicate_descriptions": dup_desc,
            "near_duplicate_names": near[:20], "missing_description": no_desc,
            "oversized": oversized[:20]}
