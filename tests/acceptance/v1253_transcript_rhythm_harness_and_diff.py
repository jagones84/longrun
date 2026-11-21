#!/usr/bin/env python3
"""v1253 — ONE transcript rhythm: aligned rows, no chevrons, a plain "harness" row,
frameless messages, and an edit row that opens its diff.

Operator (2026-11-22, round 169), with TRAE screenshots: *"fai come trae vedi che sono
allineate le cose? … thought non è tutto nel block … harness è disallineato e diverso dagli
altri … la freccetta per espandere … non serve, basta cliccare sul nome del file nel thread
per aprire … anche risposte LLM no vanno in frame, manco messaggi utente … le spaziature non
mi tornano, non sono uniformi … anche l'edit deve avere le stesse cose, con apribile finestra
diff … harness → LLM lo toglierei … chiamalo harness e basta … lo scope tipo Observation va
tenuto ma messo carino, no in stampatello … il font del thought non è lo stesso del messaggio
normale, mi piace uniformità"*.

  A  every row shares ONE 28px rhythm on ONE dotted rail (no nested rails, no chevron)
  B  a harness chip is a row: "harness" + a soft lowercase scope, raw body in place
  C  an answer and a user prompt are text, not boxes
  D  the thought body is ordinary message text and every path draws the same row
  E  the file name opens the thing (diff for an edit); the diff stat rides on the row

Deterministic and offline: static pins on webui/index.html.
Run: python3 tests/acceptance/v1253_transcript_rhythm_harness_and_diff.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:260]) if detail and not ok else ""))


def block(start, end):
    return HTML.split(start)[1].split(end)[0] if start in HTML else ""


# ---- A: one rhythm --------------------------------------------------------
_RHYTHM = block(".toolcard, details.think, .hinj {", ".toolcard-head, details.think > summary, .hinj > summary {")
_HEAD = block(".toolcard-head, details.think > summary, .hinj > summary {",
              "details.think > summary::-webkit-details-marker")
check("A1 tool, thought and harness rows share ONE gutter and ONE dotted rail",
      "padding: 0 6px 0 14px" in _RHYTHM and "border-left: 1px dotted var(--rail-line)" in _RHYTHM
      and "background: transparent" in _RHYTHM and "border-radius: 0" in _RHYTHM, _RHYTHM[:240])
check("A2 the row height is one token (28px), not a per-type number",
      "--row-h: 28px" in HTML and "min-height: var(--row-h)" in _HEAD
      and "26px" not in _HEAD, _HEAD[:140])
check("A3 the nested rails are gone — the log has ONE vertical line",
      "#log .tctree .tc-kids, #log .fgroup .fg-kids {" in HTML
      and "margin-left: 0; padding-left: 0; border-left: 0;" in HTML)
check("A4 no chevron in the transcript: the label is the control",
      "tc-chev" not in HTML and "details.think > summary::before" not in HTML
      and ".hinj > summary::before" not in HTML
      and "list-style: none" in _HEAD
      and "details.think > summary::-webkit-details-marker" in HTML
      and ".hinj > summary::-webkit-details-marker" in HTML)
check("A5 the hover tint is shared by the three row types",
      ".toolcard:hover, details.think > summary:hover, .hinj > summary:hover {" in HTML)

# ---- B: the harness row is a row -----------------------------------------
check("B1 the old wire chip is gone (no plug+arrow label, no uppercase pill)",
      "🔌 harness &rarr; LLM" not in HTML and "harness &rarr; LLM" not in HTML
      and ".hkind" not in HTML)
check("B2 it reads 'harness' plus a named scope, with the inbox glyph",
      "TOOL_SVG.inbox" in HTML and "function _harnessScope(k)" in HTML
      and 'observation: "Observation"' in HTML
      and '\'harness<span class="hrole"></span><span class="hsupp"></span>\'' in HTML)
check("B3 the scope is soft text, not a stamp: lowercase, 10.5px, dim",
      ".hinj .hrole { font-size: 10.5px; letter-spacing: 0; text-transform: none;" in HTML
      and "color: var(--dim); margin-left: 0; }" in HTML)
check("B4 the raw wire body is still the verbatim text, opened in place",
      'det.querySelector(".hbody").textContent = text;' in HTML
      and ".hinj .hbody { white-space: pre-wrap;" in HTML)
check("B5 a suppressed repeat is still a counter on the row",
      "summary .hsupp" in HTML and "identical not re-sent" in HTML)

# ---- C: messages are text ------------------------------------------------
_BUB = block(".msg .bubble {", ".msg .turnfoot")
check("C1 an answer carries no frame (no surface, no border, no radius, no padding)",
      "background: transparent; border: 0; border-radius: 0; padding: 0;" in _BUB
      and "font-size: 12.5px; font-weight: 400; line-height: 1.55;" in _BUB, _BUB[:240])
check("C2 a user prompt keeps ONE accent rule (a quote mark, not a box)",
      ".msg.user .bubble { border-left: 2px solid color-mix(" in HTML
      and "padding-left: 12px;" in HTML)
check("C3 the reveal flash no longer draws a box around the answer",
      ".msg.dotflash .who { color: var(--acc); }" in HTML
      and ".msg.dotflash .bubble { box-shadow" not in HTML)

# ---- D: the thought is message text --------------------------------------
check("D1 the thought body uses the message typography",
      "details.think .t { color: var(--txt); font-size: 12.5px; font-weight: 400; line-height: 1.55;" in HTML)
check("D2 the row glyph is drawn by every render path (live, persisted, replay)",
      HTML.count('aria-hidden="true">${TOOL_SVG.thought}</span>Thought') == 3
      and "thought: '<svg viewBox=\"0 0 20 20\">" in HTML,
      HTML.count("TOOL_SVG.thought"))
check("D3 the OPEN thought is the one framed surface",
      "details.think[open] { border: 1px solid var(--line); border-radius: 10px;" in HTML
      and "background: color-mix(in srgb, var(--panel2) 45%, transparent); }" in HTML)

# ---- E: the file name opens the thing ------------------------------------
check("E1 the edit/write row carries a +A −D slot filled from the diff endpoint",
      '<span class="tc-stat"></span>' in HTML and "function _fillEditStat(card, path)" in HTML
      and '"/api/edits/diff?session="' in HTML)
check("E2 the name opens the FILE for a read and the DIFF for an edit/write",
      "function _wireToolName(card, tool, args)" in HTML
      and 'if (tool === "fs.read") {' in HTML
      and "!ed.inWorkspace(path)) openPreview(path);" in HTML
      and "else openInEditor(path);" in HTML
      and "else showDiff(path);" in HTML)
check("E3 the row stays clean: action icons appear on hover/focus only",
      "opacity: 0; transition: opacity .12s;" in HTML
      and ".toolcard:hover .tc-action, .toolcard:focus-within .tc-action { opacity: 1; }" in HTML)
check("E4 the name is NOT a nested button (axe): a span inside the disclosure button",
      '<span class="tc-name">' in HTML and '<button type="button" class="tc-name"' not in HTML)

print("\n---\nv1253: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
