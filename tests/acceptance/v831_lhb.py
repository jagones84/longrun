#!/usr/bin/env python3
"""v831 — LHB (Longrun Harness Bench): the instrument must prove itself offline.

A benchmark that cannot fail is a decoration. This test pins the whole contract
of the new suite (`benchmarks/lhb.py` + `benchmarks/lhb_compare.py`):

  A. the corpus has the documented families, validates, and its digest covers the
     hidden expectations (a changed task changes the run provenance);
  B. staging copies ONLY `workspace/` — `expect/`, `hidden/`, `arms/` and the
     `task.json` are never visible to the arm;
  C. `--check` proves every task: ORACLE passes, STUB fails, CHEATER fails (the
     cheater passes the visible self-check, which is what makes the gap real);
  D. the scorer semantics: missing artefact is a failure, exact artefact passes,
     a changed guarded input is INVALID, an out-of-bounds write is a gate failure,
     and a multi-turn `until` window retires only the intermediate check;
  E. the runner refuses to reuse a non-empty output folder (that would overwrite
     the evidence of a finished run) and refuses `--repeat 0`.

Deterministic and offline: no server, no model, no network, no container.
Run: python3 tests/acceptance/v831_lhb.py
"""
import json
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from benchmarks import lhb                                              # noqa: E402
from benchmarks import lhb_compare as LC                                # noqa: E402

TMP = tempfile.mkdtemp(prefix="v831-")
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def make_task(root, name, task, workspace=None, expect=None):
    """Materialise a synthetic task directory for the scorer tests."""
    d = os.path.join(root, name)
    write(os.path.join(d, "task.json"), json.dumps(task))
    for rel, body in (workspace or {}).items():
        write(os.path.join(d, "workspace", rel), body)
    for rel, body in (expect or {}).items():
        write(os.path.join(d, rel), body)
    task = dict(task, dir=d)
    lhb.validate_task(task, name)
    return task


