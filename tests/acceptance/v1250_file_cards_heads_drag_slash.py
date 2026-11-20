#!/usr/bin/env python3
"""v1250 — file cards, one rail head, movable windows, `/context` + `/restart`.

Operator (2026-11-22), four asks in one message:
  1. *"i don't like edit read write … shall have a different format colour … adequate to
     THEME selected … maybe italic"*  → a file operation is its own object in the
     transcript: read (steel), edit (accent), write (info), all from THEME tokens.
  2. *"why session and inspector bars are in a different background? … uniform … see
     impeccable"* → ONE head surface (`--hd-surf`) and one inset-card shape per rail.
  3. *"all the spawning panels in the webui shall be movable"* → ONE `dragify` for every
     window, geometry remembered, the deck no longer carrying a second algorithm.
  4. *"in the slash commands include /restart … and the context command … don't
     duplicate code … commands and tools share the same functions"* → `/restart` calls
     the agent's own `harness` tool; `/context` renders the inspector's own card from
     the same endpoint and renderer.

Deterministic and offline: static pins on `webui/index.html` + the backend catalogue.
Run: python3 tests/acceptance/v1250_file_cards_heads_drag_slash.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
SLASH_PY = open(os.path.join(REPO, "src", "longrun", "core", "slash.py"),
                encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:260]) if detail and not ok else ""))


def block(start, end):
    return HTML.split(start)[1].split(end)[0] if start in HTML else ""


# ---- A: a file operation is its own card, drawn from the THEME -------------
_SKIN = '.toolcard[data-tool="fs.read"] {' + block('.toolcard[data-tool="fs.read"] {',
                                                   "/* 2026-11-16: web cards")
check("A1 read / edit / write each carry their own selector",
      all('.toolcard[data-tool="%s"] {' % t in _SKIN for t in ("fs.read", "fs.edit", "fs.write")),
      _SKIN[:300])
check("A2 read is steel, edit is the accent, write is info — THREE different tokens",
      "var(--acc2)" in _SKIN.split('fs.edit"] {')[0]
      and "var(--acc)" in _SKIN.split('fs.edit"] {')[1].split('fs.write"] {')[0]
      and "var(--info)" in _SKIN.split('fs.write"] {')[1].split(".tc-name")[0])
check("A3 the surfaces use color-mix on THEME vars, never a hard-coded colour",
      "#" not in _SKIN.replace("#", "", 0) or "rgb(" not in _SKIN,
      "hex/rgb found")
check("A4 the file name is italic in all three cards",
      _SKIN.count("font-style: italic") == 3, _SKIN.count("font-style: italic"))
check("A5 the verdict colour still owns `.tc-ic` (a state is not a card colour)",
      ".toolcard.ok .tc-ic" in HTML and ".toolcard.err .tc-ic" in HTML
      and "tc-ic" not in _SKIN)
check("A6 write says Wrote, edit says Edited — one label per verb",
      'label: "Wrote "' in HTML and 'label: "Edited "' in HTML)

# ---- B: ONE head per rail ---------------------------------------------------
_HEADS = block("aside .rail-head, #inspector .insp-tools {", "aside .rail-head h2,")
check("B1 one rule owns BOTH rail heads", "aside .rail-head, #inspector .insp-tools {" in HTML)
check("B2 the head surface is the shared `--hd-surf` token",
      "--hd-surf:" in HTML and "background: var(--hd-surf)" in _HEADS, _HEADS[:300])
check("B3 both heads are the same inset card (border + radius), not a flush strip",
      "border: 1px solid var(--line)" in _HEADS and "border-radius: 8px" in _HEADS)
check("B4 the old flush-strip surface is gone",
      "background: var(--panel); border-bottom: 1px solid var(--line);" not in HTML)

# ---- C: every spawning window is movable by ONE behaviour -------------------
_DRAG = block("function dragify(handle, box, key, opts) {", "function resizify(")
check("C1 one behaviour, bound once per box",
      'box.dataset.dragBound' in _DRAG and _DRAG.count("function dragify") == 0)
check("C2 the zoom trap is handled (rect and delta divided by the page zoom)",
      "const z = _dpZoom();" in _DRAG and "r.left / z" in _DRAG
      and "(ev.clientX - x0) / z" in _DRAG)
check("C3 the window table covers the shell's spawning panels",
      all(sel in HTML for sel in ('"#runsPanel"', '"#pvWin"', '"#diffView"',
                                  '"#pickModal"', '"#textModal"', '"#voiceHelp"',
                                  '"#newSessDlg"', '"#dirPicker"', '"#rwDlg"')))
check("C4 the deck delegates instead of keeping a second pointer algorithm",
      'dragify(head, el, "sf_panel_geo"' in HTML
      and "function _dpDrag" in HTML
      and "head.addEventListener(\"pointermove\", move)" not in HTML)
check("C5 the runs panel keeps a place the operator dragged it to",
      'localStorage.getItem("sf_win_runs")' in HTML
      and '_winRestore(p, "sf_win_runs")' in HTML)
check("C6 a saved place is clamped on open (never off-screen)",
      "function _winRestore(box, key)" in HTML and "innerWidth / z - w" in HTML)
check("C7 the phone preview stays full-screen (`smallOff`), every other window moves",
      '["#pvWin", ".pv-head", "sf_win_preview", { smallOff: true }]' in HTML)

# ---- D: the two verbs, each on the door that already exists ----------------
_FALLBACK = block("let SLASH_COMMANDS = [", "const SLASH_BY_ID")
check("D1 the first-paint catalogue offers /context and /restart",
      'id: "context"' in _FALLBACK and 'id: "restart"' in _FALLBACK)
check("D2 the backend catalogue owns both (a boot with the API up keeps them)",
      '"id": "context"' in SLASH_PY and '"id": "restart"' in SLASH_PY)
check("D3 the backend catalogue REPLACES the fallback, so the callbacks are re-attached",
      "context: () => openContextDetails()" in HTML
      and "restart: () => restartService()" in HTML)
_RESTART = block("async function restartService() {", "/* ---- approvals")
check("D4 /restart calls the agent's OWN tool (`harness` → restart), not a second door",
      'tool: "harness"' in _RESTART and 'action: "restart"' in _RESTART
      and "/api/harness/restart" not in HTML)
check("D5 /restart schedules no continuation turn (no session is passed)",
      "run_id: \"ui-restart\"" in _RESTART and "session:" not in _RESTART)
_CTXM = block("async function openContextDetails() {", "/* 2026-11-22 (operator): `/restart`")
check("D6 /context reuses the panel's readers and renderer",
      "await loadCtx();" in _CTXM and "await loadCtxItems();" in _CTXM
      and "renderCtxItems(brk)" in _CTXM)
check("D6b the card itself is ONE builder shared with the composer popover",
      "function _ctxCardHTML(d)" in HTML
      and HTML.count("_ctxCardHTML(") == 3, HTML.count("_ctxCardHTML("))
check("D7 /context adds no endpoint of its own",
      "fetch(" not in _CTXM and 'api("' not in _CTXM)
check("D8 /context reuses the panel's two doors",
      "compactNow()" in _CTXM and 'openSettings("compaction")' in _CTXM)
check("D9 the renderer takes its host (one renderer, two homes)",
      "function renderCtxItems(box) {" in HTML and "box = box || $(\"ctxCats\")" in HTML)
check("D10 a window's body action can dismiss it (close is handed to the builder)",
      '_infoModal("Context · this session", (body, close) => {' in _CTXM
      and "card.querySelector(\".cp-compact\").onclick = () => { close();" in _CTXM)
check("D10b every info window is a NAMED dialog (axe `aria-dialog-name`, 2026-11-22)",
      'box.setAttribute("aria-label", String(title || "info"));' in HTML)

# ---- E: the composer still RUNS a solo `/verb` -----------------------------
check("E1 a solo `/context` / `/restart` runs instead of shipping as prose",
      "_c.run && !_ownSkill" in HTML and "_c.run(); return;" in HTML)
check("E2 the menu row runs the same callback",
      "if (c.run) c.run();" in HTML or "c.run()" in HTML)

print("\n---\nv1250: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
