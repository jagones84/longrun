#!/usr/bin/env python3
"""v1138 — a rejected reply names the break the model can fix.

Round 73. The store held 63 replies bounced with "Your reply could not be
executed" and the generic note left the model repeating the same shape (54 nudges
in session b7329cccf94c). Nine were action-shaped JSON the parser could not read;
two breaks are provable from the text alone:

  · a trailing comma before `}` / `]`   — live: `{"action":"shell.exec","args":{…},}`
  · a payload cut before its block/list closes — live: a `steps` list left open

and the transport already records `finish_reason`, so a reply cut at the model's
output limit can say THAT and ask for a smaller call.

  A  the note names the break it can prove (comma, open block, open list)
  B  it does not invent a break: well-formed JSON, prose and the default path keep
     their old wording; the misplaced-name hint still rides along
  C  `finish_reason=length` dominates and asks for a SMALLER call; the live call
     site passes it

Deterministic: pure functions + a temporary data dir; no model, no network, no server.
Run: python3 tests/acceptance/v1138_rejection_names_the_break.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1138-")
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


# --- A: the breaks it can prove ---------------------------------------------
comma = '{"action":"shell.exec","args":{"command":"ls"},}'
check("A1 a trailing comma is named",
      "trailing comma" in A._json_break(comma), A._json_break(comma))
open_list = ('{"action":"todo.update","steps":[{"id":"n2","status":"done",'
             '"evidence":"polls 1-4 identical on purpose"}}')
check("A2 a list left open is named",
      "list is still open" in (A._json_break(open_list) or ""), A._json_break(open_list))
open_block = '{"action":"tool","tool":"fs.write","args":{"path":"/tmp/a"'
check("A3 a block left open is named",
      "still open" in (A._json_break(open_block) or ""), A._json_break(open_block))

n1 = A._rejected_reply_note(comma)
check("A4 the retry carries the break and still quotes the reply",
      "That JSON is not valid" in n1 and "trailing comma" in n1
      and "It was:" in n1 and "shell.exec" in n1, n1)
n2 = A._rejected_reply_note(open_list)
check("A5 the open-list reply gets its own sentence",
      "list is still open" in n2, n2)

# --- B: it does not invent a break ------------------------------------------
check("B1 well-formed JSON is not called broken",
      A._json_break('{"action":"todo.update","steps":[]}') is None)
check("B2 prose is not called broken",
      A._json_break("plain prose with a { brace") is None)
n3 = A._rejected_reply_note('{"foo": 1}')
check("B3 a well-formed object keeps the old, break-free note",
      "That JSON is not valid" not in n3 and "It was:" in n3, n3)
n4 = A._rejected_reply_note('{"action":"tool","shell.exec","args":{}}')
check("B4 the misplaced-name hint still rides along",
      "KEY" in n4 and '"tool":"<name>"' in n4, n4)

# --- C: the output-limit cut dominates --------------------------------------
n5 = A._rejected_reply_note(open_list, finish_reason="length")
check("C1 a length cut says the reply was CUT",
      "CUT at the model's output limit" in n5, n5)
check("C2 and asks for a SMALLER call, not a JSON lesson",
      "SMALLER call" in n5 and "That JSON is not valid" not in n5, n5)
n6 = A._rejected_reply_note(open_list, finish_reason="stop")
check("C3 any other finish reason keeps the structural sentence",
      "list is still open" in n6 and "CUT at" not in n6, n6)

src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("C4 the live call site passes the transport's finish reason",
      '(chat_usage or {}).get("finish_reason")' in src
      and "_rejected_reply_note(\n                answer," in src)

print("\n---\nv1138: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
