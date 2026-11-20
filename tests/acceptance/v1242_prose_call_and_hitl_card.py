#!/usr/bin/env python3
"""v1242 — a prose-prefixed, raw-newline tool call RUNS (never leaks), and the
`human.ask` call is a real, PERSISTED tool card in the chat.

Operator, 2026-11-20 (Master session `5033e643711a`): a turn ended as
`user_pivot` with the model's raw JSON painted in the chat as the reply —

    Vado avanti da solo. Provo i mount bypass…
    {"action":"tool","tool":"python.run","args":{"code":"import subprocess, os
     pw=open(os.path.expanduser('~/.openclaw/credentials/termux.pass'))…"}}

The call carried RAW NEWLINES inside its `code` string (technically invalid
JSON), so `_extract_action` returned None; and because the message did not START
with `{`, the machine-text guard never fired either — so the raw call was
persisted as the turn's answer and the turn stopped as `user_pivot`. Two defects:

  A  a JSON object with raw control characters inside a string is now REPAIRED
     (the control chars escaped) and re-parsed, so the model's call RUNS instead
     of being silently dropped (`textkit._escape_control_chars`)
  B  a call-shaped JSON ANYWHERE in the message is machine text — prose before it
     no longer makes it a reply, so an unparseable call can never leak
     (`agent._looks_like_json_action` no longer requires `startswith`)
  C  `human.ask` — the agent's ONE door to the operator — publishes the SAME inline
     tool card as every other tool and PERSISTS it, so the call appears and remains
     in the chat history (it used to fire only `hitl.request`)

Deterministic and offline: temp dirs, a scripted model, no network.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v1242-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
for d in ("cfg", "sessions", "graphs", "data"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}

from longrun.core import server  # noqa: E402
from longrun.agent import agent as A  # noqa: E402
from longrun.util import textkit as TK  # noqa: E402

SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
           encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# The exact shape the operator's session leaked: prose, then a call whose `code`
# value holds REAL newlines (not `\n`).
LEAK = ('Vado avanti da solo. Provo i mount bypass che aggirano il filtro dello '
        'scoped storage.\n\n'
        '{"action":"tool","tool":"python.run","args":{"code":"import subprocess, os\n'
        "pw=open('x').read().strip()\nprint('-'*40)\n\"}}")

# ---- A: the raw-control-char repair ----------------------------------------
check("A1 a raw newline inside a string is escaped",
      json.loads(TK._escape_control_chars('{"c":"a\nb"}')) == {"c": "a\nb"},
      TK._escape_control_chars('{"c":"a\nb"}'))
check("A2 extract_action_json parses the prose+raw-newline call",
      (TK.extract_action_json(LEAK) or {}).get("tool") == "python.run",
      TK.extract_action_json(LEAK))
check("A3 the agent extracts it as an ACTION (so the call RUNS)",
      (A._extract_action(LEAK) or {}).get("tool") == "python.run",
      A._extract_action(LEAK))
check("A4 its argument survives the repair",
      "import subprocess" in str((A._extract_action(LEAK) or {}).get("args", {}).get("code", "")),
      A._extract_action(LEAK))

# ---- B: the leak guard (machine text is never a reply) ----------------------
check("B1 a prose-prefixed call is machine text, not an answer",
      A._looks_like_json_action(LEAK) is True)
check("B2 a call the parser still cannot read is STILL caught by the guard",
      A._looks_like_json_action('Fatto.\n{"action":"tool","tool":"x","args":{"a":') is True)
check("B3 plain prose is NOT machine text",
      A._looks_like_json_action("Ho finito: il file e' stato scritto e il test passa.")
      is False)
check("B4 native markup is still machine text (unchanged)",
      A._looks_like_json_action('<|DSML| invoke name="x">') is True)

# ---- C: human.ask is a real, persisted tool card ---------------------------
ASK = ('{"action":"tool","tool":"human.ask",'
       '"args":{"question":"Which region should I upload to?",'
       '"options":["the first one"]}}')


def run_turn(sid, script):
    state = {"n": 0}

    def fake_stream(msgs, model, role, on_delta, usage=None, cancel=None, **kw):
        text = script(state["n"])
        state["n"] += 1
        on_delta("answer", text)
        return text, "", model

    events = []
    server.stream_with_fallback = fake_stream
    server.api_v02.gated_call = lambda tool, args, **kw: {
        "status": "executed", "observation": "", "result": {}}
    server.chat_once({"id": sid, "messages": [], "workspace": ""}, "go", model="mock",
                     on_delta=lambda c, t: None,
                     on_event=lambda kind, **d: events.append((kind, d)))
    return events


ev = run_turn("v1242hitl", lambda n: ASK)
_calls = [d for k, d in ev if k == "tool.call" and d.get("tool") == "human.ask"]
_res = [d for k, d in ev if k == "tool.result" and d.get("tool") == "human.ask"]
_hitl = [d for k, d in ev if k == "hitl.request"]
check("C1 the human.ask call is published as a tool card", len(_calls) == 1, _calls)
check("C2 the result event closes the card (not left pending)", len(_res) == 1, _res)
check("C3 the decision form still fires — card AND form, not one", len(_hitl) == 1, _hitl)
sess = server.load_session("v1242hitl") or {}
_cards = [c for c in (sess.get("tool_cards") or []) if c.get("tool") == "human.ask"]
check("C4 the call card is PERSISTED (a reload rebuilds it)", len(_cards) == 1,
      [c.get("tool") for c in (sess.get("tool_cards") or [])])
check("C5 the card carries the model's own question",
      _cards and "Which region" in str(_cards[0].get("result", "")),
      _cards)
check("C6 the branch is wired for human.ask (source pin)",
      'tool="human.ask"' in SRC and 'persist_tool_card(sess, "human.ask"' in SRC)

print("\n---")
print("v1242: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
