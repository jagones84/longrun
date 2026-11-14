#!/usr/bin/env python3
"""v992 — the chunker cannot spin forever on a bad `chunk_lines`.

`_emit_range` clamps the OVERLAP (`min(overlap, chunk_lines - 1)`) but never the
window itself. With `chunk_lines <= 0` — reachable from config, where
`int(cfg.get("chunk_lines") or 60)` turns a float like `0.5` into `0` — the loop
computes `end = s`, appends nothing and sets `s = end - 0`, so `s` never moves:
a busy `while s < e` at 100% CPU that never returns. The indexer runs it on a
background thread, so the symptom would be "ingestion never finishes".

Contract:
  A) `chunk_lines` of 0 or a negative value terminates and still covers the text;
  B) a fractional config value (0.5 -> 0) terminates through `chunk_file`;
  C) the normal path is unchanged: every source line lands in some chunk.

The hang is proven with a subprocess timeout: a hanging case fails the test
instead of hanging it.

Deterministic: no model, no server, no network.
Run: python3 tests/acceptance/v992_chunk_window_guard.py
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = []

TEXT = "\n".join("line %d of the fixture" % i for i in range(1, 41))


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def run(body, timeout=8):
    """Run a snippet in a subprocess; ('TIMEOUT' | rc, stdout+stderr)."""
    prelude = ("import sys; sys.path.insert(0, %r)\n"
               "from longrun.memory import chunk as C\n"
               "TEXT = %r\n" % (os.path.join(REPO, "src"), TEXT))
    try:
        p = subprocess.run([sys.executable, "-c", prelude + body],
                           capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "no answer in %ss" % timeout


# ---- A: zero and negative windows terminate and cover --------------------
for cl in (0, -3):
    rc, out = run(
        "out = C.chunk_doc(TEXT, %d, 0)\n"
        "lines = set()\n"
        "for c in out:\n"
        "    lines.update(range(c['start'], c['end'] + 1))\n"
        "print(len(out), min(lines) if lines else 0, max(lines) if lines else 0)\n" % cl)
    ok = rc == 0 and out.split()[0].isdigit() and int(out.split()[0]) > 0 \
        and int(out.split()[1]) == 1 and int(out.split()[2]) == 40
    check("A chunk_lines=%d terminates and covers every line" % cl, ok, (rc, out[:120]))

# ---- B: a fractional config value ---------------------------------------
rc, out = run(
    "out = C.chunk_file(TEXT, 'text', 'doc', {'chunk_lines': 0.5, 'overlap_lines': 0.5})\n"
    "print(len(out))\n")
check("B chunk_lines=0.5 terminates with chunks", rc == 0 and out.isdigit() and int(out) > 0,
      (rc, out[:120]))

# ---- C: the normal path is unchanged ------------------------------------
rc, out = run(
    "out = C.chunk_doc(TEXT, 10, 2)\n"
    "lines = set()\n"
    "for c in out:\n"
    "    lines.update(range(c['start'], c['end'] + 1))\n"
    "print(len(out), min(lines), max(lines))\n")
ok = rc == 0 and out.split()[0].isdigit() and int(out.split()[0]) == 5 \
    and int(out.split()[1]) == 1 and int(out.split()[2]) == 40
check("C 40 lines at 10 per chunk with 2 overlap", ok, (rc, out[:120]))

ok = sum(RESULTS)
print("\nv992: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
