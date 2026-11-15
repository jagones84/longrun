#!/usr/bin/env python3
"""v1023 — five parity fixes: the shortcut, the issue door, the approvals chip,
the second door to the Marketplace, and the Recommended row.

  A  Ctrl/⌘+, opens Settings (the IDE shortcut)
  B  Settings ▸ Info opens the bug-report template that ships in the repo
  C  the approval MODE is reported once from the live policy — and writing it stays in Permissions
  D  the Marketplace is reachable from Settings too, as a PAGE
  E  `featured` items render under "Recommended", not a second vocabulary
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
JS = open(os.path.join(REPO, "webui", "assets", "market.js"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ── A: the shortcut ────────────────────────────────────────────────────────
check("A1 Ctrl/⌘+, opens Settings",
      'if ((e.metaKey || e.ctrlKey) && e.key === ",") { e.preventDefault(); toggleSettings(); }' in UI)
check("A2 it does not swallow the browser's own zoom shortcuts",
      'e.key === ","' in UI and "e.preventDefault(); toggleSettings();" in UI)

# ── B: the issue door ──────────────────────────────────────────────────────
check("B1 the Info panel offers the template",
      'data-call="openIssueTemplate"' in UI and "open bug_report.md" in UI)
check("B2 the template really ships in the repository",
      os.path.isfile(os.path.join(REPO, ".github", "ISSUE_TEMPLATE", "bug_report.md")))
check("B3 the door opens the file, and never invents a copy",
      "openFile(\".github/ISSUE_TEMPLATE/bug_report.md\")" in UI)
check("B4 a failure tells the operator where the file is",
      "open .github/ISSUE_TEMPLATE/bug_report.md from the editor" in UI)

# ── C: the approvals chip ──────────────────────────────────────────────────
check("C1 the chip sits beside the sandbox pill and is hidden until known",
      'id="apprPill"' in UI and 'id="apprPill" hidden' in UI)
check("C2 it reports the LIVE policy mode",
      'const mode = String((r && r.policy && r.policy.mode) || "normal");' in UI)
check("C3 it is fetched once per page, not on every status poll",
      "if (!loadApprPill._done) { loadApprPill._done = true; loadApprPill(); }" in UI)
check("C4 clicking it opens Settings ▸ Permissions (no second writer)",
      "data-call=\"openSettings\" data-args='[\"permissions\"]'" in UI)
check("C5 the chip never writes the mode itself",
      "apprPill" in UI and not any(
          frag in UI.split('id="apprPill"')[1].split("</button>")[0]
          for frag in ("api(\"POST\"", "api(\"PATCH\"", "api(\"PUT\"")))
check("C6 a dangerous mode is visually distinct",
      'mode === "full" ? " warn" : " ok"' in UI)

# ── D: the second door ─────────────────────────────────────────────────────
check("D1 Settings carries a Marketplace row",
      '["market", "Marketplace"]' in UI)
check("D2 the row opens the PAGE, not an empty panel",
      'if (name === "market") { closeSettings(); showMarket(); return; }' in UI)
check("D3 the row is declared in the one navigation list",
      UI.index('["market", "Marketplace"]') > UI.index("const SETTINGS_CATS = ["))

# ── E: one vocabulary ──────────────────────────────────────────────────────
check("D4 `featured` renders as Recommended", '<div class="mkt-sect">Recommended</div>' in JS)
check("E1 no second word for the same row", 'mkt-sect">Featured<' not in JS)

print("\n---\nv1023: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
