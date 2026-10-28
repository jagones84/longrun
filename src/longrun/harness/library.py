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
2. **The index is what a prompt reads.** `relevant()` returns bounded index rows,
   so an editor can be told what exists without pasting whole entries into context.

Nothing here applies a change: an entry is a record of what was adopted, and the
adoption path stays `util.improve.propose` (operator decides).
"""
import hashlib
import json
import os
import re
import shutil
import time

from longrun.harness import record as record_mod
from longrun.util.fswrite import write_json

LESSON_MAX = 240
INDEX_MAX_ENTRIES = 200
RELEVANT_MAX = 8
MIN_ENTRIES_FOR_LOO = 3
_SLUG = re.compile(r"[^a-zA-Z0-9._-]+")
_STOP = {
    "the", "and", "for", "with", "from", "into", "that", "this", "all", "any",
    "are", "was", "were", "you", "your", "its", "their", "not", "but", "one",
}


def _slug(value, fallback="entry"):
    """Filesystem-safe token for a domain or an entry id."""
    out = _SLUG.sub("-", str(value or "")).strip("-").lower()
    return (out or fallback)[:64]


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
    base = os.path.basename(str(name or "")).strip()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-.")
    return safe[:96]


def _row(entry):
    """The index row of one entry: exactly the fields a prompt may read."""
    return {
        "id": entry["id"],
        "ts": round(float(entry.get("ts") or time.time()), 3),
        "task_kind": str(entry.get("task_kind") or "")[:200],
        "lesson": str(entry.get("lesson") or "")[:LESSON_MAX],
        "components": [str(c) for c in (entry.get("components") or [])][:32],
    }


def _scan(domain):
    """Rebuild the index from the entry directories (self-healing path)."""
    out = []
    base = domain_dir(domain)
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for name in names:
        path = os.path.join(base, name, "entry.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                got = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(got, dict) and got.get("id"):
            out.append(_row(got))
    return out


def index(domain):
    """The bounded index of a domain.

    Returns:
        {"domain": str, "entries": [{id, ts, task_kind, lesson, components}]}
    """
    rows = None
    try:
        with open(index_path(domain), "r", encoding="utf-8") as f:
            got = json.load(f)
        if isinstance(got, dict) and isinstance(got.get("entries"), list):
            rows = [r for r in got["entries"] if isinstance(r, dict) and r.get("id")]
    except (OSError, ValueError):
        rows = None
    if rows is None:
        rows = _scan(domain)
        if rows:
            _write_index(domain, rows)
    rows = sorted(rows, key=lambda r: (str(r.get("id")),))[:INDEX_MAX_ENTRIES]
    return {"domain": str(domain or ""), "entries": rows}


def _write_index(domain, rows):
    """Rewrite one index atomically (never raises)."""
    try:
        os.makedirs(domain_dir(domain), exist_ok=True)
        write_json(index_path(domain), {"domain": str(domain or ""),
                                        "updated": round(time.time(), 3),
                                        "entries": rows[:INDEX_MAX_ENTRIES]})
        return True
    except Exception:  # noqa: BLE001 — the index is rebuildable from the dirs
        return False


def experience_text(domain, entry_id):
    """The stored EXPERIENCE.md of one entry ('' when absent)."""
    try:
        with open(os.path.join(entry_dir(domain, entry_id), "EXPERIENCE.md"),
                  "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


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
    if not isinstance(files, dict) or not files:
        return None
    for name, src in files.items():
        if not isinstance(src, str) or not os.path.isfile(src):
            return None
        if not _component_name(name):
            return None
    lesson = str(entry.get("lesson") or "").strip()
    entry_id = _slug(entry.get("id") or (
        _slug(entry.get("task_kind"), "entry") + "-" +
        hashlib.sha256(lesson.encode("utf-8")).hexdigest()[:8]), "entry")
    target = entry_dir(domain, entry_id)
    if os.path.exists(target):
        return None  # B1: one id, one entry — a second write would be a second truth
    staging = target + ".tmp"
    try:
        os.makedirs(os.path.join(staging, "components"), exist_ok=True)
        names = []
        for name, src in files.items():
            safe = _component_name(name)
            dst = os.path.join(staging, "components", safe)
            shutil.copyfile(src, dst)
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
        os.replace(staging, target)
    except Exception:  # noqa: BLE001 — a half-written entry is worse than none
        shutil.rmtree(staging, ignore_errors=True)
        return None
    rows = index(domain)["entries"]
    if not any(r.get("id") == entry_id for r in rows):
        rows.append(_row(stored))
    _write_index(domain, rows)
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
    return [row for _n, _i, row in scored[:max(1, int(limit or RELEVANT_MAX))]]


def leave_one_out(domain):
    """The paper's honesty check: can an entry be re-used WITHOUT its own task?

    Locally this is a data-availability report, not a run: under
    `MIN_ENTRIES_FOR_LOO` entries there is nothing to conclude, and saying so is
    the point (the paper re-runs each task without its own entry, `:1428-1449`).
    """
    rows = index(domain)["entries"]
    n = len(rows)
    if n < MIN_ENTRIES_FOR_LOO:
        return {"domain": str(domain or ""), "entries": n, "status": "insufficient",
                "note": "need >=%d entries before a leave-one-out claim" % MIN_ENTRIES_FOR_LOO}
    return {"domain": str(domain or ""), "entries": n, "status": "ok",
            "note": "re-run each task with its own entry removed via harness.probe"}
