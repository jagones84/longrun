"""Matrix tool: toolcontract.audit.

Read-only, deterministic audit of the ACTIVE Nucleus and Matrix tool registries.

Design goals (defensive against harness refactors):

1. NEVER trust a registry's concrete class. ``registry.TOOL_SCHEMAS`` is a
   ``_NamespacedSchemasDict`` and ``discover_tools()`` a ``_NamespacedToolMap``
   today; both already override ``__contains__``/``get`` asymmetrically with
   respect to ``keys()``. We therefore only ever iterate ``items()``/``keys()``
   and never infer the tool set from ``in``/``.get()``.
2. NEVER trust the entry shape. A raw JSON schema, a wrapper with a nested
   ``schema``/``input_schema``/``parameters``, a ``function``-style wrapper and a
   JSON string are all accepted.
3. Findings are ACCUMULATED, never overwritten. The previous version spread the
   per-scope dict and then rebuilt the flat keys from ``result.get("nucleus",
   {}).get(...)``; on ``scope=nucleus``/``scope=matrix`` those sub-dicts do not
   exist, so every finding was silently replaced by ``[]`` and a broken registry
   was reported ``ok: True``. That is the bug this rewrite fixes.
4. A crash is distinguishable from an invalid argument, and neither is
   confusable with a clean audit: the payload carries ``error_kind``.
5. Output is versioned (``schema_version``) and reports the registry shapes it
   observed (``registry``), so a consumer can detect that the harness changed
   shape rather than silently reading zeros.
"""

from __future__ import annotations

import json
from collections import defaultdict

SCHEMA_VERSION = 2

FINDING_KEYS = (
    "malformed",
    "required_missing",
    "internal_mismatch",
    "schema_collisions",
    "warnings",
)

VALID_SCOPES = ("all", "nucleus", "matrix")

# Keys under which a runtime wrapper may carry the real JSON schema.
SCHEMA_KEYS = ("schema", "input_schema", "inputSchema", "parameters", "parameter_schema", "args_schema")
# Keys under which a runtime wrapper may carry namespace / subtool metadata.
NAMESPACE_KEYS = ("namespace", "ns", "_namespace")
SUBTOOL_KEYS = ("subtool", "sub", "_subtool")
# Keys that make a dict recognisable as a raw JSON schema by itself.
RAW_SCHEMA_KEYS = ("properties", "type", "anyOf", "oneOf", "allOf", "$ref", "additionalProperties")


def _empty_findings():
    """Return a fresh findings mapping with one (empty) list per finding key."""
    return {key: [] for key in FINDING_KEYS}


