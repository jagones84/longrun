#!/usr/bin/env python3
"""H2-3 — the harness improvement library.

After each task Harness² keeps the ADOPTED harness *plus an `EXPERIENCE.md`* —
why it was chosen, which recurring weakness it addressed, the supporting contrast —
and an index over the entries. The next task starts from the base harness and may
reuse a component from the library, never inherit the previous task's over-fitted
harness (`research/papers/harness2/harness2_2610.14224.txt:370-404`, `:1291-1294`).

Two properties matter more than the storage shape:

1. **Components are files, not prose.** "Executable components are retained rather
   than summarised as prose" (`:1294`) — a lesson you cannot run is advice.
2. **Retrieval is bounded.** `relevant()` selects canonical index rows; `retrieve()`
   supplies complete components and provenance within a hard byte budget.

Nothing here applies a change or proves historical adoption. Legacy entries remain
inspectable; the current cycle writes no durable entry from confounded evidence.
"""
import hashlib
import json
import math
import os
import re
import shutil
import stat
import tempfile
import time
from contextlib import contextmanager

from longrun.harness import record as record_mod
from longrun.util.fswrite import write_json

LESSON_MAX = 240
INDEX_MAX_ENTRIES = 200
RELEVANT_MAX = 8
COMPONENT_MAX_COUNT = 32
COMPONENT_MAX_BYTES = 16 * 1024
EXPERIENCE_MAX_BYTES = 8 * 1024
ENTRY_MAX_BYTES = 64 * 1024
METADATA_MAX_BYTES = 64 * 1024
MIN_ENTRIES_FOR_LOO = 3
_SLUG = re.compile(r"[^a-zA-Z0-9._-]+")
_STOP = {
    "the", "and", "for", "with", "from", "into", "that", "this", "all", "any",
    "are", "was", "were", "you", "your", "its", "their", "not", "but", "one",
}


def _slug(value, fallback="entry"):
    """Filesystem-safe token for a domain or an entry id."""
    out = _SLUG.sub("-", str(value or "")).strip("-").lower()
    return (out if out and out not in (".", "..") else fallback)[:64]


def _root():
    """`<harness>/library` — beside the run records."""
    return os.path.join(record_mod.dir_path(), "library")


def domain_dir(domain):
    """Absolute directory of one domain's library."""
    return os.path.join(_root(), _slug(domain, "general"))


def entry_dir(domain, entry_id):
    """Absolute directory of one entry."""
    return os.path.join(domain_dir(domain), _slug(entry_id))


def index_path(domain):
    """Path of the domain index."""
    return os.path.join(domain_dir(domain), "index.json")


def _component_name(name):
    """A safe component FILE name that keeps its case (`SKILL.md` stays `SKILL.md`).

    A component is a file the runtime loads by name, so lowercasing it (as `_slug`
    does for ids) would silently rename the component it is supposed to preserve.
    """
    if not isinstance(name, str) or len(name) > 512:
        return ""
    parts = name.split("/")
    if len(parts) > 8 or any(p in ("", ".", "..") or
                            not re.fullmatch(r"[A-Za-z0-9._-]{1,96}", p) for p in parts):
        return ""
    return name


def _row(entry):
    """The index row of one entry: exactly the fields a prompt may read."""
    return {
        "id": entry["id"],
        "ts": round(float(entry.get("ts") or 0), 3),
        "task_kind": str(entry.get("task_kind") or "")[:200],
        "lesson": str(entry.get("lesson") or "")[:LESSON_MAX],
        "components": list(entry.get("components") or []),
    }


