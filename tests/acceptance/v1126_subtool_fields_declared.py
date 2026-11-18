#!/usr/bin/env python3
"""v1126 — a subtool field the namespace does not declare is not a field at all.

Round 60. The unknown-argument ledger (measured 2026-11-18) showed real, repeated
arguments being answered as mistakes:

  improve.repairs: unknown argument 'min_severity' (did you mean 'end_line'?)  x5
  improve.repairs: unknown argument 'since'                                   x2
  self.failures:   unknown argument 'since'                                   x3

All three ARE read by the handlers, and `_SUBTOOL_FIELDS` already listed them — but
the canonical schema is built as `{pk: props[pk] for pk in fields if pk in props}`,
so a field the NAMESPACE does not declare is silently dropped: the subtool
advertised `limit` alone and the shape checker told the model its real argument was
unknown. The declaration was the missing half.

  A  improve.repairs declares limit + min_severity + since
  B  self.failures declares limit + since
  C  the shape checker no longer flags them
  D  a genuinely unknown key still warns, and the accepts list is accurate
  E  the discovery payload (`self tools tool=…`) carries the fields
  F  CATALOGUE INVARIANT: every `_SUBTOOL_FIELDS` entry is declared by its namespace
  G  the handler still reads `since` (the window helper is unchanged)

Deterministic: registry reads only; no process, no model, no network.
Run: python3 tests/acceptance/v1126_subtool_fields_declared.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1126-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as R  # noqa: E402
from longrun.tools import tools as T  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


rep = T._schema_props("improve.repairs")
check("A1 improve.repairs declares limit", "limit" in rep, rep)
check("A2 and min_severity", "min_severity" in rep, rep)
check("A3 and since", "since" in rep, rep)
check("A4 min_severity states its values",
      rep.get("min_severity", {}).get("enum") == ["info", "warning", "error"],
      rep.get("min_severity"))

fail = T._schema_props("self.failures")
check("B1 self.failures declares limit and since",
      "limit" in fail and "since" in fail, fail)

check("C1 a real min_severity is not an unknown argument",
      T._shape_notes("improve.repairs", {"min_severity": "error"}) == [],
      T._shape_notes("improve.repairs", {"min_severity": "error"}))
check("C2 a real since is not an unknown argument",
      T._shape_notes("self.failures", {"since": "2026-11-18"}) == [],
      T._shape_notes("self.failures", {"since": "2026-11-18"}))

notes = T._shape_notes("improve.repairs", {"bogus": 1})
msg = notes[0][1] if notes else ""
check("D1 a made-up key still warns", notes and notes[0][0] == "unknown", notes)
check("D2 and the accepts list names the real fields",
      "limit" in msg and "min_severity" in msg and "since" in msg, msg)

spec = (R.tool_spec("improve.repairs") or {}).get("schema") or {}
check("E1 the canonical schema carries the fields",
      {"limit", "min_severity", "since"} <= set(spec.get("properties") or {}),
      sorted(spec.get("properties") or {}))
check("E2 the subtool guidance is what the schema carries",
      "failure register" in str(spec.get("description") or "").lower(),
      str(spec.get("description"))[:120])

bad = []
for ns, acts in R._SUBTOOL_FIELDS.items():
    props = (R._LEGACY_SCHEMAS.get(ns) or {}).get("properties") or {}
    for act, fields in (acts or {}).items():
        miss = [f for f in (fields or []) if f not in props]
        if miss:
            bad.append("%s.%s: %s" % (ns, act, miss))
check("F1 every subtool field is declared by its namespace", not bad, bad[:5])

check("G1 the window helper still parses an ISO date",
      isinstance(selfevolve._since_epoch("2026-11-18"), float), "")
check("G2 and an epoch passes through", selfevolve._since_epoch(1794900000) == 1794900000.0,
      selfevolve._since_epoch(1794900000))

print("\n---\nv1126: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
