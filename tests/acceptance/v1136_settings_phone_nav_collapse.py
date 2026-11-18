#!/usr/bin/env python3
"""v1136 — a phone's Settings window is not pushed down by a dead nav column.

Round 71. The 640px block (webui/index.html ~2264) turns the settings nav into a
compact top strip: `flex: 0 0 auto`, `border-right: 0`, a full-width <select>, and
12px of main padding. Three later UNCONDITIONAL rules — the v639 rhythm and the
2026-11-16 design layer — re-declared the same selectors with the same specificity,
so they won by source order and silently restored the desktop geometry on a phone:

    measured at 390px, before:  .sw-nav flex 0 0 204px, height 204, #swMain top 310
    measured at 390px, after:   .sw-nav flex 0 0 auto,  height  57, #swMain top 163

The five pins below are structural, because the defect IS the cascade: a later
unconditional rule with the same selector beats an earlier media block, so the
phone contract must be the last word for every geometry property it owns.

Deterministic: one served file (webui/index.html); no server, no model, no network.
Run: python3 tests/acceptance/v1136_settings_phone_nav_collapse.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


page = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()


def brace_end(css, i):
    """Index just past the block whose opening brace is at `i`."""
    depth = 0
    while i < len(css):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def blocks(css, opener):
    """(start, end) of every block whose header is exactly `opener`."""
    out = []
    for m in re.finditer(re.escape(opener), css):
        i = css.find("{", m.end())
        if i < 0:
            continue
        j = brace_end(css, i)
        if j > 0:
            out.append((m.start(), j))
    return out


phone = [b for b in blocks(page, "@media (max-width: 640px)")
         if "#settingsWin .sw-nav" in page[b[0]:b[1]]]
check("A1 the phone block owns the settings nav", len(phone) == 1, len(phone))

phone_css = page[phone[0][0]:phone[0][1]] if phone else ""
check("A2 on a phone the nav is not a fixed column",
      re.search(r"#settingsWin \.sw-nav\s*\{[^}]*flex:\s*0 0 auto", phone_css) is not None,
      phone_css[:300])
check("A3 on a phone the nav has no desktop divider",
      re.search(r"#settingsWin \.sw-nav\s*\{[^}]*border-right:\s*0", phone_css) is not None,
      phone_css[:300])
check("A4 on a phone the category picker replaces the buttons",
      re.search(r"#settingsWin \.sw-nav button\s*\{\s*display:\s*none", phone_css) is not None
      and re.search(r"#settingsWin \.sw-nav-sel\s*\{\s*display:\s*block", phone_css) is not None,
      phone_css[:300])

# --- B: nothing AFTER the phone block may re-declare that geometry ----------
tail_start = phone[0][1] if phone else 0
desktop = [b for b in blocks(page, "@media (min-width: 641px)") if b[0] >= tail_start]
masked = list(page)
for s, e in desktop:
    for k in range(s, e):
        if masked[k] != "\n":
            masked[k] = " "
plain_tail = "".join(masked[tail_start:])

GEOM = ("flex", "flex-basis", "padding", "border-right", "border-bottom", "height")
offenders = []
for m in re.finditer(r"#settingsWin \.sw-nav\s*\{([^}]*)\}", plain_tail):
    body = m.group(1)
    hit = [p for p in GEOM if re.search(r"(^|;|\s)" + re.escape(p) + r"\s*:", body)]
    if hit:
        offenders.append((m.group(0)[:60], hit))
check("B1 no later UNCONDITIONAL rule re-declares the phone nav geometry",
      offenders == [], offenders)
check("B2 the main padding has ONE unconditional owner (no second phone value)",
      len(re.findall(r"#settingsWin \.sw-main\s*\{[^}]*padding:", plain_tail)) == 1
      and re.search(r"#settingsWin \.sw-main\s*\{[^}]*padding", phone_css) is None,
      re.findall(r"#settingsWin \.sw-main\s*\{[^}]{0,80}", plain_tail))

# --- C: the desktop geometry still lives, but inside a desktop block --------
desk_css = "".join(page[s:e] for s, e in desktop)
check("C1 the desktop nav keeps its 204px column",
      re.search(r"#settingsWin \.sw-nav\s*\{[^}]*flex-basis:\s*204px", desk_css) is not None)
check("C2 the desktop main keeps its generous padding",
      re.search(r"#settingsWin \.sw-main\s*\{[^}]*padding:\s*16px 18px 24px", desk_css) is not None)
check("C3 the desktop nav keeps its own padding, in the desktop block",
      re.search(r"#settingsWin \.sw-nav\s*\{[^}]*padding:\s*10px", desk_css) is not None)

# --- D: the live twin and the file's braces --------------------------------
probe_path = os.path.join(REPO, ".agent", "tools", "perf", "permissions_page_probe.mjs")
probe = open(probe_path, encoding="utf-8").read() if os.path.exists(probe_path) else ""
check("D1 the live probe measures the same contract at 390px",
      all(k in probe for k in ("D1 the phone nav is only as tall as its picker",
                               "D2 #swMain starts right under the picker",
                               "D3 the phone nav carries no desktop right border")))
check("D2 every media block this fix added is brace-closed",
      len(re.findall(r"@media \(min-width: 641px\)", page))
      == len(blocks(page, "@media (min-width: 641px)"))
      and len(re.findall(re.escape("@media (max-width: 640px)"), page))
      == len(blocks(page, "@media (max-width: 640px)")),
      (len(re.findall(r"@media \(min-width: 641px\)", page)),
       len(blocks(page, "@media (min-width: 641px)"))))

print("\n---\nv1136: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
