"""Structured output contract for model replies (M1, upgrade plan).

A model reply that must be machine-readable is validated LOCALLY against an
inline JSON Schema subset — stdlib only, no `jsonschema` dependency:

* `coerce_schema` accepts a dict (or JSON string) and REJECTS `$ref` /
  `$recursiveRef` / `$dynamicRef` before anything is dispatched;
* `extract_candidate` pulls the first parseable `{...}` / `[...]` span out of
  prose or code fences;
* `validate` checks the parsed value against the supported subset and returns
  `$.path: message` errors (capped), unknown keywords are ignored;
* `retry_message` carries the verbatim errors back for exactly ONE retry turn,
  WITHOUT re-pasting the schema (a second retry makes models drop fields).

Supported keywords: `type` (incl. union lists), `properties`, `required`,
`additionalProperties` (bool or schema), `items`, `enum`, `const`,
`min/maxLength`, `minimum/maximum` (+ boolean `exclusiveMinimum` /
`exclusiveMaximum`), `min/maxItems`, `min/maxProperties`, `allOf`,
`anyOf` / `oneOf`. Everything else (`title`, `description`, `format`,
`pattern`, `not`, `if/then/else`, composition beyond the above) is ignored —
never a failure. A run NEVER fails for schema: callers keep the raw text with
`schema_valid: False` (Hermes policy).
"""
import json
import re

#: hard cap on reported errors — the retry turn stays small.
MAX_ERRORS = 10

#: reference keywords: unresolvable without a schema registry, so rejected.
REF_KEYS = frozenset({"$ref", "$recursiveRef", "$dynamicRef"})

JSON_ONLY = ("Reply with ONLY the JSON value, no prose, no explanations, "
             "no code fences.")

OUTPUT_CONTRACT = (
    "OUTPUT CONTRACT (machine-validated): your FINAL response must be ONLY "
    "the JSON value described by this schema — no prose, no code fence, "
    "no explanation:\n%s")


