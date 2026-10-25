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

import hashlib
import io
import math
import os
import re
import shutil
import stat
import tempfile
import zipfile

from longrun.util import paths
from longrun.util.paths import REPO_ROOT as REPO, DATA_DIR as APP_DATA_DIR
SKILLS_DIR = os.path.join(REPO, "skills")

LOCAL_CATEGORY = "local"

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _digests_path():
    """Baseline file for skill content digests (env-overridable for tests)."""
    return os.environ.get("LONGRUN_SKILLS_DIGESTS") or \
        os.path.join(APP_DATA_DIR, "skills.digests.json")


def skill_digest(path):
    """P2 skill trust: sha256 of a SKILL.md's bytes, None when unreadable.

    Accepts a SKILL.md file or a skill directory (resolves SKILL.md inside).
    The digest binds (name, resolved path, content): any edit — overwrite
    install, matrix promote, upstream pull — changes it. Pure read-only.
    """
    try:
        p = str(path or "")
        if os.path.isdir(p):
            p = os.path.join(p, "SKILL.md")
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except (OSError, ValueError):
        return None


def load_digests():
    """{skill name: digest} trust baseline, {} when never recorded."""
    import json
    try:
        with open(_digests_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_digests(mapping):
    """Persist the digest baseline (best-effort, never raises)."""
    import json
    try:
        os.makedirs(os.path.dirname(_digests_path()), exist_ok=True)
        with open(_digests_path(), "w", encoding="utf-8") as f:
            json.dump({str(k): str(v) for k, v in (mapping or {}).items()},
                      f, indent=1, sort_keys=True)
        return True
    except (OSError, ValueError):
        return False


def verify_skill_digests(baseline, live=None):
    """Compare a {name: digest} baseline against the live tree (pure).

    `live` is {name: digest}; when omitted it is scanned from `list_skills()`.
    Returns {ok, changed, new, gone} as sorted name lists: `changed` caught a
    content swap under a kept name, `new` was never baselined, `gone` left.
    """
    if live is None:
        live = {}
        try:
            for s in list_skills():
                if s.get("digest"):
                    live[s["name"]] = s["digest"]
        except Exception:  # noqa: BLE001 — verification never breaks the caller
            pass
    base = baseline or {}
    live = live or {}
    ok = sorted(n for n, d in live.items() if base.get(n) == d)
    changed = sorted(n for n, d in live.items() if n in base and base.get(n) != d)
    new = sorted(n for n in live if n not in base)
    gone = sorted(n for n in base if n not in live)
    return {"ok": ok, "changed": changed, "new": new, "gone": gone}


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


_cache = {"sig": None, "skills": [], "bodies": {}}


def _matrix_skills_dir():
    try:
        from longrun.core import matrix
        if not matrix.is_enabled():
            return ""
        from longrun.tools import matrix_guard
        _root, _msrc, mdot = matrix_guard._roots()
        return os.path.join(mdot, "skills")
    except Exception:  # noqa: BLE001
        return os.path.join(paths.MATRIX_DOT_DIR, "skills")


def _skills_sig():
    """Signature of the skills tree: mtimes of SKILLS_DIR + each category dir.

    The category dirs are symlinks into the autodist store, so adding a skill
    inside a category changes the CATEGORY mtime but NOT the top-level dir
    mtime. Keying the cache on the top-level mtime alone made a freshly adopted
    skill invisible until a server restart.
    """
    mdir = _matrix_skills_dir()
    if not os.path.exists(SKILLS_DIR) and not os.path.exists(mdir):
        return None
    parts = [os.stat(SKILLS_DIR).st_mtime_ns if os.path.exists(SKILLS_DIR) else 0]
    if os.path.isdir(mdir):
        try:
            parts.append(("matrix", os.stat(mdir).st_mtime_ns))
            for name in sorted(os.listdir(mdir)):
                sd = os.path.join(mdir, name)
                sp = os.path.join(sd, "SKILL.md")
                if os.path.isfile(sp):
                    parts.append(("matrix", name, os.stat(sp).st_mtime_ns))
        except OSError:
            pass
    try:
        for cat in (sorted(os.listdir(SKILLS_DIR)) if os.path.isdir(SKILLS_DIR) else []):
            cd = os.path.join(SKILLS_DIR, cat)
            try:
                if not os.path.isdir(cd):
                    continue
                parts.append((cat, os.stat(cd).st_mtime_ns))
                for name in sorted(os.listdir(cd)):
                    sd = os.path.join(cd, name)
                    try:
                        # JAG-462: fingerprint the SKILL.md FILE, not just the skill
                        # DIRECTORY. Editing an existing SKILL.md changes the file's
                        # mtime but leaves the parent dir mtime untouched, so the
                        # cached title/description stayed STALE (and that stale text is
                        # what gets injected into the system prompt).
                        sp = os.path.join(sd, "SKILL.md")
                        parts.append((cat, name, os.stat(sd).st_mtime_ns,
                                      os.stat(sp).st_mtime_ns))
                    except OSError:
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
    # JAG-497: the body text is ALREADY read here (8192 chars) to parse the
    # title/description — keep a lowercase copy so `search_skills` can rank over
    # the real CONTENT (the instructions), not just the one-line blurb, at zero
    # extra I/O. It stays out of the returned dicts so `action:list` stays small.
    bodies = {}
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
                        with open(sp, "rb") as f:
                            raw = f.read()
                        text = raw.decode("utf-8", errors="replace")[:8192]
                    except OSError:
                        continue
                    title, desc = _parse_skill_md(text, name)
                    bodies[sp] = text.lower()
                    skills.append({"name": name, "category": cat,
                                   "path": os.path.relpath(sp, REPO),
                                   "abspath": sp,
                                   "digest": hashlib.sha256(raw).hexdigest(),
                                   "title": title, "description": desc,
                                   # JAG-451: `auto` marks MACHINE-generated skills
                                   # (the skills/created box); `local` = user-uploaded.
                                   "auto": cat == "created",
                                   "local": cat == LOCAL_CATEGORY})
    mdir = _matrix_skills_dir()
    if os.path.isdir(mdir):
        for name in sorted(os.listdir(mdir)):
            sd = os.path.join(mdir, name)
            sp = os.path.join(sd, "SKILL.md")
            if os.path.isfile(sp):
                try:
                    with open(sp, "rb") as f:
                        raw = f.read()
                    text = raw.decode("utf-8", errors="replace")[:8192]
                except OSError:
                    continue
                title, desc = _parse_skill_md(text, name)
                try:
                    rel_p = os.path.relpath(sp, REPO)
                except ValueError:
                    rel_p = sp
                bodies[sp] = text.lower()
                skills.append({"name": name, "category": "matrix",
                               "path": rel_p,
                               "abspath": sp,
                               "digest": hashlib.sha256(raw).hexdigest(),
                               "title": title, "description": desc,
                               "auto": True, "matrix": True, "local": False})
    _cache.update(sig=sig, skills=skills, bodies=bodies)
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
            try:  # trust-on-first-install: stamp the new content digest
                _bl = load_digests()
                _dg = skill_digest(os.path.join(target, "SKILL.md"))
                if _dg:
                    _bl[safe] = _dg
                    save_digests(_bl)
            except Exception:  # noqa: BLE001 — stamping never breaks install
                pass
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
            p = s.get("abspath") or os.path.join(REPO, s["path"])
            with open(p, "r",
                      encoding="utf-8", errors="replace") as f:
                return {"ok": True, **s, "content": f.read(65536)}
    return None


def skills_context(max_chars=2200):
    """The skills block injected into the agent system prompt.

    JAG-163 preloaded every installed skill as NAME + one-line description so the
    model knew what it had without a discovery round-trip.

    JAG-497 makes it a POINTER instead of an index: with 175 installed skills the
    enumeration cost ~2.6k chars of EVERY prompt for a list the model mostly
    ignores, and it still could not tell which skill really fit. The block now
    names the categories + the exact tool calls, and the model discovers the ONE
    skill it needs with `search` (ranked over name, description AND the SKILL.md
    body) or `list`. Same information reachable, a fraction of the always-on cost.
    """
    skills = list_skills()
    if not skills:
        return "Skills: none found in %s." % SKILLS_DIR
    cats = sorted({s["category"] for s in skills})
    out = ("Skills: %d installed, in categories: %s.\n"
           'Before solving a task, SEARCH this library instead of improvising: '
           'call `skills.search` {"query":"<task keywords>"} (or {"action":"search","query":"<task keywords>"}) — ranks over each skill\'s '
           "name, description AND full instructions (SKILL.md body); "
           '`skills.list` ({"action":"list"}) dumps every name; `skills.read` {"name":"<name>"} ({"action":"read","name":"<name>"}) '
           "loads ONE skill — then FOLLOW its instructions step by step."
           % (len(skills), ", ".join(cats)))
    if len(out) > max_chars:
        out = out[:max_chars] + \
            '\n…[skills block truncated — still find the rest with {"action":"search","query":"..."}]'
    return out


_SKILL_STOP = {
    "the", "and", "for", "with", "you", "are", "not", "this", "that", "error",
    "failed", "unknown", "command", "tool", "run", "get", "set", "use", "using",
    "how", "can", "help", "skill", "skills", "want", "need", "make", "does",
}


def search_skills(query, limit=10):
    """Rank installed skills against `query` (JAG-198, extended JAG-497).

    Progressive discovery (Claude Code / ScaleMCP pattern): the model can find
    the ONE relevant skill without loading the whole library into context.

    JAG-497: the ranking now also reads the SKILL.md BODY (the actual
    instructions), not only name/title/description — that is where a skill really
    says what it does, and it is what lets a content-only query find the skill
    after the always-on index was dropped from the prompt. Weights: name/title 3x,
    description 2x, body 1x. Pure lexical + deterministic — no model, no network
    (an embedding index would add a model dependency and non-deterministic tests
    for a 175-file library a keyword scan covers instantly). Multiword queries
    need two distinct term matches unless the skill name/title matches; a
    single-word query must match its name, title, or description.
    Returns a list of {name, category, title, description, score}, best first.
    """
    words = set(re.findall(r"[a-z]{3,}", str(query or "").lower())) - _SKILL_STOP
    if not words:
        return []
    bodies = _cache.get("bodies") or {}
    # v647: IDF weighting. A word that appears in 40 skills ("test") used to
    # outvote a word that appears in 3 ("battery"), so "how to run the test
    # battery gate" returned browser-testing and log-forensics while the local
    # testing skill never surfaced. A term is now worth log(N/df): the rarer it
    # is in THIS library, the more it says about the skill that has it.
    docs, df = [], dict.fromkeys(words, 0)
    for s in list_skills():
        strong = (str(s.get("name") or "") + " " + str(s.get("title") or "")).lower()
        weak = str(s.get("description") or "").lower()
        body = bodies.get(s.get("abspath") or "", "")
        present = {w for w in words if w in strong or w in weak or w in body}
        if not present:
            continue
        for w in present:
            df[w] += 1
        docs.append((s, strong, weak, body, present))
    if not docs:
        return []
    idf = {w: math.log((len(docs) + 1.0) / (1.0 + df[w])) + 1.0 for w in words}
    scored = []
    for s, strong, weak, body, present in docs:
        name_hits = present & {w for w in words if w in strong}
        # A multi-word query needs two distinct terms, or a name/title hit; a
        # single word must appear in the name, the title or the description.
        if len(words) == 1:
            if not (name_hits or any(w in weak for w in present)):
                continue
        elif len(present) < min(2, len(words)) and not name_hits:
            continue
        score = 0.0
        for w in present:
            weight = idf[w]
            if w in strong:
                score += 3 * weight
            if w in weak:
                score += 2 * weight
            if w in body:
                score += 1 * weight
        if score:
            scored.append((round(score, 3), s))
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
    # P2 skill trust: content swaps under a kept name (overwrite install,
    # matrix promote, upstream pull). Report-only like everything else here.
    changed = []
    try:
        bl = load_digests()
        if bl:
            changed = verify_skill_digests(bl)["changed"]
    except Exception:  # noqa: BLE001 — audit stays read-only and total
        changed = []
    return {"count": len(sk), "duplicate_descriptions": dup_desc,
            "near_duplicate_names": near[:20], "missing_description": no_desc,
            "oversized": oversized[:20], "changed": changed}