def _as_mapping(obj):
    """Best-effort plain-dict view of any mapping; ``{}`` for anything else."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        try:
            return dict(obj.items())
        except Exception:  # noqa: BLE001 - a hostile Mapping must not crash the audit
            return {}
    items = getattr(obj, "items", None)
    if callable(items):
        try:
            return dict(items())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _alias_keys(mapping):
    """Keys that the registry exposes as legacy aliases rather than as tools.

    ``registry.TOOL_SCHEMAS`` keeps ~20 dotless legacy aliases (``shell``, ``git``,
    ``memory``...) in a private ``_legacy`` dict. They are not tools and must not
    be reported as namespace violations. We probe for that attribute instead of
    importing the private class, so a refactor only costs us the exemption.
    """
    legacy = getattr(mapping, "_legacy", None)
    if isinstance(legacy, dict):
        try:
            return {str(key) for key in legacy.keys()}
        except Exception:  # noqa: BLE001
            return set()
    return set()


def _canonical(value):
    """Stable, order-independent string form of a JSON-ish value."""
    try:
        return json.dumps(value, sort_keys=True, default=repr, separators=(",", ":"))
    except Exception:  # noqa: BLE001
        return repr(value)


def _unwrap(entry):
    """Return the JSON schema carried by ``entry``, or ``None`` when there is none.

    Accepts a raw schema, a runtime wrapper (nested under any of :data:`SCHEMA_KEYS`),
    an OpenAI-style ``{"function": {...}}`` wrapper, or a JSON string.
    """
    if isinstance(entry, (bytes, bytearray)):
        try:
            entry = entry.decode("utf-8")
        except Exception:  # noqa: BLE001
            return None
    if isinstance(entry, str):
        try:
            entry = json.loads(entry)
        except Exception:  # noqa: BLE001
            return None
    if not isinstance(entry, dict):
        return None

    for key in SCHEMA_KEYS:
        nested = entry.get(key)
        if isinstance(nested, dict):
            return nested

    function = entry.get("function")
    if isinstance(function, dict):
        for key in SCHEMA_KEYS:
            nested = function.get(key)
            if isinstance(nested, dict):
                return nested
        if any(key in function for key in RAW_SCHEMA_KEYS):
            return function

    if any(key in entry for key in RAW_SCHEMA_KEYS):
        return entry

    # A dict with no recognisable schema markers is still handed back so the
    # caller can report it precisely ("type is not 'object'") instead of
    # pretending it was absent.
    return entry


def _declared(entry, schema, keys):
    """First non-None metadata value found in the wrapper, then in the schema."""
    for source in (entry, schema):
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if value is not None:
                return value
    return None


def _signature(schema, props, required):
    """Order-independent contract fingerprint used for collision detection."""
    return (
        str(schema.get("type", "object")),
        _canonical(props),
        tuple(sorted(set(required))),
        _canonical(schema.get("anyOf")),
        _canonical(schema.get("oneOf")),
        _canonical(schema.get("allOf")),
    )


def _audit_registry(mapping):
    """Audit one registry mapping; returns findings, tools audited and totals."""
    findings = _empty_findings()
    groups = defaultdict(list)
    audited = []
    aliases = _alias_keys(mapping)
    entries = _as_mapping(mapping)

    for raw_name, entry in sorted(entries.items(), key=lambda kv: str(kv[0])):
        name = str(raw_name)

        namespace, separator, subtool = name.partition(".")
        if not separator or not namespace or not subtool:
            if name in aliases:
                # Legacy alias of an existing tool, not a tool of its own.
                continue
            findings["malformed"].append({
                "tool": name,
                "reason": "missing namespace separator (expected '<namespace>.<subtool>')",
            })
            continue

        if subtool.count("."):
            findings["warnings"].append({
                "tool": name,
                "reason": "subtool contains a dot; '<namespace>.<subtool>' expects exactly one",
            })

        audited.append(name)
        schema = _unwrap(entry)
        if not isinstance(schema, dict):
            findings["malformed"].append({"tool": name, "reason": "schema is not an object"})
            continue

        if schema.get("type") != "object":
            findings["malformed"].append({
                "tool": name,
                "reason": "type is not 'object'",
                "type": schema.get("type"),
            })

        props = schema.get("properties")
        if not isinstance(props, dict):
            findings["malformed"].append({"tool": name, "reason": "properties is not an object"})
            props = {}
        else:
            non_string = sorted((repr(key) for key in props if not isinstance(key, str)))
            if non_string:
                findings["malformed"].append({
                    "tool": name,
                    "reason": "non-string property name(s)",
                    "properties": non_string,
                })
                props = {key: value for key, value in props.items() if isinstance(key, str)}

        required = schema.get("required")
        if required is None:
            required = []
        elif isinstance(required, (list, tuple)) and all(isinstance(item, str) for item in required):
            required = list(required)
        else:
            findings["malformed"].append({
                "tool": name,
                "reason": "required is not a list of strings",
            })
            required = []

        missing = sorted(set(required) - set(props))
        if missing:
            findings["required_missing"].append({"tool": name, "missing": missing})

        duplicated = sorted({item for item in required if list(required).count(item) > 1})
        if duplicated:
            findings["warnings"].append({
                "tool": name,
                "reason": "duplicate entries in required",
                "keys": duplicated,
            })

        declared_namespace = _declared(entry, schema, NAMESPACE_KEYS)
        if declared_namespace is not None and str(declared_namespace) != namespace:
            findings["internal_mismatch"].append({
                "tool": name,
                "expected_namespace": namespace,
                "declared_namespace": declared_namespace,
            })

        declared_subtool = _declared(entry, schema, SUBTOOL_KEYS)
        if declared_subtool is not None and str(declared_subtool) != subtool:
            findings["internal_mismatch"].append({
                "tool": name,
                "expected_subtool": subtool,
                "declared_subtool": declared_subtool,
            })

        groups[(namespace, _signature(schema, props, required))].append(name)

    for (namespace, _sig), names in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if len(names) <= 1:
            continue
        findings["schema_collisions"].append({
            "namespace": namespace,
            "tools": sorted(names),
            "reason": "identical argument contracts across subtools",
        })

    findings["total"] = len(audited)
    findings["tools"] = sorted(audited)
    findings["entries"] = len(entries)
    findings["aliases_skipped"] = len(aliases.intersection(entries.keys()))
    return findings


def _load_runtime():
    """Load both registries independently so one failure cannot hide the other."""
    env = {
        "nucleus_kind": None,
        "matrix_kind": None,
        "hotload": "skipped",
        "errors": [],
    }
    nucleus = {}
    matrix = {}

    try:
        from longrun.tools import registry
        nucleus = getattr(registry, "TOOL_SCHEMAS", None)
        if nucleus is None:
            env["errors"].append("nucleus: registry.TOOL_SCHEMAS missing")
            nucleus = {}
        env["nucleus_kind"] = type(nucleus).__name__
    except Exception as exc:  # noqa: BLE001
        env["errors"].append("nucleus: %s: %s" % (type(exc).__name__, exc))

    try:
        from longrun.core.matrix import discover_tools, hotload
        try:
            hotload()
            env["hotload"] = "ok"
        except Exception as exc:  # noqa: BLE001
            env["hotload"] = "error: %s: %s" % (type(exc).__name__, exc)
        matrix = discover_tools()
        if matrix is None:
            matrix = {}
        env["matrix_kind"] = type(matrix).__name__
    except Exception as exc:  # noqa: BLE001
        env["errors"].append("matrix: %s: %s" % (type(exc).__name__, exc))

    return nucleus, matrix, env


def _as_bool(value):
    """Lenient boolean coercion (the router may deliver 'yes'/'0'/1)."""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _select(parts, scope):
    """Merge the findings of the scopes selected by ``scope``.

    When more than one scope contributes, every finding is annotated with the
    ``registry`` it came from; otherwise two identical findings (one per
    registry) would be indistinguishable in the flat lists.
    """
    selected = _empty_findings()
    names = []
    contributors = [key for key in parts if scope == "all" or key == scope]
    annotate = len(contributors) > 1
    for key in contributors:
        part = parts[key]
        for finding_key in FINDING_KEYS:
            for item in part.get(finding_key) or []:
                if annotate and isinstance(item, dict) and "registry" not in item:
                    item = dict(item, registry=key)
                selected[finding_key].append(item)
        names.extend(part.get("tools") or [])
    return selected, sorted(names)


def audit(args=None, run_id=None, subtool=None):
    """Audit the active tool contracts.

    ``scope`` selects ``all``, ``nucleus`` or ``matrix``. Malformed contracts,
    missing required properties and namespace/subtool disagreements are always
    fatal; ``strict`` additionally makes ambiguous identical subtool contracts
    fatal. ``detail=False`` returns counts only (same verdict, smaller payload).
    """
    args = args if isinstance(args, dict) else {}

    try:
        scope = str(args.get("scope") or "all").strip().lower()
        if scope not in VALID_SCOPES:
            return {
                "ok": False,
                "error": "scope must be one of: " + ", ".join(VALID_SCOPES),
                "error_kind": "invalid_argument",
                "exit_code": 64,  # usage error, per the harness exit table
                "schema_version": SCHEMA_VERSION,
            }
        strict = _as_bool(args.get("strict", False))
        detail = _as_bool(args.get("detail", True))

        nucleus_map, matrix_map, env = _load_runtime()
        parts = {
            "nucleus": _audit_registry(nucleus_map),
            "matrix": _audit_registry(matrix_map),
        }

        for label, mapping in (("nucleus", nucleus_map), ("matrix", matrix_map)):
            if not hasattr(mapping, "items") or not isinstance(_as_mapping(mapping), dict):
                parts[label]["warnings"].append({
                    "tool": "*",
                    "reason": "%s registry is not a mapping (got %s); nothing audited"
                              % (label, type(mapping).__name__),
                })

        selected, tools = _select(parts, scope)

        fatal = bool(
            selected["malformed"]
            or selected["required_missing"]
            or selected["internal_mismatch"]
        )
        if strict and selected["schema_collisions"]:
            fatal = True

        result = {
            "ok": not fatal,
            "scope": scope,
            "strict": strict,
            "schema_version": SCHEMA_VERSION,
            "total": len(tools),
            "counts": {key: len(selected[key]) for key in FINDING_KEYS},
            "tools": tools,
            "matrix_tools": sorted(parts["matrix"]["tools"]),
            "namespaces": sorted({name.split(".", 1)[0] for name in tools}),
            "registry": env,
            "nucleus": {key: parts["nucleus"][key] for key in FINDING_KEYS},
            "matrix": {key: parts["matrix"][key] for key in FINDING_KEYS},
        }
        for key in ("total", "tools", "entries", "aliases_skipped"):
            result["nucleus"][key] = parts["nucleus"][key]
            result["matrix"][key] = parts["matrix"][key]

        if not detail:
            # detail=False must actually shrink the payload: the per-registry
            # sub-dicts would otherwise re-ship every finding and defeat the
            # flag (a ~6 KB answer for a counts-only request).
            for label in ("nucleus", "matrix"):
                part = result[label]
                for key in FINDING_KEYS:
                    part[key] = len(part[key] or [])
                part["tools"] = len(part["tools"] or [])

        # Flat keys expose the findings OF THE SELECTED SCOPE. They are built by
        # extending the same lists, never by re-reading a sub-dict that may not
        # exist: that is exactly what used to erase every finding.
        for key in FINDING_KEYS:
            result[key] = list(selected[key]) if detail else []

        # Make the verdict explicit instead of letting the harness infer it:
        # 0 = clean audit, 1 = fatal findings. Code and `ok` always agree.
        result["exit_code"] = 0 if not fatal else 1

        result["counts"]["fatal"] = int(bool(fatal))
        if env.get("errors"):
            result["warnings"] = result["warnings"] + [
                {"tool": "*", "reason": "registry load: " + err} for err in env["errors"]
            ]
        return result

    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": "%s: %s" % (type(exc).__name__, exc),
            "error_kind": "internal_error",
            "exit_code": 1,
            "schema_version": SCHEMA_VERSION,
        }


def execute(args, run_id=None, subtool=None):
    """Matrix execute entry point."""
    return audit(args, run_id, subtool)


TOOL_SCHEMA = {
    "description": (
        "Audit the active Nucleus and Matrix tool contracts for malformed schemas, "
        "required properties that do not exist, namespace/subtool disagreements and "
        "ambiguous identical subtool contracts. Read-only and deterministic."
    ),
    "type": "object",
    "properties": {
        "scope": {
            "type": "string",
            "enum": list(VALID_SCOPES),
            "default": "all",
            "description": "Registry scope to audit.",
        },
        "strict": {
            "type": "boolean",
            "default": False,
            "description": "Treat ambiguous identical subtool signatures as fatal.",
        },
        "detail": {
            "type": "boolean",
            "default": True,
            "description": "Include the finding lists; false returns counts only.",
        },
    },
    "required": [],
    "approval": "auto",
}

TOOL_SCHEMAS = {"toolcontract.audit": dict(TOOL_SCHEMA)}
