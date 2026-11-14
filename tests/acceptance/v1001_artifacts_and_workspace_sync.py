#!/usr/bin/env python3
"""v1001 — the Workspace list is reconciled with the disk, and MyArtifacts reads it.

Source (operator, 2026-11-14): *"i edited a file in the editor and saved but did not
appear into the RH panel workspace diff list. verify and fix this. that shall be
synced with actual repository (workspace folder) status … add MyArtifacts page"*.

Two defects, one store:
  A) an editor-dock save posts `POST /api/fs/write`, which wrote the file and never
     journalled it, so the Workspace change list could not show it at all;
  B) the list was the journal's memory only — a file changed or deleted on disk
     afterwards (another agent, an external editor, a shell) was reported with the
     stale recorded counts.

Locked here:
  A1 a save through the real handler is journalled under the session;
  A2 its row reports `disk: "clean"` and the real net counts;
  B1 an external change flips the row to `disk: "changed"` with the NEW counts;
  B2 the diff's right column follows the disk (the file as it is now);
  B3 a deleted file reports `disk: "missing"`;
  C  `GET /api/artifacts` aggregates the same journal (session, kind, size, exists);
  D  the MyArtifacts page exists as a third top-level tab, reads that route, opens
     a card in the dedicated preview window (v1002), and refreshes on `edits.recorded`.

Deterministic: no model, no network, no server. Run:
python3 tests/acceptance/v1001_artifacts_and_workspace_sync.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v1001-")
WORK = os.path.join(TMP, "workspace")
for _d in ("config", "sessions", "edits", "runs", "graphs", WORK):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_BROWSE_ROOTS"] = WORK
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import edits as E          # noqa: E402
from longrun.core import api_v02 as A         # noqa: E402

RESULTS = []
KEY = "v1001sess"
NOTE = os.path.join(WORK, "note.md")


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail and not ok else ""))


def row(path=NOTE):
    for f in E.summary(KEY)["files"]:
        if f["path"] == path:
            return f
    return {}


# --- A: an editor-dock save through the REAL handler is journalled ------------
with open(NOTE, "w", encoding="utf-8") as f:
    f.write("v1\nv2\n")
E.clear(KEY)
r = A.fs_write({"path": NOTE, "content": "v1\nv2\nv3\n", "session": KEY, "root": WORK})
check("A0 the save still succeeds", r.get("ok") is True, r)
check("A1 the save is in the session journal", row().get("path") == NOTE, E.summary(KEY))
saved = row()
check("A2 the row is reconciled with the disk (clean) and counts the real change",
      saved.get("disk") == "clean" and saved.get("add") == 1 and saved.get("del") == 0, saved)
check("A3 the save is an EDIT, not a new file", saved.get("action") == "modified", saved)
ANON = os.path.join(WORK, "anon.md")
with open(ANON, "w", encoding="utf-8") as f:
    f.write("x\n")
check("A4 a save with no session is not journalled",
      A.fs_write({"path": ANON, "content": "x\ny\n", "root": WORK}).get("ok") is True
      and all(f["path"] != ANON for f in E.summary(KEY)["files"]), E.summary(KEY))

# --- B: the DISK has the last word -------------------------------------------
with open(NOTE, "w", encoding="utf-8") as f:
    f.write("v1\nv2\nv3\nv4\nv5\n")          # edited outside the harness
cur = row()
check("B1 an external edit flips the row to changed", cur.get("disk") == "changed", cur)
check("B2 its counts describe the file as it is NOW", cur.get("add") == 3, cur)
d = E.diff(KEY, NOTE)
check("B3 the diff reports the disk state", d.get("disk") == "changed", d.get("disk"))
right = [x.get("r") for x in (d.get("rows") or [])]
check("B4 the diff's right column is the live file", "v4" in right and "v5" in right, right[-4:])
check("B5 the diff counts match the list", d.get("add") == 3, d.get("add"))

os.remove(NOTE)
gone = row()
check("B6 a deleted file reports missing", gone.get("disk") == "missing", gone)
check("B7 the missing file keeps its recorded counts instead of inventing zeros",
      gone.get("add") == 1, gone)
with open(NOTE, "w", encoding="utf-8") as f:
    f.write("v1\nv2\nv3\n")

# --- C: the artifacts index reads the same journal ---------------------------
art = E.artifacts()
check("C1 the produced file is an artifact", len(art.get("artifacts") or []) == 1, art)
a0 = (art.get("artifacts") or [{}])[0]
check("C2 it carries session, kind, size and existence",
      a0.get("session") == KEY and a0.get("kind") == "document"
      and a0.get("size", 0) > 0 and a0.get("exists") is True, a0)
os.remove(NOTE)
check("C3 a missing file is marked, never hidden",
      E.artifacts()["artifacts"][0].get("exists") is False, E.artifacts())
with open(NOTE, "w", encoding="utf-8") as f:
    f.write("v1\n")
check("C4 the kind filter is real", E.artifacts(kind="image")["count"] == 0)
check("C7 the kind table covers the reference categories",
      [E.kind_of(x) for x in ("a.pptx", "a.html", "a.docx", "a.xlsx", "a.mp4",
                              "a.png", "a.mp3", "a.py", "a.json", "a.bin")] ==
      ["slides", "html", "document", "sheet", "video", "image", "audio", "code",
       "data", "other"],
      [E.kind_of(x) for x in ("a.pptx", "a.html", "a.docx", "a.xlsx", "a.mp4")])
check("C5 the HTTP handler wraps the same index", "artifacts" in A.artifacts_list({}))
check("C6 the route is wired", 'path == "/api/artifacts"' in open(
    os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read())

# --- E: the WORKSPACE scope reads the folder, not only the journal -------------
WS = os.path.join(WORK, "proj")
for sub in ("", ".agent/docs/proposals", "node_modules/pkg", ".agent/trash"):
    os.makedirs(os.path.join(WS, sub), exist_ok=True)
for rel in ("report.docx", "deck.pptx", ".agent/docs/proposals/p.html",
            "node_modules/pkg/skip.md", ".agent/trash/skip.md"):
    with open(os.path.join(WS, rel), "w", encoding="utf-8") as f:
        f.write("x\n")
J = os.path.join(WS, "made.md")
with open(J, "w", encoding="utf-8") as f:
    f.write("a\n")
E.record(KEY, J, "", "a\n", "created")
w = E.workspace_artifacts(WS)
names = {x["name"]: x for x in (w.get("artifacts") or [])}
check("E1 the workspace scope lists files the journal never saw",
      "report.docx" in names and "p.html" in names, sorted(names))
check("E2 hidden folders ARE scanned (the proposal html lives under .agent)",
      names.get("p.html", {}).get("kind") == "html", names.get("p.html"))
check("E3 dependency trees and harness churn stay out", "skip.md" not in names, sorted(names))
check("E4 a journaled file keeps its provenance in the scan",
      names.get("made.md", {}).get("session") == KEY
      and names["made.md"]["source"] == "journal", names.get("made.md"))
check("E5 an unjournaled file claims no session",
      names.get("report.docx", {}).get("session") is None
      and names["report.docx"]["source"] == "workspace", names.get("report.docx"))
check("E6 kinds are counted for the chips", w["kinds"].get("slides") == 1, w.get("kinds"))
check("E7 the route takes scope + workspace",
      A.artifacts_list({"scope": "workspace", "workspace": WS, "root": WORK}).get("scope") == "workspace")
check("E8 a path outside the allowed roots is refused",
      "error" in A.artifacts_list({"scope": "workspace", "workspace": "/", "root": WORK}))

# --- D: the page ------------------------------------------------------------
ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("D1 the third tab exists beside Sessions/Control",
      'id="tabArtifacts"' in ui and 'data-call="showArtifacts"' in ui
      and ui.find('id="tabControl"') < ui.find('id="tabArtifacts"'))
check("D2 the page is a real container, not a panel",
      'id="artifactsView"' in ui and 'id="artGrid"' in ui and 'body.artifacts-on #app { display: none; }' in ui)
check("D3 it reads the real route", '"/api/artifacts?" + qs.toString()' in ui)
check("D4 a card opens the file in the dedicated preview window (v1002: not the editor)",
      "c.onclick = () => openPreview(c.dataset.path, row);" in ui
      and "function openPreview(path, row)" in ui
      and "function openArtifact(" not in ui)
check("D5 a write repaints the page (SSE, no polling)",
      '"edits.recorded": () => { loadEdits(); _artIfOpen(); }' in ui)
check("D6 the hash deep-links the page",
      'location.hash === "#artifacts"' in ui and ui.count('location.hash === "#artifacts"') == 2)
check("D7 the Workspace row shows the disk state as a glyph, not a sentence",
      '.eddisk' in ui and 'f.disk === "changed"' in ui and 'role="img" aria-label=' in ui)
check("D8 the tab strip is one table, not two hand-written toggles",
      "const TAB_IDS = {" in ui and 'artifacts: "tabArtifacts"' in ui)
check("D11 the change row shows the FILE NAME on its own line (the rail is narrow)",
      '#editsList .edmeta' in ui and 'class="edmeta"' in ui and "esc(_short(f.path))" in ui)
check("D12 the chip row carries the reference categories",
      'html: "HTML"' in ui and 'slides: "PPT"' in ui and 'sheet: "Sheet"' in ui
      and 'video: "Video"' in ui and 'image: "Image"' in ui and 'audio: "Audio"' in ui)
check("D12b every category is offered (dimmed at zero), not hidden",
      "ART_KIND_ORDER.map(k =>" in ui and 'class="art-chip\' + (r[2] ? "" : " is-empty")' in ui)
check("D13 the page has a Workspace / All-sessions scope switch",
      'id="artScopeWorkspace"' in ui and 'id="artScopeJournal"' in ui
      and 'qs.set("scope", "workspace")' in ui and 'qs.set("workspace", _art.ws)' in ui)
check("D14 a file with no journal claims no session (it says 'workspace')",
      'esc(a.session ? (_art.titles[a.session] || a.session) : "workspace")' in ui)
check("D15 the phone topbar rules are declared AFTER the base rules they override",
      # they used to sit between two base blocks, so the whole compaction was dead
      # and the search + gear sat outside a 390 px viewport.
      ui.find("#topbar { gap: 10px; }") < ui.find("/* ---- PHONE HEADER")
      and "@media (max-width: 480px) and (min-height: 501px)" in ui)
deck = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8").read()
check("D9 the deck's twin tab bar carries the same third tab",
      'href="/#artifacts"' in deck and "My Artifacts" in deck)
check("D10 the deck's token rewrite covers EVERY top-level link",
      'querySelectorAll(\'header a[href^="/"]\')' in deck)

print("---")
passed = sum(RESULTS)
print("v1001: %d/%d PASS" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
