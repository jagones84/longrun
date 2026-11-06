#!/usr/bin/env python3
"""Shape check only: the grader validates every CSV, the manifest and the rules."""
import json
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent
out = WS / "out"
if not (out / "MANIFEST.json").is_file():
    print("missing out/MANIFEST.json")
    sys.exit(1)
try:
    m = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
except ValueError as exc:
    print("manifest is not JSON: %s" % exc)
    sys.exit(1)
if m.get("version") != 1 or not isinstance(m.get("files"), dict) or not m["files"]:
    print("manifest must be {version: 1, files: {...}} with entries")
    sys.exit(1)
print("shape ok (%d files listed)" % len(m["files"]))
