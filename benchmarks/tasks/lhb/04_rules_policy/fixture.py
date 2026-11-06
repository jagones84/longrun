#!/usr/bin/env python3
"""Deterministic inputs for the policy task: 12 small JSON files."""
import json
import sys
from pathlib import Path

ws = Path(sys.argv[1])
src = ws / "data" / "in"
src.mkdir(parents=True, exist_ok=True)
for n in range(1, 13):
    rows = [
        {"id": "I%02da" % n, "value": n * 2},
        {"id": "I%02db" % n, "value": " %d " % (n * 3)},
        {"id": "I%02dc" % n, "value": n % 5},
    ]
    (src / ("%02d.json" % n)).write_text(
        json.dumps({"batch": n, "items": rows}, indent=2) + "\n", encoding="utf-8")
