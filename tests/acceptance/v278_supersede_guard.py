#!/usr/bin/env python3
"""v278 — a 'superseded' must be JUSTIFIED; unrecognized actions are coerced.

JAG-278 root cause (live session 86f0cfb0d728): the model force-closed 5 OPEN steps
as 'superseded' with reasons that actually said the work was STILL open ("il lavoro
resta aperto") — a bogus justification for "eating" tasks. And 61 turns were wasted
on the opaque "not a valid tool call" retry because the model emitted an action the
harness did not recognise.

Locked here:
  * a 'superseded' reason that reads as still-pending is REJECTED;
  * a specific abandonment reason is accepted;
  * an unknown action NAME with a recognizable payload is coerced by SHAPE;
  * an OpenAI-style function call is normalised to a tool call;
  * a made-up "I am done" envelope is detected (and handled as prose by the loop);
  * the retry now NAMES the emitted action so it is diagnosable and teachable;
  * the chat card + node detail show the close reason.

Deterministic, no live server. Run: python3 tests/v278_supersede_guard.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v278-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import taskgraph as TG   # noqa: E402
from longrun.core import server as S       # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- 1) 'superseded' must justify the abandonment -----------------------------
g = TG.ensure("s1", session_id="s1")
n = TG.add_node(g, "alpha")


def _rejected(reason):
    try:
        TG.update_node(TG.load("s1"), n["id"], status="superseded", reason=reason)
        return False
    except ValueError:
        return True


check("a blank reason is rejected", _rejected("   "))
check("a 'still-open' reason (IT) is rejected", _rejected("il lavoro resta aperto"))
check("a 'still-open' reason (EN) is rejected", _rejected("the work remains open for later"))
check("a reason that says the list is not done is rejected", _rejected("non completato"))
_no = TG.update_node(TG.load("s1"), n["id"], status="superseded",
                     reason="obsolete: the request was dropped by the user")
check("a specific abandonment reason is accepted", _no["status"] == "superseded")
check("the accepted reason is stored", _no.get("reason", "").startswith("obsolete"))

# --- 2) normalisation of unrecognized actions ---------------------------------
_nm = S._normalize_action
check("unknown action name + steps payload -> update_todos",
      _nm({"action": "update", "steps": [{"id": "n1", "status": "done"}]})
      == {"action": "update_todos", "steps": [{"id": "n1", "status": "done"}]})
check("unknown action name + todos payload -> write_todos",
      _nm({"action": "set_todos", "todos": [{"label": "a"}]})
      == {"action": "write_todos", "todos": [{"label": "a"}]})
check("OpenAI function-call shape -> tool call",
      _nm({"name": "shell", "arguments": "{\"command\": \"ls\"}"})
      == {"action": "tool", "tool": "shell", "args": {"command": "ls"}})
check("tool envelope with 'name' instead of 'tool' -> tool call",
      _nm({"action": "tool", "name": "web", "args": {"query": "x"}})
      == {"action": "tool", "tool": "web", "args": {"query": "x"}})
check("a real tool call is still left unchanged",
      _nm({"action": "tool", "tool": "bash", "args": {"cmd": "ls"}})
      == {"action": "tool", "tool": "bash", "args": {"cmd": "ls"}})

# --- 3) a made-up "I am done" envelope ----------------------------------------
check("_term_action recognises answer/finish/done",
      S._term_action({"action": "answer"}) and S._term_action({"action": "finish"})
      and S._term_action({"action": "Done"}))
check("_term_action rejects a real tool name", not S._term_action({"action": "shell"}))
check("_term_action rejects a harness action", not S._term_action({"action": "update_todos"}))

# --- 4) the retry NAMES the emitted action + the UI shows the reason ----------
with open(os.path.join(REPO, "src", "longrun", "core/server.py"), encoding="utf-8") as f:
    srv = f.read()
with open(os.path.join(REPO, "src", "longrun", "agent/agent.py"), encoding="utf-8") as f:
    srv += f.read()
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    ui = f.read()
check("the retry message names the emitted action", "You emitted:" in srv)
check("the chat card renders the close reason", ".tcreason" in ui)
check("the node detail renders the reason", "reason:" in ui)
check("the policy forbids a still-open 'superseded' reason",
      "remains open" in S.TASK_POLICY and "REJECTED" in S.TASK_POLICY)

# --- 5) composer + context panel (JAG-278 UI) ---------------------------------
check("the context panel keeps %/bar/state on one row (compact moved above the donut)",
      'class="ctxhead"' in ui and "ctxbig" not in ui)
check("the compact action sits directly above the context breakdown",
      ui.index('id="compactBtn"') < ui.index('id="ctxCats"'))
check("the model picker moved OUT of the header into the composer",
      ui.index('id="model-btn"') > ui.index('<div id="composerBar">'))
check("the composer has a + attach menu",
      'id="plusMenu"' in ui and "function togglePlus" in ui)
check("attachments render as chips + are built into a block",
      'id="attachRow"' in ui and "function _attachBlock" in ui)
check("attachments are prepended to the sent message", "msg = _attBlock" in ui)
check("voice input uses the Web Speech API (no server dependency)",
      "webkitSpeechRecognition" in ui and "function micToggle" in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

