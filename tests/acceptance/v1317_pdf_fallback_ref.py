#!/usr/bin/env python3
"""v1317 — two quality defects from the audit's CodeQL triage.

  A  `docio._pdf_pages_diag_fallback` parsed `pdfinfo` for the page count and then
     returned an EMPTY list: the count was computed and thrown away, so PDF
     diagnostics said "0 pages / 0 text-bearing pages" whenever PyMuPDF was absent
     — the exact case the fallback exists for (`py/unused-local-variable`, the
     `total` assignment). It now splits one `pdftotext` run on the form feed that
     separates pages and reports real per-page char counts.
  B  `architect._webui_providers(op="test")` built `ref` only when a model was
     named, then formatted it inside a ternary — safe today only because the
     ternary checks `model` first (`py/uninitialized-local-variable`). `ref` is
     now initialised, so a reorder of that ternary cannot raise NameError.

Deterministic: `_run` is stubbed, no PDF, no subprocess. Run:
    python3 tests/acceptance/v1317_pdf_fallback_ref.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

_TMP = tempfile.mkdtemp(prefix="sf-v1317-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(_TMP, _k)
    os.makedirs(os.path.join(_TMP, _k), exist_ok=True)
os.environ["LONGRUN_DATA_HOME"] = _TMP

from longrun.memory import docio  # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


# ── A · the fallback reports real per-page rows ─────────────────────────────
_real_which, _real_run = docio.shutil.which, docio._run
_TWO = b"hello world\fpage two has more text here"
docio.shutil.which = lambda name: "/usr/bin/pdftotext" if name == "pdftotext" else _real_which(name)
_calls = []


def _make_run(body):
    def _fake_run(cmd, timeout=None):
        _calls.append(list(cmd))
        if cmd[:1] == ["pdftotext"]:
            return 0, body, b""
        return 0, b"", b""
    return _fake_run


docio._run = _make_run(_TWO)
try:
    rows = docio._pdf_pages_diag_fallback("x.pdf")
finally:
    docio.shutil.which, docio._run = _real_which, _real_run

check("A1 the fallback returns pages instead of the empty list it used to",
      bool(rows), rows)
check("A2 per-page char counts are real",
      [r["page"] for r in rows] == [1, 2] and [r["chars"] for r in rows] == [11, 27],
      rows)
check("A3 it uses one pdftotext call and no pdfinfo",
      any(c[:1] == ["pdftotext"] for c in _calls)
      and not any(c[:1] == ["pdfinfo"] for c in _calls), _calls)

# a trailing form feed is the separator after the LAST page, not a new page
docio.shutil.which = lambda name: "/usr/bin/pdftotext"
docio._run = _make_run(_TWO + b"\f")
try:
    trailing = docio._pdf_pages_diag_fallback("x.pdf")
finally:
    docio.shutil.which, docio._run = _real_which, _real_run
check("A4 a trailing form feed is not counted as a page",
      len(trailing) == 2 and [r["chars"] for r in trailing] == [11, 27], trailing)

# an empty / failed pdftotext still yields nothing (image-only PDF path stays)
docio.shutil.which = lambda name: "/usr/bin/pdftotext"
docio._run = lambda cmd, timeout=None: (0, b"", b"")
try:
    empty = docio._pdf_pages_diag_fallback("x.pdf")
finally:
    docio.shutil.which, docio._run = _real_which, _real_run
check("A5 an empty pdftotext output yields no rows (OCR path keeps over)",
      empty == [], empty)

# ── B · `ref` is initialised before the ternary that formats it ─────────────
from longrun.agent import architect  # noqa: E402

_src = open(architect.__file__, encoding="utf-8").read()
_fn = _src[_src.index("def _webui_providers("):]
_fn = _fn[:_fn.index("\ndef ", 10)]
_branch = _fn[_fn.index('if op == "test"'):]
_pre = _branch[:_branch.index("if model:")]
check("B1 `ref` is initialised before the model branch",
      'ref = ""' in _pre, _pre.strip().splitlines()[:6])

# behaviour: op=test with NO model reports the provider, never a model ref
from longrun.model import providers as _prov  # noqa: E402

_real_probe = _prov.probe
_prov.probe = lambda pid, timeout=10: {"ok": True, "models": 4, "latency_ms": 7}
try:
    res = architect._webui_providers({"id": "openrouter"}, "test")
finally:
    _prov.probe = _real_probe
check("B2 op=test with no model reports the provider branch",
      res.get("ok") is True and "reachable" in res.get("stdout", ""), res)

print()
if FAILED:
    print("FAILED %d/%d: %s" % (len(FAILED), len(CHECKS), ", ".join(FAILED)))
    sys.exit(1)
print("OK %d/%d" % (len(CHECKS), len(CHECKS)))