@contextmanager
def _open_regular(path):
    """Open every path segment without following symlinks, including ancestors."""
    descriptors = []
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
        fd = os.open(os.path.abspath(os.sep), flags)
        descriptors.append(fd)
        parts = os.path.abspath(path).split(os.sep)[1:]
        for part in parts[:-1]:
            fd = os.open(part, flags, dir_fd=fd)
            descriptors.append(fd)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        descriptors.append(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("not a regular library file")
        yield fd
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _read_file(domain, entry_id, relative, max_bytes):
    """Bounded UTF-8 read; refuse unsafe paths and unsupported platforms."""
    if (not isinstance(entry_id, str) or _slug(entry_id) != entry_id or
            entry_id.startswith(".stage-")):
        return None
    parts = relative.split("/")
    if any(p in ("", ".", "..") or not re.fullmatch(r"[A-Za-z0-9._-]{1,96}", p)
           for p in parts):
        return None
    path_parts = [_slug(domain, "general"), entry_id] + parts
    try:
        with _open_regular(os.path.join(_root(), *path_parts)) as fd:
            if os.fstat(fd).st_size > max_bytes:
                return None
            chunks = []
            remaining = max_bytes + 1
            while remaining:
                chunk = os.read(fd, min(remaining, 8192))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            body = b"".join(chunks)
        if len(body) > max_bytes:
            return None
        return {"text": body.decode("utf-8"), "provenance": {
            "domain": _slug(domain, "general"), "entry_id": entry_id,
            "path": "/".join(path_parts), "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }}
    except (OSError, ValueError, AttributeError, NotImplementedError):
        return None


def _metadata(domain, entry_id):
    got = _read_file(domain, entry_id, "entry.json", METADATA_MAX_BYTES)
    if got is None:
        return None
    try:
        entry = json.loads(got["text"])
        if not isinstance(entry, dict) or entry.get("id") != entry_id:
            return None
        names = entry.get("components")
        if (not isinstance(names, list) or not names or len(names) > COMPONENT_MAX_COUNT or
                any(not _component_name(n) for n in names) or len(set(names)) != len(names)):
            return None
        if any(b.startswith(a + "/") for a in names for b in names if a != b):
            return None
        if not math.isfinite(float(entry.get("ts") or 0)):
            return None
        return entry
    except (ValueError, TypeError, OverflowError):
        return None


def _scan(domain):
    """Rebuild the index from the entry directories (self-healing path)."""
    out = []
    base = domain_dir(domain)
    try:
        if os.path.realpath(base) != os.path.abspath(base):
            return out
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for name in names:
        if _slug(name) != name or name.startswith(".stage-"):
            continue
        got = _metadata(domain, name)
        if got is not None:
            out.append(_row(got))
    return out


def index(domain):
    """The bounded index of a domain.

    Returns:
        {"domain": str, "entries": [{id, ts, task_kind, lesson, components}]}
    """
    rows = _scan(domain)
    rows = sorted(rows, key=lambda r: (str(r.get("id")),))[:INDEX_MAX_ENTRIES]
    _write_index(domain, rows)
    return {"domain": str(domain or ""), "entries": rows}


def _write_index(domain, rows):
    """Rewrite one index atomically (never raises)."""
    try:
        os.makedirs(domain_dir(domain), exist_ok=True)
        if os.path.realpath(domain_dir(domain)) != os.path.abspath(domain_dir(domain)):
            return False
        write_json(index_path(domain), {"domain": str(domain or ""),
                                        "updated": round(time.time(), 3),
                                        "entries": rows[:INDEX_MAX_ENTRIES]})
        return True
    except Exception:  # noqa: BLE001 — the index is rebuildable from the dirs
        return False


def experience_text(domain, entry_id):
    """Legacy text accessor; empty on missing, unsafe or oversized experience."""
    got = read_experience(domain, entry_id)
    return got["text"] if got is not None else ""


def _budget(value, maximum):
    try:
        return min(maximum, max(0, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 0


def read_component(domain, entry_id, name, max_bytes=COMPONENT_MAX_BYTES):
    """Return {name, text, provenance}, or None; never truncate executable text."""
    budget = _budget(max_bytes, COMPONENT_MAX_BYTES)
    entry = _metadata(domain, entry_id)
    if not budget or entry is None or name not in entry["components"]:
        return None
    got = _read_file(domain, entry_id, "components/" + name, budget)
    return dict(got, name=name) if got is not None else None


def read_experience(domain, entry_id, max_bytes=EXPERIENCE_MAX_BYTES):
    """Return {text, provenance}, or None for an invalid or unreadable entry."""
    budget = _budget(max_bytes, EXPERIENCE_MAX_BYTES)
    if not budget or _metadata(domain, entry_id) is None:
        return None
    return _read_file(domain, entry_id, "EXPERIENCE.md", budget)


def retrieve(domain, entry_id, max_bytes=ENTRY_MAX_BYTES):
    """Read one complete entry for editor reuse, or refuse the whole bundle.

    Returns {domain, id, components: [{name, text, provenance}],
    experience: {text, provenance}}. Budget counts UTF-8 text bytes, not metadata.
    Caller budgets can lower, never raise, the fixed safety caps.
    """
    remaining = _budget(max_bytes, ENTRY_MAX_BYTES)
    entry = _metadata(domain, entry_id)
    if not remaining or entry is None:
        return None
    experience = _read_file(domain, entry_id, "EXPERIENCE.md",
                            min(remaining, EXPERIENCE_MAX_BYTES))
    if experience is None:
        return None
    remaining -= experience["provenance"]["bytes"]
    components = []
    for name in entry["components"]:
        got = _read_file(domain, entry_id, "components/" + name,
                         min(remaining, COMPONENT_MAX_BYTES))
        if got is None:
            return None
        remaining -= got["provenance"]["bytes"]
        components.append(dict(got, name=name))
    return {"domain": _slug(domain, "general"), "id": entry_id,
            "components": components, "experience": experience}


def _experience_md(entry, components):
    """The human/agent-readable record of one adoption."""
    evidence = entry.get("evidence") or {}
    fixed = ", ".join(str(x) for x in (evidence.get("fixed") or [])) or "none recorded"
    lines = [
        "# EXPERIENCE — %s" % entry["id"],
        "",
        "## Situation",
        str(entry.get("task_kind") or "(unspecified task kind)"),
        "",
        "## Lesson",
        str(entry.get("lesson") or "(none recorded)")[:LESSON_MAX],
        "",
        "## Evidence",
        "- contrast verdict: %s" % (evidence.get("verdict") or "unknown"),
        "- error classes it removed: %s" % fixed,
    ]
    if evidence.get("base_run") or evidence.get("cand_run"):
        lines.append("- runs: %s -> %s" % (evidence.get("base_run") or "?",
                                          evidence.get("cand_run") or "?"))
    lines += ["", "## Components",
              ("- " + "\n- ".join(components)) if components else "- (none)"]
    return "\n".join(lines) + "\n"


def add(domain, entry):
    """Store one adopted entry; returns the index row, or None when refused.

    Args:
        domain: the library bucket (a task family, e.g. "office").
        entry: {id?, task_kind, lesson, evidence?, files: {name: source_path}}
    Returns:
        The stored row on success. None on a duplicate id, a dangling component,
        or a write failure (in which case nothing is left behind).
    """
    if not isinstance(entry, dict):
        return None
    files = entry.get("files") or {}
    if not isinstance(files, dict) or not files or len(files) > COMPONENT_MAX_COUNT:
        return None
    for name, src in files.items():
        if not isinstance(src, str) or not os.path.isfile(src):
            return None
        if os.path.realpath(src) != os.path.abspath(src):
            return None
        if not _component_name(name):
            return None
        if any(other.startswith(name + "/") for other in files if isinstance(other, str)):
            return None
    lesson = str(entry.get("lesson") or "").strip()
    entry_id = _slug(entry.get("id") or (
        _slug(entry.get("task_kind"), "entry") + "-" +
        hashlib.sha256(lesson.encode("utf-8")).hexdigest()[:8]), "entry")
    if entry_id.startswith(".stage-"):
        return None
    target = entry_dir(domain, entry_id)
    if os.path.exists(target):
        return None  # B1: one id, one entry — a second write would be a second truth
    staging = None
    try:
        base = domain_dir(domain)
        os.makedirs(base, exist_ok=True)
        if os.path.realpath(base) != os.path.abspath(base):
            return None
        staging = tempfile.mkdtemp(prefix=".stage-", dir=base)
        os.makedirs(os.path.join(staging, "components"))
        names = []
        for name, src in files.items():
            safe = _component_name(name)
            dst = os.path.join(staging, "components", safe)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with _open_regular(src) as fd:
                with os.fdopen(os.dup(fd), "rb") as source, open(dst, "wb") as output:
                    shutil.copyfileobj(source, output)
            names.append(safe)
        stored = {
            "id": entry_id, "ts": time.time(),
            "task_kind": str(entry.get("task_kind") or ""),
            "lesson": lesson[:LESSON_MAX],
            "evidence": entry.get("evidence") or {},
            "components": sorted(names),
        }
        write_json(os.path.join(staging, "entry.json"), stored)
        with open(os.path.join(staging, "EXPERIENCE.md"), "w", encoding="utf-8") as f:
            f.write(_experience_md(stored, sorted(names)))
        # Committed directories are nonempty, so rename cannot replace a winner.
        os.rename(staging, target)
    except Exception:  # noqa: BLE001 — a half-written entry is worse than none
        if staging:
            shutil.rmtree(staging, ignore_errors=True)
        return None
    index(domain)  # Cache only: every read still scans the committed directories.
    return _row(stored)


def _tokens(text):
    """Comparable words: lowercase, ≥4 chars, no stop words."""
    return {w for w in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if len(w) >= 4 and w not in _STOP}


def relevant(domain, task_text, limit=RELEVANT_MAX):
    """Index rows that plausibly apply to this task, best first.

    Deterministic keyword overlap over `task_kind` + `lesson`; no match returns
    [] rather than a recent-but-irrelevant entry.
    """
    try:
        limit = min(RELEVANT_MAX, max(0, int(limit)))
    except (TypeError, ValueError, OverflowError):
        return []
    if not limit:
        return []
    want = _tokens(task_text)
    if not want:
        return []
    scored = []
    for row in index(domain)["entries"]:
        have = _tokens("%s %s" % (row.get("task_kind"), row.get("lesson")))
        overlap = len(want & have)
        if overlap:
            scored.append((overlap, str(row.get("id")), row))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [row for _n, _i, row in scored[:limit]]


def leave_one_out(domain):
    """The paper's honesty check: can an entry be re-used WITHOUT its own task?

    Locally this is a data-availability report, not a run: under
    `MIN_ENTRIES_FOR_LOO` entries there is nothing to conclude, and saying so is
    the point (the paper re-runs each task without its own entry, `:1428-1449`).
    """
    rows = index(domain)["entries"]
    n = len(rows)
    return {"domain": str(domain or ""), "entries": n, "status": "not-run",
            "availability": "sufficient" if n >= MIN_ENTRIES_FOR_LOO else "insufficient",
            "note": "no matched leave-one-out reruns measured; entry counts are availability only"}
