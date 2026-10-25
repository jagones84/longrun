#!/usr/bin/env python3
"""v284 — inspector/context/composer polish + voice-input guidance.

JAG-284 (user): (1) put Approvals at the top — it matters; (2) the Context panel
showed an "Other" category that is never filled; (3) the message-send bar still
looked broken; (4) explain how other IDEs give you voice input.

Locked here:
  * Approvals is the FIRST inspector section (and the first palette entry);
  * the Context panel hides empty categories and shows a hint when nothing is
    carried, instead of a permanent empty "Other" chip;
  * the composer's secondary actions (editor / compact / new session) move behind
    a "⋯" overflow menu so the toolbar stays a single tidy row;
  * the voice help explains the OS-dictation route (Windows Win+H, macOS Fn Fn).

Deterministic, no live server. Run: python3 tests/v284_ui_polish.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    ui = f.read()

# --- 1) Approvals first -------------------------------------------------------
check("Approvals is the first inspector section",
      ui.index('data-insp="approvals"') < ui.index('data-insp="context"')
      and ui.index('data-insp="approvals"') < ui.index('data-insp="plan"'))
check("Approvals is the first inspector entry in the command palette",
      '[["approvals", "Approvals"], ["context", "Context"], ["plan", "Plan"]' in ui)

# --- 1b) JAG-415/416: Context above Plan; session role is scoped clearly -----
check("the Context inspector section sits above Plan",
      ui.index('data-insp="context"') < ui.index('data-insp="plan"'))
check("the per-session role section is distinct from global Rules",
      # JAG-425: the inline handler became a delegated data-call attribute — assert
      # the INTENT (session-only role; global rules in Settings) without locking syntax.
      '>Rules<span class="ihd-s"' in ui
      and "Global_rules.md" in ui
      and 'data-insp="rules"' in ui)
check("clicking a donut slice highlights its bar (seg + bar share a data-i key)",
      'class="seg" data-i="' in ui and 'class="bdbar" data-i="' in ui
      and 'querySelectorAll(".ctxdonut .seg")' in ui and 'classList.toggle("hl"' in ui)

# --- 1c) JAG-396: opaque menus, prominent compact, composer keeps the model ----
check("floating menus are opaque (sessions / attach / overflow / slash)",
      '.sess-menu { position: absolute; z-index: 50; background: var(--menubg);' in ui
      and 'background: var(--menubg); border: 1px solid var(--line); border-radius: 12px;' in ui
      and 'padding: 4px; z-index: 40; background: var(--menubg); }' in ui
      and '#slashMenu { background: var(--menubg); }' in ui)
check("the compact action is an inline text action under the stats",
      'id="compactBtn" class="lnk"' in ui and ".ctxacts {" in ui)
check("the composer keeps the model picker visible and shrinkable (never collapses it)",
      '.cb-right .model-wrap > button { max-width: 160px; min-width: 34px;' in ui
      and 'gap: 6px; flex-wrap: wrap; min-width: 0; }' in ui)

# --- 2) Context: hide empty categories, explain when empty -------------------
check("context chips only render non-empty categories (no always-empty 'Other')",
      "const chips = nonEmpty.map(" in ui
      and 'order.filter(([k]) => (k === "pending" ? pending : data[k] || []).length)' in ui)
check("an empty context shows a helpful hint instead of blank chips",
      "Nothing is carried in context yet" in ui and "empty categories are hidden" in ui)

# --- 3) composer: secondary actions behind a "⋯" overflow menu ----------------
check("the composer has a ⋯ overflow button + menu",
      'id="moreMenu"' in ui and 'id="moreBtn"' in ui and 'class="more-wrap"' in ui)
check("the editor/compact/new-session actions moved into the menu",
      ui.index('id="moreMenu"') < ui.index('id="dockBtn"'))
check("the more-menu is wired (toggle + outside click)",
      "function SparkEditorToggle" in ui and "function toggleMore" in ui
      and '$("moreBtn").onclick' in ui)
check("the more-menu opens upward, right-aligned",
      "#moreMenu { position: absolute; right: 0; bottom: calc(100% + 8px)" in ui)
check("the mic sits before the model picker (compact right cluster)",
      ui.index('id="micBtn"') < ui.index('id="model-btn"'))
check("the right cluster stays ONE row and lets the model shrink (JAG-427)",
      "#composerBar .cb-right { flex-wrap: nowrap; justify-content: flex-end;" in ui
      and "#composerBar .cb-right .model-wrap > button { min-width: 34px; }" in ui)

# --- 4) voice input guidance --------------------------------------------------
check("voice help explains the OS-dictation route (Win+H / Fn Fn)",
      "Win + H" in ui and "Fn Fn" in ui and "operating system dictation" in ui)
check("voice help keeps the HTTPS / localhost explanation",
      "isSecureContext" in ui and "ssh -L 8790" in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
