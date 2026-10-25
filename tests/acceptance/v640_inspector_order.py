#!/usr/bin/env python3
"""v640 — the inspector's order and the empty states that were pure decoration.

Operator, verbatim: "il serch deve stare sopra", "togli quel titolone pending
changes non serve a un cazzo", and the Codebase card printed the same verdict
twice (auto-index line + freshness banner).

Contract:
  A) Codebase: the search card is the FIRST card of the section; the status card
     comes after it.
  B) Workspace / pending changes: no caps title, and the state (`#editsStat`)
     lives on the action row next to refresh / approve all / reject all.
  C) Codebase status: auto-index + freshness are ONE `.cb-line.cb-wrap` line;
     the old banner classes are colours, not boxes.

Run: python tests/acceptance/v640_inspector_order.py
"""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v640_")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPHS_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
for d in ("cfg", "sessions", "graphs", "threads", "data"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = src("webui", "index.html")

# ---- A. Codebase: search on top ---------------------------------------------
sec = UI[UI.find('data-insp="codebase"'):]
sec = sec[:sec.find("</section>")]
check("A1 the search input is the first control of the Codebase section",
      sec.find('id="cbQuery"') > 0 and sec.find('id="cbQuery"') < sec.find('id="cbMeta"'),
      "cbQuery=%d cbMeta=%d" % (sec.find('id="cbQuery"'), sec.find('id="cbMeta"')))
check("A2 the status card still exists (the counts are real state)",
      'id="cbMeta"' in sec and 'role="status"' in sec)

# ---- B. pending changes ------------------------------------------------------
check("B1 no caps title for pending changes",
      "Pending changes \u00b7" not in UI and "PENDING CHANGES" not in UI)
acts = UI[UI.find('id="editsList"'):]
acts = acts[:acts.find("</section>")]
check("B2 the state is the first item of the action row",
      re.search(r'<div class="acts">\s*<span id="editsStat"', acts) is not None, acts[:160])
check("B3 the three actions survive as inline links",
      'data-call="loadEdits"' in acts and 'data-call="approveEdits"' in acts
      and 'data-call="rejectEdits"' in acts)

# ---- C. one auto-index line --------------------------------------------------
check("C1 auto-index and freshness share ONE wrapping line",
      '<div class="cb-line cb-wrap">auto-index <b>' in UI)
check("C2 the freshness verdict is a colour, not a banner",
      ".cb-stale { color: var(--warn); }" in UI and ".cb-fresh { color: var(--ok); }" in UI
      and ".cb-auto" not in UI)
check("C3 the wrap rule is explicit",
      ".cb-line.cb-wrap { white-space: normal; }" in UI)

print("\nv640: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
