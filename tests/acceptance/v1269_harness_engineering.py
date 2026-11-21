#!/usr/bin/env python3
"""v1269 — the three harness-engineering levers longrun was missing (round 168).

Source (read in full, 2026-02-17):
  LangChain, *Improving Deep Agents with harness engineering*,
  https://www.langchain.com/blog/improving-deep-agents-with-harness-engineering
  A fixed `gpt-5.2-codex` went from 52.8% to 66.5% on Terminal-Bench 2.0
  (+13.7 points, Top 30 -> Top 5) by changing only three harness levers:
    1. a `LocalContextMiddleware` that maps the workspace and tooling at start
       (context discovery is error prone; inject it instead);
    2. a `LoopDetectionMiddleware` that counts edits per file and says
       "consider reconsidering your approach" (doom loops, 10+ edits);
    3. time-budget warnings that shift the agent from exploring to verifying
       (agents are famously bad at time estimation).
  The survey "Agent Harness Engineering" (ETCLOVG, 2026) and arXiv:2611.25896
  bound the claim: the harness is an independent layer, and a run that can
  verify early should stop earlier.

What this pins:

  A  the environment card: sorted, bounded, honest about what it skipped, and
     silent when there is no workspace
  B  the per-file edit counter: one note at the limit, per path, writes only
  C  the wall-clock warning: 75% and 90%, once each, never before the cap
  D  the live seams: all three are called from the running turn loop, and the
     edit note is attached before the hazard note
  E  the three modules import nothing from the app

Deterministic: no model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from longrun.harness import edit_loop as el      # noqa: E402
from longrun.harness import env_card as ec       # noqa: E402
from longrun.harness import time_budget as tb    # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


def touch(path, body=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


# ── A · the environment card ────────────────────────────────────────────────
WS = tempfile.mkdtemp(prefix="sf-v1269-")
touch(os.path.join(WS, "README.md"))
touch(os.path.join(WS, "tests", "test_x.py"), "def test_x():\n    assert True\n")
touch(os.path.join(WS, "src", "app.py"))
touch(os.path.join(WS, ".hidden"))
card = ec.build(WS)
check("A1 the card names the root", ("root: " + WS) in card, card[:120])
check("A2 it lists the directories", "dirs: src, tests" in card, card)
check("A3 it lists the files", "README.md" in card and "files: " in card, card)
check("A4 it skips dot entries", ".hidden" not in card, card)
check("A5 it finds the workspace's own check",
      "check: python3 -m pytest -q tests" in card, card)
check("A6 no workspace, no card",
      ec.build("") == "" and ec.build("/nonexistent-sf-v1269") == "")
BIG = tempfile.mkdtemp(prefix="sf-v1269-big-")
for i in range(30):
    os.makedirs(os.path.join(BIG, "d%02d" % i), exist_ok=True)
big = ec.build(BIG)
check("A8 30 directories are summarised, not dumped",
      "(+22 more)" in big and len(big) <= ec.MAX_TEXT, big.splitlines()[-1] if big else "")

# ── B · the per-file edit counter ───────────────────────────────────────────
counts = {}
for _ in range(2):
    counts, note = el.observe(counts, "fs.write", {"path": "a.py"})
check("B1 no note before the limit", note == "" and counts["a.py"] == 2, note)
counts, note = el.observe(counts, "fs.write", {"path": "a.py"})
check("B2 the third write earns the note", "EDIT LOOP" in note and "a.py" in note, note[:120])
check("B3 the note names the count", "3 times" in note, note[:120])
counts, note = el.observe(counts, "fs.edit", {"path": "./a.py"})
check("B4 the same file under another spelling is the same counter",
      counts["a.py"] == 4 and note == "", counts)
counts, note = el.observe(counts, "fs.write", {"path": "b.py"})
check("B5 another file has its own counter", counts["b.py"] == 1 and note == "", counts)
counts, note = el.observe(counts, "fs.read", {"path": "b.py"})
check("B6 a read is not an edit", counts["b.py"] == 1 and note == "", counts)
counts, note = el.observe(counts, "fs.write", {})
check("B7 a write with no path is ignored", note == "" and counts == {"a.py": 4, "b.py": 1}, counts)
counts2 = {}
for _ in range(6):
    counts2, note = el.observe(counts2, "fs.append", {"path": "c.log"})
check("B8 the note repeats at every boundary (3, then 6)",
      counts2["c.log"] == 6 and "6 times" in note, note[:120])
check("B9 the note never proposes the fix",
      "different route" in el.text("x.py", 3) and "```" not in el.text("x.py", 3))

# ── C · the wall-clock warning ──────────────────────────────────────────────
fired = set()
check("C1 nothing at half the budget",
      tb.check(0, 1800, 3600, fired) == ("", ""))
stage, note = tb.check(0, 2880, 3600, fired)
check("C2 the shift note at 80%", stage == "shift" and "verification" in note, note[:120])
check("C3 it names the minutes left", "12 minutes" in note, note[:120])
fired.add(stage)
check("C4 each stage fires once", tb.check(0, 2900, 3600, fired) == ("", ""))
stage, note = tb.check(0, 3450, 3600, set())
check("C5 the final note at 95%", stage == "final" and "Stop exploring" in note, note[:120])
check("C6 no cap, no warning", tb.check(0, 9999, 0, set()) == ("", ""))
check("C7 a clock that went backwards is ignored", tb.check(100, 50, 3600, set()) == ("", ""))

# ── D · the live seams ──────────────────────────────────────────────────────
source = open(os.path.join(SRC, "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("D1 the turn loop counts edits", "edit_loop as _el" in source)
check("D2 the turn loop warns about time", "time_budget as _tb" in source)
check("D3 the session gets an environment card", "env_card as _env" in source)
_utc = source.find("def user_turn_context(")
check("D4 the card is built by the user-turn owner",
      "env_card as _env" in source[_utc:_utc + 3000])
_loop = source.find("edit_loop as _el")
_hazard = source.find("hazard_notice as _hazard")
check("D5 the edit note is attached before the hazard note",
      0 < _loop < _hazard, "%d < %d" % (_loop, _hazard))
check("D6 the warning reads the keepgoing wall clock",
      "_tb.check(_kg_started" in source and "_kg_wall_secs" in source)

# ── E · the pure modules stay pure ─────────────────────────────────────────
for name in ("env_card.py", "edit_loop.py", "time_budget.py"):
    body = open(os.path.join(SRC, "longrun", "harness", name), encoding="utf-8").read()
    check("E · %s imports no app package" % name,
          "from longrun.agent" not in body and "from longrun.core" not in body
          and "from longrun.tools" not in body)

print("\n%d/%d checks passed" % (len(CHECKS) - len(FAILED), len(CHECKS)))
if FAILED:
    print("FAILED: " + ", ".join(FAILED))
    sys.exit(1)
