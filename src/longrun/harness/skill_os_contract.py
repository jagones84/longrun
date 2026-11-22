#!/usr/bin/env python3
"""Skill OS contract — screen cross-OS assumptions before a skill is run.

Source: arXiv:2611.26256, "SkillBridge: Cost-Aware Diagnosis and Repair of
Cross-OS Compatibility Defects in Agent Skills" (round 163). A skill is a mixed
artifact — guide text, scripts, metadata, install contract and OS assumptions —
and a skill authored on one OS fails on another for reasons scattered across all
five fields. Static contract analysis screens 3,270 skill-OS cases at precision
0.218 / recall 0.685: it is a recall-oriented SCREEN that selects where expensive
dynamic validation goes, never a verdict (`skillbridge_cross_os_skills_2611.26256.txt:334-387`).

  * `build(files)` — the contract from `{relpath: text}` (the caller reads the
    folder; this module is pure).
  * `screen(contract, target_os=None)` — evidence that fires only when it is
    matched, reachable, in conflict with the target OS and not covered by a
    fallback. Each finding names the contract field and the repair target.
  * `rank(evidence)` — executable blockers before wording, contradictions before
    isolated mentions, missing fallbacks before guarded branches.
  * `audit(rows)` — screening precision/recall/F1 against reviewed labels.

Static only: this is a hypothesis for the operator, not a confirmed defect.
"""
from __future__ import annotations

import re
import sys

FORMAT = "longrun-skill-os-contract/1"

OSES = ("linux", "macos", "windows")

REPAIR = {
    "G": "guarded guide alternatives or portable commands",
    "P": "portable wrapper, missing file, or target-OS entrypoint",
    "M": "correct support metadata or add the missing contract",
    "D": "per-OS install recipe, dependency probe, adapter, or headless fallback",
    "A": "adapter, runtime path API, guard, or explicit unsupported declaration",
    "X": "repair the authoritative field or suppress guarded evidence",
}

#: field, rule id, snippet pattern, the OSes it conflicts with, weight, and the
#: fallback tokens that show the assumption is already handled.
RULES = (
    ("G", "posix-command", r"(?m)(^\s*(\./|bash\s|sh\s+\S|chmod\s|export\s+\w+=)|\|\s*grep\b)", 
     ("windows",), 3, ("powershell", "cmd /c", "win32", "windows")),
    ("G", "apple-native", r"(?i)\b(osascript|open\s+-a|pbcopy|pbpaste|AppleScript)\b",
     ("linux", "windows"), 3, ("fallback", "if not darwin", "linux")),
    ("G", "windows-native", r"(?i)(\bpowershell\b|\.ps1\b|\bcmd\s+/c\b|%APPDATA%|\\\\\w+)",
     ("linux", "macos"), 3, ("wsl", "pwsh -Command", "bash", "fallback")),
    ("P", "posix-only-surface", r"(?im)^(?:.*/)?[\w.-]+\.(sh|bash|zsh)$",
     ("windows",), 2, (".ps1", ".bat", ".cmd", "portable")),
    ("P", "windows-only-surface", r"(?im)^(?:.*/)?[\w.-]+\.(ps1|bat|cmd)$",
     ("linux", "macos"), 2, (".sh", ".py", "portable")),
    ("D", "debian-install", r"(?i)\b(apt-get|apt\s+install|dpkg\s+-i)\b",
     ("macos", "windows"), 2, ("brew", "winget", "conda", "fallback")),
    ("D", "homebrew-install", r"(?i)\bbrew\s+(install|tap)\b",
     ("windows",), 2, ("winget", "choco", "apt", "fallback")),
    ("D", "windows-install", r"(?i)\b(winget|choco|scoop)\s+install\b",
     ("linux", "macos"), 2, ("apt", "brew", "fallback")),
    ("A", "procfs", r"(?i)(/proc/\d+|/proc/self|/proc/cpuinfo)",
     ("macos", "windows"), 2, ("sysctl", "psutil", "fallback")),
    ("A", "posix-paths", r"(?i)(\bchmod\s+[0-7]{3,4}\b|/tmp/|/usr/local/bin|/dev/null)",
     ("windows",), 1, ("tempfile", "os.devnull", "fallback")),
    ("A", "desktop-session", r"(?i)\b(xclip|xdotool|xsel|DISPLAY=|Wayland)\b",
     ("macos", "windows"), 2, ("pbpaste", "powershell", "headless", "fallback")),
)

FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---", re.S)
PLATFORM_LINE = re.compile(r"(?im)^\s*(platform|platforms|os|supported[_-]?os)\s*:\s*(.+)$")


def current_os():
    """The OS this process runs on, in the paper's vocabulary."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def build(files):
    """The five contract fields from a skill folder's text files.

    `files` is `{relpath: text}`. Guide is `SKILL.md` (or the first markdown);
    package is every non-text surface's path; metadata is the front-matter;
    dependencies are install lines; assumptions are every file's text searched
    by the rules.
    """
    files = {str(k).replace("\\", "/"): str(v or "") for k, v in (files or {}).items()}
    guide_key = "SKILL.md" if "SKILL.md" in files else next(
        (k for k in files if k.lower().endswith(".md")), "")
    guide = files.get(guide_key, "")
    fm = FRONTMATTER.search(guide)
    metadata = fm.group(1) if fm else ""
    package = sorted(k for k in files if not k.lower().endswith((".md", ".txt", ".json")))
    deps = "\n".join(line for block in files.values()
                     for line in block.splitlines()
                     if re.search(r"(?i)\b(install|pip\s|npm\s+i|apt|brew|winget|choco|"
                                  r"cargo\s+i|go\s+install|uv\s+pip)\b", line))
    return {
        "guide": guide,
        "guide_key": guide_key,
        "package": package,
        "metadata": metadata,
        "dependencies": deps,
        "files": files,
    }


def _declared_platforms(metadata):
    found = set()
    for m in PLATFORM_LINE.finditer(metadata or ""):
        value = m.group(2).lower()
        for os_name in OSES:
            if os_name in value or (os_name == "macos" and re.search(r"\b(mac|darwin|osx)\b", value)):
                found.add(os_name)
    return found


def _fallback(text, tokens):
    low = text.lower()
    return any(tok.lower() in low for tok in tokens or ())


def screen(contract, target_os=None):
    """Evidence for one target OS, ranked. `skip` when the static screen is silent."""
    os_name = (target_os or current_os()).lower()
    if os_name not in OSES:
        return {"format": FORMAT, "ok": False, "error": "unknown OS %r" % target_os,
                "evidence": [], "hypothesis": "skip"}
    fields = {
        "G": contract.get("guide", ""),
        "P": "\n".join(contract.get("package") or []),
        "M": contract.get("metadata", ""),
        "D": contract.get("dependencies", ""),
        "A": (contract.get("guide", "") + "\n"
              + "\n".join(str(v) for v in (contract.get("files") or {}).values())),
    }
    evidence = []
    files = contract.get("files") or {}
    guide_key = contract.get("guide_key") or "SKILL.md"
    # Each rule searches the ONE field it is attached to: the guide, the package
    # surface (its paths), the metadata, the install lines, or the whole skill
    # (an assumption can sit in a script as easily as in the guide).
    scopes = {
        "G": [(guide_key, fields["G"])],
        "P": [("(package)", fields["P"])],
        "M": [(guide_key, fields["M"])],
        "D": [("(dependencies)", fields["D"])],
        "A": sorted(files.items()),
    }
    for field, rule_id, pattern, conflicts, weight, fallbacks in RULES:
        if os_name not in conflicts:
            continue
        try:
            rx = re.compile(pattern)
        except re.error:  # noqa: BLE001 — a bad rule is skipped, never raised
            continue
        for rel, text in scopes.get(field, []):
            hits = list(rx.finditer(str(text or "")))
            if not hits:
                continue
            if _fallback(contract.get("guide", "") + "\n" + str(text or ""), fallbacks):
                continue
            for hit in hits[:3]:
                evidence.append({
                    "field": field,
                    "rule": rule_id,
                    "os": os_name,
                    "file": rel,
                    "line": str(text or "").count("\n", 0, hit.start()) + 1,
                    "snippet": " ".join(hit.group(0).split())[:160],
                    "conflict": "assumes an OS surface that %s does not provide" % os_name,
                    "repair": REPAIR[field],
                    "weight": weight,
                })
    declared = _declared_platforms(contract.get("metadata", ""))
    if declared and os_name not in declared:
        evidence.append({
            "field": "M", "rule": "declared-unsupported", "os": os_name,
            "file": contract.get("guide_key") or "SKILL.md", "line": 1,
            "snippet": "platform: " + ", ".join(sorted(declared)),
            "conflict": "the metadata declares support that excludes %s" % os_name,
            "repair": REPAIR["M"], "weight": 4,
        })
    if declared and len(declared) > 1 and (contract.get("package") or []):
        surfaces = " ".join(contract.get("package") or []).lower()
        posix_only = surfaces and not re.search(r"\.(ps1|bat|cmd)$", surfaces, re.I)
        win_only = surfaces and not re.search(r"\.(sh|bash|py)$", surfaces, re.I)
        if "windows" in declared and posix_only:
            evidence.append({
                "field": "X", "rule": "support-claim-vs-surface", "os": os_name,
                "file": contract.get("guide_key") or "SKILL.md", "line": 1,
                "snippet": "declares windows; package surface is POSIX-only",
                "conflict": "a broad support claim with single-OS evidence",
                "repair": REPAIR["X"], "weight": 4,
            })
        if ("linux" in declared or "macos" in declared) and win_only:
            evidence.append({
                "field": "X", "rule": "support-claim-vs-surface", "os": os_name,
                "file": contract.get("guide_key") or "SKILL.md", "line": 1,
                "snippet": "declares POSIX; package surface is Windows-only",
                "conflict": "a broad support claim with single-OS evidence",
                "repair": REPAIR["X"], "weight": 4,
            })
    ranked = rank(evidence)
    return {
        "format": FORMAT,
        "ok": True,
        "os": os_name,
        "evidence": ranked,
        "hypothesis": "validate" if ranked else "skip",
        "note": "a screening hypothesis, not a confirmed defect: "
                "static precision is modest and recall is the point",
    }


def rank(evidence):
    """Executable blockers before wording, contradictions before mentions."""
    order = {"P": 0, "X": 0, "D": 1, "A": 2, "G": 3, "M": 4}
    return sorted(evidence or (),
                  key=lambda e: (order.get(e.get("field"), 9), -int(e.get("weight") or 0),
                                 e.get("rule") or ""))


def audit(rows):
    """Screening precision/recall/F1 against reviewed OS-issue labels.

    Rows: {"selected": bool, "confirmed": bool}. Computed only over rows that
    carry both decisions, exactly as the paper scopes its own P/R/F1.
    """
    tp = fp = fn = 0
    used = 0
    for row in rows or ():
        row = row or {}
        if "selected" not in row or "confirmed" not in row:
            continue
        used += 1
        if row["selected"] and row["confirmed"]:
            tp += 1
        elif row["selected"] and not row["confirmed"]:
            fp += 1
        elif not row["selected"] and row["confirmed"]:
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision is not None and recall is not None and (precision + recall) else None)
    return {
        "format": FORMAT,
        "rows": used,
        "precision": None if precision is None else round(precision, 4),
        "recall": None if recall is None else round(recall, 4),
        "f1": None if f1 is None else round(f1, 4),
        "confusion": {"tp": tp, "fp": fp, "fn": fn},
        "findings": ([{"kind": "low-precision",
                       "note": "a screen selects work; it does not label a defect"}]
                     if precision is not None and precision < 0.5 else []),
    }
