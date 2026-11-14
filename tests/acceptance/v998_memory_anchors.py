#!/usr/bin/env python3
"""v998 — a finished turn leaves WHERE/VERIFY anchors for the next session.

CO-3 (2026-11-14), from CoReMem (arXiv 2611.17316 §3.1): what pays across a task
boundary is not the narrative but the ANCHORS — where the code is and the
command that proves a change works. Longrun captured the raw material (one
persisted tool card per call, with `args` and `exit_code`) and extracted anchors
for COMPACTION, but the only cross-session text was a <=140-char prose lesson.

`memory/anchors.py` writes ONE bounded note per turn from the cards the harness
already stored, with no model call:

  A) the extraction: changed files first, then read files, then the LAST
     SUCCESSFUL check command — a failed command or a plain `ls` is not a check;
  B) a turn that touched nothing leaves no note (a note is never invented);
  C) the note is stored as `repo.anchor`, governed (scoped, deduped, budgeted)
     and injected in its own labelled bucket;
  D) the end-of-turn pass writes it WITHOUT the importance gate that gates the
     prose lesson — a small edit is exactly what the next session needs.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v998-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                 # noqa: E402,F401 — import cycle
from longrun.agent import agent                 # noqa: E402
from longrun.memory import anchors              # noqa: E402
from longrun.memory import memory               # noqa: E402
from longrun.model import context_limits       # noqa: E402
from longrun.model import prompt                # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


WS_A = os.path.join(TMP, "alpha")
WS_B = os.path.join(TMP, "beta")
os.makedirs(WS_A, exist_ok=True)
os.makedirs(WS_B, exist_ok=True)


def card(tool, args, ok=True, exit_code=0):
    return {"tool": tool, "args": args, "ok": ok, "exit_code": exit_code}


# ---- A. the extraction ----------------------------------------------------
cards = [
    card("fs.read", {"path": os.path.join(WS_A, "src/a.py")}),
    card("fs.read", {"path": os.path.join(WS_A, "src/a.py")}),          # duplicate
    card("fs.write", {"path": os.path.join(WS_A, "src/b.py")}),
    card("shell.run", {"command": "ls -la"}, ok=True),                  # not a check
    card("shell.run", {"command": "python3 -m pytest tests/y.py"}, ok=False, exit_code=1),
    card("shell.run", {"command": "python3 -m pytest tests/x.py -q"}, ok=True),
    card("git.run", {"args": "status --short"}, ok=True),               # not a check
]
note = anchors.note_from_cards(cards, workspace=WS_A)
check("A1 changed files come first, read files after, duplicates collapsed",
      note.startswith("WHERE: src/b.py, src/a.py"), note)
check("A2 a successful test command is the VERIFY",
      "VERIFY: python3 -m pytest tests/x.py -q" in note, note)
check("A3 a FAILED command is not a VERIFY", "tests/y.py" not in note, note)
check("A4 a plain `ls` and `git status` are not a check",
      "ls -la" not in note and "status --short" not in note, note)
check("A5 the note is ONE line", "\n" not in note)

only_fail = [card("shell.run", {"command": "pytest tests/z.py"}, ok=False, exit_code=2)]
check("A6 a turn whose only check failed leaves no note",
      anchors.note_from_cards(only_fail, workspace=WS_A) == "")

check("A7 a turn that touched nothing leaves no note",
      anchors.note_from_cards([card("web.search", {"q": "x"})], workspace=WS_A) == "")

long_cards = [card("fs.read", {"path": os.path.join(WS_A, "d/%02d.py" % i)}) for i in range(8)]
long_cards.append(card("shell.run", {"command": "python3 -m pytest " + "a" * 90 + ".py"}, ok=True))
short = anchors.note_from_cards(long_cards, workspace=WS_A, max_chars=60)
check("A8 a tight cap keeps VERIFY and drops locations",
      short.startswith("VERIFY: ") and len(short) <= 60, short)

# ---- C. storage, governance, injection ------------------------------------
note_a = anchors.remember({"id": "998a", "workspace": WS_A}, cards)
check("C1 remember() writes the note and returns it", note_a == note and bool(note_a))
saved = memory.governed_query(kind="repo.anchor", limit=10, workspace=WS_A)
check("C2 the record is stored with its workspace and text",
      len(saved) == 1 and saved[0].get("content") == note
      and saved[0].get("workspace") == WS_A, saved)
check("C3 an empty turn writes nothing",
      anchors.remember({"id": "998a", "workspace": WS_A}, []) == ""
      and len(memory.governed_query(kind="repo.anchor", limit=10)) == 1)
anchors.remember({"id": "998a", "workspace": WS_A}, cards)       # same note again
check("C4 a repeated note supersedes the old copy (one live record)",
      len(memory.governed_query(kind="repo.anchor", limit=10, workspace=WS_A)) == 1)

anchors.remember({"id": "998b", "workspace": WS_B},
                 [card("fs.read", {"path": os.path.join(WS_B, "beta.py")})])
blk = prompt.memory_block({"id": "998a", "workspace": WS_A}, ws=WS_A)
check("C5 the prompt carries the labelled anchor bucket", "repo anchors" in blk, blk)
check("C6 this workspace's anchor is in it", "src/b.py" in blk)
check("C7 another workspace's anchor is NOT", "beta.py" not in blk)

for i in range(3):
    anchors.remember({"id": "998a", "workspace": WS_A},
                     [card("fs.write", {"path": os.path.join(WS_A, "n%d.py" % i)})])
blk2 = prompt.memory_block({"id": "998a", "workspace": WS_A}, ws=WS_A)
check("C8 at most two anchors are injected", blk2.count("WHERE:") == 2,
      blk2.count("WHERE:"))

check("C9 the kind is budgeted like the other harness-written kinds",
      memory.hygiene_budget("repo.anchor") == int(context_limits.limit(
          "memory_max_records")))

# ---- D. the end-of-turn wiring (no importance gate) -----------------------
before = len(memory.query(kind="repo.anchor", limit=100))
agent._improvement_pass({"id": "998c", "workspace": WS_A, "tool_cards": []},
                        "edit one file", "done", [], 0, None, {},
                        evidence=[], cards=[card("fs.edit", {"path": "small.py"})])
after = memory.query(kind="repo.anchor", limit=100)
check("D1 a low-importance turn still writes its anchor", len(after) == before + 1,
      "%d -> %d" % (before, len(after)))
check("D2 the record names the edited file",
      any("small.py" in (r.get("content") or "") for r in after))

print("checks: %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
