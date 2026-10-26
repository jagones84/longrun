#!/usr/bin/env python3
"""v667 (RED) — harness comparison against a stored baseline (R0 of run-evidence lot).

`benchmarks/compare.py` can already run several arms on the SAME model and the
SAME tasks (`bare` control, `longrun`, `hermes`) and writes `compare.json`.
What it could not do is answer "is this better or worse than last time?", so
every result was read by hand.

This test pins the pure verdict function and the baseline file round-trip. It
never calls a model, never touches the network and never starts the service.

Contract:
  verdict(current, baseline, min_delta) ->
    {"state": "no_baseline" | "unmatched" | "ok" | "improved" | "regressed",
     "deltas": {arm: float}, "new_arms": [...], "dropped_arms": [...], "margin": float}
  - `no_baseline` when there is nothing to compare against (first run);
  - `unmatched` when the model or the task count differs: comparing two
    different models is exactly the mistake the KB warns about;
  - `regressed` when ANY common arm drops by more than `min_delta`;
  - `improved` when no arm regressed and one gained more than `min_delta`;
  - arms that appear/disappear are reported, never counted as a regression.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo(start):
    p = start
    while True:
        if os.path.isdir(os.path.join(p, "src", "longrun")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            raise SystemExit("repository root not found from %s" % start)
        p = parent


REPO = _repo(HERE)
TMP = tempfile.mkdtemp(prefix="sf-v667-")
sys.path.insert(0, REPO)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail and not ok else ""))


def _summary(model="m1", n=20, arms=None):
    arms = arms if arms is not None else {"bare": 0.5, "longrun": 0.6}
    return {"model": model, "n_tasks": n,
            "arms": {k: {"pass@1": v, "passed": 0, "n": 0} for k, v in arms.items()}}


try:
    from benchmarks import compare as C
    _err = None
except Exception as e:  # noqa: BLE001 — a broken import is a FAIL, not a crash
    C, _err = None, e

check("A0 benchmarks.compare imports", C is not None, _err)

verdict = getattr(C, "verdict", None) if C else None
check("A1 benchmarks.compare.verdict exists", callable(verdict))

if callable(verdict):
    # ---- state machine -------------------------------------------------------
    v = verdict(_summary(), None)
    check("B1 no baseline -> no_baseline", v.get("state") == "no_baseline", v)
    check("B2 no baseline lists the arms as new",
          sorted(v.get("new_arms") or []) == ["bare", "longrun"], v)

    v = verdict(_summary(), _summary())
    check("C1 identical scores -> ok", v.get("state") == "ok", v)
    check("C2 identical scores -> zero deltas",
          all(abs(d) < 1e-9 for d in (v.get("deltas") or {}).values()), v)

    cur = _summary(arms={"bare": 0.5, "longrun": 0.5})
    v = verdict(cur, _summary(arms={"bare": 0.5, "longrun": 0.6}), 0.05)
    check("C3 a 0.10 drop regresses", v.get("state") == "regressed", v)
    check("C4 the delta is reported",
          abs((v.get("deltas") or {}).get("longrun", 0) + 0.1) < 1e-6, v)

    v = verdict(_summary(arms={"bare": 0.5, "longrun": 0.7}),
                _summary(arms={"bare": 0.5, "longrun": 0.6}), 0.05)
    check("C5 a 0.10 gain -> improved", v.get("state") == "improved", v)

    v = verdict(_summary(arms={"bare": 0.5, "longrun": 0.59}),
                _summary(arms={"bare": 0.5, "longrun": 0.6}), 0.05)
    check("C6 a drop inside the margin -> ok", v.get("state") == "ok", v)

    v = verdict(_summary(model="m2"), _summary(model="m1"))
    check("D1 a different model is unmatched", v.get("state") == "unmatched", v)
    v = verdict(_summary(n=10), _summary(n=20))
    check("D2 a different task count is unmatched", v.get("state") == "unmatched", v)

    v = verdict(_summary(arms={"bare": 0.5, "longrun": 0.6, "hermes": 0.55}),
                _summary(arms={"bare": 0.5, "longrun": 0.6}))
    check("E1 a new arm is reported, not a regression",
          v.get("state") == "ok" and "hermes" in (v.get("new_arms") or []), v)
    v = verdict(_summary(arms={"bare": 0.5}),
                _summary(arms={"bare": 0.5, "longrun": 0.6}))
    check("E2 a missing arm is dropped, not a regression",
          v.get("state") == "ok" and "longrun" in (v.get("dropped_arms") or []), v)

    # ---- baseline file round-trip -------------------------------------------
    p = os.path.join(TMP, "baseline.json")
    saver, loader = getattr(C, "save_baseline", None), getattr(C, "load_baseline", None)
    check("F0 save_baseline/load_baseline exist",
          callable(saver) and callable(loader))
    if callable(saver) and callable(loader):
        check("F1 a missing baseline loads as None", loader(p) is None)
        saver(p, _summary())
        with open(p, encoding="utf-8") as f:
            on_disk = json.load(f)
        check("F2 the baseline is written",
              ((on_disk.get("arms") or {}).get("longrun") or {}).get("pass@1") == 0.6,
              on_disk)
        check("F3 the baseline reads back", (loader(p) or {}).get("model") == "m1")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{not json")
        check("F4 a corrupt baseline loads as None, never raises", loader(p) is None)

    _SRC = C.__file__ and open(C.__file__, encoding="utf-8").read() or ""
    check("G1 the CLI wires --baseline", '"--baseline"' in _SRC)
    check("G2 a regression returns a non-zero exit", "return 3" in _SRC)

ok = all(results)
print("%d/%d" % (sum(1 for r in results if r), len(results)))
raise SystemExit(0 if ok else 1)
