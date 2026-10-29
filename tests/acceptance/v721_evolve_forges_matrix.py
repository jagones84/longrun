#!/usr/bin/env python3
"""v721 — evolve's CODE arm: a green mined pattern is also forged into Matrix (EV-13).

The operator's request: "evolve dovrebbe usare Matrix come suo braccio esecutivo
del codice" — mine -> scaffold -> test+verify_target -> keep only if it passes.
Until now `improve.evolve` stopped at a skill, so a green pattern never became
code. `evolve_once` now forges the green ones through the SAME
`selfevolve.forge_from_draft` the `improve{forge}` action uses (one implementation).

  A  a green pattern is forged once and the report carries the tool
  B  `forge_per_run` bounds the run (one evolved pass cannot flood src/Matrix)
  C  `forge_on_evolve: false` switches the arm off
  D  a refused/red forge is recorded on the report and never fails the run
  E  an invalid bound degrades to 1 instead of crashing

Deterministic: the pipeline is stubbed (no sandbox, no model, no network); the
forge itself is real and runs in a temporary Matrix root.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v721-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.environ["LONGRUN_MATRIX_SRC"] = os.path.join(TMP, "src", "Matrix")
os.environ["LONGRUN_MATRIX_DOT"] = os.path.join(TMP, ".Matrix")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve as SE  # noqa: E402
from longrun.util import improve  # noqa: E402
from longrun.tools import registry  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


def set_selfevolve(**kw):
    cfg = registry.load_config()
    sec = cfg.setdefault("selfevolve", {})
    sec.update(kw)
    registry.save_config(cfg)
    registry.load_config(reload=True)


def forged_names():
    root = os.environ["LONGRUN_MATRIX_SRC"]
    tdir = os.path.join(root, "tools")
    return sorted(f[:-3] for f in os.listdir(tdir) if f.endswith(".py")) if os.path.isdir(tdir) else []


# two replayable patterns, both "green"
P1 = ["fs.read", "fs.edit", "shell.exec"]
P2 = ["fs.read", "fs.write", "memory.recall"]
_old_mine, _old_pipe = SE.mine, SE.pipeline


def _pipe(pattern, out, support=0, **kw):
    d = SE.draft(pattern, support, out) or ""
    return {"ok": True, "dir": d, "verify": {"green": True},
            "archived": {"rel": "skills/created/x"}}


SE.mine = lambda hist, c: [{"pattern": list(P1), "support": 3},
                           {"pattern": list(P2), "support": 3}]
SE.pipeline = _pipe

# ------------------------------------- A: one forge, reported ------------
set_selfevolve(forge_on_evolve=True, forge_per_run=1)
reports = improve.evolve_once()
forged = [r for r in reports if (r.get("matrix") or {}).get("ok")]
check("A1 exactly one pattern was forged", len(forged) == 1, reports)
check("A2 the report names the Matrix tool",
      forged and str((forged[0].get("matrix") or {}).get("matrix_tool", "")).startswith("learned_"), forged)
check("A3 the forged file exists",
      len([n for n in forged_names() if n.startswith("learned_")]) == 1, forged_names())
check("A4 every report still states its skill outcome",
      all(r.get("green") is True and r.get("rel") for r in reports), reports)

# ------------------------------------- B: the bound holds ---------------
set_selfevolve(forge_per_run=2)
reports2 = improve.evolve_once()
made = [n for n in forged_names() if n.startswith("learned_")]
check("B1 the bound is respected across patterns", len(made) == 2, made)
check("B2 the next pattern is the one that gets forged",
      (reports2[1].get("matrix") or {}).get("ok") is True
      and not (reports2[1].get("matrix") or {}).get("skipped"), reports2)
# A second pass must not report the pattern it already forged as a CLOBBER ERROR
# ("refusing to clobber …") — that is work already done, not a failure.
check("B3 an already-forged pattern is skipped, not refused",
      (reports2[0].get("matrix") or {}).get("ok") is True
      and (reports2[0].get("matrix") or {}).get("skipped") == "already forged", reports2)
_check_cleared = True
for _n in made:
    try:
        os.remove(os.path.join(os.environ["LONGRUN_MATRIX_SRC"], "tools", _n + ".py"))
    except OSError:
        _check_cleared = False
check("B4 the reset removed the forged modules", _check_cleared, forged_names())

# ------------------------------------- C: the switch --------------------
before = len([n for n in forged_names() if n.startswith("learned_")])
set_selfevolve(forge_on_evolve=False)
reports3 = improve.evolve_once()
after = len([n for n in forged_names() if n.startswith("learned_")])
check("C1 the arm can be switched off", after == before, (before, after))
check("C2 no report claims a Matrix tool when it is off",
      not any("matrix" in r for r in reports3), reports3)

# ------------------------------------- D: a red forge is recorded --------
_real_forge = SE.forge_from_draft
SE.forge_from_draft = lambda d, **kw: {"ok": False, "error": "not replayable: batch"}
try:
    set_selfevolve(forge_on_evolve=True, forge_per_run=1)
    reports4 = improve.evolve_once()
finally:
    SE.forge_from_draft = _real_forge
check("D1 a red forge does not fail the evolve run", len(reports4) == 2, reports4)
check("D2 the refusal is on the report",
      (reports4[0].get("matrix") or {}).get("ok") is False
      and "batch" in str((reports4[0].get("matrix") or {}).get("error")), reports4)

# ------------------------------------- E: a bad bound -------------------
set_selfevolve(forge_per_run="nonsense")
try:
    reports5 = improve.evolve_once()
    ok = True
except Exception as e:  # noqa: BLE001
    ok, reports5 = False, str(e)
check("E1 an invalid bound degrades to 1 instead of crashing", ok is True, reports5)

SE.mine, SE.pipeline = _old_mine, _old_pipe

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
