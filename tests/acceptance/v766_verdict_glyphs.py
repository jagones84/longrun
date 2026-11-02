#!/usr/bin/env python3
"""v766 — a verdict is a glyph that follows the theme, not a colour emoji.

Source (operator, 2026-11-01, PWA/mobile round): the chrome still painted every
verdict with a COLOUR EMOJI. Measured before the change: 45 `✅/✕`-class verdict
paint sites across toasts, approval cards, the improvement review, the plan-stop
map, the task tree, the settings save confirmations and the status dots of the
model / MCP / provider / key lists.

Why it is a defect and not taste:
  * an emoji carries its own palette, so the SAME chip is bright green on
    `graphite`, `sepia` and `sakura` — it cannot express the theme's accent;
  * it renders ~1.35em tall inside 10-11px rows, which is what clipped the phone
    session badge to a sliver (fixed in v762) and why a bell emoji used to shift
    the rail row height;
  * `craft-floor` bans colour emoji in product chrome outright, and this UI is
    meant to read as an instrument, not as a chat toy.

Contract (the vocabulary already used by `taskTree()` for its evidence chip):
  A) the verdict/dot emoji are GONE from `webui/index.html`;
  B) verdicts use ✓ (ok) / ✕ (fail or blocked), which inherit `currentColor`;
  C) status dots use SHAPES — ● loaded / ○ available / ◐ degraded / ⊘ no key —
     so the difference survives a monochrome theme;
  D) the remaining emoji inventory is RATCHETED: it may not grow.

Deterministic: static contract on webui/index.html. No server, no model, no net.
Run: python3 tests/acceptance/v766_verdict_glyphs.py
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = os.path.join(REPO, "webui", "index.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


ui = open(UI, encoding="utf-8").read()

# ---------------- A: the colour-emoji verdicts are gone ----------------
GONE = {
    "\u2705": "white heavy check mark",
    "\u274c": "cross mark",
    "\u26d4": "no entry",
    "\U0001f7e2": "green circle",
    "\u26aa": "white circle (emoji)",
    "\U0001f7e0": "orange circle",
    "\U0001f512": "lock",
}
left = {cp: name for cp, name in GONE.items() if cp in ui}
check("A1 no colour-emoji verdict or status dot is left in the shell",
      not left, left)

# ---------------- B: the verdict vocabulary is text glyphs ----------------
PAIRS = [
    ('ok.textContent = "\u2713 approve"', "an approval offers a text check"),
    ('no.textContent = "\u2715 deny"', "a denial offers a text cross"),
    ('ok.textContent = "\u2713 accept"', "an improvement offer uses the check"),
    ('no.textContent = "\u2715 reject"', "an improvement rejection uses the cross"),
    ('("\u2713 green \u00b7 "', "a green verify prints the check"),
    ('"\u2715 " + (why || "not verified")', "a red verify prints the cross"),
    ('goal_reached: "\u2713 goal reached"', "the plan-stop map is text"),
    ('if (reason === "goal_reached" && !goalVisible()) return "\u2713 work complete"',
     "a plain chat never claims a goal the operator did not set"),
    ('blocked: "\u2715 blocked"', "a blocked stop is a cross"),
    ('blocked: "\u2715", cancelled: "\u2298"', "the task tree marks are text"),
]
for needle, why in PAIRS:
    check("B " + why, needle in ui, needle)

# ---------------- C: status dots are shapes ----------------
DOTS = [
    ('m.loaded ? "\u25cf" : (m.available ? "\u25cb" : "\u2298")',
     "the model menu: loaded / available / no key"),
    ('c.connected ? "\u25cf" : (c.enabled ? "\u25d0" : "\u25cb")',
     "the MCP list: connected / enabled / off"),
    ('p.available ? "\u25cf" : "\u25d0"',
     "the provider list: available / degraded"),
    ('k.set ? "\u25cf" : "\u25d0"',
     "the keys list: set / missing"),
]
for needle, why in DOTS:
    check("C " + why, needle in ui, needle)

# ---------------- D: the emoji inventory may not grow ----------------
# Measured 2026-11-01 after this pass: 121 remaining, all CONTENT markers
# (🎯 /goal, 📎 attachments, 🗂/📁 pickers, ⚙/🗑 actions) or the tab-title bell.
# They are parked in the plan as a separate slice, not silently blessed: the
# ratchet only forbids ADDING more chrome emoji without the operator's word.
astral = [ch for ch in ui if ord(ch) >= 0x1F000]
check("D1 the remaining emoji inventory does not grow (ratchet 121)",
      len(astral) <= 121, "%d found" % len(astral))
check("D2 an error toast leads with the cross, not with a word",
      'toast("\u2715 " + r.error)' in ui
      and 'push("\u2715 blocked "' in ui
      and 'push("\u2715 run aborted")' in ui, "")

print("---")
ok = sum(results)
print("\nv766: %d/%d PASS" % (ok, len(results)))
raise SystemExit(0 if ok == len(results) else 1)
