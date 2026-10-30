#!/usr/bin/env python3
"""Read-back of the ARTIFACTS a turn wrote — mechanical, task-agnostic.

Why this module exists
----------------------
A turn can end with the files it was asked for and still answer nothing: an empty
sheet, a table where a chart was required, a PDF with one line, a workbook whose
third sheet is blank. Measured 2026-10-30 on JobBench `online_merchants/task1`:
Longrun delivered both artifacts in 54 s and scored 6/58 — the judge's failures
were things the harness could have SHOWN it ("Sheet 3 has no visualization",
"the catalog averages are not quoted"), while Harness² — whose loop keeps
re-reading its own output for 50-100 steps — scored 48/58.

The harness cannot judge meaning, so it does what it CAN do mechanically: it
opens every document the turn produced and reports its structure back to the
agent before the turn is allowed to close. Nothing here knows what a rubric is,
what the task is, or which fields matter; it only describes the files.

Design rules
------------
* Pure and offline: no model call, no network, no server import.
* Only DOCUMENT artifacts are audited (see `DELIVERABLE_EXTS`): a source-file
  edit is not a deliverable, and auditing every `.py` would be noise.
* Every reader degrades to a size/error line when its library is missing — the
  audit can make a turn SLOWER, never break it.
* The result is facts, never a verdict: the agent decides what to fix.
"""
import csv
import os
import time
from pathlib import Path

#: Files a task can be graded on. Source code is deliberately absent.
DELIVERABLE_EXTS = (".xlsx", ".xlsm", ".csv", ".pdf", ".docx", ".pptx",
                    ".md", ".txt", ".html", ".htm")

#: Directories that are inputs, caches or tooling — never "what I wrote".
#: Tool/cache directories only. An INPUT folder is deliberately NOT skipped: the
#: mtime rule already separates "given to the turn" from "written by it", and a
#: module that hard-codes a benchmark's folder name is not generic.
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
             ".pytest_cache", ".mypy_cache"}

MAX_FILES = 8
MAX_CSV_ROWS = 5000
MAX_TEXT_CHARS = 200_000
#: A big workbook/PDF is described by its size only: opening a 200 MB xlsx to
#: count charts would make the audit the slowest part of the turn.
MAX_WORKBOOK_BYTES = 25 * 1024 * 1024
MAX_PDF_BYTES = 40 * 1024 * 1024


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _workbook_facts(path):
    """Sheets with their used range, plus charts and conditional formatting."""
    try:
        from openpyxl import load_workbook
    except Exception:  # noqa: BLE001 — a missing reader is a fact, not a crash
        return {"error": "openpyxl missing"}
    try:
        wb = load_workbook(path)
    except Exception as exc:  # noqa: BLE001
        return {"error": "unreadable: %s" % type(exc).__name__}
    sheets = []
    charts = cf = 0
    for ws in wb.worksheets:
        charts += len(getattr(ws, "_charts", []) or [])
        try:
            cf += len(list(ws.conditional_formatting))
        except Exception:  # noqa: BLE001
            pass
        sheets.append({"name": ws.title, "rows": int(ws.max_row or 0),
                       "cols": int(ws.max_column or 0)})
    try:
        wb.close()
    except Exception:  # noqa: BLE001
        pass
    return {"sheets": sheets, "charts": charts, "conditional_formatting": cf}


def _csv_facts(path):
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, []) or []
            rows = 0
            for _ in reader:
                rows += 1
                if rows >= MAX_CSV_ROWS:
                    break
    except OSError as exc:
        return {"error": str(exc)[:120]}
    return {"columns": [str(c)[:40] for c in header[:12]], "rows": rows}


def _pdf_facts(path):
    try:
        from pypdf import PdfReader
    except Exception:  # noqa: BLE001
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except Exception:  # noqa: BLE001
            return {"error": "pypdf missing"}
    try:
        reader = PdfReader(path)
        pages = len(reader.pages)
        text = ""
        if pages:
            text = reader.pages[0].extract_text() or ""
    except Exception as exc:  # noqa: BLE001
        return {"error": "unreadable: %s" % type(exc).__name__}
    return {"pages": pages, "page1_chars": len(text.strip())}


