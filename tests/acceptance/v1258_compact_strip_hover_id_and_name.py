#!/usr/bin/env python3
"""v1258 — the round-174 contract of the composer strip, the chat header, the todo rows
and the tool row's two readings.

Operator (2026-11-22, round 174): *"invece di scrivere workspace and plan sulla barra sopra
la msg box metti le icone, risparmi spazio e togli il riassunto 4 done, run id. Lì in alto a
destra metti l'autogeneration icon IA"*; *"on top of chat … non mettere l'id di session chat,
occupa spazio. Fallo apparire e copiare al click sul nome stesso al passaggio del mouse"*;
*"i todo in chat thread non possono contenere il testo tutto a destra: deve stare in basso al
done e Jx number così può occupare lo spazio orizzontale"*; *"se clicco sul file si apre file
normale nell'editor. Se clicco sui numeri di linee modificati a destra si apre il pannello
diff"*.

  A  the strip is icon-only, carries no summary, and the ✨ is its right end
  B  the chat header shows the id only on hover/focus; the name itself copies
  C  a todo row is meta-above / label-full-width (chat thread and Plan panel)
  D  the tool row's file NAME opens the editor; only +A −D opens the diff

Deterministic and offline: static pins on webui/index.html.
Run: python3 tests/acceptance/v1258_compact_strip_hover_id_and_name.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
STRIP = HTML[HTML.index('<div id="cmpSuper">'):HTML.index('<div id="inpWrap">')]
FS = open(os.path.join(REPO, "webui", "assets", "filtersort.js"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:240]) if detail and not ok else ""))


# ---- A: the strip ---------------------------------------------------------
check("A1 the two toggles are ICONS with a name, not the words workspace/plan",
      'aria-label="workspace"' in STRIP and 'aria-label="plan"' in STRIP
      and "<svg" in STRIP
      and ">workspace<" not in STRIP and ">plan<" not in STRIP)
check("A2 no summary line survives (the panel's count is the only count)",
      'id="csSum"' not in STRIP and 'class="cs-sum"' not in HTML
      and '["sPlan", "sWorkspace"].forEach' not in HTML)
check("A3 the ✨ is the strip's right end, inside the strip",
      '<span id="cmpSpark"></span>' in STRIP
      and "#cmpSpark { margin-left: auto;" in HTML)
check("A4 the strip is still the message box's top row (dropup body above it)",
      HTML.index('id="cmpSuper"') < HTML.index('id="inpWrap"')
      and "bottom: calc(100% + 6px);" in HTML)

# ---- B: the chat header ---------------------------------------------------
CH = HTML[HTML.index('<div id="chatHead" hidden>'):HTML.index('id="chatSearchBar"')]
check("B1 the session id is NOT printed inline (no space until asked for)",
      'id="chatHeadId"' in CH
      and "#chatHead .ch-id { position: absolute;" in HTML
      and "display: none;" in HTML[HTML.index("#chatHead .ch-id {"):HTML.index("#chatHead .ch-sp")]
      and "#chatHead .ch-title:hover ~ .ch-id, #chatHead .ch-title:focus-visible ~ .ch-id { display: block; }" in HTML)
check("B2 the NAME is the copy control (pointer + keyboard)",
      'class="ch-title" id="chatHeadTitle" role="button" tabindex="0"' in CH
      and 'aria-label="copy this session\'s name and id"' in CH
      and '_cht.onclick = _copySessionName;' in HTML
      and 'e.key === "Enter" || e.key === " "' in HTML)
check("B3 the dedicated ⧉ copy control still exists (name + id, JAG-480)",
      'id="chatHeadCopy"' in HTML and 'aria-label="copy name"' in HTML
      and "const payload = t ? (t + \"\\n\" + sessionId) : sessionId;" in HTML)

# ---- C: the todo rows -----------------------------------------------------
check("C1 the chat-thread todo summary is ONE column (meta line, then the label)",
      ".tctree > summary" in HTML
      and "display: grid; grid-template-columns: minmax(0, 1fr); align-items: start;" in HTML
      and ".tctree .tclabel { min-width: 0; overflow-wrap: anywhere; }" in HTML)
check("C2 the Plan / task row is the same anatomy, always (no two-line fallback)",
      ".task { display: grid; grid-template-columns: minmax(0, 1fr); gap: 3px; align-items: start; }" in HTML
      and ".task .tlabel { flex: 0 0 100%; }" in HTML
      and "function _markWrappedTasks" not in HTML)
check("C3 the status badge and the Jx / Ax.nY ids share the meta line",
      ".tctree .tcmeta { display: flex; flex-direction: row; align-items: center; gap: 6px; }" in HTML
      and ".task .tmeta { display: flex; flex-direction: row; align-items: center;" in HTML)

# ---- D: the tool row's two readings --------------------------------------
WTN = HTML[HTML.index("function _wireToolName"):HTML.index("const _editStatSeen")]
check("D1 the file NAME opens the file in the editor (every tool)",
      'nm.title = "open " + p;' in WTN and "openInEditor(path);" in WTN
      and "openPreview(" not in WTN)
check("D2 the line stat (+A −D) is the only diff affordance",
      'const st = card.querySelector(".tc-stat");' in WTN
      and "showDiff(path);" in WTN
      and WTN.index("showDiff(path);") > WTN.index('const st = card.querySelector(".tc-stat")'))
check("D3 the editor shows an out-of-workspace path with its own warning (one rule)",
      "⚠ outside the workspace" in
      open(os.path.join(REPO, "webui", "assets", "editor.js"), encoding="utf-8").read())

# ---- E: the axe finding this round closed ---------------------------------
check("E1 aria-controls names the filter dialog only while it is OPEN",
      'btn.setAttribute("aria-controls"' not in FS[FS.index('btn.setAttribute("aria-haspopup"'):
                                                      FS.index("function dirty()")]
      and 'if (on) btn.setAttribute("aria-controls", pop.id);' in FS
      and 'else btn.removeAttribute("aria-controls");' in FS)

print("\n---\nv1258: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
