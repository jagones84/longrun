#!/usr/bin/env python3
"""v1285 — the automatic evolve path carries the purpose the miner derived.

Bug hunt 2026-11-23 (F-004). `mine()` derives a `purpose` from the `purpose`
field of the runs behind a pattern; `draft()` records it and `scan()` passes it.
But `improve.evolve_once` — the automatic stage-2 pass — called
`selfevolve.pipeline(pattern, out, support, c=..., promote_if_green=...)` WITHOUT
`purpose`, so an auto-installed skill recorded `purpose: ""` even when every run
behind it had stated one. Measured (`.agent/trash/rsci_purpose_drop.py`): the
mined purpose is `'summarize a file into a note'`, the evolve-style draft's is
`''`. A skill whose purpose nobody states is un-addressable for the agent that
must choose it.

Contract:
  A `mine()` derives the purpose from the runs (the input to carry)
  B `scan()` records it on the draft (the reference path)
  C `improve.evolve_once` passes the mined purpose to `pipeline` (the fix)
  D `pipeline` with no purpose records none and does NOT gate (documents that an
    empty purpose is not the protection the old docstring claimed)

Deterministic: no model, no network, isolated temp dirs.
Run: python3 tests/acceptance/v1285_evolve_carries_mined_purpose.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


tmp = tempfile.mkdtemp(prefix="sf-v1285-")
os.environ["LONGRUN_OFFLINE"] = "1"
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "MATRIX_DOT", "MATRIX_SRC",
           "SKILLS_DIR", "PROPOSALS_DIR", "IMPROVEMENT_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(tmp, _k)

from longrun.tools import registry              # noqa: E402
from longrun.util import selfevolve as SE       # noqa: E402

registry._external_tools = lambda: {}           # never start an MCP client in a test

PURPOSE = "summarize a file into a note"
SEQ = ["fs.read", "fs.write", "shell.exec"]
hist = os.path.join(tmp, "history.json")
for i in (1, 2, 3):
    SE.record("run%d" % i, SEQ, path=hist, outcome="ok", purpose=PURPOSE)

# ---- A: the miner derives the purpose --------------------------------------
seqs, ocs, pps = SE.history_split(hist)
cands = SE.mine(seqs, outcomes=ocs, purposes=pps)
got = [c for c in cands if c["pattern"] == SEQ]
check("A1 mine() yields the repeated pattern", bool(got), [c["pattern"] for c in cands])
check("A2 the derived purpose is what the runs stated",
      got and got[0].get("purpose") == PURPOSE, got[0].get("purpose") if got else None)

# ---- B: scan() records the purpose on the draft ----------------------------
scan_out = os.path.join(tmp, "scan_drafts")
paths = SE.scan(seqs, scan_out, outcomes=ocs, purposes=pps)
recorded = [json.load(open(os.path.join(p, "proposal.json"))).get("purpose") for p in paths]
check("B1 scan() records the purpose on the draft",
      PURPOSE in recorded, recorded)

# ---- C: the fix — evolve_once passes the purpose to pipeline ---------------
src = open(os.path.join(REPO, "src", "longrun", "util", "improve.py"),
           encoding="utf-8").read()
block = src.split("def evolve_once(", 1)[-1].split("\ndef ", 1)[0]
check("C1 evolve_once's pipeline call passes the mined purpose",
      "purpose=cand.get(\"purpose\")" in block, "evolve_once body")

# ---- D: an empty purpose records none and does not gate (the real contract) -
p_empty = os.path.join(tmp, "pipe_empty")
rep = SE.pipeline(SEQ, p_empty, 3, runner=lambda d, c: (True, "ok"),
                  promote_if_green=False)
prop = json.load(open(os.path.join(rep["dir"], "proposal.json")))
check("D1 an empty purpose records none and still runs the pipeline",
      prop.get("purpose") == "" and rep.get("verify", {}).get("green") is True,
      prop.get("purpose"))

print("---")
ok_n = sum(RESULTS)
print("v1285: %d/%d PASS" % (ok_n, len(RESULTS)))
raise SystemExit(0 if ok_n == len(RESULTS) else 1)