def _text_facts(path):
    try:
        data = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"error": str(exc)[:120]}
    return {"lines": data.count("\n") + 1, "chars": len(data),
            "empty": not data.strip(),
            "head": " ".join(data.split())[:160]}


def _xlsx_text(path, limit=MAX_TEXT_CHARS):
    """Every cell value as text — what a reader WITHOUT a renderer can see."""
    try:
        from openpyxl import load_workbook
    except Exception:  # noqa: BLE001
        return ""
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception:  # noqa: BLE001
        return ""
    out, used = [], 0
    try:
        for ws in wb.worksheets:
            out.append(str(ws.title))
            for row in ws.iter_rows(values_only=True):
                line = " ".join(str(c) for c in row if c is not None)
                if not line:
                    continue
                out.append(line)
                used += len(line) + 1
                if used >= limit:
                    return "\n".join(out)[:limit]
    except Exception:  # noqa: BLE001 — one broken sheet must not sink the audit
        pass
    finally:
        try:
            wb.close()
        except Exception:  # noqa: BLE001
            pass
    return "\n".join(out)[:limit]


def _pdf_text(path, pages=10, limit=MAX_TEXT_CHARS):
    """The first `pages` pages of a PDF as text (empty when no reader)."""
    try:
        from pypdf import PdfReader
    except Exception:  # noqa: BLE001
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except Exception:  # noqa: BLE001
            return ""
    try:
        reader = PdfReader(path)
        parts = [(p.extract_text() or "") for p in reader.pages[:pages]]
        return "\n".join(parts)[:limit]
    except Exception:  # noqa: BLE001
        return ""


def _ooxml_text(path, prefix, limit=MAX_TEXT_CHARS):
    """Text of an OOXML part set (docx/pptx) with the stdlib only."""
    import re
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            names = sorted(n for n in z.namelist()
                           if n.startswith(prefix) and n.endswith(".xml"))
            blob, used = [], 0
            for name in names:
                data = z.read(name).decode("utf-8", "replace")
                hits = re.findall(r"<a:t>([^<]*)</a:t>|<w:t[^>]*>([^<]*)</w:t>", data)
                text = " ".join(a or b for a, b in hits)
                blob.append(text)
                used += len(text)
                if used >= limit:
                    break
            return "\n".join(blob)[:limit]
    except Exception:  # noqa: BLE001
        return ""


def deliverable_text(path, limit=MAX_TEXT_CHARS):
    """The words a reader can search INSIDE a deliverable (capped, never raises).

    EV-37: the read-back used to count structure (`charts=1`) and never read the
    words. A rubric — or a colleague — credits a figure by FINDING it, so the
    question "is the source named, is the number written down" is mechanical and
    worth answering.
    """
    suffix = Path(path).suffix.lower()
    try:
        if suffix in (".xlsx", ".xlsm"):
            if os.path.getsize(path) > MAX_WORKBOOK_BYTES:
                return ""
            return _xlsx_text(path, limit)
        if suffix == ".pdf":
            if os.path.getsize(path) > MAX_PDF_BYTES:
                return ""
            return _pdf_text(path, limit=limit)
        if suffix == ".docx":
            return _ooxml_text(path, "word/", limit)
        if suffix == ".pptx":
            return _ooxml_text(path, "ppt/slides/", limit)
        if suffix in (".csv", ".md", ".txt", ".html", ".htm"):
            return Path(path).read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:  # noqa: BLE001 — the audit must never break a turn
        return ""
    return ""


