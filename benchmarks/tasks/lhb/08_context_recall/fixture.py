#!/usr/bin/env python3
"""Deterministic 24-note corpus: five canonical facts, five superseded decoys."""
import sys
from pathlib import Path

ws = Path(sys.argv[1])
docs = ws / "data" / "docs"
docs.mkdir(parents=True, exist_ok=True)

FACTS = {
    7: "Project codename: northwind",
    19: "Release date: 2026-12-03",
    12: "Maximum batch size: 480",
    23: "Owning team: atlas",
    16: "Rollback window: 45m",
}
DECOYS = {
    3: "Project codename: southwind (superseded)",
    21: "Release date: 2026-11-20 (superseded)",
    5: "Maximum batch size: 240 (superseded)",
    9: "Owning team: borax (superseded)",
    14: "Rollback window: 90m (superseded)",
}

for n in range(1, 25):
    lines = ["# Operations note %02d" % n, "",
             "Owner rotation for shift %02d; review before the weekly sync." % n, ""]
    for k in range(1, 10):
        lines.append("Checklist item %d.%d: confirm the routine for subsystem %02d "
                     "and record the outcome in the shared log." % (n, k, n))
    lines.append("")
    if n in FACTS:
        lines.append(FACTS[n])
    if n in DECOYS:
        lines.append(DECOYS[n])
    (docs / ("note_%02d.md" % n)).write_text("\n".join(lines) + "\n", encoding="utf-8")