def contract_block(schema):
    """The goal appendix for a schema-bound subagent run."""
    try:
        compact = json.dumps(schema, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"))
    except (TypeError, ValueError):
        compact = "{}"
    return (OUTPUT_CONTRACT % compact) + "\n" + JSON_ONLY


def coerce_schema(raw):
    """(schema|None, error|None) for a user-supplied schema. Never raises."""
    try:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                return None, "output_schema is not valid JSON"
        if not isinstance(raw, dict):
            return None, "output_schema must be a JSON Schema object"
        try:
            raw = json.loads(json.dumps(raw, ensure_ascii=False))
        except (TypeError, ValueError):
            return None, "output_schema is not JSON-serializable"
        found = _find_ref(raw)
        if found:
            return None, "output_schema uses %s, which this validator cannot resolve" % found
        return raw, None
    except Exception as e:  # noqa: BLE001 — coerce must never raise
        return None, "output_schema invalid: %s" % e


def _find_ref(node):
    """First reference keyword in `node`, or None (keys only, never values)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in REF_KEYS:
                return k
            hit = _find_ref(v)
            if hit:
                return hit
    elif isinstance(node, list):
        for v in node:
            hit = _find_ref(v)
            if hit:
                return hit
    return None


_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL)


def extract_candidate(text):
    """First parseable `{...}` / `[...]` span in `text`, or None. Never raises."""
    if not isinstance(text, str) or not text:
        return None
    m = _FENCE_RE.search(text)
    if m:
        inner = m.group(1).strip()
        try:
            json.loads(inner)
            return inner
        except ValueError:
            pass
    opens = sorted([(i, c) for i, c in enumerate(text) if c in "{["])
    for i, _ in opens:
        span = _balanced_span(text, i)
        if span is None:
            continue
        try:
            json.loads(span)
            return span
        except ValueError:
            continue
    return None


def _balanced_span(text, start):
    """The balanced bracket span starting at `start`, string-aware, or None."""
    depth = 0
    instr = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
            continue
        if c == '"':
            instr = True
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
            if depth < 0:
                return None
    return None


def validate_text(text, schema):
    """(data|None, errors) for a raw model reply. Never raises."""
    try:
        cand = extract_candidate(text)
        if cand is None:
            return None, ["response contains no JSON value"]
        try:
            data = json.loads(cand)
        except ValueError as e:
            return None, ["response is not valid JSON: %s" % e]
        errs = validate(data, schema or {})
        return (data if not errs else None), errs
    except Exception as e:  # noqa: BLE001
        return None, ["validation failed: %s" % e]


def validate(data, schema):
    """[$.path: message] for `data` against the supported subset (cap 10)."""
    out = []
    try:
        _walk(data, schema if isinstance(schema, dict) else {}, "$", out)
    except Exception as e:  # noqa: BLE001 — validation must never raise
        out.append("$: validator error: %s" % e)
    return out[:MAX_ERRORS]


def retry_message(errors):
    """The single repair turn: verbatim errors, schema NOT re-pasted."""
    lines = ["Your previous response was rejected by the output contract validator.",
             "Validation errors:"]
    lines += ["- %s" % e for e in (errors or ["unknown error"])]
    lines += ["", "Reply with ONLY the corrected JSON value matching the OUTPUT "
                   "CONTRACT from your task context. No prose, no explanations."]
    return "\n".join(lines)


def _kind(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _type_ok(v, t):
    if isinstance(t, list):
        return any(_type_ok(v, one) for one in t)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return _kind(v) == t


def _walk(data, schema, path, out):
    if len(out) >= MAX_ERRORS or not isinstance(schema, dict):
        return
    t = schema.get("type")
    if t is not None and not _type_ok(data, t):
        out.append("%s: expected %s, got %s" % (path, t, _kind(data)))
        return
    if isinstance(data, dict):
        props = schema.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        for r in schema.get("required") or []:
            if isinstance(r, str) and r not in data:
                out.append("%s: required property %r is missing" % (path, r))
        for k, v in data.items():
            if k in props and isinstance(props[k], dict):
                _walk(v, props[k], "%s.%s" % (path, k), out)
            else:
                extra = schema.get("additionalProperties")
                if extra is False:
                    out.append("%s.%s: unexpected property" % (path, k))
                elif isinstance(extra, dict):
                    _walk(v, extra, "%s.%s" % (path, k), out)
    if isinstance(data, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for i, v in enumerate(data):
                _walk(v, items, "%s[%d]" % (path, i), out)
    if "enum" in schema and isinstance(schema["enum"], list):
        if data not in schema["enum"]:
            out.append("%s: %r is not one of %r" % (path, data, schema["enum"]))
    if "const" in schema:
        if data != schema["const"]:
            out.append("%s: must equal %r" % (path, schema["const"]))
    if isinstance(data, str):
        _minmax(out, path, len(data), schema, "minLength", "maxLength", "chars")
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        _minmax(out, path, data, schema, "minimum", "maximum", "")
        _exclusive(out, path, data, schema)
    if isinstance(data, list):
        _minmax(out, path, len(data), schema, "minItems", "maxItems", "items")
    if isinstance(data, dict):
        _minmax(out, path, len(data), schema, "minProperties", "maxProperties",
                "properties")
    for sub in schema.get("allOf") or []:
        if isinstance(sub, dict):
            _walk(data, sub, path, out)
    for key in ("anyOf", "oneOf"):
        branches = schema.get(key)
        if not isinstance(branches, list) or not branches:
            continue
        passing = 0
        first_errs = []
        for sub in branches:
            if not isinstance(sub, dict):
                continue
            trial = []
            _walk(data, sub, path, trial)
            if not trial:
                passing += 1
            elif not first_errs:
                first_errs = trial
        if key == "oneOf" and passing > 1:
            out.append("%s: matches %d oneOf branches, must match exactly one"
                       % (path, passing))
        elif passing == 0:
            out.append("%s: matches no %s branch%s" % (
                path, key, (": " + first_errs[0]) if first_errs else ""))


def _minmax(out, path, value, schema, lok, hik, unit):
    lo, hi = schema.get(lok), schema.get(hik)
    try:
        if lo is not None and value < int(lo):
            out.append("%s: below %s %s" % (path, lok, lo))
        if hi is not None and value > int(hi):
            out.append("%s: above %s %s" % (path, hik, hi))
    except (TypeError, ValueError):
        pass


def _exclusive(out, path, value, schema):
    for key, op, name in (("exclusiveMinimum", lambda v, b: v <= b, "over"),
                          ("exclusiveMaximum", lambda v, b: v >= b, "under")):
        bound = schema.get(key)
        if bound is None:
            continue
        try:
            if isinstance(bound, bool):
                base = schema.get("minimum" if key == "exclusiveMinimum"
                                  else "maximum")
                if base is None or not op(value, base):
                    continue
                out.append("%s: must be %s %s (exclusive)" % (path, name, base))
            elif op(value, bound):
                out.append("%s: must be %s %s (exclusive)" % (path, name, bound))
        except TypeError:
            pass
