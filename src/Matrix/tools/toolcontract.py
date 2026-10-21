"""Matrix tool: toolcontract.audit.

Audit the active Nucleus and Matrix tool registries for malformed contracts and
ambiguous subtool signatures. The result is read-only and deterministic.
"""

from collections import defaultdict


def _unwrap(entry):
    """Return a JSON schema from either a raw schema or a Matrix runtime spec."""
    if isinstance(entry, dict) and isinstance(entry.get("schema"), dict):
        return entry["schema"]
    return entry


def _audit_schemas(schemas):
    """Return structured findings for a mapping of full tool names to schemas."""
    malformed = []
    required_missing = []
    internal_mismatch = []
    groups = defaultdict(list)

    for raw_name, entry in sorted((str(name), value) for name, value in (schemas or {}).items()):
        schema = _unwrap(entry)
        if not isinstance(schema, dict):
            malformed.append({"tool": raw_name, "reason": "schema is not an object"})
            continue

        if schema.get("type") != "object":
            malformed.append({"tool": raw_name, "reason": "type is not object"})

        props = schema.get("properties")
        if not isinstance(props, dict):
            malformed.append({"tool": raw_name, "reason": "properties is not an object"})
            props = {}

        required = schema.get("required")
        if required is None:
            required = []
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            malformed.append({"tool": raw_name, "reason": "required is not a list of strings"})
            required = []

        missing = sorted(set(required) - set(props))
        if missing:
            required_missing.append({"tool": raw_name, "missing": missing})

        namespace = raw_name.split(".", 1)[0]
        declared_namespace = schema.get("_namespace")
        declared_subtool = schema.get("_subtool")

        # Matrix runtime specs carry metadata outside the nested ``schema``.
        if isinstance(entry, dict):
            declared_namespace = entry.get("namespace", declared_namespace)
            declared_subtool = entry.get("subtool", declared_subtool)

        if declared_namespace is not None and str(declared_namespace) != namespace:
            internal_mismatch.append({
                "tool": raw_name,
                "expected_namespace": namespace,
                "declared_namespace": declared_namespace,
            })
        if declared_subtool is not None:
            expected_subtool = raw_name.split(".", 1)[1] if "." in raw_name else "run"
            if str(declared_subtool) != expected_subtool:
                internal_mismatch.append({
                    "tool": raw_name,
                    "expected_subtool": expected_subtool,
                    "declared_subtool": declared_subtool,
                })

        signature = (
            schema.get("type", "object"),
            tuple(sorted((key, repr(value)) for key, value in props.items())),
            tuple(required),
            tuple(sorted((index, repr(value)) for index, value in enumerate(schema.get("anyOf") or []))),
        )
        groups[(namespace, signature)].append(raw_name)

    collisions = []
    for (namespace, signature), names in sorted(groups.items()):
        if len(names) <= 1:
            continue
        collisions.append({
            "namespace": namespace,
            "tools": names,
            "reason": "identical argument contracts across subtools",
        })

    return {
        "malformed": malformed,
        "required_missing": required_missing,
        "internal_mismatch": internal_mismatch,
        "schema_collisions": collisions,
        "total": len(schemas or {}),
    }


def _load_runtime():
    """Load the active Nucleus and Matrix registries at call time."""
    from longrun.core.matrix import discover_tools, hotload
    from longrun.tools import registry

    hotload()
    return registry.TOOL_SCHEMAS, discover_tools()


def _as_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def audit(args=None, run_id=None, subtool=None):
    """Audit runtime tool contracts.

    ``scope`` is one of ``all``, ``nucleus`` or ``matrix``. ``strict`` makes
    ambiguous identical subtool signatures fatal; malformed contracts are always
    fatal. The result is deterministic and contains no mutable registry state.
    """
    args = args or {}
    try:
        scope = str(args.get("scope") or "all").strip().lower()
        if scope not in {"all", "nucleus", "matrix"}:
            return {"ok": False, "error": "scope must be one of all, nucleus or matrix"}
        strict = _as_bool(args.get("strict", False))
        nucleus, matrix = _load_runtime()

        nucleus_result = _audit_schemas(nucleus)
        matrix_result = _audit_schemas(matrix)
        matrix_result["tools"] = sorted(str(name) for name in matrix.keys())

        if scope == "nucleus":
            result = {"scope": scope, **nucleus_result}
        elif scope == "matrix":
            result = {"scope": scope, **matrix_result}
        else:
            result = {
                "scope": scope,
                "nucleus": nucleus_result,
                "matrix": matrix_result,
                "total": nucleus_result["total"] + matrix_result["total"],
                "namespaces": sorted({name.split(".", 1)[0] for name in nucleus} |
                                     {name.split(".", 1)[0] for name in matrix}),
                "matrix_tools": matrix_result["tools"],
            }

        result["malformed"] = result.get("nucleus", {}).get("malformed", []) + result.get("matrix", {}).get("malformed", [])
        result["required_missing"] = result.get("nucleus", {}).get("required_missing", []) + result.get("matrix", {}).get("required_missing", [])
        result["internal_mismatch"] = result.get("nucleus", {}).get("internal_mismatch", []) + result.get("matrix", {}).get("internal_mismatch", [])
        result["schema_collisions"] = result.get("nucleus", {}).get("schema_collisions", []) + result.get("matrix", {}).get("schema_collisions", [])

        fatal = bool(result["malformed"] or result["required_missing"] or result["internal_mismatch"])
        if strict and result["schema_collisions"]:
            fatal = True
        result["ok"] = not fatal
        result["strict"] = strict
        return result
    except Exception as exc:
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}


def execute(args, run_id=None, subtool=None):
    """Matrix execute entry point."""
    return audit(args, run_id, subtool)


TOOL_SCHEMA = {
    "description": (
        "[MATRIX] Audit the runtime built-in and Matrix tool schemas for malformed "
        "contracts, missing required properties, internal namespace/subtool mismatches, "
        "and ambiguous identical subtool signatures. Read-only."
    ),
    "type": "object",
    "properties": {
        "scope": {
            "type": "string",
            "enum": ["all", "nucleus", "matrix"],
            "default": "all",
            "description": "Registry scope to audit.",
        },
        "strict": {
            "type": "boolean",
            "default": False,
            "description": "Treat ambiguous identical subtool signatures as fatal.",
        },
    },
    "required": [],
    "approval": "auto",
}

TOOL_SCHEMAS = {"toolcontract.audit": dict(TOOL_SCHEMA)}
