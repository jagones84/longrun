#!/usr/bin/env python3
"""v967 — the meta Pareto history survives a restart (RSI-H-3).

`meta_run` saves every round to `data/meta/meta-report-<epoch>.json`, but the
module rebuilt `_history` / `_frontier` empty at import, so after a restart
`GET /api/meta` answered `total_evaluated: 0` and the frontier was gone — even
though every evaluation in it had already been paid for.

Contract:
  A) two saved reports are loaded at import → `status()` sees both, and the
     frontier is the non-dominated subset (a dominated candidate is absent);
  B) an empty (or non-report) directory → `total_evaluated: 0`, `frontier: None`,
     no exception at import;
  C) a corrupt report is SKIPPED, the valid one next to it is loaded;
  D) the reload keeps the same 500-row cut as `meta_run`, the newest rows.

Deterministic: temp dirs, no server, no model, no network. Each case runs in its
own interpreter because the load happens once, at `longrun.util.meta` import —
a fresh process IS the restart under test.

Run: python3 tests/acceptance/v967_meta_history_reload.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SELF = os.path.abspath(__file__)
LIMIT = 500


def _result(label, quality, cost):
    return {"label": label, "quality": quality, "cost_tokens": cost,
            "cost_usd": round(cost / 1e6 * 0.15, 6), "duration_s": 1.0}


def _write(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(payload, str):
            f.write(payload)
        else:
            json.dump(payload, f, indent=2)


def _fixtures(case, meta_dir):
    """Write what a previous process would have left on disk."""
    if case == "a":
        _write(os.path.join(meta_dir, "meta-report-1000.json"),
               {"results": [_result("A", 0.9, 1000)]})
        _write(os.path.join(meta_dir, "meta-report-2000.json"),
               {"results": [_result("B", 0.4, 5000)]})
    elif case == "b":
        _write(os.path.join(meta_dir, "notes.txt"), "not a report")
    elif case == "c":
        _write(os.path.join(meta_dir, "meta-report-1000.json"),
               {"results": [_result("A", 0.9, 1000)]})
        _write(os.path.join(meta_dir, "meta-report-2000.json"), "{ this is not json")
        _write(os.path.join(meta_dir, "meta-report-3000.json"), {"ts": 1, "n_candidates": 0})
    elif case == "d":
        for stamp in (1000, 2000, 3000):
            rows = [_result("f%d-%d" % (stamp // 1000, i), 0.1 + i / 10000.0, i)
                    for i in range(300)]
            _write(os.path.join(meta_dir, "meta-report-%d.json" % stamp), {"results": rows})


def child(case, root):
    """Fresh interpreter: fixtures first, THEN the import under test."""
    meta_dir = os.path.join(root, "data", "meta")
    os.makedirs(meta_dir, exist_ok=True)
    os.environ["LONGRUN_DATA_DIR"] = os.path.join(root, "data")
    os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(root, "cfg")
    os.environ["LONGRUN_DB"] = os.path.join(root, "events.db")
    _fixtures(case, meta_dir)
    sys.path.insert(0, os.path.join(REPO, "src"))

    from longrun.util import meta as M  # noqa: E402

    results = []

    def check(name, ok, detail=""):
        results.append(bool(ok))
        print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))

    st = M.status()
    labels = [r["label"] for r in (st.get("frontier") or [])]
    if case == "a":
        check("A1 two saved reports are loaded at import", st["total_evaluated"] == 2,
              st["total_evaluated"])
        check("A2 the frontier is not lost", st.get("frontier") is not None, st.get("frontier"))
        check("A3 a dominated candidate (higher cost, lower quality) is NOT on the frontier",
              "B" not in labels, labels)
        check("A4 the history is in chronological order (oldest report first)",
              [r["label"] for r in M._history] == ["A", "B"],
              [r["label"] for r in M._history])
        check("A5 the frontier uses the one pareto_frontier rule",
              labels == [r["label"] for r in M.pareto_frontier(M._history)], labels)
    elif case == "b":
        check("B1 an empty report dir loads nothing", st["total_evaluated"] == 0,
              st["total_evaluated"])
        check("B2 an empty report dir has no frontier", st.get("frontier") is None,
              st.get("frontier"))
        check("B3 a non-report file in the dir is ignored", M._history == [], M._history)
    elif case == "c":
        check("C1 a corrupt report is skipped", st["total_evaluated"] == 1,
              st["total_evaluated"])
        check("C2 the valid report next to it is loaded", labels == ["A"], labels)
        check("C3 a JSON without `results` is skipped too", len(M._history) == 1, M._history)
    elif case == "d":
        check("D1 the reload keeps the same 500-row cut", len(M._history) == LIMIT,
              len(M._history))
        check("D2 the newest evaluation is kept", M._history[-1]["label"] == "f3-299",
              M._history[-1]["label"])
        check("D3 the oldest rows are the ones dropped",
              all(r["label"] != "f1-0" for r in M._history))

    print("---")
    ok = sum(results)
    print("case %s: %d/%d PASS" % (case, ok, len(results)))
    return 0 if ok == len(results) else 1


def parent():
    if len(sys.argv) >= 3 and sys.argv[1] == "--case":
        return child(sys.argv[2], sys.argv[3])
    tmp = tempfile.mkdtemp(prefix="v967_")
    failed = []
    try:
        for case in ("a", "b", "c", "d"):
            root = os.path.join(tmp, case)
            os.makedirs(root, exist_ok=True)
            env = dict(os.environ)
            env.update({"LONGRUN_DATA_DIR": os.path.join(root, "data"),
                        "LONGRUN_CONFIG_DIR": os.path.join(root, "cfg"),
                        "LONGRUN_DB": os.path.join(root, "events.db")})
            proc = subprocess.run([sys.executable, SELF, "--case", case, root],
                                  env=env, capture_output=True, text=True, timeout=180)
            sys.stdout.write(proc.stdout)
            sys.stderr.write(proc.stderr)
            if proc.returncode != 0:
                failed.append(case)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nv967: %s" % ("4/4 cases PASS" if not failed else "FAILED cases: %s" % failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(parent())