def facts(path):
    """Structural facts for one file (never raises)."""
    suffix = Path(path).suffix.lower()
    size = 0
    try:
        size = os.path.getsize(path)
    except OSError:
        pass
    out = {"size": size}
    if size == 0:
        out["empty"] = True
    if suffix in (".xlsx", ".xlsm"):
        if size > MAX_WORKBOOK_BYTES:
            out["skipped"] = "workbook over %d MB" % (MAX_WORKBOOK_BYTES // (1024 * 1024))
        else:
            out.update(_workbook_facts(path))
    elif suffix == ".csv":
        out.update(_csv_facts(path))
    elif suffix == ".pdf":
        if size > MAX_PDF_BYTES:
            out["skipped"] = "pdf over %d MB" % (MAX_PDF_BYTES // (1024 * 1024))
        else:
            out.update(_pdf_facts(path))
    elif suffix in (".md", ".txt", ".html", ".htm") and size <= MAX_TEXT_CHARS:
        out.update(_text_facts(path))
    return out


def inventory(workspace, since=0.0, limit=MAX_FILES, exclude=()):
    """Documents written under `workspace` at/after `since`, oldest first.

    `since` is the turn's start: inputs staged before the turn carry an older
    mtime and are therefore never reported as something the model produced.
    `exclude` names directories that are the HARNESS'S OWN state (data, sessions,
    harness records). They can live inside a workspace, and a record the harness
    wrote about the turn is not a deliverable of the turn — measured 2026-10-30:
    a chat whose workspace held `LONGRUN_*` state dirs had its own harness note
    read back as an artifact.
    """
    root = str(workspace or "").strip()
    if not root or not os.path.isdir(root):
        return []
    skip = {os.path.abspath(os.path.expanduser(str(p))) for p in (exclude or ()) if p}
    if os.path.abspath(root) in skip:
        return []
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS
                       and os.path.abspath(os.path.join(dirpath, d)) not in skip]
        for name in filenames:
            if not name.lower().endswith(DELIVERABLE_EXTS) or name.startswith("."):
                continue
            full = os.path.join(dirpath, name)
            if os.path.abspath(full) in skip:
                continue
            if _mtime(full) + 1.0 < float(since or 0.0):
                continue
            found.append(full)
    found.sort(key=_mtime)
    entries = []
    for full in found[-int(limit):]:
        try:
            rel = os.path.relpath(full, root)
        except ValueError:
            rel = full
        entries.append({"path": rel, "kind": Path(full).suffix.lower().lstrip("."),
                        "facts": facts(full)})
    return entries


#: A source a task can hand over: documents PLUS the structured data formats that
#: are never deliverables but are always evidence.
INPUT_EXTS = DELIVERABLE_EXTS + (".json", ".xml", ".yaml", ".yml", ".db", ".sqlite")

#: The formats a figure comes FROM. A prose brief is an input, not a source: it
#: tells you what to do, it does not supply the numbers, so a deliverable is not
#: required to cite it.
DATA_EXTS = (".csv", ".tsv", ".xlsx", ".xlsm", ".json", ".xml", ".yaml", ".yml",
             ".db", ".sqlite")


def inputs(workspace, since=0.0, limit=12, exclude=()):
    """The files the turn was GIVEN: they existed before it started.

    The mirror image of `inventory` — same workspace, opposite side of `since`. A
    task normally hands the agent a set of sources; an answer that never accounts
    for one of them rests on an input nobody looked at. That is a fact the harness
    can state without knowing the task, so it states it.
    """
    root = str(workspace or "").strip()
    if not root or not os.path.isdir(root):
        return []
    skip = {os.path.abspath(os.path.expanduser(str(p))) for p in (exclude or ()) if p}
    if os.path.abspath(root) in skip:
        return []
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS
                       and os.path.abspath(os.path.join(dirpath, d)) not in skip]
        for name in filenames:
            if not name.lower().endswith(INPUT_EXTS) or name.startswith("."):
                continue
            full = os.path.join(dirpath, name)
            if os.path.abspath(full) in skip:
                continue
            if _mtime(full) + 1.0 >= float(since or 0.0):
                continue  # written BY this turn, not given to it
            try:
                found.append(os.path.relpath(full, root))
            except ValueError:
                found.append(full)
    return sorted(found)[:int(limit)]


