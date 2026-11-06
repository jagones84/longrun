#!/usr/bin/env python3
"""Build out/report.json from the real scanner output and its attempt counter."""
import hashlib
import json
import sys
from pathlib import Path

ws = Path(sys.argv[1])
scan = ws / "out" / "scan.txt"
body = scan.read_bytes()
attempts = int((ws / "state" / ".scan_attempts").read_text(encoding="utf-8").strip())
report = {"lines": len([l for l in scan.read_text(encoding="utf-8").splitlines() if l.strip()]),
          "sha256": hashlib.sha256(body).hexdigest(),
          "attempts": attempts}
(ws / "out" / "report.json").write_text(
    json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("report built (attempts=%d)" % attempts)
