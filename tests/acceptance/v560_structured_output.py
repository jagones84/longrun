#!/usr/bin/env python3
"""v560 (staged, RED) — structured output contract for model replies.

M1 of the upgrade plan: `model/structured.py` coerces a JSON Schema (rejecting
$ref before anything), extracts the JSON candidate from prose, validates
locally with a stdlib subset validator, and builds a one-shot retry message
with verbatim errors (schema NOT re-pasted). `subagent.spawn` accepts
`output_schema` (malformed -> rejected BEFORE spawning) and `collect`
validates with exactly one repair turn; a run never fails for schema.

Deterministic, no model, no network.
"""
import os
import sys

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
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail and not ok else ""))


try:
    from longrun.model import structured as S  # noqa: E402
    _has = True
except Exception as e:  # noqa: BLE001 — RED means the module is missing
    S, _has, _err = None, False, e

check("A0 model.structured exists", _has, "" if _has else _err)

# ---- B: coerce_schema -------------------------------------------------------
if _has:
    _s, _e = S.coerce_schema({"type": "object", "properties": {"a": {"type": "string"}},
                              "required": ["a"]})
    check("B1 a valid schema coerces", _s is not None and _e is None, _e)
    _s, _e = S.coerce_schema({"type": "object", "x": {"$ref": "#/defs/y"}})
    check("B2 $ref is rejected before anything", _s is None and bool(_e), _e)
    _s, _e = S.coerce_schema('{"type": "object"}')
    check("B3 a JSON string schema is accepted", _s == {"type": "object"}, _e)
    _s, _e = S.coerce_schema(["not", "a", "dict"])
    check("B4 a non-dict schema is rejected", _s is None and bool(_e), _e)
    _s, _e = S.coerce_schema({"type": "object", "defs": {"y": {"$recursiveRef": "#"}}})
    check("B5 $recursiveRef is rejected too", _s is None and bool(_e), _e)
else:
    for n in ("B1 a valid schema coerces", "B2 $ref is rejected before anything",
              "B3 a JSON string schema is accepted", "B4 a non-dict schema is rejected",
              "B5 $recursiveRef is rejected too"):
        check(n, False, "structured missing")

# ---- C: extract_candidate ---------------------------------------------------
if _has:
    check("C1 fenced JSON is extracted",
          S.extract_candidate('here:\n```json\n{"a": 1}\n```') == '{"a": 1}')
    check("C2 prose-embedded JSON is extracted",
          S.extract_candidate('result {"a": 2} done') == '{"a": 2}')
    check("C3 text without JSON gives None",
          S.extract_candidate("no json here at all") is None)
else:
    for n in ("C1 fenced JSON is extracted", "C2 prose-embedded JSON is extracted",
              "C3 text without JSON gives None"):
        check(n, False, "structured missing")

# ---- D: validate ------------------------------------------------------------
if _has:
    _sch = {"type": "object", "properties": {"a": {"type": "string"},
                                             "n": {"type": "integer"}},
            "required": ["a"], "additionalProperties": False}
    check("D1 valid data passes", S.validate({"a": "x", "n": 3}, _sch) == [])
    _errs = S.validate({"n": "not-an-int"}, _sch)
    check("D2 missing required + wrong type are reported",
          any("a" in e and "required" in e for e in _errs)
          and any("$.n" in e for e in _errs), _errs)
    check("D3 additionalProperties:false rejects extras",
          any("$.b" in e for e in S.validate({"a": "x", "b": 1}, _sch)))
    check("D4 enum is enforced",
          S.validate({"c": "zzz"}, {"properties": {"c": {"enum": ["aa", "bb"]}}}) != [])
    _nested_data = {"a": {"b": 1}}
    _nested_schema = {"properties": {"a": {"properties": {"b": {"type": "string"}}}}}
    _nested_errs = S.validate(_nested_data, _nested_schema)
    check("D5 nested paths use $.a.b",
          any("$.a.b" in e for e in _nested_errs), _nested_errs)
    _many = S.validate({"a": 1}, {"properties": {"a": {"type": "string",
                  "enum": ["x", "y"], "minLength": 5, "const": "z"}}})
    check("D6 errors are capped at 10", len(_many) <= 10, len(_many))
else:
    for n in ("D1 valid data passes", "D2 missing required + wrong type are reported",
              "D3 additionalProperties:false rejects extras", "D4 enum is enforced",
              "D5 nested paths use $.a.b", "D6 errors are capped at 10"):
        check(n, False, "structured missing")

# ---- E: retry message -------------------------------------------------------
if _has:
    _msg = S.retry_message(["$.a: required", "$.n: not integer"])
    check("E1 the retry carries verbatim errors",
          "$.a: required" in _msg and "$.n: not integer" in _msg)
    check("E2 the retry does NOT re-paste the schema",
          '"properties"' not in _msg and '"required"' not in _msg)
else:
    check("E1 the retry carries verbatim errors", False, "structured missing")
    check("E2 the retry does NOT re-paste the schema", False, "structured missing")

# ---- F: spawn rejects a malformed schema before spawning --------------------
try:
    from longrun.agent import subagent as SA  # noqa: E402
    _got = SA.spawn("do nothing", output_schema={"x": {"$ref": "#/y"}})
    check("F1 malformed schema is rejected without spawning",
          _got.get("subagent_id") is None and "invalid" in str(_got.get("error", "")).lower(),
          _got)
except Exception as e:  # noqa: BLE001
    check("F1 malformed schema is rejected without spawning", False, "spawn: %s" % e)

# ---- G: source locks (spawn stores + collect validates once) ----------------
def _read(*parts):
    try:
        with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


_SUB = _read("src", "longrun", "agent", "subagent.py")
check("G1 spawn accepts output_schema", "output_schema=None" in _SUB)
check("G2 the contract rides in the child goal",
      "OUTPUT_CONTRACT" in _SUB or "output contract" in _SUB.lower())
check("G3 collect validates and repairs at most once",
      _SUB.count("schema_valid") >= 2 and "repair" in _SUB.lower())

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
