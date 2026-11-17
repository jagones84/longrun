#!/usr/bin/env python3
"""v1108 — a closed draft's record says it was closed.

Round 40. `repair_mark` wrote `proposal.json` and never touched `REPAIR.md`, so
every closed draft still carried "DRAFT — material, not a change. Nothing was
executed …" — measured 2026-11-18: 3 of 3 fixed drafts contradicted their own
record. The Status section is now derived from the record and stamped on close.

  A  a fresh draft says DRAFT
  B  a close stamps FIXED with the commit and the date, and removes the DRAFT line
  C  only the Status section is replaced — an operator note elsewhere survives
  D  a second close restamps, it does not append a second Status
  E  a record without a fix still reads DRAFT (the single owner of the text)

Deterministic: temp data/session dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1108_repair_status_stamp.py
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1108-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
for _d in (os.environ["LONGRUN_CONFIG_DIR"], os.environ["LONGRUN_DATA_DIR"],
           os.environ["LONGRUN_SESSIONS_DIR"],
           os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")):
    os.makedirs(_d, exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S  # noqa: E402,F401 — the supported import order
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SESS = os.environ["LONGRUN_SESSIONS_DIR"]
HEAD = "shell.exec: missing REQUIRED argument 'cmd'"
with open(os.path.join(SESS, "s_a.json"), "w", encoding="utf-8") as f:
    json.dump({"id": "s_a", "messages": [], "tool_cards": [
        {"tool": "shell.exec", "ok": False, "error": HEAD}] * 3}, f)

OUT = os.path.join(_tmp, "repairs")
res = selfevolve.issue_drafts(OUT, limit=1, min_severity="info")
NAME = (res.get("written") or [{}])[0].get("issue")
MD = os.path.join(OUT, NAME, "REPAIR.md")
DRAFT = "DRAFT — material, not a change. Nothing was executed"


def md():
    return open(MD, encoding="utf-8").read()


# ------------------------------------------------- A: before the close --------
check("A1 a fresh draft says it is material, not a change", DRAFT in md(), md()[-300:])
check("A2 and records no fix in its record",
      "fix" not in json.load(open(os.path.join(OUT, NAME, "proposal.json"))), "")

# ------------------------------------------------- B: the close --------------
r = selfevolve.repair_mark(OUT, NAME, "abc123", note="schema re-read", when="2026-03-01")
txt = md()
check("B1 the close succeeds", r.get("ok") is True, r)
check("B2 the record now reads FIXED with the commit", "**FIXED** at `abc123`" in txt, txt[-400:])
check("B3 with its moment, not 'now'", "2026-03-01" in txt, txt[-300:])
check("B4 and the DRAFT sentence is gone", DRAFT not in txt, txt[-300:])
check("B5 the note travels", "schema re-read" in txt, "")

# ------------------------------------------------- C: nothing else is lost ---
with open(MD, "a", encoding="utf-8") as f:
    f.write("\n## Operator notes\n\nkeep me\n")
selfevolve.repair_mark(OUT, NAME, "def456", when="2026-04-01")
txt = md()
check("C1 an operator section appended after Status survives the restamp",
      "keep me" in txt and "## Operator notes" in txt, txt[-400:])
check("C2 and the status follows the newer commit",
      "**FIXED** at `def456`" in txt and "abc123" not in txt.split("## Status")[-1], txt[-400:])

# ------------------------------------------------- D: one Status, always ------
check("D1 a second close did not append a second Status section",
      txt.count("## Status") == 1, txt.count("## Status"))

# ------------------------------------------------- E: the single owner --------
check("E1 a record without a fix still reads DRAFT (one owner of the text)",
      selfevolve._status_text({"kind": "repair"}).startswith("DRAFT — material"), "")
check("E2 and a fixed record never does",
      "**FIXED**" in selfevolve._status_text({"fix": {"commit": "x", "date": 0,
                                                      "note": ""}}), "")

print("\n---\nv1108: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
