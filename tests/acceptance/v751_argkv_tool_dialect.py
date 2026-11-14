#!/usr/bin/env python3
"""v751 — the native `<arg_key>/<arg_value>` tool-call dialect is parsed, not dropped.

Measured 2026-10-31 on the JobBench bookkeeping task (session cfbf25499a77):
glm-5.3-flash emitted its own template instead of the harness JSON. Every such
turn was "not a valid action", the invalid streak hit its cap, and the turn closed
with `no_valid_action` and 0 delivered files (0/88, previous run 10/88). The
dialect carries the whole call, so the parser has to read it.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v751-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agent                # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# The exact bytes from session cfbf25499a77 (first key lost its opening tag).
READ = ('<tool_call>action</arg_key><arg_value>tool</arg_value><arg_key>tool</arg_key>'
        '<arg_value>fs.read</arg_value><arg_key>args</arg_key>'
        '<arg_value>{"path": "/home/jagones/.longrun/data/offload/cfbf25499a77/002.txt"}'
        '</arg_value></tool_call>')

act = agent._extract_action(READ)
check("A1 the dialect resolves to a tool action",
      isinstance(act, dict) and act.get("action") == "tool", act)
check("A2 the tool name is read", (act or {}).get("tool") == "fs.read", act)
check("A3 the JSON args are decoded, not left as text",
      isinstance((act or {}).get("args"), dict)
      and (act or {}).get("args", {}).get("path", "").endswith("002.txt"), act)

CMD = ('<tool_call>action</arg_key><arg_value>tool</arg_value><arg_key>tool</arg_key>'
       '<arg_value>shell.exec</arg_value><arg_key>args</arg_key>'
       '<arg_value>{"cmd": "grep -v MATCH /tmp/x.txt | head -60"}</arg_value></tool_call>')
act2 = agent._extract_action(CMD)
check("A4 a shell command survives the pipe characters",
      (act2 or {}).get("args", {}).get("cmd", "").startswith("grep -v MATCH"), act2)

# A harness action in the same dialect keeps its fields.
TODO = ('<tool_call>action</arg_key><arg_value>todo.update</arg_value>'
        '<arg_key>steps</arg_key><arg_value>[{"id":"n3","status":"done"}]</arg_value>'
        '</tool_call>')
act3 = agent._extract_action(TODO)
check("A5 a harness action in the dialect keeps its payload",
      isinstance(act3, dict) and act3.get("action") == "todo.update"
      and isinstance(act3.get("steps"), list), act3)

check("A6 the dialect is machine text, never chat prose",
      agent._looks_like_json_action(READ) is True)
check("A7 ordinary prose does not match", agent._argkv_action("I read the file.") is None)
check("A8 a half-written key is not an action",
      agent._extract_action("<arg_value>nothing</arg_value>") is None)

# Live 2026-11-14 (session b7329cccf94c): glm-5.3-flash dropped the `action` pair
# entirely and wrote its name bare after `<tool_call>` — the k/v pairs carry
# `tool`+`args` with NO `action` key. The whole call was rejected ("Your reply
# could not be executed", ~25 retries) and the turn ended on `budget` with 5 of
# its 8 steps open. A `tool` pair IS the call.
LIVE = ('<tool_call>action\n<arg_key>tool</arg_key>\n<arg_value>fs.read</arg_value>\n'
        '<arg_key>args</arg_key>\n'
        '<arg_value>{"path": "src/Matrix/memory/hooks.py"}</arg_value>\n</tool_call>')
act_live = agent._extract_action(LIVE)
check("A9 the live bare-`action` dialect resolves to a tool action",
      isinstance(act_live, dict) and act_live.get("action") == "tool", act_live)
check("A10 the live dialect's tool name is read",
      (act_live or {}).get("tool") == "fs.read", act_live)
check("A11 the live dialect's JSON args are decoded, not left as text",
      isinstance((act_live or {}).get("args"), dict)
      and (act_live or {}).get("args", {}).get("path", "").endswith("hooks.py"), act_live)
LIVE2 = ('<tool_call>action\n<arg_key>tool</arg_key>\n<arg_value>matrix.status</arg_value>\n'
         '<arg_key>args</arg_key>\n<arg_value>{}</arg_value>\n</tool_call>')
check("A12 an empty-args live dialect still resolves",
      (agent._extract_action(LIVE2) or {}).get("tool") == "matrix.status",
      agent._extract_action(LIVE2))
# The tool fallback must NOT hijack a call that names a real action.
MIXED = ('<tool_call>action</arg_key><arg_value>todo.update</arg_value>'
         '<arg_key>tool</arg_key><arg_value>fs.read</arg_value>'
         '<arg_key>steps</arg_key><arg_value>[{"id":"n1","status":"done"}]</arg_value>'
         '</tool_call>')
check("A13 an explicit action pair is never re-labelled as a tool call",
      (agent._extract_action(MIXED) or {}).get("action") == "todo.update",
      agent._extract_action(MIXED))

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
