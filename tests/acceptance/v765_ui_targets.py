#!/usr/bin/env python3
"""v765 — the chrome is legible and its targets are hittable (measured, not assumed).

Source (operator, 2026-11-01): "see for any other things to change according to your
personal screenshots in desktop and mobile image view so you can decide. also menu
settings etcetera many are full of unuseful spacings and text".

Baseline measured live before the change (headless CDP, `ui_goldens.py`):
  * 419 interactive controls at 1440x1000, **372** of them under 24x24 — the WCAG 2.2
    AA minimum (2.5.8). The worst recurring ones: `.fgroup-rw` / `.tc-rw` at 20x15 and
    `.msg .copy` at 28x21, i.e. a hit area smaller than the glyph;
  * micro-type in the session rail: the role label at 9px, the message count at 10px,
    the id chip at 9.5px — three sizes for three facts in the same row;
  * the id chip was declared TWICE: once with `--acc2` text on an `--accent` border
    (two accents for a hex id) and once dim on a hairline. The second won, so the
    first was dead CSS pretending to be a design decision.

Contract:
  A) the session rail uses one type scale and ONE definition per piece of meta;
  B) the id chip is an identifier: dim text, hairline border, no accent;
  C) a pointer target is at least 24x24 where the control is a glyph.

Deterministic: static contract checks on webui/index.html. No server, no model.
Run: python3 tests/acceptance/v765_ui_targets.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = os.path.join(REPO, "webui", "index.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


ui = open(UI, encoding="utf-8").read()


def rule(selector):
    """The declarations of the FIRST rule whose selector list starts with `selector`."""
    i = ui.find(selector + " {")
    if i < 0:
        return ""
    return ui[i:ui.find("}", i)]


def rules(selector):
    """Every rule for `selector` (a base rule and a polish rule can both exist)."""
    out = []
    start = 0
    while True:
        i = ui.find(selector + " {", start)
        if i < 0:
            return out
        out.append(ui[i:ui.find("}", i)])
        start = i + 1


# ---- A. one type scale in the rail -------------------------------------------
jid = rule(".sess .jid")
check("A1 the id chip is declared once",
      ui.count(".sess .jid {") == 1)
check("A2 it is an identifier: dim on a hairline, no second accent",
      "var(--dim)" in jid and "var(--line)" in jid
      and "acc2" not in jid and "var(--accent)" not in jid,
      jid[:120])
check("A3 the rail meta is 11px (count) / 10.5px (role, id) — nothing at 9px",
      "font-size: 11px" in rule(".sess .n")
      and "font-size: 10.5px" in rule(".sess .nrl")
      and "font-size: 10.5px" in jid
      and "font-size: 9px" not in ui.split(".sess .nrl {")[1].split("}")[0],
      rule(".sess .n")[:60])
check("A4 the row count is declared once too (the older 10px copy is gone)",
      ui.count(".sess .n {") == 1)

# ---- B. pointer targets ------------------------------------------------------
copy = rule(".msg .copy")
check("B1 the transcript copy button is at least 28x24",
      "min-height: 24px" in copy and "min-width: 28px" in copy, copy[:140])
rw = rule(".tc-rw, .task-rw, .fgroup-rw")
check("B2 the three group-rewind glyphs are 24x24 boxes",
      "width: 24px" in rw and "height: 24px" in rw
      and "align-items: center" in rw and "justify-content: center" in rw, rw[:160])
check("B3 the rewind rule is still ONE selector list (no per-class drift)",
      ui.count(".tc-rw, .task-rw, .fgroup-rw {") == 1)
check("B4 the rail head controls are 24x24 and sized in ONE place",
      any("width: 24px; height: 24px" in r for r in rules(".srail-tools button"))
      and sum(1 for r in rules(".srail-tools button") if "width:" in r) == 1,
      [r.split("{")[0].strip() for r in rules(".srail-tools button")])
check("B5 the tool-card disclosure is a 28px row, not an 18px strip",
      "min-height: 28px" in rule(".toolcard-head"), rule(".toolcard-head")[:80])
check("B6 the tool-card verdict is a pip painted by the card state",
      '<span class="tc-ic" aria-hidden="true"></span>' in ui
      and ".toolcard.ok .tc-ic { background: var(--ok); }" in ui
      and 'textContent = data.ok ? "✅" : "⛔"' not in ui)

# ---- C. no regression of the pins that matter --------------------------------
check("C1 the copy hover still uses the accent",
      ".msg .copy:hover { color: var(--txt); border-color: var(--acc); }" in ui)
check("C2 the rail rewind buttons keep their class names (behaviour pins)",
      'class="tc-rw"' in ui and 'class="task-rw"' in ui and 'class="fgroup-rw"' in ui)

# ---- D. the audit's own sanity: the rail has no text below 10.5px ------------
# Line-scoped: a selector never spans lines here, and the JS bundle mentions
# `.sessions` in strings, so an unanchored regex would match code.
rail_rules = re.findall(r"(?m)^[ \t]*\.(?:sess|sgroup)[^\n{}]*\{[^}]*\}", ui)
tiny = []
for r in rail_rules:
    if "::before" in r or "::after" in r:
        continue          # state pips carry no text
    for px in re.findall(r"font-size:\s*([\d.]+)px", r):
        if float(px) < 10.5:
            tiny.append((px, r.split("{")[0].strip()[:40]))
check("D1 the session rail carries no information text below 10.5px",
      not tiny, tiny[:6])
check("D2 the finished-turn marker is a monochrome pip, not a bell emoji",
      'content: ""; width: 11px; height: 11px' in rule(".sess.done::before")
      and 'class="rb-pip"' in ui
      and 'class="rp-ic" aria-hidden="true"></span>' in ui)
# The bell is allowed in exactly ONE place: the browser tab title, which lives outside
# the page's visual language (a tab has no tokens to paint with).
check("D3 the bell emoji survives only in the tab title",
      ui.count("🔔") == 1
      and 'document.title = n ? "(" + n + ") 🔔 " + base : base;' in ui,
      ui.count("🔔"))

print("---\n\nv765: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