try:
    # ---------------------------------------------------------------- A. corpus
    tasks = lhb.load_tasks()
    check("A1 the shipped corpus has 8 tasks", len(tasks) == 8, len(tasks))
    fams = {t["family"] for t in tasks}
    want = {"delivery", "state", "policy", "honesty", "guard", "recovery", "context"}
    check("A2 all seven harness axes are covered", fams == want, sorted(fams))
    check("A3 every task names its mechanism", all(t.get("mechanism") for t in tasks))
    dig = lhb.task_set_digest(tasks)
    check("A4 the task-set digest is a stable sha256",
          len(dig) == 64 and dig == lhb.task_set_digest(tasks), dig[:12])

    # --------------------------------------------------------------- B. staging
    ws = os.path.join(TMP, "stage", "01")
    task1 = [t for t in tasks if t["id"] == "01_delivery_report"][0]
    lhb.stage(task1, ws)
    staged = sorted(r for r in os.listdir(ws))
    check("B1 staging copies the workspace tree", "data" in staged and "check.py" in staged,
          staged)
    leaked = []
    for base, _dirs, files in os.walk(ws):
        for n in files:
            rel = os.path.relpath(os.path.join(base, n), ws)
            if rel.startswith(("expect", "hidden", "arms")) or rel == "task.json":
                leaked.append(rel)
    check("B2 no hidden tree is staged", not leaked, leaked)
    check("B3 the guard covers the staged inputs",
          "data/sales.csv" in lhb.guard_snapshot(task1, ws))

    # ------------------------------------------------------------- C. --check
    t0 = time.time()
    rc = LC.check(tasks)
    check("C1 --check proves all 8 tasks (oracle/stub/cheater)", rc == 0, rc)
    check("C2 --check is offline and fast (< 90 s)", (time.time() - t0) < 90,
          round(time.time() - t0, 1))

    # ---------------------------------------------------- D. scorer semantics
    root = os.path.join(TMP, "synthetic")
    spec = {
        "id": "zz_semantics", "family": "delivery", "mechanism": "synthetic",
        "prompts": ["do the thing"],
        "checks": [{"id": "answer", "kind": "json_exact", "path": "out/a.json",
                    "expect": "expect/a.json"}],
        "gates": [{"id": "bounds", "kind": "no_writes_outside"},
                  {"id": "tmp", "kind": "no_tmp"}],
    }
    t = make_task(root, "zz", spec, workspace={"data.txt": "input\n"},
                  expect={"expect/a.json": json.dumps({"ok": True})})
    ws = os.path.join(TMP, "syn-ws")
    lhb.stage(t, ws)
    guard = lhb.guard_snapshot(t, ws)
    missing = lhb.verify(t, ws, guard)
    check("D1 a missing artefact fails", missing["status"] == "failed"
          and missing["outcome"] == 0.0, missing["status"])
    write(os.path.join(ws, "out", "a.json"), json.dumps({"ok": True}))
    good = lhb.verify(t, ws, guard)
    check("D2 the exact artefact passes", good["status"] == "passed" and good["strict"])

    with open(os.path.join(ws, "data.txt"), "a", encoding="utf-8") as f:
        f.write("tampered\n")
    bad = lhb.verify(t, ws, guard)
    check("D3 a changed guarded input is INVALID",
          bad["status"] == "invalid" and bad["tamper"], bad["status"])
    lhb.stage(t, ws)
    guard2 = lhb.guard_snapshot(t, ws)
    write(os.path.join(ws, "out", "a.json"), json.dumps({"ok": True}))
    write(os.path.join(ws, "stray.txt"), "x\n")
    gate = lhb.verify(t, ws, guard2)
    check("D4 an out-of-bounds write fails the gate, not the outcome",
          gate["status"] == "failed" and gate["outcome"] == 1.0
          and gate["procedure"] == 0.5, (gate["status"], gate["outcome"],
                                         gate["procedure"]))
    write(os.path.join(ws, "scratch.tmp"), "x\n")
    tmp_gate = lhb.verify(t, ws, guard2)
    check("D5 a .tmp file fails the tmp gate", tmp_gate["procedure"] < 0.5,
          tmp_gate["procedure"])

    chain = {
        "id": "zz_chain", "family": "state", "mechanism": "synthetic",
        "prompts": ["one", "two"],
        "checks": [
            {"id": "always", "kind": "text_contains", "path": "out/x.txt",
             "patterns": ["a"]},
            {"id": "only_first", "kind": "text_contains", "path": "out/x.txt",
             "patterns": ["b"], "until": 1},
        ],
        "gates": [],
    }
    ct = make_task(root, "zzchain", chain, workspace={"in.txt": "i\n"})
    cws = os.path.join(TMP, "chain-ws")
    lhb.stage(ct, cws)
    write(os.path.join(cws, "out", "x.txt"), "ab\n")
    s1 = lhb.verify(ct, cws, lhb.guard_snapshot(ct, cws), step=0)
    s2 = lhb.verify(ct, cws, lhb.guard_snapshot(ct, cws), step=1)
    check("D6 the until window retires only the intermediate check",
          len(s1["checks"]) == 2 and len(s2["checks"]) == 1
          and s2["strict"], (len(s1["checks"]), len(s2["checks"])))

    # ------------------------------------------------------- E. runner guards
    busy = os.path.join(TMP, "busy")
    write(os.path.join(busy, "keep.txt"), "evidence\n")
    rc_busy = LC.main(["--arms", "oracle", "--out", busy])
    check("E1 a non-empty --out is refused", rc_busy == 2, rc_busy)
    rc_rep = LC.main(["--arms", "oracle", "--repeat", "0"])
    check("E2 --repeat 0 is refused", rc_rep == 2, rc_rep)
    rc_local = LC.main(["--arms", "longrun", "--model",
                        "dgx:nex-n25-mini-uncensored-q8"])
    check("E2b a local DGX model is refused (project rule 2026-11-06)",
          rc_local == 2, rc_local)

    empty = os.path.join(TMP, "empty")
    os.makedirs(empty)
    rc_ok = LC.main(["--arms", "oracle", "--only", "05_honesty_impossible",
                     "--out", empty])
    check("E3 the oracle arm runs end to end with no model", rc_ok == 0, rc_ok)
    run = json.load(open(os.path.join(empty, "run.json"), encoding="utf-8"))
    only05 = [t for t in tasks if t["id"] == "05_honesty_impossible"]
    check("E4 the run manifest carries a parity block and the task digest",
          run["parity"]["task_set"] == lhb.task_set_digest(only05)
          and run["arms"]["oracle"]["pass@1"] == 1.0, run["parity"]["tasks"])

finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n%d/%d checks green" % (sum(1 for r in RESULTS if r), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
