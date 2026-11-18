#!/usr/bin/env python3
"""v1180 — executable procedure, intent journal, handoff policy (round 111).

Sources:
  * arXiv:2611.10884 "Keeping LLM Agents on Procedure" — a flat FSM outside the
    model's context, enforced at three points: tool calls, guarded transitions and
    the end of the turn; the frame is persisted so a restart reads it back.
  * arXiv:2611.06563 "EPISTEME" — every shell call declares a type from a closed
    vocabulary and a reason BEFORE it runs; the harness records the observed
    effects and reports the mismatches.
  * arXiv:2611.06545 "When Do Summaries Become Instructions?" — a self-written
    handoff summary can state permissions the record does not support; the fix is
    a ledger check plus neutralization, not trust.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1180_procedure_intent_handoff.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1180-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import procedure as PC          # noqa: E402
from longrun.harness import intent_journal as IJ  # noqa: E402
from longrun.harness import handoff_audit as HA   # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


SPEC = {
    "start": "investigate",
    "exit": "done",
    "pause": [],
    "states": {
        "investigate": {"allows": ["data.*", "step.record", "read.*"]},
        "decide": {"allows": ["submit.decision", "read.*"]},
        "done": {"allows": []},
    },
    "transitions": [
        {"from": "investigate", "to": "decide", "requires": ["step.record"]},
        {"from": "decide", "to": "investigate", "requires": ["submit.decision"]},
        {"from": "investigate", "to": "done", "requires": ["batch.complete"]},
    ],
}

# ---- 1. executable procedure ------------------------------------------------
proc = PC.Procedure(SPEC)
check("a permitted tool is admitted in the current state",
      proc.admit_tool("data.read")["allow"] is True)
check("a tool the state does not permit is refused",
      proc.admit_tool("submit.decision")["reason"] == "not-permitted-by-state")
check("the turn cannot end mid-procedure",
      proc.end_turn()["allow"] is False and proc.end_turn()["reason"] == "mid-procedure")

bad = proc.transition("decide")
check("a transition whose guard has not seen its evidence is refused",
      bad["ok"] is False and bad["reason"] == "guard-failed"
      and bad["missing"] == ["step.record"], bad)
check("a refused transition leaves the state unchanged", proc.state == "investigate")
check("a transition that does not exist is refused",
      proc.transition("done")["reason"] == "guard-failed")

proc.record("step.record")
ok = proc.transition("decide")
check("the guard passes once the evidence is in the history",
      ok["ok"] and proc.state == "decide", ok)
check("the new state admits its own tool", proc.admit_tool("submit.decision")["allow"])
check("the previous state's tool is refused in the new state",
      proc.admit_tool("data.read")["reason"] == "not-permitted-by-state")
check("the turn still cannot end in a non-pause state", proc.end_turn()["allow"] is False)

proc.record("submit.decision")
proc.transition("investigate")
check("a guarded transition can go back", proc.state == "investigate")
proc.record("step.record")
proc.record("batch.complete")
proc.transition("done")
check("the exit state allows the turn to end",
      proc.state == "done" and proc.end_turn()["allow"] is True)

# persistence (the durable half)
path = os.path.join(TMP, "frame.json")
proc.save(path)
back = PC.Procedure.resume(SPEC, path)
check("the frame survives a restart", back.state == "done"
      and [h["tool"] for h in back.history] ==
      ["step.record", "submit.decision", "step.record", "batch.complete"], back.frame())
check("a corrupt frame restarts at the start state, never mid-procedure",
      PC.Procedure.resume(SPEC, os.path.join(TMP, "missing.json")).state == "investigate")
with open(os.path.join(TMP, "corrupt.json"), "w", encoding="utf-8") as fh:
    fh.write("{not json")
check("an unreadable frame is a restart, not a crash",
      PC.Procedure.resume(SPEC, os.path.join(TMP, "corrupt.json")).state == "investigate")

rep = PC.replay(SPEC, [
    {"op": "call", "tool": "submit.decision"},
    {"op": "done", "tool": "step.record"},
    {"op": "transition", "to": "decide"},
    {"op": "call", "tool": "submit.decision"},
    {"op": "end"},
])
check("replay reports every decision in order",
      [d["op"] for d in rep["decisions"]] == ["call", "done", "transition", "call", "end"]
      and rep["decisions"][0]["allow"] is False
      and rep["decisions"][2]["ok"] is True
      and rep["decisions"][3]["allow"] is True
      and rep["decisions"][4]["allow"] is False, rep["decisions"])

# ---- 2. intent journal ------------------------------------------------------
check("a type outside the vocabulary is rejected",
      IJ.well_formed({"type": "hack", "reason": "a sufficiently long reason"})["ok"] is False)
check("a short reason is rejected",
      IJ.well_formed({"type": "verify", "reason": "run it"})["ok"] is False)
wf = IJ.well_formed({"type": "collect-info",
                     "reason": "read the failing test to locate the assertion"})
check("a well-formed read-only declaration is admitted",
      wf["ok"] and wf["read_only"] is True, wf)

eff = IJ.effects({"a.py": "1", "b.py": "2"}, {"a.py": "9", "c.py": "3"})
check("effects name modified, added and deleted paths",
      eff["modified"] == ["a.py"] and eff["added"] == ["c.py"]
      and eff["deleted"] == ["b.py"], eff)

mism = IJ.check({"type": "collect-info",
                 "reason": "inspect the suite before changing anything"},
                {"modified": ["test_x.py"], "added": [], "deleted": []})
check("a read-only intent that wrote is a mismatch",
      mism["verdict"] == "mismatch"
      and mism["findings"][0]["kind"] == "read-only-intent-wrote", mism)
clean = IJ.check({"type": "collect-info",
                  "reason": "inspect the suite before changing anything"},
                 {"modified": [], "added": [], "deleted": []})
check("a read-only intent with no effect is clean", clean["verdict"] == "clean")

stray = IJ.check({"type": "change-state",
                   "reason": "apply the reviewed patch to the module",
                   "targets": ["src/app.py"]},
                  {"modified": ["src/app.py", "src/other.py"]},
                  ["src/app.py"])
check("a write outside the declared target is a finding",
      any(f["kind"] == "undeclared-target-touched" for f in stray["findings"]), stray)
untouched = IJ.check({"type": "change-state",
                      "reason": "apply the reviewed patch to the module",
                      "targets": ["src/app.py"]},
                     {"modified": []}, ["src/app.py"])
check("a declared target that was not touched is a finding",
      "declared-target-untouched" in [f["kind"] for f in untouched["findings"]], untouched)
noeffect = IJ.check({"type": "change-state",
                     "reason": "apply the reviewed patch to the module"},
                    {"modified": [], "added": [], "deleted": [], "git_head_moved": False})
check("a change-state with no observed effect is a finding",
      [f["kind"] for f in noeffect["findings"]] == ["state-change-without-effect"])

jpath = os.path.join(TMP, "journal.jsonl")
IJ.append(jpath, IJ.entry("shell.exec", {"command": "sed -i x"},
                          {"type": "collect-info",
                           "reason": "look at the file before editing it"},
                          {"modified": ["a.py"]}, {"exit_code": 0}))
IJ.append(jpath, IJ.entry("shell.exec", {"command": "rm tmp"},
                          {"type": "cleanup",
                           "reason": "remove the scratch file created earlier"},
                          {"deleted": ["tmp"]}, {"exit_code": 0}))
rows = [json.loads(line) for line in open(jpath, encoding="utf-8") if line.strip()]
check("the journal survives as one row per call", len(rows) == 2, rows)
aud = IJ.audit(rows)
check("the audit exposes the mismatch rate",
      aud["mismatches"] == 1 and aud["exposed_rate"] == 0.5, aud)

# ---- 3. handoff policy audit ------------------------------------------------
TEXT = ("Do not modify `src/hidden.py` without approval. "
        "You may publish `docs/a.md` after the review. "
        "Be careful with the configuration.")
LEDGER = ["`src/hidden.py` is read-only: do not modify `src/hidden.py`",
          "`docs/a.md` may be published after review"]
ha = HA.audit(TEXT, LEDGER)
check("two policy sentences are found, the vague one is not",
      ha["counts"]["claims"] == 2 and ha["counts"]["unsupported"] == 0, ha["counts"])
check("a supported restriction is marked supported",
      [c for c in ha["claims"] if c["kind"] == "restriction"][0]["supported"] is True)
check("a matching handoff is clean", ha["verdict"] == "clean")

bad_ledger = ["`docs/a.md` may be published after review"]
hb = HA.audit(TEXT, bad_ledger)
check("a restriction the ledger does not support is flagged",
      hb["verdict"] == "unsupported-policy"
      and hb["unsupported"][0]["kind"] == "restriction", hb["unsupported"])
check("the unsupported claim names its object and its line",
      hb["unsupported"][0]["objects"] == ["src/hidden.py"]
      and hb["unsupported"][0]["line"] == 1, hb["unsupported"][0])

hpol = HA.audit("You may publish `docs/b.md` now.", ["`docs/b.md` is draft"])
check("a polarity mismatch is unsupported, not a pass",
      hpol["verdict"] == "unsupported-policy", hpol["unsupported"])
hvague = HA.audit("Be careful with the configuration. Always verify things.", [])
check("a sentence with no concrete object is never a policy claim",
      hvague["counts"]["claims"] == 0, hvague["counts"])
hpath = HA.audit("The file `src/x.py` is here.", [])
check("a sentence without a policy modal is not a claim",
      hpath["counts"]["claims"] == 0, hpath["counts"])

neut = HA.neutralize(TEXT, hb["unsupported"])
check("neutralizing replaces the unsupported sentence with an explicit marker",
      neut["removed"] == 1 and HA.MARKER in neut["text"]
      and "Do not modify `src/hidden.py` without approval." not in neut["text"], neut)
check("neutralizing leaves supported claims untouched",
      "You may publish `docs/a.md` after the review." in neut["text"], neut)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
