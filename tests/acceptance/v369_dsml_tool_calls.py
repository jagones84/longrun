#!/usr/bin/env python3
"""v369 — native DSML tool-call markup is parsed, not looped (JAG-369).

The A8 "Master" agent (model `openrouter:deepseek/deepseek-v4.1-flash`) answered a
tool request with DeepSeek's NATIVE tool-call markup instead of the harness' JSON
protocol. The markup wraps the marker "DSML" in full-width vertical bars (U+FF5C)
and carries an <invoke name="X"> with <parameter name="Y"> children.

Before this fix `extract_json` returned None, `_looks_like_json_action` was False
(the text does not start with `{`/`[`), so the call was silently dropped and the
harness looped forever (the model re-emitted the same markup every turn) — which
also leaked one raw markup message into the visible chat.

Run: python3 tests/acceptance/v369_dsml_tool_calls.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v369-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _s  # noqa: E402,F401  (server bootstraps agent)
from longrun.agent import agent as a  # noqa: E402

# The DSML marker: "DSML" wrapped in two full-width vertical bars (U+FF5C).
D = "\uff5c\uff5cDSML\uff5c\uff5c"
OPEN = "<" + D
CLOSE = "</" + D

SAMPLE = (
    OPEN + " calls>\n"
    + OPEN + ' invoke name="shell">\n'
    + OPEN + ' parameter name="command" string="true">ls -la /tmp</' + D + " parameter>\n"
    + CLOSE + " invoke>\n"
    + CLOSE + " calls>"
)

MULTI = (
    OPEN + " calls>\n"
    + OPEN + ' invoke name="fs.write">\n'
    + OPEN + ' parameter name="path" string="true">/tmp/a.txt</' + D + " parameter>\n"
    + OPEN + ' parameter name="content" string="true">hello\nworld</' + D + " parameter>\n"
    + OPEN + ' parameter name="lines" string="false">42</' + D + " parameter>\n"
    + CLOSE + " invoke>\n"
    + CLOSE + " calls>"
)

SAMPLE_BRACED = (
    OPEN + " calls>\n"
    + OPEN + ' invoke name="shell">\n'
    + OPEN + ' parameter name="command" string="true">python3 -c "import json; print(json.loads(\'{}\'))"</'
    + D + " parameter>\n"
    + CLOSE + " invoke>\n"
    + CLOSE + " calls>"
)

HERMES_TOOL_CALL = """<tool_call>
<function=tool>
<parameter=tool>
matrix.test
</parameter>
<parameter=args>
{"target":"tool:toolcontract","code":"from Matrix.tools import toolcontract\\nr = toolcontract.audit({'scope':'all'})\\nassert r['ok']"}
</parameter>
</function>
</tool_call>"""

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --------------------------------------------------------------- detection ----
check("DSML markup is detected", a._looks_like_dsml(SAMPLE))
check("plain prose is not DSML", not a._looks_like_dsml("just an answer"))
check("None is not DSML", not a._looks_like_dsml(None))

# The exact pre-fix failure: the JSON path misses it entirely.
check("extract_json() finds no JSON in DSML markup",
      a.extract_json(SAMPLE) is None, repr(a.extract_json(SAMPLE)))

# ----------------------------------------------------------------- parsing ----
act = a._dsml_action(SAMPLE)
check("a single invocation parses to the harness tool action",
      isinstance(act, dict) and act.get("action") == "tool"
      and act.get("tool") == "shell" and act.get("args") == {"command": "ls -la /tmp"},
      str(act))

m = a._dsml_action(MULTI)
check("multiple parameters are captured",
      m.get("tool") == "fs.write"
      and m.get("args", {}).get("path") == "/tmp/a.txt"
      and m.get("args", {}).get("content") == "hello\nworld",
      str(m))
check("a string=\"false\" parameter is decoded from JSON",
      m.get("args", {}).get("lines") == 42, str(m.get("args")))

check("non-DSML text yields no action", a._dsml_action("plain prose") is None)
check("DSML with no invocation yields no action",
      a._dsml_action(OPEN + " calls>" + CLOSE + " calls>") is None)

# ---------------------------------------------- the Tool Tests dialect (JAG-526)
# Verbatim shapes from session 0e13bdb23c5b after a compaction: an EXTRA
# attribute on the invoke, the real tool name as the element TEXT, and a
# mismatched `</… parameter>` close. Every one of these used to return None and
# trigger the (wrong) "That JSON was invalid" retry.
REAL = (
    OPEN + " calls>\n"
    + OPEN + ' invoke name="tool" string="true">shell.exec</' + D + " parameter>\n"
    + OPEN + ' parameter name="args" string="true">{"command": "ls -la /tmp"}</' + D + " parameter>\n"
    + CLOSE + " invoke>\n"
    + CLOSE + " calls>"
)
REAL_EMPTY = (
    OPEN + " calls>\n"
    + OPEN + ' invoke name="tool" string="true">self.info</' + D + " parameter>\n"
    + OPEN + ' parameter name="args" string="true">{}</' + D + " parameter>\n"
    + CLOSE + " invoke>\n"
    + CLOSE + " calls>"
)
# An invocation with NO tool name at all is still unusable — but it must be
# recognised as DSML so the retry names the markup, not "invalid JSON".
NO_NAME = (
    OPEN + " invocation>\n"
    + OPEN + ' parameter name="cmd">ls -la</' + D + " parameter>\n"
    + CLOSE + " invocation>"
)
# The original meta envelope (tool name as a parameter) must keep working.
ENVELOPE = (
    OPEN + " calls>\n"
    + OPEN + ' invoke name="tool">\n'
    + OPEN + ' parameter name="tool">fs.read</' + D + " parameter>\n"
    + OPEN + ' parameter name="args">{"path": "/tmp/a"}</' + D + " parameter>\n"
    + CLOSE + " invoke>\n"
    + CLOSE + " calls>"
)
_real_want = {"action": "tool", "tool": "shell.exec",
              "args": {"command": "ls -la /tmp"}}
check("E1 extra invoke attributes + tool name as text parse",
      a._dsml_action(REAL) == _real_want, str(a._dsml_action(REAL)))
check("E2 the full pipeline resolves that markup (no JSON retry)",
      a._extract_action(REAL) == _real_want, str(a._extract_action(REAL)))
check("E3 an empty args object parses",
      a._dsml_action(REAL_EMPTY) == {"action": "tool", "tool": "self.info", "args": {}},
      str(a._dsml_action(REAL_EMPTY)))
check("E4 a nameless invocation is still DSML (truthful retry, not 'invalid JSON')",
      a._looks_like_dsml(NO_NAME) and a._dsml_action(NO_NAME) is None)
check("E5 the tool-parameter envelope still parses",
      a._dsml_action(ENVELOPE) == {"action": "tool", "tool": "fs.read",
                                   "args": {"path": "/tmp/a"}},
      str(a._dsml_action(ENVELOPE)))

# ----------------------------------------- Hermes XML tool-call dialect ----
_xml_action = {
    "action": "tool",
    "tool": "matrix.test",
    "args": {
        "target": "tool:toolcontract",
        "code": "from Matrix.tools import toolcontract\n"
                "r = toolcontract.audit({'scope':'all'})\n"
                "assert r['ok']",
    },
}
check("Hermes XML wrapper is detected as a tool call",
      a._looks_like_json_action(HERMES_TOOL_CALL))
check("Hermes XML wrapper parses its meta tool and JSON args",
      a._extract_action(HERMES_TOOL_CALL) == _xml_action,
      str(a._extract_action(HERMES_TOOL_CALL)))

# ------------------------------------------------- never leak to the user ----
check("DSML is never shown as a chat reply",
      a._looks_like_json_action(SAMPLE))
check("a normal prose answer still passes the guard",
      not a._looks_like_json_action("Here is the result you asked for."))

# ------------------------------------------ the parsed action is well-formed ----
# `_normalize_action` must leave the DSML-derived tool call untouched.
check("the parsed action survives _normalize_action unchanged",
      a._normalize_action(a._dsml_action(SAMPLE)) == act)

# ------------------------------- FULL pipeline (the trap that slipped) ----
# `extract_json` returns an EMPTY LIST on failure, NOT None — so chat_once must
# use a FALSY check to fall back to DSML. This regression is why the fix must be
# exercised end-to-end, not only `_dsml_action` in isolation.
check("_extract_action resolves a plain DSML answer (extract_json -> None)",
      a._extract_action(SAMPLE) == act, str(a._extract_action(SAMPLE)))
# The REAL-world shape: the command carries `{ }` so extract_json returns a FALSY
# non-None (an empty list/dict) — the exact case the `is None` check missed.
_br = a.extract_json(SAMPLE_BRACED)
check("a brace-carrying DSML answer makes extract_json falsy (not None)",
      (_br is not None) and (not _br), repr(_br))
check("_extract_action resolves it via the falsy-check fallback",
      (a._extract_action(SAMPLE_BRACED) or {}).get("tool") == "shell",
      str(a._extract_action(SAMPLE_BRACED)))
check("_extract_action still prefers a valid JSON action",
      a._extract_action('{"action":"tool","tool":"shell","args":{"command":"ls"}}')
      == {"action": "tool", "tool": "shell", "args": {"command": "ls"}})
check("_extract_action returns no action for plain prose",
      not a._extract_action("just a normal answer"))

# ---------------------------------------------- the drifting marker (JAG-534) ----
# Live session 18c103e0d9a1 (2026-10-23): the model switched to ONE bar per side
# (<｜DSML｜ calls>). The exact-string check missed it, `_extract_action` returned
# the JSON *inside* the markup, the chat showed the raw markup as the answer and
# the turn ended mid-work ("gli agenti muoiono").
ONE = "<\uff5cDSML\uff5c"
C1 = "</\uff5cDSML\uff5c"
SINGLE = (ONE + " calls>\n" + ONE + ' invoke name="todo.update">\n'
          + ONE + ' parameter name="steps" string="false">[{"id": "n1", "status": "doing"}]'
          + C1 + " parameter>\n" + C1 + " invoke>\n" + C1 + " calls>")
check("F1 a ONE-bar marker is detected", a._looks_like_dsml(SINGLE))
check("F2 one-bar markup is never shown as a chat reply",
      a._looks_like_json_action(SINGLE))
check("F3 one-bar todo.update becomes the harness action",
      a._extract_action(SINGLE) == {"action": "todo.update",
                                    "steps": [{"id": "n1", "status": "doing"}]},
      str(a._extract_action(SINGLE)))

# The Master session: the inner tags lost the marker entirely.
BARE = (OPEN + " calls>\n" + OPEN + ' invoke name="python.run">\n'
        + '<parameter name="code">print(1)</parameter>\n'
        + "</invoke>\n" + CLOSE + " calls>")
check("F4 bare <parameter>/</invoke> inside a marked block still parse",
      a._extract_action(BARE) == {"action": "tool", "tool": "python.run",
                                  "args": {"code": "print(1)"}},
      str(a._extract_action(BARE)))

# The model wrapped a HARNESS action in an invented `permission` envelope.
PERM = (OPEN + " calls>\n" + OPEN + ' invoke name="permission">bash' + CLOSE + " parameter>\n"
        + OPEN + ' parameter name="action">todo.update</' + D + " parameter>\n"
        + OPEN + ' parameter name="steps">[{"id": "n61", "status": "doing"}]</'
        + D + " parameter>\n" + CLOSE + " invoke>\n" + CLOSE + " calls>")
check("F5 an invented `permission` envelope unwraps to the harness action",
      a._extract_action(PERM) == {"action": "todo.update",
                                  "steps": [{"id": "n61", "status": "doing"}]},
      str(a._extract_action(PERM)))

# Arguments written as ATTRIBUTES of the invoke, no <parameter> children.
ATTR = (ONE + " calls>\n" + ONE
        + ' invoke name="skills" action="search" query="web sources">'
        + C1 + " invoke>\n" + C1 + " calls>")
check("F6 arguments written as invoke ATTRIBUTES are captured",
      a._extract_action(ATTR) == {"action": "tool", "tool": "skills",
                                  "args": {"action": "search", "query": "web sources"}},
      str(a._extract_action(ATTR)))

# Tool name as the element TEXT + a JSON `args` parameter carrying the payload.
TEXT_ARGS = (ONE + " calls>\n" + ONE + ' invoke name="action" string="true">shell.exec'
             + C1 + " parameter>\n" + ONE + ' parameter name="args" string="false">{"cmd": "ls"}'
             + C1 + " parameter>\n" + C1 + " invoke>\n" + C1 + " calls>")
check("F7 element-text tool name + JSON args parameter parse",
      a._extract_action(TEXT_ARGS) == {"action": "tool", "tool": "shell.exec",
                                       "args": {"cmd": "ls"}},
      str(a._extract_action(TEXT_ARGS)))

# The invocation body IS a full action JSON.
JSON_BODY = (OPEN + " calls>\n" + OPEN + ' invoke name="tool_call">\n'
             + '{"action": "tool", "tool": "shell.exec", "args": {"command": "ls"}}\n'
             + "</tool_call>")
check("F8 an invocation whose body is a JSON action is used as-is",
      a._extract_action(JSON_BODY) == {"action": "tool", "tool": "shell.exec",
                                       "args": {"command": "ls"}},
      str(a._extract_action(JSON_BODY)))

# No <invoke> at all: the action JSON follows the marker, or the parameters hang
# directly off <calls> (and `command` names the only tool that takes it).
NO_INVOKE_JSON = (OPEN + ' calls>[{"action": "todo.update", "steps": '
                  '[{"id": "n13", "status": "done", "evidence": "x"}]}]')
check("F9 a bare action JSON after the marker is used",
      a._extract_action(NO_INVOKE_JSON) == {"action": "todo.update",
                                            "steps": [{"id": "n13", "status": "done",
                                                       "evidence": "x"}]},
      str(a._extract_action(NO_INVOKE_JSON)))
NO_INVOKE_PARAMS = (OPEN + " calls>\n" + OPEN + ' parameter name="args" string="false">'
                    + '{"command": "ls -la"}' + CLOSE + ">\n" + CLOSE + " calls>")
check("F10 parameters without an <invoke> infer shell.exec from `command`",
      a._extract_action(NO_INVOKE_PARAMS) == {"action": "tool", "tool": "shell.exec",
                                              "args": {"command": "ls -la"}},
      str(a._extract_action(NO_INVOKE_PARAMS)))

# A string="false" value followed by the model's stray `"}}` still decodes.
JUNK = (OPEN + " calls>\n" + OPEN + ' parameter name="args" string="false">{"command": "ls"}"}}'
        + CLOSE + ">\n" + CLOSE + " calls>")
check("F11 trailing junk after a string=\"false\" value is ignored",
      a._extract_action(JUNK) == {"action": "tool", "tool": "shell.exec",
                                  "args": {"command": "ls"}},
      str(a._extract_action(JUNK)))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
