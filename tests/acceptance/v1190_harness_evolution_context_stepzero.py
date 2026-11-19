#!/usr/bin/env python3
"""v1190 — harness evolution gate, context attrition, step-zero opening (round 121).

Sources:
  * arXiv:2611.22299 "Harnesses That Improve Themselves" — failure attribution and
    the four safeguards that admit a modular harness edit.
  * arXiv:2610.36114 "Context Is a Pipeline, Not a Window" — the S1 delivery
    boundary, the destructive prefix slice, and yield.
  * arXiv:2611.01953 "Step-Zero Attack" — peek, counted staged extraction, and a
    body/name binding.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1190_harness_evolution_context_stepzero.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1190-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import harness_evolution as HE  # noqa: E402
from longrun.harness.checks import context_pipeline as CP  # noqa: E402
from longrun.harness.checks import step_zero as SZ  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# ---- 1. harness evolution ---------------------------------------------------
ONE = {"rollouts": [{"failed": True, "harness_error": "cwd-lost",
                     "reasoning_named_cause": True}]}
diag1 = HE.diagnose(ONE)
check("one failed rollout cannot be attributed",
      diag1["attribution"] == "undecided"
      and any(f["kind"] == "single-rollout" for f in diag1["findings"]), diag1)
HARNESS_RUN = {"rollouts": [
    {"failed": True, "harness_error": "edit-format", "reasoning_named_cause": True},
    {"failed": True, "harness_error": "exit-before-tests", "reasoning_named_cause": True},
    {"failed": True, "harness_error": "cwd-lost", "reasoning_named_cause": True},
]}
diag2 = HE.diagnose(HARNESS_RUN)
check("a recurring block between reasoning and execution is a harness flaw",
      diag2["attribution"] == "harness" and diag2["recurring"] == 3
      and diag2["findings"][0]["kind"] == "harness-flaw", diag2)
MODEL_RUN = {"rollouts": [
    {"failed": True, "action_executed": True},
    {"failed": True, "action_executed": True},
]}
diag3 = HE.diagnose(MODEL_RUN)
check("clean calls that fail on the task are a model limit, so no edit is proposed",
      diag3["attribution"] == "model"
      and diag3["findings"][0]["kind"] == "model-limit", diag3)

GOOD = {"module": "ver", "diff_lines": 20, "held_out_split": True,
        "held_out": {"before": 0.30, "after": 0.45},
        "runtime_executed": True, "token_per_task": 46000, "token_cap": 110000}
adm = HE.admit(GOOD)
check("a small executed module patch with a held-out gain is merged",
      adm["decision"] == "merge" and adm["findings"] == [], adm)
check("a patch that helps only one model family is routed instead",
      HE.admit({**GOOD, "router_branch": True})["decision"] == "route")
full = HE.admit({**GOOD, "module": "all"})
check("a full-harness rewrite is refused",
      full["decision"] == "refuse"
      and any(f["kind"] == "full-harness-edit" for f in full["findings"]), full)
big = HE.admit({**GOOD, "diff_lines": 400, "edit_budget": 40})
check("an oversized patch is refused",
      any(f["kind"] == "edit-too-large" for f in big["findings"]), big)
check("a patch never executed in the task image is refused",
      any(f["kind"] == "not-executed"
          for f in HE.admit({**GOOD, "runtime_executed": False})["findings"]))
check("a patch whose added path never runs is refused as dead code",
      any(f["kind"] == "dead-code"
          for f in HE.admit({**GOOD, "dead_code": True})["findings"]))
check("a candidate with no held-out split is refused",
      any(f["kind"] == "no-held-out"
          for f in HE.admit({**GOOD, "held_out_split": False})["findings"]))
check("a flat held-out result is refused",
      any(f["kind"] == "no-held-out-gain"
          for f in HE.admit({**GOOD, "held_out": {"before": 0.4, "after": 0.4}})["findings"]))
check("overlapping evolution and test pools are refused",
      any(f["kind"] == "dev-test-overlap"
          for f in HE.admit({**GOOD, "dev_test_overlap": True})["findings"]))
check("a task-specific shortcut is refused as a hardcoded rule",
      any(f["kind"] == "hardcoded-rule"
          for f in HE.admit({**GOOD, "hardcoded_task": True})["findings"]))
check("an edit that breaches the runtime token cap is refused",
      any(f["kind"] == "token-cap-exceeded"
          for f in HE.admit({**GOOD, "token_per_task": 200000})["findings"]))

bloat = HE.bloat([{"id": "r1", "triggered": True},
                  {"id": "r2", "triggered": False},
                  {"id": "r3", "triggered": False, "pruned": True}])
check("a rule added for a failure that never recurred is pruned",
      bloat["decision"] == "prune" and bloat["live"] == 2
      and [f["rule"] for f in bloat["findings"]] == ["r2"], bloat)
check("a rule set whose rules all triggered is kept",
      HE.bloat([{"id": "r1", "triggered": True}])["decision"] == "keep")

# ---- 2. context pipeline ----------------------------------------------------
bounds = CP.boundaries()["boundaries"]
check("the pipeline names five boundaries with the unit each one loses",
      len(bounds) == 5 and all(b["unit"] for b in bounds)
      and [b["id"] for b in bounds] == ["S1", "S2", "S3", "S4", "S5"], bounds)
PAYLOAD = {"a": "aaaaaaaaaa", "b": "bbbbbbbbbb", "late": "zzzzzzzzzz"}
fits = CP.deliver(PAYLOAD, 500, "prefix")
check("a payload inside the budget is delivered whole",
      fits["parsed"] and fits["delivered"] == ["a", "b", "late"]
      and fits["dropped"] == [], fits)
prefix = CP.deliver(PAYLOAD, 30, "prefix")
check("a prefix slice past a key drops that field whole",
      "late" not in prefix["delivered"] and "late" in prefix["dropped"]
      and "a" in prefix["delivered"], prefix)
check("a prefix slice breaks the payload it cuts",
      prefix["broken"] is True and prefix["parsed"] is False
      and prefix["ok"] is False, prefix)
rows = CP.deliver(PAYLOAD, 30, "rows")
check("a row-aware cut keeps the payload parseable",
      rows["parsed"] is True and rows["broken"] is False and rows["ok"] is True, rows)
check("a row-aware cut names every field it dropped",
      "late" in rows["dropped"]
      and set(rows["delivered"]) | set(rows["dropped"]) == set(PAYLOAD), rows)
check("an unknown delivery mode is refused",
      CP.deliver(PAYLOAD, 30, "middle")["ok"] is False)

rep = CP.profile([
    {"boundary": "S1", "produced": 60, "survived": 20, "computations": 10, "findings": 4},
    {"boundary": "S1", "produced": 40, "survived": 20, "computations": 10, "findings": 2},
    {"boundary": "S4", "produced": 10, "survived": 10},
])
check("a boundary reports produced, survived and lost counts",
      rep["boundaries"]["S1"] == {"produced": 100, "survived": 40, "lost": 60,
                                  "loss_rate": 0.6}, rep["boundaries"]["S1"])
check("yield is findings over computations",
      rep["yield"] == 0.3, rep["yield"])
check("a campaign with no computation has no yield rather than zero",
      CP.profile([{"boundary": "S1", "produced": 1, "survived": 1}])["yield"] is None)

# ---- 3. step zero -----------------------------------------------------------
SMALL = [{"name": "a.txt", "produced_bytes": 10, "declared_size": 10},
         {"name": "b.txt", "produced_bytes": 10, "declared_size": 10}]
safe = SZ.peek(SMALL, 100)
check("a peek inside the budget is safe and writes nothing",
      safe["decision"] == "safe" and safe["writes"] == 0
      and safe["produced_bytes"] == 20, safe)
BOMB = [{"name": "ok.txt", "produced_bytes": 10, "declared_size": 10},
        {"name": "bomb.bin", "produced_bytes": 8 * 1024 * 1024, "declared_size": 64}]
peekbomb = SZ.peek(BOMB, 4 * 1024 * 1024)
check("a peek reports the offending stream, and still writes nothing",
      peekbomb["decision"] == "refuse" and peekbomb["writes"] == 0
      and any(f["kind"] == "byte-budget" for f in peekbomb["findings"]), peekbomb)
check("a declared size is never trusted over produced bytes",
      peekbomb["produced_bytes"] > 4 * 1024 * 1024
      and peekbomb["members"][-1]["declared_size"] == 64, peekbomb["members"])
check("a member whose name escapes the destination is refused",
      any(f["kind"] == "unsafe-member"
          for f in SZ.peek([{"name": "../etc/passwd", "produced_bytes": 1}], 10)["findings"]))
check("a symlink member is refused",
      any(f["kind"] == "symlink-member"
          for f in SZ.peek([{"name": "link", "produced_bytes": 1, "symlink": True}], 10)["findings"]))

ok = SZ.extract(SMALL, 100)
check("a fitting extraction commits every member",
      ok["decision"] == "commit" and ok["writes"] == ["a.txt", "b.txt"], ok)
ref = SZ.extract(BOMB, 4 * 1024 * 1024)
check("an extraction over the budget refuses and leaves the workspace untouched",
      ref["decision"] == "refuse" and ref["writes"] == []
      and any(f["kind"] == "byte-budget" for f in ref["findings"]), ref)
prot = SZ.extract(SMALL, 100, protect=["a.txt"])
check("an existing protected file is not replaced",
      prot["decision"] == "refuse"
      and any(f["kind"] == "protected-file" for f in prot["findings"]), prot)
check("the protected file is replaced only when that is requested",
      SZ.extract(SMALL, 100, protect=["a.txt"], allow_overwrite=True)["decision"] == "commit")

w = SZ.bind_write("alpha.txt", "abc", "abc")
check("a body that matches its committed digest is written",
      w["decision"] == "write" and w["writes"] == ["alpha.txt"], w)
bad = SZ.bind_write("alpha.txt", "beta", "abc")
check("a body that disagrees with its declaration is withheld",
      bad["decision"] == "refuse"
      and any(f["kind"] == "declaration-mismatch" for f in bad["findings"]), bad)
check("a name with no committed digest is withheld",
      any(f["kind"] == "no-commitment"
          for f in SZ.bind_write("alpha.txt", "abc", "")["findings"]))
check("a body is not written over a protected file",
      any(f["kind"] == "protected-file"
          for f in SZ.bind_write("a.txt", "abc", "abc", protect=["a.txt"])["findings"]))
check("an escaping declared name is withheld",
      any(f["kind"] == "unsafe-name"
          for f in SZ.bind_write("../x", "abc", "abc")["findings"]))

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
