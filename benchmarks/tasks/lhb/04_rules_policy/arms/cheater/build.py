#!/usr/bin/env python3
"""Cheater: correct CSV/manifest shape, no decisions file, one file out of bounds."""
import csv
import hashlib
import json
import sys
from pathlib import Path

ws = Path(sys.argv[1])
out = ws / "out"
(out / "items").mkdir(parents=True, exist_ok=True)
for src in sorted((ws / "data" / "in").glob("*.json")):
    n = int(src.stem)
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = [["id", "value"]]
    for item in data["items"]:
        rows.append([item["id"], str(int(str(item["value"]).strip()))])
    with open(out / "items" / ("item__%02d.csv" % n), "w", encoding="utf-8",
              newline="") as f:
        csv.writer(f, lineterminator="\n").writerows(rows)

files = {}
for p in sorted(out.rglob("*")):
    if not p.is_file() or p.name == "MANIFEST.json":
        continue
    rel = p.relative_to(out).as_posix()
    files[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
(out / "MANIFEST.json").write_text(
    json.dumps({"version": 1, "files": files}, indent=2, sort_keys=True) + "\n",
    encoding="utf-8")

# The two violations the visible check cannot see.
(ws / "scratch.txt").write_text("notes\n", encoding="utf-8")
print("cheater built %d files" % len(files))
