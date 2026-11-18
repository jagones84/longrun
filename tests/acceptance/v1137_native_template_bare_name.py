#!/usr/bin/env python3
"""v1137 — a native tool-call template whose NAME lost its tag is still a call.

Round 72. The live store held 63 replies the harness bounced with
"Your reply could not be executed"; the shipped parser (checked against the same
strings) would still reject 62 of them. 52 were one shape:

    <tool_call>shell.exec<arg_key>args</arg_key><arg_value>{"command": …}</arg_value></tool_call>

i.e. the model's native template with the `tool` pair's opening tag lost: the name
sits bare after `<tool_call>`, and `args` is the only pair the argkv reader sees.
Session `b7329cccf94c` burned 54 such nudges on it.

  A  the bare-name shape parses (prose prefix, `</arg_value>` terminator, harness
     action in the same envelope, separate arg keys, JSON-in-a-string args)
  B  it stays a PARSER, not a guess: an unknown name never executes, prose with no
     argument pair is not a call, and the two older dialects are unchanged
  C  `_extract_action` (the live entry point) uses it, and the name check reads the
     static schema table instead of spawning the MCP catalogue from the parse path

Deterministic: pure functions + a temporary data dir; no model, no network, no server.
Run: python3 tests/acceptance/v1137_native_template_bare_name.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1137-")
os.environ["LONGRUN_DATA_DIR"] = TMP
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: F401,E402 — breaks the agent<->server cycle
from longrun.agent import agent as A  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def act(text):
    return A._extract_action(text)


# --- A: the measured shape, and its neighbours -------------------------------
live = ('<tool_call>shell.exec<arg_key>args</arg_key>'
        '<arg_value>{"command": "cd /tmp && echo RC=$?"}</arg_value></tool_call>\n')
a1 = act(live)
check("A1 the bare-name shell.exec template is a tool call",
      isinstance(a1, dict) and a1.get("action") == "tool"
      and a1.get("tool") == "shell.exec", a1)
check("A2 its argument object survives",
      isinstance(a1, dict) and (a1.get("args") or {}).get("command") == "cd /tmp && echo RC=$?", a1)

a3 = act("Token errato (401): riscrivo la sonda." + live)
check("A3 a prose prefix does not hide the call",
      isinstance(a3, dict) and a3.get("tool") == "shell.exec", a3)

a4 = act('<tool_call>fs.write</arg_value><arg_key>args</arg_key>'
         '<arg_value>{"path": "/tmp/a", "content": "x"}</arg_value>')
check("A4 the `</arg_value>`-after-the-name variant parses too",
      isinstance(a4, dict) and a4.get("tool") == "fs.write"
      and (a4.get("args") or {}).get("content") == "x", a4)

a5 = act('<tool_call>todo.update<arg_key>args</arg_key>'
         '<arg_value>{"steps": [{"id": "n188", "status": "doing"}]}</arg_value></tool_call>')
check("A5 a HARNESS action in the same envelope keeps its payload",
      isinstance(a5, dict) and a5.get("action") == "todo.update"
      and (a5.get("steps") or [{}])[0].get("id") == "n188", a5)

a6 = act('<tool_call>fs.read<arg_key>path</arg_key><arg_value>/tmp/x</arg_value></tool_call>')
check("A6 separate arg keys become the arg object",
      isinstance(a6, dict) and a6.get("tool") == "fs.read"
      and (a6.get("args") or {}).get("path") == "/tmp/x", a6)

a7 = act('<tool_call>shell.exec<arg_key>args</arg_key>'
         '<arg_value>"{\\"command\\": \\"echo hi\\"}"</arg_value></tool_call>')
check("A7 args carried as a JSON STRING are decoded",
      isinstance(a7, dict) and (a7.get("args") or {}).get("command") == "echo hi", a7)

# --- B: it is a parser, not a guess -----------------------------------------
b1 = act('<tool_call>nonsense.word<arg_key>args</arg_key><arg_value>{"x": 1}</arg_value></tool_call>')
check("B1 a name the catalogue does not know is NOT executed", b1 is None, b1)
b2 = act("Just an idea: the tool <tool_call> we discussed, with <arg_value> prose.")
check("B2 prose without an argument pair is not a call", b2 is None, b2)
b3 = act('{"action":"tool","tool":"fs.read","args":{"path":"/tmp/x"}}')
check("B3 the shipped JSON envelope still parses",
      isinstance(b3, dict) and b3.get("tool") == "fs.read", b3)
b4 = act('<tool_call>action</arg_key><arg_value>tool</arg_value>'
         '<arg_key>tool</arg_key><arg_value>fs.read</arg_value>'
         '<arg_key>args</arg_key><arg_value>{"path":"/tmp/x"}</arg_value>')
check("B4 the 2026-11-14 tool+args dialect still parses",
      isinstance(b4, dict) and b4.get("tool") == "fs.read", b4)
b5 = act("plain prose, no markup at all")
check("B5 plain prose is never an action", b5 is None, b5)
b6 = act('<tool_call>shell.exec<arg_key>args</arg_key><arg_value>{"command": "a"}</arg_value></tool_call>'
         '<tool_call>fs.read<arg_key>args</arg_key><arg_value>{"path": "/tmp/x"}</arg_value></tool_call>')
check("B6 a two-call reply is not merged into one guessed call",
      not (isinstance(b6, dict) and b6.get("tool") == "shell.exec"), b6)

# --- C: the live entry point, and the name check's cost ---------------------
check("C1 _extract_action (what the loop calls) accepts the live shape",
      isinstance(act(live), dict))
check("C2 a built-in name is known, a made-up one is not",
      A._known_tool_name("fs.write") and A._known_tool_name("shell.exec")
      and not A._known_tool_name("nonsense.word"))
src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
fn = src[src.find("def _known_tool_name"):src.find("def _argkv_action")]
check("C3 the name check reads the static schema table (no MCP spawn in the parse path)",
      "_reg.TOOL_SCHEMAS" in fn and "_reg.tool_spec" not in fn, fn[:200])

print("\n---\nv1137: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
