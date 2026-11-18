#!/usr/bin/env python3
"""v1175 — setup progress is controlled per BLOCK, with rollback and reuse (round 106).

Source: arXiv:2611.18443, "HerAgent: A Block-Level Checkpointing Harness for
Coding-Agent Environment Setup". Its abstraction is the semantic setup block: one
unit used for execution, validation, checkpointing, repair and rollback. The
measured claims this test pins are the mechanism, not the benchmark number:

  * a failed validation rolls the block back to the last GOOD block's checkpoint,
    and the rollback removes what the failed block created (command-level
    recovery is "too local to remove polluted state");
  * a successful block leaves a replayable checkpoint (tar + manifest with the
    block digest and the pre/post workspace fingerprints);
  * with `reuse`, an unchanged block whose pre-state matches its checkpoint is
    skipped — the cost saving, counted as `commands_skipped`.

Deterministic: real `subprocess` on temp dirs with `/bin/sh` built-ins only; no
model, no network, no server.

Run: python3 tests/acceptance/v1175_setup_blocks.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import setup_blocks as SB     # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def fresh():
    root = tempfile.mkdtemp(prefix="sf-v1175-")
    work = os.path.join(root, "work")
    state = os.path.join(root, "state")
    os.makedirs(work)
    return work, state


def exists(work, name):
    return os.path.isfile(os.path.join(work, name))


# ---- 1. a good plan runs, validates and checkpoints -------------------------
work, state = fresh()
GOOD = [
    {"name": "base", "commands": ["echo base > a.txt"], "validate": "test -f a.txt"},
    {"name": "deps", "commands": ["echo deps > b.txt"], "validate": "test -f b.txt"},
]
out = SB.run(GOOD, work, state)
check("the good plan succeeds", out["ok"] is True, out.get("blocks"))
check("both blocks ran and left their files", exists(work, "a.txt") and exists(work, "b.txt"))
check("every command and validation was executed",
      out["cost"]["commands_run"] == 4 and out["cost"]["commands_skipped"] == 0,
      out["cost"])
check("each block left a replayable checkpoint",
      all(b.get("status") == "ran" and b.get("checkpoint") for b in out["blocks"])
      and os.path.isfile(os.path.join(state, "setup", "deps", "manifest.json")))

# ---- 2. an unchanged plan is skipped on the second run ----------------------
out2 = SB.run(GOOD, work, state, reuse=True)
check("a second run reuses both blocks",
      out2["ok"] and [b["status"] for b in out2["blocks"]] == ["reused", "reused"],
      out2["blocks"])
check("reuse skips the commands and counts the saving",
      out2["cost"]["commands_run"] == 0 and out2["cost"]["commands_skipped"] == 4,
      out2["cost"])

# ---- 3. a failed validation rolls back to the last good block ---------------
BAD = [
    {"name": "base", "commands": ["echo base > a.txt"], "validate": "test -f a.txt"},
    {"name": "broken", "commands": ["echo polluted > c.txt"],
     "validate": "test -f missing.txt"},
]
out3 = SB.run(BAD, work, state)
check("the broken block fails the plan", out3["ok"] is False,
      out3.get("failed_block"))
check("the failure names the validation stage",
      (out3["blocks"][-1].get("failed") or {}).get("stage") == "validate",
      out3["blocks"][-1].get("failed"))
check("rollback restores the previous checkpoint",
      out3["blocks"][-1].get("rollback") == "base",
      out3["blocks"][-1].get("rollback"))
check("rollback REMOVES what the failed block created", not exists(work, "c.txt"))
check("rollback keeps the last good block's files", exists(work, "a.txt"))

# ---- 4. a failing command is caught before validation -----------------------
work2, state2 = fresh()
out4 = SB.run([{"name": "one", "commands": ["exit 3"], "validate": "true"}],
              work2, state2)
check("a non-zero command fails the block without a prior checkpoint",
      out4["ok"] is False and out4["blocks"][-1]["failed"]["stage"] == "command"
      and out4["blocks"][-1]["rollback"] is None,
      out4["blocks"][-1])

# ---- 5. the plan loader ------------------------------------------------------
p = os.path.join(work2, "plan.json")
with open(p, "w", encoding="utf-8") as fh:
    fh.write('{"blocks": [{"name": "x", "commands": []}]}')
check("load_plan accepts the object form", SB.load_plan(p)[0]["name"] == "x")
with open(p, "w", encoding="utf-8") as fh:
    fh.write("{}")
try:
    SB.load_plan(p)
    ok = False
except ValueError:
    ok = True
check("load_plan refuses a plan with no blocks", ok)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
