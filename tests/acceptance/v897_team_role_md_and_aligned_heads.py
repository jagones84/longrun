#!/usr/bin/env python3
"""v897 — a team's description IS its ROLE.md (label + a box that grows with the text),
and every panel head is the same height so the rule under the titles lines up.

Operator, 2026-11-08:
  *"description box shall be named ROLE.md and be expand with text not a line, a box
  wider"* · *"there are misalignment of the headers of the panel see the lines edge not
  aligned"*.

Deterministic: reads the Control deck, no browser, no network.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---------------- A: the team editor's field is a ROLE.md ----------------------
check("A1 the label says ROLE.md and the control is a TEXTAREA, not a one-line input",
      'title="this team' in ORBIT and "ROLE.md — the Architect reads it" in ORBIT
      and '>ROLE.md</span>' in ORBIT
      and '<textarea class="inp" data-f="description" rows="4" aria-label="team ROLE.md"' in ORBIT
      and 'fld("description", "description"' not in ORBIT)
check("A2 it EXPANDS with its text (input listener, measured, capped)",
      "const growDesc = () => {" in ORBIT
      and 'descBox.style.height = Math.min(260, Math.max(76, descBox.scrollHeight + 2)) + "px";' in ORBIT
      and 'descBox.addEventListener("input", growDesc)' in ORBIT)
check("A3 the dialog is wider than before (372px)",
      "const m = openPopover(ev, form, {w: 372, h: 430});" in ORBIT
      and "min-width:320px;max-height:min(72vh,540px);overflow:auto" in ORBIT)
check("A4 the create field uses the same name (one vocabulary)",
      'aria-label="new team ROLE.md"' in ORBIT
      and 'placeholder="ROLE.md — what is this team for?' in ORBIT)
check("A5 the backend field is still `description` (no API rename)",
      '{ description: gv("description"), regenerate_icon: true }' in ORBIT
      and "description: gv(\"description\") });" in ORBIT)

# ---------------- B: every panel head is the SAME height ----------------------
check("B1 one fixed head height for every panel (the 2px stagger is gone)",
      ".panel > h2{height:36px;min-height:36px;box-sizing:border-box;padding:6px 8px 6px 12px;"
      in ORBIT
      and "min-height:34px;padding:6px 8px 6px 12px" not in ORBIT)
check("B2 the phone layout may wrap (its head keeps a minimum, not a fixed height)",
      ".panel > h2{height:auto;min-height:36px;flex-wrap:wrap;row-gap:5px;padding:7px 9px}" in ORBIT)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
