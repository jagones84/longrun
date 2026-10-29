#!/usr/bin/env python3
"""v716 — a mined pattern must be replayable: only real tools enter a skill.

Found on the live service: `improve{verify}` on the draft
`shell.exec-batch-shell.exec` answered `unknown tools: batch`. The agent loop
records its own pseudo-actions (`batch`, `subagent`, `dispatch`) next to real
tools (agent.py `used_tools.append(...)`), so the miner built "skills" out of
steps no runner can invoke — 29 drafts on the operator's store, none of them
verifiable.

  A  one predicate decides what is a tool (`_dispatchable`)
  B  the recorder keeps only those names; a sequence that loses them all is not
     stored; history stays RAW (it is data, not a candidate)
  C  the miner drops them from any row — including old rows already on disk
  D  the sweep removes drafts whose pattern can never verify
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v716-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve as SE  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ------------------------------------- A: one predicate --------------------
check("A1 a canonical tool is dispatchable", SE._dispatchable("fs.read") is True)
check("A2 a plain legacy tool is dispatchable", SE._dispatchable("shell") is True)
check("A3 a loop pseudo-action is not a tool",
      all(SE._dispatchable(x) is False for x in ("batch", "subagent", "dispatch")), "")
check("A4 an invented name is not a tool", SE._dispatchable("nope.tool") is False)

# ------------------------------------- B: the recorder filters ---------------
hist = os.path.join(TMP, "seq.json")
ok = SE.record("k1", ["fs.read", "batch", "fs.write", "subagent"], path=hist)
check("B1 a run keeps its real tools only", ok is True
      and SE.history(path=hist) == [["fs.read", "fs.write"]], SE.history(path=hist))
check("B2 a run with no real tool is not stored",
      SE.record("k2", ["batch", "dispatch"], path=hist) is False, "")
check("B3 history stays raw data (a hand-written row is not rewritten)",
      (open(hist, "w", encoding="utf-8").write(json.dumps(
          {"k9": {"tools": ["batch", "fs.read", "fs.edit"], "ts": 1}})) > 0)
      and SE.history(path=hist) == [["batch", "fs.read", "fs.edit"]], SE.history(path=hist))

# ------------------------------------- C: the miner filters too --------------
c = {"min_len": 2, "min_count": 2, "max_len": 6}
got = SE.mine([["batch", "fs.read", "fs.edit", "subagent", "shell"]] * 3, dict(c))
pats = [m["pattern"] for m in got]
check("C1 the pattern is built from the real steps only",
      pats and all("batch" not in p and "subagent" not in p for p in pats), pats)
check("C2 a sequence of pseudo-actions alone yields nothing",
      SE.mine([["batch", "dispatch", "subagent"]] * 3, dict(c)) == [], "")
check("C3 real patterns still mine", any(p == ["fs.read", "fs.edit"] for p in pats)
      or any("fs.read" in p for p in pats), pats)

# ------------------------------------- D: the sweep removes the dead ones ----
out = os.path.join(TMP, "drafts")
os.makedirs(out, exist_ok=True)


def draft(name, pattern):
    d = os.path.join(out, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump({"kind": "skill", "status": "proposed", "name": name,
                   "pattern": pattern}, f)
    return d


draft("shell.exec-batch-shell.exec", ["shell.exec", "batch", "shell.exec"])
draft("fs.read-fs.edit-shell", ["fs.read", "fs.edit", "shell"])
removed = (SE.prune_junk(out, {"min_len": 3}) or {}).get("removed") or []
left = sorted(os.listdir(out))
check("D1 a draft with an unreplayable step is swept",
      "shell.exec-batch-shell.exec" in removed, removed)
check("D2 a replayable draft survives", left == ["fs.read-fs.edit-shell"], left)
check("D3 the policy is the same predicate the miner uses",
      "not all(_dispatchable(" in open(os.path.join(
          REPO, "src", "longrun", "util", "selfevolve.py"), encoding="utf-8").read(), "")

print("\n---\nv716: %d/%d PASS" % (sum(results), len(results)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if all(results) else 1)
