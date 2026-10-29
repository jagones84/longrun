#!/usr/bin/env python3
"""v280 — best-of-N selection + self-evolving skill miner/promotion gate.

The user asked whether best-of-N and self-evolving are actually tested. They are
(legacy v145/v146/v147/v148/v205), but those suites were NOT part of the battery,
so a regression could ship unnoticed. This suite locks the behaviour into the gate:
best-of-N N selection + the ranker, and the self-evolving mine -> draft -> synth ->
verify -> promote write-gate (fail-closed).

Deterministic, no live model, no network. Run: python3 tests/v280_bestofn_selfevolve.py
"""
import json
import os
import py_compile
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v280-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
# no sealed held-out suite in the test env: exercise the LOCAL write-gate directly.
os.environ["LONGRUN_REQUIRE_HELDOUT"] = "0"
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import bestofn as B        # noqa: E402
from longrun.util import selfevolve as E     # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def _status(proposal_dir):
    with open(os.path.join(proposal_dir, "proposal.json"), encoding="utf-8") as f:
        return (json.load(f) or {}).get("status")


# --- 1) best-of-N selection --------------------------------------------------
check("N=1 when disabled (no overhead)", B.n_of({"enabled": False, "n": 5}) == 1)
check("N is the configured value",
      B.n_of({"enabled": True, "n": 3, "adaptive": False}) == 3)
check("N clamps to a minimum of 1",
      B.n_of({"enabled": True, "n": 0, "adaptive": False}) == 1)
check("N clamps to a maximum of 16",
      B.n_of({"enabled": True, "n": 99, "adaptive": False}) == 16)
check("a non-int N falls back to 1",
      B.n_of({"enabled": True, "n": "abc", "adaptive": False}) == 1)
_c = B.cfg({"enabled": True, "n": 4})
check("cfg merges DEFAULTS + override",
      _c["enabled"] is True and _c["n"] == 4 and "min_score" in _c)

best, scores = B.choose(["a", "aaa", "aa"], scorer=lambda t: len(t))
check("choose picks the highest-scoring candidate", best == "aaa")
check("choose returns one score per candidate", len(scores) == 3)
check("choose returns None below min_score",
      B.choose(["x"], scorer=lambda t: 0.1, c={"min_score": 0.5})[0] is None)
check("choose on an empty list -> (None, [])", B.choose([]) == (None, []))
check("a raising scorer scores 0 instead of crashing",
      B.choose(["x"], scorer=lambda t: 1 / 0)[1][0][1] == 0.0)

# --- 2) self-evolving stage 1: mining ----------------------------------------
SEQ = ["fs.read", "fs.edit", "shell"]
c1 = E.cfg({"min_len": 2, "min_count": 3, "max_len": 6})
mined = E.mine([SEQ, SEQ, SEQ], c1)
check("mine finds the repeated sequence", any(m["pattern"] == SEQ for m in mined))
check("the sequence reports its support", any(m["support"] == 3 for m in mined))
check("a one-off sequence is not proposed", E.mine([SEQ], c1) == [])
check("slug is filesystem-safe", E.slug(["fs.read", "fs/edit!"]) == "fs.read-fs-edit")

hist = os.path.join(TMP, "seq.json")
check("record refuses an empty sequence", E.record("k", [], path=hist) is False)
# v716: the recorder keeps only names the harness can EXECUTE (a mined pattern is
# a skill candidate; `batch`/`subagent` are loop actions, not tools), so the
# fixture uses real tool names instead of the old "a"/"b" placeholders.
check("record writes a run", E.record("k1", ["fs.read", "fs.edit"], path=hist) is True)
check("record drops a name that is not a tool",
      E.record("k2", ["batch", "fs.read"], path=hist) is True
      and E.history(path=hist).count(["fs.read"]) == 1, str(E.history(path=hist)))
check("history reads it back", E.history(path=hist) == [["fs.read", "fs.edit"], ["fs.read"]])

# --- 3) self-evolving stage 2: synth -> verify -> promote --------------------
out = os.path.join(TMP, "props")
skills_root = os.path.join(TMP, "skills")
d = E.draft(SEQ, 3, out)
check("draft writes proposal.json + SKILL.md",
      bool(d) and os.path.isfile(os.path.join(d, "proposal.json"))
      and os.path.isfile(os.path.join(d, "SKILL.md")))
check("draft starts as 'proposed'", _status(d) == "proposed")

syn = E.synth(SEQ, out)
check("synth writes skill.json / runner.py / check.py",
      bool(syn) and all(os.path.isfile(syn[k]) for k in ("skill", "runner", "check"))
      and syn["steps"] == 3)
_compiles = True
for _p in (syn["runner"], syn["check"]):
    try:
        py_compile.compile(_p, doraise=True, cfile=_p + "c")
    except Exception:
        _compiles = False
check("the generated runner/check compile", _compiles)

rep = E.verify(d, runner=lambda pd, cmd: (True, "green"))
check("verify marks a green proposal 'verified'",
      rep["green"] is True and _status(d) == "verified")

arch = E.promote(d, skills_dir=skills_root)
check("promote archives a verified proposal",
      arch.get("ok") is True and os.path.isdir(arch.get("path") or ""))
check("JAG-426: an auto-generated skill archives under skills/created/",
      "/created/" in (arch.get("path") or "").replace(os.sep, "/"))
check("the archived proposal is marked 'archived'", _status(d) == "archived")

d2 = E.draft(["shell", "git"], 2, out)
check("promote refuses an unverified proposal",
      E.promote(d2, skills_dir=skills_root).get("ok") is False)

d3 = E.draft(["web", "skills"], 2, out)
E.verify(d3, runner=lambda pd, cmd: (False, "red"))
check("verify marks a red proposal 'rejected'", _status(d3) == "rejected")
check("promote refuses a rejected proposal",
      E.promote(d3, skills_dir=skills_root).get("ok") is False)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