def _line(entry):
    """One human line per artifact: `path — <facts>`."""
    f = entry.get("facts") or {}
    kind = entry.get("kind") or "file"
    if f.get("error"):
        return "%s (%s) — %s" % (entry["path"], kind, f["error"])
    if "sheets" in f:
        cells = ", ".join("%s %dx%d" % (s["name"], s["rows"], s["cols"])
                          for s in f["sheets"][:8])
        return ("%s (%s) — %d sheet(s): %s; charts=%d; conditional-formatting=%d%s"
                % (entry["path"], kind, len(f["sheets"]), cells, f.get("charts", 0),
                   f.get("conditional_formatting", 0),
                   "; EMPTY" if f.get("size") == 0 else ""))
    if "columns" in f:
        return ("%s (csv) — %d row(s), columns: %s"
                % (entry["path"], f.get("rows", 0), ", ".join(f["columns"])))
    if "pages" in f:
        return "%s (pdf) — %d page(s), %d chars on page 1" % (
            entry["path"], f.get("pages", 0), f.get("page1_chars", 0))
    if "lines" in f:
        return "%s (%s) — %d line(s), %d chars%s" % (
            entry["path"], kind, f.get("lines", 0), f.get("chars", 0),
            " (EMPTY)" if f.get("empty") else "")
    tail = (" (%s)" % f["skipped"] if f.get("skipped")
            else (" (EMPTY)" if f.get("empty") else ""))
    return "%s (%s) — %d bytes%s" % (entry["path"], kind, f.get("size", 0), tail)


def review(workspace, request="", since=0.0, limit=MAX_FILES, exclude=()):
    """The read-back observation, or None when this turn wrote no document.

    The wording is deliberately a CHECKLIST, not a grade: the agent must be able to
    point at each requirement in the read-back, and the last line says what to do
    when it cannot.
    """
    entries = inventory(workspace, since=since, limit=limit, exclude=exclude)
    if not entries:
        return None
    lines = ["READ-BACK of what you WROTE this turn (harness: mechanical file "
             "inspection, not a judgement of your work):", ""]
    lines += ["  - " + _line(e) for e in entries]
    lines += ["", "Before you answer, check this against the request:",
              "  * every file/sheet/column/figure the request names must be visible above;",
              "  * an empty artifact, a sheet with no rows, or a requested visual "
              "element that shows `charts=0` is NOT delivered;",
              "  * if a requirement is missing, fix the artifact now — a requirement "
              "you cannot point at in the read-back is not done."]
    given = inputs(workspace, since=since, exclude=exclude)
    if given:
        lines += ["", "INPUTS you were GIVEN (they existed before this turn): %d file(s) — %s"
                  % (len(given), ", ".join(given)),
                  "  * every input above must be used or explicitly dismissed; a source "
                  "you never opened cannot back a claim."]
        # EV-37: a figure whose source is never NAMED cannot be credited by a
        # reader — or a grader — however correct it is. Mechanical test: is the
        # input's filename inside the text of what you wrote?
        try:
            blob = " ".join(deliverable_text(os.path.join(workspace, e["path"]))
                            for e in entries)[:MAX_TEXT_CHARS]
        except Exception:  # noqa: BLE001
            blob = ""
        if blob:
            # A DATA source must be named; the prose brief must not. Requiring
            # `TASK_INSTRUCTIONS.txt` in the report is noise the model then spends
            # turns on (measured 2026-10-30), and a brief is not a source of
            # figures — the numbers come from the data files.
            unnamed = [g for g in given
                       if os.path.splitext(g)[1].lower() in DATA_EXTS
                       and os.path.basename(g) not in blob]
            if unnamed:
                lines += ["  * NOT NAMED in any deliverable: %s — name the file a "
                          "figure came from; an invisible source cannot be credited."
                          % ", ".join(unnamed[:8])]
    if any((e.get("facts") or {}).get("charts") for e in entries):
        lines += ["  * a chart is a PICTURE: a reader that extracts text sees only your "
                  "cells — the plotted numbers must also appear as cells (a caption "
                  "naming the chart is not the data)."]
    head = " ".join(str(request or "").split())[:600]
    if head:
        lines += ["", "Request (head): " + head]
    return "\n".join(lines)
