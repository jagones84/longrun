#!/usr/bin/env python3
"""v1069 — a canary case makes a perfect held-out score a TRIPWIRE, not a triumph.

Source of the mechanism: PROCTOR, arXiv:2609.02246 (stored S-2026-11-18-007),
§5.5 — "canary cases … no honest agent can pass, so that a perfect score is itself
evidence of cheating". Longrun's promotion gate is deterministic + held-out-sealed
(`util/selfevolve.promote`, `plan/heldout.py`) but had NO positive control: nothing
proved the gate would reject a cheater (a candidate that reads the answer key, or a
silent parser fallback that lifts the metric).

Contract pinned here:
  C1 `longrun.plan.canary` exists and its detector is pure (no I/O, no model).
  C2 an absent/undeclared canary is `unbound`, NEVER green (no positive control).
  C3 a canary that PASSED is `tripped` — evidence of leakage, not quality.
  C4 a canary that FAILED is `ok` — the healthy outcome.
  C5 a declared canary missing from the results is `unbound`.
  C6 `plan.heldout.gate` refuses (green False, reason `canary_tripped`) when the
     canary passes in the suite's output.
  C7 `util.selfevolve.promote` refuses a proposal whose held-out gate tripped on
     the canary (the error names the canary).

Deterministic: temp dirs; the held-out suite is a 1-line script; no model.
Run: python3 tests/acceptance/v1069_promotion_canary.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-1069-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_TMP, "cfg")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_TMP, "skills")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


try:
    from longrun.plan import canary, heldout  # noqa: E402
except Exception as e:  # noqa: BLE001
    canary = heldout = None
    IMPORT_ERR = e
else:
    IMPORT_ERR = None

check("C1 plan.canary imports", canary is not None, IMPORT_ERR or "")

if canary is not None:
    check("C2 no canary declared -> unbound (never green)",
          canary.evaluate({"cases": {"a": True}}, canary_id=None).get("verdict") == "unbound")
    r_pass = canary.evaluate({"cases": {"canary_x": True, "a": True}}, canary_id="canary_x")
    check("C3 a PASSED canary is tripped",
          r_pass.get("verdict") == "tripped" and r_pass.get("case") == "canary_x", r_pass)
    r_fail = canary.evaluate({"cases": {"canary_x": False, "a": True}}, canary_id="canary_x")
    check("C4 a FAILED canary is ok", r_fail.get("verdict") == "ok", r_fail)
    r_missing = canary.evaluate({"cases": {"a": True}}, canary_id="canary_x")
    check("C5 a declared-but-absent canary is unbound",
          r_missing.get("verdict") == "unbound", r_missing)


def _heldout_dir(where, canary_id):
    """Write a sealed-suite dir whose command prints `CASE <canary> PASS`."""
    os.makedirs(os.path.join(where, "suite"), exist_ok=True)
    suite = os.path.join(where, "suite", "check_all.py")
    with open(suite, "w", encoding="utf-8") as fh:
        fh.write("print('CASE %s PASS')\n" % canary_id)
    with open(os.path.join(where, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"files": {"suite/check_all.py": _sha(suite)},
                   "command": "python3 check_all.py", "canary": canary_id}, fh)


# ---- C6: the sealed held-out gate refuses when the canary passes -------------
_c6_ok, _c6_detail = False, "heldout not importable: %r" % (IMPORT_ERR,)
if heldout is not None and canary is not None:
    _d = os.path.join(_TMP, "heldout-c6")
    _heldout_dir(_d, "canary_x")
    os.environ["LONGRUN_HELDOUT_DIR"] = _d
    try:
        _rep = heldout.gate(runner=lambda suite, cmd: (True, "CASE canary_x PASS"))
        _c6_ok = (_rep.get("green") is False and _rep.get("reason") == "canary_tripped")
        _c6_detail = _rep
    except Exception as e:  # noqa: BLE001
        _c6_detail = "raised: %r" % (e,)
    finally:
        os.environ.pop("LONGRUN_HELDOUT_DIR", None)
check("C6 heldout.gate refuses when the canary passes", _c6_ok, _c6_detail)

# ---- C7: promote() refuses a proposal whose held-out gate tripped the canary --
_c7_ok, _c7_detail = False, "heldout/selfevolve not importable: %r" % (IMPORT_ERR,)
if heldout is not None and canary is not None:
    try:
        from longrun.util import selfevolve  # noqa: E402
    except Exception as e:  # noqa: BLE001
        _c7_detail = "import: %r" % (e,)
    else:
        _hd = os.path.join(_TMP, "heldout-c7")
        _heldout_dir(_hd, "canary_x")
        os.environ["LONGRUN_HELDOUT_DIR"] = _hd
        _pd = os.path.join(_TMP, "proposals", "canaryhit")
        os.makedirs(_pd, exist_ok=True)
        with open(os.path.join(_pd, "proposal.json"), "w", encoding="utf-8") as fh:
            json.dump({"name": "canaryhit", "status": "verified", "origin": "user",
                       "green_streak": 1, "pattern": ["fs.read"],
                       "verify": {"cases": {"default": True}, "baseline": {}}}, fh)
        try:
            _out = selfevolve.promote(
                _pd, skills_dir=os.path.join(_TMP, "skills-c7"),
                c={"min_green_streak": 1, "category": "created", "verify_timeout": 5})
            _c7_ok = (_out.get("ok") is False
                      and "canary integrity" in str(_out.get("error", ""))
                      and (_out.get("canary") or {}).get("verdict") == "tripped")
            _c7_detail = _out
        except Exception as e:  # noqa: BLE001
            _c7_detail = "raised: %r" % (e,)
        finally:
            os.environ.pop("LONGRUN_HELDOUT_DIR", None)
check("C7 promote refuses when the canary tripped", _c7_ok, _c7_detail)

shutil.rmtree(_TMP, ignore_errors=True)
print("\n---\nv1069: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
