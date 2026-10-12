"""v436 — mobile theme + Plan goal box (JAG-431h).

Two WebUI fixes:
  1. On a phone the sessions drawer (`#aside`) and the bottom tab bar (`#tabbar`)
     hardcoded a dark background, so the sand/light theme was NOT applied there.
     They now use the theme tokens (`--aside` / `--menubg`).
  2. The Plan panel's goal input sat on the same row as the ▶ goal / clear / reset
     buttons, leaving it a sliver on a narrow panel. It is now a full-width row of
     its own, BELOW the buttons, spanning the panel width.

Pins the markup/CSS in webui/index.html. Deterministic, offline.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- 1: the mobile drawers follow the theme ---------------------------------
check("1a the mobile #aside drawer no longer hardcodes a dark background",
      "rgba(10,12,24,.96)" not in HTML, "")
check("1b the mobile #aside drawer uses the theme token --aside",
      "background: var(--aside); backdrop-filter: blur(14px);" in HTML, "")
check("1c the mobile #tabbar no longer hardcodes a dark background",
      "rgba(8,10,20,.85)" not in HTML, "")
check("1d the mobile #tabbar uses the theme token --menubg",
      "background: var(--menubg); backdrop-filter: blur(12px);" in HTML, "")

# --- 2: the Plan goal box is full-width on its own row -----------------------
check("2a the goal input is full-width on its own row (u-w100, u-mt6)",
      'id="planInp" class="inp u-w100 u-mt6 u-p610 u-fs12"' in HTML, "")
check("2b the goal input no longer shares the buttons row (no u-f1)",
      'id="planInp" class="inp u-f1 u-p610 u-fs12"' not in HTML, "")
check("2c the goal/clear/reset buttons are still present",
      'data-call="planGoal"' in HTML and 'data-call="clearSession"' in HTML
      and 'data-call="resetPlan"' in HTML, "")
# the input must come AFTER the buttons row (i.e. below it)
_pb = HTML.index('data-call="planGoal"')
_pi = HTML.index('id="planInp"')
check("2d the goal input sits BELOW the buttons", _pi > _pb, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
