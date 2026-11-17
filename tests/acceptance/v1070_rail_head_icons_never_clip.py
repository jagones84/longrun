#!/usr/bin/env python3
"""v1070 — squeezing the sessions rail never makes a panel icon disappear (JAG-936).

Operator, 2026-11-17: *"squeezing session LH panel causes icon to disappear"* — with
a screenshot of a narrow rail where the head showed only two of its four panel
buttons.

Nothing hid them in code. Measured live (CDP, `#aside` forced to 150/180/220/280):
the head was ONE 36px flex row that had to hold the label, the fold control and four
24px buttons (~102px), and the rail is 220px wide BY DEFAULT (min 150) — so at the
default width the row already overflowed the `aside`'s `overflow: hidden` and the
last buttons were CLIPPED. Two of four were simply not there.

Contract pinned here (source — the browser geometry is measured by hand):
  A1 the head may grow instead of clipping (height auto, min-height keeps 36px)
  A2 the row wraps as the fallback, with the icon block `flex: 0 0 auto` so buttons
     can never shrink below their 24px target
  A3 the label is the thing that gives way below 250px (container query), so the
     head is ONE row of controls at the 220px default
  A4 the four buttons keep their 24x24 target (WCAG 2.2 AA) — nothing is shrunk
  A5 the rule is declared AFTER the RH-2 head block that pins the old one-row 36px
     geometry (a media/override placed before it would lose)
  A6 the inspector head is untouched (the change is scoped to the sessions rail)

Run: python3 tests/acceptance/v1070_rail_head_icons_never_clip.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


RH2 = ("aside .rail-head, #inspector .insp-tools {\n"
       "    height: var(--rail-hd);")
I = HTML.find("aside .rail-head { height: auto; min-height: var(--rail-hd);")
CQ = HTML.find("@container rail (max-width: 249px)")

check("A1 the head may grow instead of clipping",
      I > 0 and "height: auto; min-height: var(--rail-hd);" in HTML, "offset=%d" % I)
check("A2 the row wraps and the icon block cannot shrink",
      "aside .rail-head h2 { flex-wrap: wrap; row-gap: 4px; min-width: 0; }" in HTML
      and "aside .rail-head h2 .srail-tools { flex: 0 0 auto; margin-left: auto; }" in HTML
      and "aside .rail-head h2 .srail-tools button { flex: 0 0 auto; }" in HTML, "")
check("A3 the label yields first below 250px (one row of controls at the 220px default)",
      CQ > 0 and '#aside { container-type: inline-size; container-name: rail; }' in HTML
      and "aside .rail-head h2 .hd-name { display: none; }" in HTML[CQ:CQ + 200],
      "container@%d" % CQ)
check("A3b the label ellipsizes rather than overlapping when it is shown",
      "aside .rail-head h2 .hd-name { min-width: 0; overflow: hidden;" in HTML, "")
check("A4 the four panel buttons keep their 24x24 target",
      ".srail-tools button { width: 24px; height: 24px; padding: 0; border-radius: 6px;" in HTML,
      "")
check("A5 declared AFTER the RH-2 head block it relaxes",
      I > 0 and RH2 in HTML and I > HTML.find(RH2), "rh2@%d" % HTML.find(RH2))
check("A6 the inspector head keeps its pinned 36px geometry",
      RH2 in HTML and "#inspector .insp-tools { height: auto" not in HTML, "")
check("A7 the four buttons are still in the DOM, in order",
      all(('id="%s"' % i) in HTML for i in ("railAgents", "railJobs", "railOrg", "railConst"))
      and HTML.find('id="railAgents"') < HTML.find('id="railConst"'), "")

print("---")
print("%d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
