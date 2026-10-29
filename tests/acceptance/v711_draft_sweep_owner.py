#!/usr/bin/env python3
"""v711 — the junk-draft sweep has ONE owner, so every miner prunes.

Found on the live store: `<DATA>/proposals/skills/` held 77 drafts that are all
2-tool sequences, i.e. below `min_len` (3 since v656). `prune_junk` existed and
worked, but only the `improve` tool's mine branch called it — the end-of-turn
pass ("mine on a high-signal turn") wrote drafts forever and never swept.

  A  sweep_drafts() is the owner: it removes junk, keeps real drafts, answers
  B  mine_once sweeps before it mines (both callers inherit it)
  C  the tool no longer spells the folder or the sweep a second time
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v711-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import improve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def draft(root, name, pattern):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump({"kind": "skill", "status": "proposed", "name": name,
                   "pattern": pattern, "support": 4}, f)
    return d


DRAFTS = os.path.join(TMP, "data", "proposals", "skills")
improve.DRAFT_DIR = DRAFTS
draft(DRAFTS, "fs.read-shell", ["fs.read", "shell"])            # legacy pair
draft(DRAFTS, "shell-shell", ["shell", "shell"])                # loop
draft(DRAFTS, "fs.read-fs.edit-shell", ["fs.read", "fs.edit", "shell"])  # real

# ------------------------------------------------------- A: the one owner ---
removed = improve.sweep_drafts()
check("A1 the sweep removes drafts below min_len and tool loops",
      sorted(removed) == ["fs.read-shell", "shell-shell"], removed)
check("A2 it answers with the names it removed", isinstance(removed, list) and removed, removed)
left = sorted(os.listdir(DRAFTS))
check("A3 a real 3-step draft survives", left == ["fs.read-fs.edit-shell"], left)
check("A4 a missing folder is empty, not an error", improve.sweep_drafts() == [], "")

# ------------------------------------------ B: mine_once inherits the sweep --
draft(DRAFTS, "junk.read-fetch", ["fs.read", "web.fetch"])
before = sorted(os.listdir(DRAFTS))
paths = improve.mine_once(note="v711")
after = sorted(os.listdir(DRAFTS))
check("B1 mining swept the junk draft it did not need to keep",
      "junk.read-fetch" not in after and "junk.read-fetch" in before, (before, after))
check("B2 mining still answers a list of drafts", isinstance(paths, list), type(paths))
check("B3 the real draft is still there after mining",
      "fs.read-fs.edit-shell" in after, after)

# ------------------------------------- C: no second spelling, no second sweep -
tools_src = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"), encoding="utf-8").read()
improve_src = open(os.path.join(REPO, "src", "longrun", "util", "improve.py"), encoding="utf-8").read()
check("C1 the tool uses the one drafts owner",
      "improve.DRAFT_DIR" in tools_src
      and 'os.path.join(improve.PROPOSAL_DIR, "skills")' not in tools_src, "")
check("C2 the tool does not sweep by itself any more",
      "selfevolve.prune_junk" not in tools_src and "improve.sweep_drafts()" in tools_src, "")
check("C3 mine_once sweeps before it mines",
      improve_src.index("        sweep_drafts()\n")
      < improve_src.index("return selfevolve.mine_history(out, note=note) or []"), "")
agent_src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("C4 the end-of-turn pass mines through the same funnel",
      "improve_mod.mine_once(" in agent_src, "")

print("\n---\nv711: %d/%d PASS" % (sum(results), len(results)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if all(results) else 1)
