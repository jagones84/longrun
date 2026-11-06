#!/usr/bin/env python3
"""Shape check only: the grader is hidden and stricter than this file."""
import json
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent
p = WS / "out" / "report.json"
if not p.is_file():
    print("missing out/report.json")
    sys.exit(1)
try:
    d = json.loads(p.read_text(encoding="utf-8"))
except ValueError as exc:
    print("not JSON: %s" % exc)
    sys.exit(1)
need = {"rows", "revenue_total", "revenue_by_region", "top_product", "monthly"}
if set(d) != need:
    print("keys differ: %s" % sorted(set(d) ^ need))
    sys.exit(1)
if not isinstance(d["rows"], int) or d["rows"] <= 0:
    print("rows must be a positive integer")
    sys.exit(1)
if round(sum(d["revenue_by_region"].values()), 2) != round(d["revenue_total"], 2):
    print("region revenues do not add up to the total")
    sys.exit(1)
print("shape ok")
