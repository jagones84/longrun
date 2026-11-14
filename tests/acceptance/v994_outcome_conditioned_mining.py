#!/usr/bin/env python3
"""v994 — a mined candidate carries the OUTCOME and the PURPOSE of its runs (OCM).

The live loop mines tool-name repeats and nothing else: `record` stored
`{tools, ts}`, so "91 candidates, all one shape" (measured 2026-11-14) was all
it could ever say. Harness² conditions its editor on a CONTRAST and produces
nothing without one (core/editors.py:18-20); this is the evidence-based
counterpart inside Longrun's own miner.

  A  record stores the outcome and the purpose; a row without them is UNKNOWN
  B  mine annotates every candidate with support_ok / support_bad / unknown
  C  a pattern whose known runs ALL failed is refused, before any draft exists
  D  a caller that passes no outcomes keeps the historical behaviour exactly
  E  the outcome of a dropped run is dropped WITH it (no misaligned split)
  F  mine_history writes the purpose into proposal.json and SKILL.md, and the
     split into the note
  G  the live call sites pass what they already computed

Deterministic: no model, no network, no server.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v994-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "DB", "HELDOUT_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(TMP, "skills")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "HELDOUT_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve as SE  # noqa: E402

PAT = ["fs.read", "fs.write", "shell.exec"]
# A SECOND pattern built from whatever THIS install can actually dispatch: the
# test is about the outcome rule, not about which tool names exist, and a
# hardcoded name an environment does not know silently shrinks the fixture to one
# pattern (it did, on the first battery run).
OTHER = sorted(t for t in SE._known_tools() if t not in PAT)[:3]
HIST = os.path.join(TMP, "sequences.json")
DRAFTS = os.path.join(TMP, "drafts")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       "" if ok else "  -> %r" % (detail,)))


def _cands(seqs, **kw):
    return SE.mine(seqs, SE.cfg(), **kw)


check("Z0 the fixture itself is sound: two distinct, dispatchable patterns",
      len(set(OTHER)) == 3 and all(SE._dispatchable(t) for t in OTHER + PAT), OTHER)


# ------------------------------- A: record keeps the outcome and the purpose ---
SE.record("a-ok", PAT, path=HIST, outcome="ok", purpose="ship the release notes")
SE.record("a-legacy", PAT, path=HIST)
rows = {r["tools"][0] + str(r["ts"]): r for r in SE.history_rows(HIST)}
all_rows = SE.history_rows(HIST)
ok_row = [r for r in all_rows if r["outcome"] == "ok"]
legacy_row = [r for r in all_rows if not r["outcome"]]
check("A1 record() stores the outcome it was given", len(ok_row) == 1, all_rows)
check("A2 record() stores the purpose it was given",
      bool(ok_row) and ok_row[0]["purpose"] == "ship the release notes",
      ok_row[0] if ok_row else None)
check("A3 a row without an outcome reads as UNKNOWN, never as ok",
      len(legacy_row) == 1 and legacy_row[0]["outcome"] == ""
      and legacy_row[0]["purpose"] == "", legacy_row)
check("A4 an unknown outcome is not written into the store at all",
      "outcome" not in json.load(open(HIST, encoding="utf-8"))["a-legacy"],
      json.load(open(HIST, encoding="utf-8"))["a-legacy"])

# --------------------------------------------- B: mine annotates the split ---
SEB = os.path.join(TMP, "seqB.json")
for i, oc in enumerate(("ok", "ok", "ok", "error")):
    SE.record("b%d" % i, PAT, path=SEB, outcome=oc, purpose="deploy the box")
SE.record("b-legacy", PAT, path=SEB)          # a row written before OCM
seqs, ocs, pps = SE.history_split(SEB)
cands = _cands(seqs, outcomes=ocs, purposes=pps)
hit = [c for c in cands if list(c["pattern"]) == PAT]
check("B1 the split counts the runs that succeeded and the ones that failed",
      bool(hit) and hit[0]["support_ok"] == 3 and hit[0]["support_bad"] == 1
      and hit[0]["unknown"] == 1, hit[0] if hit else None)
check("B2 the candidate carries the most common purpose of its runs",
      bool(hit) and hit[0]["purpose"] == "deploy the box",
      [c.get("purpose") for c in cands])
check("B3 the split adds up to the support, so no run is counted twice",
      bool(hit) and hit[0]["support"] == 5
      and hit[0]["support_ok"] + hit[0]["support_bad"] + hit[0]["unknown"]
      == hit[0]["support"], hit[0] if hit else None)

# --------------------------------------------------------- C: the refusal ---
SE2 = os.path.join(TMP, "seq2.json")
for i in range(3):
    SE.record("c-ok%d" % i, PAT, path=SE2, outcome="ok", purpose="p")
_SEQ2 = SE.history_split(SE2)
kept = _cands(_SEQ2[0], outcomes=_SEQ2[1], purposes=_SEQ2[2])
check("C0 a pattern whose runs succeeded is kept", len(kept) == 1, kept)

SE3 = os.path.join(TMP, "seq3.json")
for i in range(3):
    SE.record("c-bad%d" % i, PAT, path=SE3, outcome="error")
for i in range(3):
    SE.record("c-corr%d" % i, OTHER, path=SE3, outcome="corrected")
_S3 = SE.history_split(SE3)
bad = _cands(_S3[0], outcomes=_S3[1], purposes=_S3[2])
check("C1 a pattern seen only in FAILING runs is refused", bad == [], bad)
check("C1b the other all-failed pattern is refused too",
      not [c for c in bad if list(c["pattern"]) == OTHER], bad)

SE4 = os.path.join(TMP, "seq4.json")
for i, oc in enumerate(("ok", "ok", "error")):
    SE.record("c4-%d" % i, PAT, path=SE4, outcome=oc)
_S4 = SE.history_split(SE4)
mixed = _cands(_S4[0], outcomes=_S4[1], purposes=_S4[2])
check("C2 ONE success keeps the candidate (the rule is all-failed, not most-failed)",
      len(mixed) == 1 and mixed[0]["support_ok"] == 2 and mixed[0]["support_bad"] == 1,
      mixed)

SE5 = os.path.join(TMP, "seq5.json")
for i in range(4):
    SE.record("c5-%d" % i, PAT, path=SE5, outcome="corrected")
_S5 = SE.history_split(SE5)
check("C3 a pattern seen only in CORRECTED runs is refused, not promoted",
      _cands(_S5[0], outcomes=_S5[1], purposes=_S5[2]) == [], "corrected is a failure")

# ------------------------- D: no outcomes -> the historical behaviour, exactly ---
_S6 = SE.history_split(SE3)          # three `error` runs, outcomes NOT passed
legacy = SE.mine(_S6[0], SE.cfg())
check("D1 with no outcomes passed nothing is refused (old callers unchanged)",
      len(legacy) == 2 and legacy[0]["support_ok"] == 0,
      [c["pattern"] for c in legacy])
check("D2 and the split reads all-unknown", all(c["unknown"] == c["support"] for c in legacy),
      legacy)

# --------------------------- E: a dropped run takes its outcome with it (alignment) ---
SE7 = os.path.join(TMP, "seq7.json")
for i in range(3):
    SE.record("e-ok%d" % i, PAT, path=SE7, outcome="ok")
SE.record("e-short", ["fs.read", "fs.write"], path=SE7, outcome="error")
_S7 = SE.history_split(SE7)
c7 = SE.mine(_S7[0], SE.cfg(), outcomes=_S7[1], purposes=_S7[2])
check("E1 the 2-tool run drops out of the history anyway", len(_S7[0]) == 4, _S7[0])
check("E1b its outcome is dropped with it: the candidate is 3 ok / 0 failed",
      len(c7) == 1 and c7[0]["support_ok"] == 3 and c7[0]["support_bad"] == 0,
      c7)

# --------------------------------------- F: the draft says what it is for ---
SE8 = os.path.join(TMP, "seq8.json")
for i in range(3):
    SE.record("f-%d" % i, PAT, path=SE8, outcome="ok", purpose="rotate the logs")
paths = SE.mine_history(DRAFTS, path=SE8)
d = os.path.join(DRAFTS, SE.slug(PAT))
prop = json.load(open(os.path.join(d, "proposal.json"), encoding="utf-8"))
md = open(os.path.join(d, "SKILL.md"), encoding="utf-8").read()
check("F1 mine_history writes the draft", len(paths) == 1 and os.path.isfile(os.path.join(d, "proposal.json")), paths)
check("F2 proposal.json carries the purpose of the runs",
      prop.get("purpose") == "rotate the logs", prop)
check("F3 the note names the split",
      "runs behind this candidate: 3 ok / 0 failed / 0 unknown" in (prop.get("note") or ""),
      prop.get("note"))
check("F4 SKILL.md tells the reader what the sequence was FOR",
      "## What it was for" in md and "rotate the logs" in md, md[:400])

# ------------------------------------ G: the live call sites pass what they have ---
AGENT = open(os.path.join(REPO, "src/longrun/agent/agent.py"), encoding="utf-8").read()
IMPROVE = open(os.path.join(REPO, "src/longrun/util/improve.py"), encoding="utf-8").read()
check("G1 the end-of-turn recorder passes the outcome and the purpose",
      "_se.record(" in AGENT and "outcome=(" in AGENT and "purpose=message" in AGENT,
      "agent.py")
check("G2 evolve mines through the ONE aligned split, never a rebuilt list",
      "selfevolve.history_split()" in IMPROVE
      and "selfevolve.mine(_seqs, c, outcomes=_ocs, purposes=_pps)" in IMPROVE,
      "improve.py")

print("\n%d/%d PASS" % (sum(results), len(results)))
sys.stdout.flush()
sys.exit(0 if all(results) else 1)
