"""Matrix tool namespace: grep."""

TOOL_SCHEMAS = {
    "grep.search": {
        "description": 'exact regex search over workspace files',
        "type": "object",
        "properties": {},
        "required": [],
        "approval": "auto",
    },
}


def execute(args, run_id=None, subtool=None):
    args = args or {}
    return {"ok": True, "stdout": "grep.search executed", "subtool": subtool or 'search'}
