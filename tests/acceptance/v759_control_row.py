#!/usr/bin/env python3
"""v759 — the Inspector control row: a field and its action are ONE control.

The rail grammar set the head (36px) and the row (29px). Inside a card the row
content was still broken: `#inspector .card > .u-df > .inp { flex: 1 1 100% }`
put every field on its own line and orphaned a 24.5px button underneath a 27px
field, on a card whose fill was the SAME value as the field's. The operator read
it as "spazio bottoni mi sembra strano".

Contract:
  A) the field and its action share one row; the field has a 120px floor and the
     action never shrinks.
  B) the field and the button are the same box (28px, radius 8).
  C) a field inside a card sits on the deeper ground, so it has an edge.
  D) the Codebase freshness verdict is printed ONCE (it was appended twice).
  E) actions carry no coloured emoji: one accent only, and a mono chip instead.

Run: python tests/acceptance/v759_control_row.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v759_")
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

# ---- A. one row ---------------------------------------------------------------
check("A1 no field is forced onto its own line",
      "#inspector .card > .u-df > .inp { flex: 1 1 100% !important; }" not in UI)
check("A2 the field keeps a real width floor and may shrink",
      "#inspector .card > .u-df > .inp { flex: 1 1 96px !important; min-width: 0 !important; }" in UI)
check("A3 the action never shrinks and the row is centred",
      "#inspector .card > .u-df > .ghost, #inspector .card > .u-df > .lnk { flex: 0 0 auto; }" in UI
      and "#inspector .card > .u-df { flex-wrap: wrap !important; align-items: center; gap: 8px !important; }" in UI)

# ---- B. one box ---------------------------------------------------------------
check("B1 the field is 28px tall",
      "#inspector input.inp { height: 28px; min-height: 28px; }" in UI)
check("B2 the button is the same 28px box",
      "#inspector button.ghost { height: 28px; min-height: 28px; padding: 0 10px;" in UI
      and "font-size: 11.5px; line-height: 1; border-radius: 8px; }" in UI)

# ---- C. the field has an edge --------------------------------------------------
check("C1 a field inside a card sits on the deeper ground",
      "#inspector .card .inp { background: var(--bg); }" in UI)

# ---- D. one verdict ------------------------------------------------------------
check("D1 the freshness verdict is appended once, not twice",
      "autoHtml + freshHtml +" not in UI)
check("D2 the auto-index line still carries it",
      'autoHow + freshHtml + "</div>"' in UI)

# ---- E. one accent -------------------------------------------------------------
check("E1 no coloured emoji in the codebase / pending-edit actions",
      ">⚡ build</button>" not in UI and '"⚡ build"' not in UI
      and '(f.action === "created" ? "🆕" : "📝")' not in UI)
check("E2 browse / editor are the inline links",
      ">browse</button>" in UI and ">editor</button>" in UI
      and 'aria-label="browse folders"' in UI)
check("E3 the pending-edit marker is one mono chip drawn by both lists",
      ".edkind {" in UI and UI.count('class="edkind') >= 2
      and '"new" : "edit"' in UI)
check("E4 the context list classifies rows with a mono label, not five emoji",
      "#inspector .ctxkind {" in UI and '<span class="ctxkind">file</span>' in UI
      and "📘 <span>" not in UI and "🔧 <span>" not in UI)
check("E5 the skill row has no second, coloured provenance marker",
      "dot.textContent = s.matrix" not in UI and "row.append(dot, info, ins)" not in UI)

print("\nv759: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
