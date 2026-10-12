#!/usr/bin/env python3
"""v430 — docling as the top document-ingestion backend (JAG-430).

The user chose "optimal RAG ingestion": docling (IBM, MIT) is a pure-Python package
(`pip install docling`) that adds layout-aware reading order, real TABLE structure
(TableFormer) and native IMAGE input on top of the plain-text stack. These static
guards pin the wiring so the backend cannot silently disappear.

Deterministic (no model, no network).

Run: python3 tests/acceptance/v430_docling_ingest.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


DOCIO = _read("src", "longrun", "memory", "docio.py")
REQS = _read("requirements.txt")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- 1: images are ingestible (docling-only) --------------------------------
check("1a IMAGE_EXT is declared",
      "IMAGE_EXT = {" in DOCIO, "")
check("1b BINARY_DOC_EXT includes the image extensions",
      "BINARY_DOC_EXT |= IMAGE_EXT" in DOCIO, "")
check("1c .png/.jpg are in the image set",
      '".png"' in DOCIO and '".jpg"' in DOCIO, "")

# --- 2: availability + detection --------------------------------------------
check("2a available() reports the docling backend",
      '"docling": _has_docling()' in DOCIO, "")
check("2b _has_docling / _has_module exist",
      "def _has_docling(" in DOCIO and "def _has_module(" in DOCIO, "")

# --- 3: the backend + its precedence ----------------------------------------
check("3a the _docling backend is defined", "def _docling(" in DOCIO, "")
check("3b it uses docling's DocumentConverter",
      "DocumentConverter" in DOCIO and "export_to_markdown" in DOCIO, "")
ex = DOCIO[DOCIO.index("def extract("):]
check("3c extract() tries docling BEFORE markitdown",
      ex.index("_docling(path)") < ex.index("_markitdown(path)"), "")
check("3d docling result is tagged as the engine 'docling'",
      '"docling"' in ex, "")

# --- 4: graceful degradation ------------------------------------------------
check("4a images without docling return an actionable reason",
      "install docling" in DOCIO, "")

# --- 5: it is a declared (optional) dependency ------------------------------
check("5 requirements.txt pins docling", "docling>=" in REQS, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
