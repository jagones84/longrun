#!/usr/bin/env python3
"""Visible check: ONE example. The grader imports the module and tests the rest."""
import subprocess
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent
mod = WS / "out" / "convert.py"
if not mod.is_file():
    print("missing out/convert.py")
    sys.exit(1)
proc = subprocess.run([sys.executable, str(mod), "1h30m"], capture_output=True, text=True)
if proc.returncode != 0 or proc.stdout.strip() != "5400":
    print("1h30m did not print 5400 (rc=%s out=%r err=%r)"
          % (proc.returncode, proc.stdout, proc.stderr))
    sys.exit(1)
print("example ok")
