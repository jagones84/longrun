#!/usr/bin/env python3
"""v899 — the deck's ghost controls are glyphs (no frame), and the model-policy button
reports what it did instead of firing silently and ending in a modal.

Operator, 2026-11-08:
  *"remove frames from buttons, place adequately, the f model policy button DO NOTHING
  whats its aim? its not workdin gnothing happen"*.

Measured live before the change: `POST /api/teams/T9/models` answers 200 with the policy
refs and `assigned: 2` — the button WAS calling the server. With an org that already
follows the policy nothing visibly changed, the only feedback was a modal at the end of
seven sequential requests, and `.btn.ghost` still drew `.btn`'s 1px frame around every
header icon.

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


# ---------------- A: a ghost control is the glyph ------------------------------
check("A1 a ghost button has NO frame (hover paints the surface instead)",
      ".btn.ghost{background:transparent;border-color:transparent}" in ORBIT)
check("A2 the panel head's icon buttons are frameless and read as one cluster",
      "border-color:transparent;background:transparent}" in ORBIT
      and ".panel > h2 .btn.mini:hover{background:var(--hover);color:var(--txt)}" in ORBIT
      and ".panel > h2 .ctools{display:inline-flex;align-items:center;gap:2px}" in ORBIT)
check("A3 the ⋮ glyph stays frameless too (no regression on v892)",
      ".btn.ghost.mini.dots{border:0;background:transparent;" in ORBIT)

# ---------------- B: the policy reports a STATE -------------------------------
i_btn = ORBIT.index('id="agPolicy"')
i_st = ORBIT.index('id="agPolicySt"')
i_reset = ORBIT.index('id="rzReset"')
check("B1 the result glyph sits in the SAME cluster, right after the gear",
      -1 < i_btn < i_st < i_reset)
check("B2 the run is ANIMATED in place (disabled + gen-busy + aria-busy, cleared in finally)",
      'btn.disabled = true; btn.classList.add("gen-busy"); btn.setAttribute("aria-busy", "true");' in ORBIT
      and 'btn.disabled = false; btn.classList.remove("gen-busy"); btn.removeAttribute("aria-busy");' in ORBIT
      and "} finally {" in ORBIT.split("async applyModelPolicy(){")[1][:2500])
policy = ORBIT[ORBIT.index("async applyModelPolicy(){"):]
policy = policy[:policy.index("\n  /* v622:")]
check("B3 the result is a GLYPH, not a modal sentence (the guard may still alert)",
      'alert("model policy\\n' not in policy
      and 'genState(st, changed.length ? "ok" : "same", why);' in policy)
check("B4 'already compliant' has its own mark (a ✓ would be a lie)",
      's.textContent = (kind === "warn") ? "✗" : (kind === "same" ? "=" : "✓");' in ORBIT
      and ".gen-ic.same{color:var(--dim)}" in ORBIT)
check("B5 the policy is still the SERVER's (no client-side model decision)",
      '"/api/teams/" + encodeURIComponent(tid) + "/models"' in policy
      and "cloud[0]" not in policy and "this.api.post(\"/api/agents\"" not in policy)
check("B6 the reported count is the CHANGED agents, not the server's writes",
      "if (was !== now) changed.push(" in policy and "changed.length" in policy)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
