#!/usr/bin/env python3
"""v1252 — the transcript is a log, not a stack of boxes; only "Thought" is framed.

Operator (2026-11-22), looking at a turn with four model-retry rows and their harness
notes: *"non mi piace vedere testi e messaggi vari nei box … guarda invece TRAE che bello!
solo i thoughts ha nei frames nelle chat session thread … copia spudoratamente il formato
… anche l'estetica vuole la sua parte"*. And: *"non voglio read edit tutto italico, solo il
nome file — il Read no"*. And on the rails: *"inspector panel e sessions panel non hanno
stesso margine dal TOP bar … io li toglierei dal frame oltre che allinearli"*.

The shape now (TRAE's):
  · a tool call is ONE 26px line on a left timeline — glyph, verb, italic file, time —
    no card surface; the details open in place;
  · the reasoning block is the ONLY framed surface, labelled "Thought", with a dot that
    pulses while it streams and stops when the turn moves on;
  · a file operation tints its GLYPH and its FILE NAME, never the verb;
  · both rail heads are frameless labels, 12px from the topbar.

  A  the tool row carries no surface (timeline, hover tint, in-place details)
  B  the tool colour reaches the glyph and the file name only; the verb is normal text
  C  "Thought" is the one framed block; the live dot animates and stops
  D  both rail heads are frameless and start at the same offset
  E  ONE name for the block ("thought"), no second vocabulary

Deterministic and offline: static pins on webui/index.html.
Run: python3 tests/acceptance/v1252_transcript_log_and_thought_frame.py
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


_ROW = block(".toolcard { display: flex; flex-direction: column; align-items: stretch; gap: 0;",
             "/* 2026-11-01: the head is the card's disclosure control")

# ---- A: a tool call is a LINE ---------------------------------------------
check("A1 the row has no card surface of its own",
      "border: 0; border-left: 1px solid var(--line);" in _ROW
      and "background: transparent" in _ROW
      and "border-radius: 0" in _ROW
      and "background: var(--panel2)" not in _ROW, _ROW[:300])
check("A2 it is a 26px line, not a padded box",
      ".toolcard-head { display: flex; align-items: center; gap: 8px; min-height: 26px; }" in HTML
      and "padding: 0 4px 0 10px" in _ROW)
check("A3 the open state happens in place (accent rail + tint, no second card)",
      ".toolcard.expanded {" in HTML and "border-left-color: var(--acc)" in HTML
      and "border-radius: 0 8px 8px 0" in HTML)
check("A4 a hover tint replaces the card",
      ".toolcard:hover { background: color-mix(" in HTML)
check("A5 no later pass re-introduces the card surface",
      "border-radius: 10px; background: var(--panel); padding: 8px 11px;" not in HTML
      and ".toolcard { border-radius: 0; background: transparent; padding: 0 4px 0 10px; }" in HTML)

# ---- B: only the file name is italic --------------------------------------
check("B1 one builder puts the verb in text and the file name in `.tc-file`",
      "function _toolNameHTML(ui)" in HTML
      and '\' <i class="tc-file">\'' in HTML)
check("B2 the file tools return verb + file (the verb is not part of the label)",
      'verb: "Read", file:' in HTML and 'verb: "Wrote", file:' in HTML
      and 'verb: "Edited", file:' in HTML)
check("B3 BOTH renderers (new card and live update) use the same builder",
      HTML.count("_toolNameHTML(") == 3, HTML.count("_toolNameHTML("))
check("B4 `.tc-name` is never italic — the italic rule is `.tc-file` only",
      ".toolcard .tc-file { font-style: italic; }" in HTML
      and ".tc-name { font-style: italic" not in HTML)
check("B5 the tool keeps a colour on its glyph (read/edit/write differ by token)",
      all('.toolcard[data-tool="%s"] .tc-ic {' % t in HTML
          for t in ("fs.read", "fs.edit", "fs.write")))

# ---- C: the ONE framed block ----------------------------------------------
_THINK = block("details.think { margin: 0 0 10px;", "/* v1.6.3 (JAG-55)")
# Re-pointed (not weakened) 2026-11-22: TRAE's shape is a plain collapsed row and the card
# only around the OPEN text, so the frame lives on `[open]` and the closed row is frameless.
check("C1 the reasoning block is framed only while it is open (TRAE's shape)",
      "border: 1px solid transparent" in _THINK and "background: transparent" in _THINK
      and "details.think[open] { border-color: var(--line);" in _THINK
      and "background: color-mix(" in _THINK and "border-radius: 10px" in _THINK, _THINK[:300])
check("C2 it is labelled Thought in every path (live, persisted, replayed)",
      HTML.count("<summary>Thought</summary>") == 2
      and '<span class="tdot"></span>Thought' in HTML,
      HTML.count("<summary>Thought</summary>"))
check("C3 the live block pulses, and stops when the turn moves on",
      'class="think live"' in HTML
      and ".think > summary .tdot" in HTML.replace("details", "")
      and HTML.count('classList.remove("live")') >= 2,
      HTML.count('classList.remove("live")'))
check("C4 reduced motion turns the pulse off",
      "@media (prefers-reduced-motion: reduce) { details.think > summary .tdot { animation: none; } }" in HTML)
check("C5 the body text is flush inside the frame (no second left rule)",
      "details.think .t { color: var(--dim); font-size: 12px; white-space: pre-wrap;" in HTML
      and "details.think .t {" in HTML)

# ---- D: the rail heads are labels -----------------------------------------
_HEADS = block("aside .rail-head, #inspector .insp-tools {", "aside .rail-head h2,")
check("D1 one rule, no surface, no border, no radius",
      "background: transparent; border: 0; border-radius: 0;" in _HEADS, _HEADS[:200])
check("D2 the shared `--hd-surf` token is gone (a card with no card)",
      "--hd-surf" not in HTML)
check("D3 both rails start 12px from the topbar",
      # the session rail by its padding, the inspector by margin + sticky offset (so the
      # pinned head never travels the 12px it is aligned with).
      "#aside { padding-top: 12px; }" in HTML
      and "#inspector .insp-tools { position: sticky; top: 12px; z-index: 3; margin-top: 12px; }" in HTML)
check("D4 the context rail has ONE top-padding truth (the head carries the 12px)",
      HTML.count("#rail { padding-top: 0; }") == 1
      and "#rail { padding: 12px 12px 14px; }" not in HTML)

# ---- E: one vocabulary ----------------------------------------------------
check("E1 the control names the block the operator sees",
      '"show every thought block"' in HTML and '"hide every thought block"' in HTML)
check("E2 no visible 'chain-of-thought block' copy is left",
      "chain-of-thought block<" not in HTML
      and '"show every chain-of-thought block"' not in HTML
      and '"hide every chain-of-thought block"' not in HTML)
check("E3 no colour emoji in the transcript labels",
      "🧠 chain-of-thought" not in HTML)

print("\n---\nv1252: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
