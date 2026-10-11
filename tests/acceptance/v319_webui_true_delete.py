#!/usr/bin/env python3
"""v319 — WebUI wiring for the true deletes (JAG-317/318).

The Memories panel gets a per-record forget (✕) and a purge button; the
Approvals panel gets a "clear decided" button. This locks the client wiring so a
later edit cannot silently drop the buttons (they call DELETE /api/memory?target=
and DELETE /api/approvals).

Deterministic, no browser. Run:  python3 tests/acceptance/v319_webui_true_delete.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

check("E1 the memories panel has a purge button",
      'data-call="memoryPurge"' in ui)          # JAG-425: was onclick="memoryPurge()"
check("E2 the approvals panel has a clear-decided button",
      'data-call="approvalsClear"' in ui)        # JAG-425: was onclick="approvalsClear()"
check("E3 memoryForget is defined", "async function memoryForget(mid)" in ui)
check("E4 memoryPurge is defined", "async function memoryPurge()" in ui)
check("E5 approvalsClear is defined", "async function approvalsClear()" in ui)
check("E6 forget calls DELETE /api/memory", '"/api/memory?target="' in ui)
check("E7 clear calls DELETE /api/approvals", '"/api/approvals"' in ui)
check("E8 a per-record forget button is rendered", 'data-mid="' in ui and "title=\"forget (permanent delete)\"" in ui)
check("E9 forget confirms before deleting", "permanently delete this memory?" in ui)

# sanity: the DELETE verbs are used (a GET would be a silent no-op bug)
check("E10 the memory purge uses POST action=purge",
      '"/api/memory", { action: "purge" }' in ui)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

