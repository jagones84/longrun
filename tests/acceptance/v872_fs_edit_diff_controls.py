#!/usr/bin/env python3
"""v872 — fs.edit diffs resolve relative paths only when the journal is unambiguous."""

import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
TEMP = tempfile.TemporaryDirectory(prefix="v872-fs-edit-")
os.environ["LONGRUN_CONFIG_DIR"] = str(Path(TEMP.name, "config"))
os.environ["LONGRUN_SESSIONS_DIR"] = str(Path(TEMP.name, "sessions"))
os.environ["LONGRUN_DATA_DIR"] = str(Path(TEMP.name, "data"))
os.environ["LONGRUN_DB"] = str(Path(TEMP.name, "events.db"))
os.environ["LONGRUN_EDITS_DIR"] = str(Path(TEMP.name, "edits"))
sys.path.insert(0, str(REPO / "src"))

from longrun.tools import edits  # noqa: E402

RESULTS: list[bool] = []
KEY = "v872-session"


def check(name: str, ok: bool, detail: Any = "") -> None:
    """Record one deterministic acceptance result."""
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail and not ok else ""))


def seed(paths: list[str]) -> None:
    """Replace the session journal with one changed entry per supplied path."""
    edits.clear(KEY)
    for index, path in enumerate(paths):
        edits.record(
            KEY,
            path,
            "before-%d\n" % index,
            "after-%d\n" % index,
            "modified",
        )


def main() -> int:
    """Check path resolution and accessible tool-card action controls."""
    exact_path = "/workspace/src/stats.py"
    seed([exact_path])
    exact = edits.diff(KEY, exact_path)
    check("E1 exact absolute journal path still resolves",
          not exact.get("error") and exact.get("add") == 1)

    relative = edits.diff(KEY, "src/stats.py")
    check("E2 unique relative suffix resolves the recorded file",
          not relative.get("error") and relative.get("rows"))

    seed([r"C:\workspace\src\stats.py"])
    windows_relative = edits.diff(KEY, "src/stats.py")
    check("E3 relative suffix normalizes Windows path separators",
          not windows_relative.get("error") and windows_relative.get("rows"))

    seed([
        "/workspace-a/src/stats.py",
        "/workspace-b/src/stats.py",
    ])
    ambiguous = edits.diff(KEY, "src/stats.py")
    check("E4 matching multiple journal paths returns an ambiguity error",
          "ambiguous" in str(ambiguous.get("error", "")).lower())

    seed([exact_path])
    basename = edits.diff(KEY, "stats.py")
    check("E5 basename-only lookup does not select a journal entry",
          bool(basename.get("error"))
          and "ambiguous" not in str(basename.get("error", "")).lower())

    html = (REPO / "webui" / "index.html").read_text(encoding="utf-8")
    update_start = html.find("function updateToolCard(data)")
    update_end = html.find("\nfunction ", update_start + 1)
    update_source = html[update_start:update_end]
    action_style = re.search(
        r"\.toolcard \.tc-action\s*\{([^}]+)\}", html
    )
    action_css = action_style.group(1) if action_style else ""
    check("U1 diff/open actions render labeled SVG buttons",
          'className = "ghost tc-action tcdiff"' in update_source
          and 'className = "ghost tc-action tcopen"' in update_source
          and 'setAttribute("aria-label"' in update_source
          and "<svg" in update_source
          and 'aria-hidden="true"' in update_source)
    check("U2 icon controls have a 28px pointer target and visible hover/focus",
          "min-width: 28px" in action_css
          and "min-height: 28px" in action_css
          and ".toolcard .tc-action:hover" in html
          and ".toolcard .tc-action:focus-visible" in html)

    passed = sum(RESULTS)
    print("v872: %d/%d checks" % (passed, len(RESULTS)))
    return 0 if RESULTS and all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
