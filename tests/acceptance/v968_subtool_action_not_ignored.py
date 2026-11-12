#!/usr/bin/env python3
"""v968 — a subtool call never warns about the action the harness injected.

When a call resolves to a canonical `<namespace>.<subtool>` name, the dispatcher
injects the action itself (`tools.py`: `args.setdefault("action", injected_action)`),
while the derived per-subtool schema does not redeclare `action`. `_shape_notes`
then reported it as `unknown argument 'action' … ignored` on a call that
succeeded — a false statement attached to every such observation, about a key
nothing ignored. Measured live on `skills.retire` before the fix.

Contract:
  A) the real dispatch path (`skills.retire`) succeeds with NO `warning` key;
  B) a key the model really made up is still named, with its accepted arguments;
  C) a plain tool that DECLARES `action` is unaffected;
  D) the schema-level helper agrees with the dispatch-level result.

`skills.list` is not a case: its props are empty, so the helper returns early.

Deterministic: temp skills/data dirs, no server, no model, no network.

Run: python3 tests/acceptance/v968_subtool_action_not_ignored.py
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="v968_")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_TMP, "skills")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(_TMP, "cfg"))
os.environ.setdefault("LONGRUN_DB", os.path.join(_TMP, "events.db"))
os.makedirs(os.environ["LONGRUN_SKILLS_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def main():
    # A) the exact production path that produced the false warning
    res = T._dispatch_execute_raw("skills.retire", {}) or {}
    check("A1 a canonical subtool call succeeds", res.get("ok") is True, res.get("error"))
    check("A2 it carries NO 'unknown argument' warning", "warning" not in res,
          res.get("warning"))
    check("A3 it ran as a dry run", res.get("dry_run") is True, res.get("dry_run"))

    # B) a key the model really made up is still named, non-fatally
    res2 = T._dispatch_execute_raw("skills.retire", {"bogus": 1}) or {}
    warn = str(res2.get("warning") or "")
    check("B1 a made-up key is still reported", "unknown argument 'bogus'" in warn, warn)
    check("B2 and the call still ran", res2.get("ok") is True, res2.get("error"))

    # C) the same key on a plain tool that DOES declare `action` stays silent
    check("C1 a declared action is not an unknown key",
          T._shape_notes("skills", {"action": "list"}) == [],
          T._shape_notes("skills", {"action": "list"}))

    # D) the helper agrees with the dispatch-level result
    notes = T._shape_notes("skills.retire", {"action": "retire"})
    check("D1 the injected action produces no note", notes == [], notes)
    notes2 = T._shape_notes("skills.retire", {"action": "retire", "bogus": 1})
    check("D2 a made-up key still produces exactly one note", len(notes2) == 1, notes2)
    check("D3 the note names the accepted arguments",
          bool(notes2) and "accepts:" in notes2[0][1], notes2)

    ok = sum(results)
    print("\nv968: %d/%d PASS" % (ok, len(results)))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
