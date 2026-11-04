#!/usr/bin/env python3
"""v798 — the matched-run probe compares TWO repeated trials by default, not one.

Evidence for the need (2026-11-04): `harness/whole.py` shipped `"repeats": 1` and
`compose.reflect` requires `repeats >= 2` AND two agreeing contrasts before it will
call an attribution `repeated_matched_runs` (`harness/compose.py:92-93`). With the
shipped default every experiment the engine could run was therefore labelled
`confounded` / `insufficient` — the engine answered, but the answer could not
support any claim. A small apparent gain between two single rollouts is noise.

Contract locked here:
  * the shipped default is 2, and `repeats_of()` is the ONE reader (no second
    `or 1` default hiding in the executor);
  * the clamp is [1, 3] and garbage falls back to the default instead of raising;
  * a caller (or the `LONGRUN_HARNESS_REPEATS` escape hatch) still wins, so an
    operator can force 1 and pay half only on purpose;
  * `compose.reflect` really upgrades the attribution at 2 agreeing repeats, which
    is the whole reason for the change.

Deterministic, no live model, no network, no server, no container.

Run: python3 tests/acceptance/v798_probe_repeats.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v798-")
for _k, _v in (("LONGRUN_DATA_DIR", "data"), ("LONGRUN_CONFIG_DIR", "cfg"),
               ("LONGRUN_SESSIONS_DIR", "sessions"), ("LONGRUN_RUNS_DIR", "runs"),
               ("LONGRUN_DB", "events.db"), ("LONGRUN_HARNESS_DIR", "harness")):
    os.environ[_k] = os.path.join(TMP, _v)
os.environ.pop("LONGRUN_HARNESS_REPEATS", None)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import compose, probe, whole     # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---------------------------------------------------------------- A. the default --
check("A1 the shipped default is two repeats", whole.DEFAULTS.get("repeats") == 2,
      whole.DEFAULTS.get("repeats"))

# ------------------------------------------------------------- B. the ONE reader --
check("B1 no config -> the default", whole.repeats_of({}) == 2, whole.repeats_of({}))
check("B2 an explicit 1 still means 1 (opt out on purpose)",
      whole.repeats_of({"repeats": 1}) == 1, whole.repeats_of({"repeats": 1}))
check("B3 zero is clamped to 1 (one rule, no special case)",
      whole.repeats_of({"repeats": 0}) == 1, whole.repeats_of({"repeats": 0}))
check("B4 None falls back to the default", whole.repeats_of({"repeats": None}) == 2)
check("B5 garbage falls back to the default, never raises",
      whole.repeats_of({"repeats": "many"}) == 2, whole.repeats_of({"repeats": "many"}))
check("B6 the upper clamp is 3", whole.repeats_of({"repeats": 99}) == 3,
      whole.repeats_of({"repeats": 99}))
check("B7 the lower clamp is 1", whole.repeats_of({"repeats": -5}) == 1,
      whole.repeats_of({"repeats": -5}))

# ------------------------------------------------------- C. propagated to probe --
_w = probe.whole_cfg({})
check("C1 probe passes the default through", _w.get("repeats") == 2, _w.get("repeats"))
check("C2 probe.cfg() carries it too", probe.cfg().get("repeats") == 2,
      probe.cfg().get("repeats"))
check("C3 a caller override still wins", probe.cfg({"repeats": 3}).get("repeats") == 3,
      probe.cfg({"repeats": 3}).get("repeats"))

os.environ["LONGRUN_HARNESS_REPEATS"] = "1"
try:
    check("C4 the env escape hatch still forces one", probe.cfg().get("repeats") == 1,
          probe.cfg().get("repeats"))
finally:
    os.environ.pop("LONGRUN_HARNESS_REPEATS", None)

# ------------------------------------------- D. the attribution it unlocks ------
_contrast = {"verdict": "improved", "errors": {"fixed": ["e1"], "introduced": []}}
_trial1 = {"candidate": {"name": "c1", "kind": "skill"}, "contrast": _contrast,
           "repeats": 1, "contrasts": [_contrast]}
_one = compose.reflect([_trial1])
check("D1 one rollout is still labelled confounded",
      (_one["edits"][0] or {}).get("attribution") == "confounded",
      _one["edits"][0].get("attribution"))
check("D2 one rollout is not admissible", _one["evidence"]["consistent_repeats"] is False)

_trial2 = {"candidate": {"name": "c1", "kind": "skill"}, "contrast": _contrast,
           "repeats": 2, "contrasts": [_contrast, _contrast]}
_two = compose.reflect([_trial2])
check("D3 two agreeing repeats upgrade the attribution",
      (_two["edits"][0] or {}).get("attribution") == "repeated_matched_runs",
      _two["edits"][0].get("attribution"))
check("D4 two agreeing repeats are admissible as EVIDENCE (still NO_ENTRY)",
      _two["evidence"]["consistent_repeats"] is True and _two["status"] == "NO_ENTRY",
      (_two["evidence"], _two["status"]))

_disagree = {"verdict": "regressed", "errors": {}}
_trial3 = {"candidate": {"name": "c1"}, "contrast": _contrast,
           "repeats": 2, "contrasts": [_contrast, _disagree]}
_three = compose.reflect([_trial3])
check("D5 disagreeing repeats stay confounded (never a win)",
      (_three["edits"][0] or {}).get("attribution") == "confounded",
      _three["edits"][0].get("attribution"))

# ------------------------------------------------------------- E. source pins --
_src = open(os.path.join(REPO, "src", "longrun", "harness", "whole.py"),
            encoding="utf-8").read()
check("E1 the executor has ONE repeats reader", _src.count("def repeats_of(") == 1)
check("E2 the executor uses it", "repeats = repeats_of(c)" in _src)
check("E3 no second `or 1` default survives on repeats",
      'int(c.get("repeats") or 1)' not in _src)

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
