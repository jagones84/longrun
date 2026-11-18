#!/usr/bin/env python3
"""v1171 — declared numeric ranges are enforced, and the silent clamp is gone.

A54 P4: `shell.exec {timeout_secs: -5}` and `"abc"` were accepted silently; a
numeric string was coerced. The schema already declares the key but without
`minimum`/`maximum`, while `sessions` declares 0..900.

A54's "unlocated" grep clamp is located at src/Matrix/tools/grep.py:87-88:
`limit` is clamped 1..500 and `context` 0..5 in silence. The schema now declares
those ranges and the validator refuses an out-of-range value.

`"1"` stays ACCEPTED: v874 A6 pins that a numeric string for an integer argument
is not a new strictness. A54's expectation for `"1"` is corrected here.

Run: python3 tests/acceptance/v1171_tool_arg_ranges.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1171-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_OFFLINE"] = "1"
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402
from longrun.tools import tools as T  # noqa: E402
from Matrix.tools import grep as G  # noqa: E402

registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail else ""))


def shell(args):
    return T._dispatch_execute("shell.exec", dict({"command": "true"}, **args))


# ---- A1/A2: a negative and a non-numeric timeout are usage errors ---------
bad_neg = shell({"timeout_secs": -5})
check("A1 a negative timeout is exit 64 and names the argument",
      bad_neg.get("exit_code") == 64
      and "timeout_secs" in str(bad_neg.get("error") or ""), bad_neg)
bad_txt = shell({"timeout_secs": "abc"})
check("A2 a non-numeric timeout is exit 64 and says integer",
      bad_txt.get("exit_code") == 64
      and "integer" in str(bad_txt.get("error") or "").lower(), bad_txt)

# ---- A3: the existing contract (v874 A6) is preserved --------------------
check("A3 a numeric string for an integer argument is still accepted",
      T._shape_notes("shell.exec", {"command": "true",
                                    "timeout_secs": "1"}) == [])

# ---- A4/A5: out-of-range values are refused ------------------------------
bad_zero = shell({"timeout_secs": 0})
check("A4 zero is below the declared minimum (exit 64)",
      bad_zero.get("exit_code") == 64, bad_zero)
bad_big = shell({"timeout_secs": 3601})
check("A5 a value above the declared maximum is exit 64",
      bad_big.get("exit_code") == 64, bad_big)

# ---- A6: every timeout_secs schema declares its bounds -------------------
missing = []
for name, schema in registry._LEGACY_SCHEMAS.items():
    prop = (schema.get("properties") or {}).get("timeout_secs")
    if prop is None:
        continue
    if "minimum" not in prop or "maximum" not in prop:
        missing.append(name)
check("A6 every timeout_secs schema has minimum and maximum", not missing, missing)

# ---- B1: the grep range is in its schema --------------------------------
grep_schema = G.TOOL_SCHEMAS["grep.search"]["properties"]
check("B1 grep.search declares context 0..5 and limit 1..500",
      grep_schema["context"].get("minimum") == 0
      and grep_schema["context"].get("maximum") == 5
      and grep_schema["limit"].get("minimum") == 1
      and grep_schema["limit"].get("maximum") == 500,
      (grep_schema.get("context"), grep_schema.get("limit")))

# ---- B2/B3: the validator enforces that range and keeps valid values -----
_orig_matrix = registry._matrix_tools
registry._matrix_tools = lambda: {
    "grep.search": {"schema": G.TOOL_SCHEMAS["grep.search"],
                    "enabled": True, "approval": "auto"}}
try:
    notes = T._shape_notes("grep.search", {"pattern": "x", "context": 99})
    check("B2 grep.search context=99 is a range error, not a silent clamp",
          any(kind == "range" for kind, _text in notes), notes)
    bad_grep = T._dispatch_execute("grep.search", {"pattern": "x", "context": 99})
    check("B2b the same call is exit 64", bad_grep.get("exit_code") == 64, bad_grep)
    check("B3 valid grep values are still accepted",
          T._shape_notes("grep.search", {"pattern": "x", "context": 3,
                                         "limit": 100}) == [])
finally:
    registry._matrix_tools = _orig_matrix

print("---")
ok = sum(results)
print("\nv1171: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
