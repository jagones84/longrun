#!/usr/bin/env python3
"""v649 — a generated Matrix tool must be well-formed BEFORE it becomes callable.

Source (operator): "ALCUNI sono autogenerati da matrix quindi devi rafforzare le
regole per crearli bene e/o altri modi per no farle fallire creare male".

Gap found by reading the live path (`_hotload_locked` -> `_extract_module_subtools`):
a Matrix tool is written by a MODEL. The loader used to silently default `type`,
`properties` and `required`, so a malformed contract reached the registry and the
defect only appeared at CALL time — an empty `required` made every argument
optional, a placeholder description told the next agent nothing, and the
`[MATRIX]` tag was the only thing saying where it came from. `toolcontract.audit`
already knew how to detect all of that, but the generative path never called it.

Contract:
  A) a missing / placeholder description is refused;
  B) a non-object `type`, a non-dict `properties`, a non-string key is refused;
  C) a `required` that is not a list of strings, or names never declared, is refused;
  D) an `anyOf` branch requiring an undeclared name is refused;
  E) a well-formed tool still loads (the gate must not break the shipped ones);
  F) hotload reports the refusal per tool instead of exposing it;
  G) a scaffold STUB is not callable until it is described;
  H) promotion runs the same gate: a test proof does not bless a bad contract.

Deterministic: temp dirs, no model, no network, no server.
Run: python3 tests/acceptance/v649_matrix_contract_gate.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v649_")
for name, tail in {
    "LONGRUN_DATA_DIR": "data",
    "LONGRUN_CONFIG_DIR": "cfg",
    "LONGRUN_DB": "events.db",
    "LONGRUN_SESSIONS_DIR": "sessions",
    "LONGRUN_GRAPH_DIR": "graphs",
    "LONGRUN_EDITS_DIR": "edits",
    "LONGRUN_RUNS_DIR": "runs",
    "LONGRUN_ROLES_DIR": "roles",
    "LONGRUN_COSTS_DIR": "costs",
    "LONGRUN_THREADS_DIR": "threads",
    "LONGRUN_MATRIX_SRC": "matrix_src",
    "LONGRUN_MATRIX_DOT": "matrix_dot",
    "LONGRUN_APPROVALS": "approvals.json",
}.items():
    os.environ[name] = os.path.join(TMP, tail)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import matrix  # noqa: E402
from longrun.tools import matrix_guard  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


matrix_guard.ensure_layout(TMP)
MSRC = matrix._roots(TMP)[1]
TOOLS = os.path.join(MSRC, "tools")
os.makedirs(TOOLS, exist_ok=True)

GOOD = {
    "description": "probe.ping — Return pong for the given label.",
    "type": "object",
    "properties": {"label": {"type": "string"}},
    "required": ["label"],
}


def write_tool(name, schema_literal):
    """Write a Matrix tool module whose TOOL_SCHEMAS entry is `schema_literal`."""
    path = os.path.join(TOOLS, name + ".py")
    body = (
        '"""probe."""\n\n'
        "TOOL_SCHEMAS = {\n    %r: %s,\n}\n"
        "TOOL_SCHEMA = dict(TOOL_SCHEMAS[%r])\n\n"
        "def execute(args, run_id=None, subtool=None):\n"
        '    return {"ok": True, "stdout": "pong"}\n'
        % ("probe." + name, schema_literal, "probe." + name)
    )
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    return path


def errs_for(tname):
    hl = matrix.hotload(TMP)
    return [e for e in hl["errors"] if tname in (e.get("tool") or "")]


# ---- A. description ---------------------------------------------------------
check("A1 no description at all is refused",
      "description is required" in matrix._schema_problem("p.x", {"properties": {}}))
check("A2 the scaffold placeholder is refused",
      "placeholder" in matrix._schema_problem(
          "p.x", {"description": "REPLACE THIS DESCRIPTION: state exactly what p.x does."}))
check("A3 a real description passes",
      matrix._schema_problem("p.x", {"description": "p.x — ping it."}) == "")

# ---- B. shape ---------------------------------------------------------------
check("B1 type must be object",
      'type must be "object"' in matrix._schema_problem(
          "p.x", {"description": "d", "type": "string"}))
check("B2 properties must be a dict",
      "properties must be an object" in matrix._schema_problem(
          "p.x", {"description": "d", "properties": ["a"]}))
check("B3 property names must be strings",
      "property name must be a string" in matrix._schema_problem(
          "p.x", {"description": "d", "properties": {1: {}}}))

# ---- C/D. required and anyOf ------------------------------------------------
check("C1 required must be a list of strings",
      "required must be a list of strings" in matrix._schema_problem(
          "p.x", {"description": "d", "required": "label"}))
check("C2 a required name must be declared",
      "required names not declared" in matrix._schema_problem(
          "p.x", {"description": "d", "properties": {}, "required": ["label"]}))
check("D1 an anyOf branch cannot require an undeclared name",
      "anyOf requires undeclared names" in matrix._schema_problem(
          "p.x", {"description": "d", "properties": {"a": {}},
                  "anyOf": [{"required": ["b"]}]}))

# ---- E. a correct tool still loads -----------------------------------------
write_tool("ok", repr(GOOD))
hl = matrix.hotload(TMP)
check("E1 a well-formed tool is exposed", "probe.ok" in hl["loaded_tools"],
      hl["errors"])
check("E2 nothing is reported for it", not errs_for("probe.ok"), errs_for("probe.ok"))

# ---- F. the refusals are reported, not exposed ------------------------------
write_tool("nodesc", "{'type': 'object', 'properties': {}, 'required': []}")
check("F1 a description-less tool is not exposed",
      "probe.nodesc" not in matrix.hotload(TMP)["loaded_tools"])
check("F2 and the reason names the file and the defect",
      any("invalid tool contract" in (e.get("error") or "") for e in errs_for("probe.nodesc")),
      errs_for("probe.nodesc"))
write_tool("badreq", "{'description': 'p.badreq — d.', 'type': 'object', "
                     "'properties': {}, 'required': ['label']}")
check("F3 an undeclared required is refused at load",
      "probe.badreq" not in matrix.hotload(TMP)["loaded_tools"]
      and any("required names not declared" in (e.get("error") or "")
              for e in errs_for("probe.badreq")))

# ---- G. the scaffold stub is not callable until described -------------------
made = matrix.scaffold("tool", "probe.stub", "", repo_root=TMP)
stub_hl = made.get("hotload") or {}
check("G1 scaffold succeeds and reports the load refusal",
      made.get("ok") is True
      and "probe.stub" not in (stub_hl.get("loaded_tools") or []),
      stub_hl.get("errors"))
with open(made.get("path") or "", encoding="utf-8") as f:
    src = f.read()
src = src.replace("REPLACE THIS DESCRIPTION: state exactly what probe.stub does, "
                  "each input, and the output it returns.",
                  "probe.stub — Return pong; the label is echoed back.")
with open(made.get("path") or "", "w", encoding="utf-8", newline="\n") as f:
    f.write(src)
check("G2 after the description is written the tool is exposed",
      "probe.stub" in matrix.hotload(TMP)["loaded_tools"])

# ---- H. promotion runs the same gate ---------------------------------------
# `badreq` is its own namespace file, so verify_target resolves the SAME module
# the loader refused (a proof recorded for `probe` would answer for probe.py).
matrix._record_verified("tool", "badreq", "test_matrix.py", TMP)
v = matrix.verify_target("tool", "badreq", repo_root=TMP)
check("H1 a recorded test proof does not bless a bad contract",
      v.get("ok") is False and "invalid tool contract" in (v.get("error") or ""),
      v)

print("---")
passed = sum(results)
print("\nv649: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
