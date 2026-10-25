#!/usr/bin/env python3
"""v632 — the Context panel is a stat readout; the session role starts closed.

Operator report (screenshot of the RH Context panel): two full-width buttons
stacked, an essay about the dry-run and a card of chrome around every number —
~40% of the panel was dead space. And the Rules panel opened the session ROLE.md
editor expanded on every load.

Contract:
  A) Context: numbers + meter stay, the two actions are ONE row of inline text
     actions, and the dry-run is a COLLAPSED <details> with no prose.
  B) Rules: the session role <details> is rendered CLOSED (expand on demand), and
     the header line carries the identity only — no explanatory sentence.

Run: python tests/acceptance/v632_context_compact.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v632_")
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


def block(selector):
    head = selector + " {"
    return UI.split(head)[1].split("}")[0] if head in UI else ""


# ---- A. Context panel ----------------------------------------------------------
check("A1 the two actions share ONE row of inline text actions",
      '<div class="ctxacts">' in UI and 'id="compactBtn" class="lnk"' in UI
      and 'class="lnk" data-call="openSettings" data-args=\'["compaction"]\'' in UI)
check("A2 the full-width button rule is gone (no 100% bar)",
      "#inspector #compactBtn" not in UI and "width: 100%; margin: 2px 0 8px;" not in UI)
check("A3 the dry-run is a COLLAPSED row with a two-word summary",
      '<details class="dryrun u-mt6">' in UI
      and "<summary>dry-run next turn</summary>" in UI
      and "Dry-run the next turn</b> — exactly what the assembler would send" not in UI)
check("A4 every stat id still exists (nothing lost by compacting)",
      all(t in UI for t in ('id="ctxPct"', 'id="ctxBar"', 'id="ctxState"',
                            'id="ctxMsgs"', 'id="ctxTok"', 'id="ctxBudget"', 'id="ctxCats"')))
check("A5 compacting shows a busy state on the inline action",
      'btn.classList.add("busy")' in UI and 'btn.textContent = "compacting…"' in UI
      and 'btn.textContent = "compact"' in UI)
check("A6 the actions sit INSIDE the stats card (compact readout)",
      UI.index('class="ctxacts"') < UI.index('id="ctxCats"'))

# ---- B. Rules panel ------------------------------------------------------------
check("B1 the session role starts CLOSED (expand on demand)",
      '_rulesRow("role", "session role"' in UI
      and '!!(role && role.text), false));' in UI)
check("B2 the header line is identity only (no explanatory sentence)",
      "agent identity (roster); the role text below" not in UI
      and '"ad-hoc session (no agent)"' in UI)
check("B3 the role editor keeps its save path (nothing lost)",
      'id="rule_role"' in UI or 'id="\' + id + \'"' in UI)

# ---- C. dead chrome ------------------------------------------------------------
check("C1 the labelled hide-empty row left no dead CSS",
      ".rail-filter {" not in UI)
check("C2 the rail toolbar is still ONE row",
      'class="rail-tools" role="toolbar"' in UI)

print("\nv632: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
