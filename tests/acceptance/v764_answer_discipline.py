#!/usr/bin/env python3
"""v764 — the ANSWER is a value, and a REJECTION is a contract (2026-11-01).

Three defects found by reading the GAIA transcripts of the sandbox arms, all of them
in the harness rather than in the model:

  T  `strip_think` matched the LITERAL `<think>` only, so the routed model's real
     markup (`<think signature="reasoning-details://…">`) reached the answer
     surface and the graded answer became the whole thinking block.
  R  an invalid action was rejected with no tool name and no schema, so the model
     guessed `{"action":"web"}`, `{"action":"http"}`, `{"action":"browser"}` in a
     row instead of reading the registry.
  N  a failed tool told the model to "say plainly in your answer WHAT failed",
     which turned a finished answer (`17`) into `17 Note: all network lookups…`.
  E  a factual question could be closed with ZERO tool calls: `5d0080cb` was
     answered from memory (`2.4`, golden `0.1777`) while the same question, when
     the model chose to look, was solved by web.search → web.fetch.
  S  the keyless search engine every sandboxed arm depends on returned nothing.

Deterministic: no live model, no network, no server.
Run: python3 tests/acceptance/v764_answer_discipline.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v764-")
os.environ.setdefault("LONGRUN_DATA_DIR", os.path.join(TMP, "data"))
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(TMP, "cfg"))
os.environ.setdefault("LONGRUN_DB", os.path.join(TMP, "events.db"))
os.environ.setdefault("LONGRUN_SESSIONS_DIR", os.path.join(TMP, "sessions"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util.textkit import strip_think                       # noqa: E402
# `agent` imports `core.server` at module scope, and `core.server` imports names
# BACK from `agent`: importing the agent first is a circular import. Load the
# server first, the way every other acceptance test does.
from longrun.core import server as _server                        # noqa: E402,F401
from longrun.agent import agent as A                               # noqa: E402
from longrun.tools import registry                                 # noqa: E402

registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --------------------- T. reasoning markup, whatever the model calls it ----
clean, think = strip_think('4')
check("T1 plain text is untouched", clean == "4" and think is None, (clean, think))

_signed = ('<think signature="reasoning-details://[{&quot;type&quot;: '
           '&quot;reasoning.text&quot;}]">\nThe answer must be just the number.\n</think>'
           '\n\n3')
clean, think = strip_think(_signed)
check("T2 a SIGNED think block is stripped and kept as reasoning",
      clean.strip() == "3" and "just the number" in (think or ""), (clean, think))

clean, _ = strip_think("a <THINKING>hmm</THINKING> b")
check("T3 case and the `thinking` spelling are stripped", clean.strip() == "a  b", clean)

clean, think = strip_think("<think>one</think>X<think>two</think>")
check("T4 every block is stripped, not just the first",
      clean == "X" and "one" in (think or "") and "two" in (think or ""), (clean, think))

clean, _ = strip_think("<think signature='x'>unclosed body 7")
check("T5 an unclosed tag is dropped but its body survives (never lose the answer)",
      "<think" not in clean and "7" in clean, clean)

clean, _ = strip_think('<reasoning>r</reasoning> 42')
check("T6 the `reasoning` spelling is stripped", clean.strip() == "42", clean)

# ------------------- R. a rejection names the way out (no blind guessing) ----
note = A._invalid_action_note({"action": "web"})
check("R1 a bad action names the tools it probably meant",
      "web.search" in note or "web.fetch" in note, note[:200])
check("R2 the rejection points at the QUERY and the SCHEMA lookup",
      'self.tools {query:' in note and 'self.tools {tool:' in note, note[-220:])
check("R3 it still states the three valid shapes",
      '"action":"tool"' in note and "todo.write" in note and "plain prose" in note)
check("R4 it echoes what the model emitted",
      '"action": "web"' in note or '"action":"web"' in note, note[:120])
_bare = A._invalid_action_note(None, "I will now do it")
check("R5 a non-dict rejection never raises and still teaches",
      "That was not a valid action" in _bare and "self.tools" in _bare, _bare[:120])
_miss = A._tool_near_misses("fs.raed")
check("R6 a MISSPELLED tool name resolves to its real neighbours",
      any(n.startswith("fs.") for n in _miss), _miss)

# ------------------ N. the final answer never carries the diagnostics ----
_src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("N1 the failed-tool note no longer invites a failure report in the answer",
      "say plainly in your answer" not in _src)
check("N2 it says where the disclosure belongs and that the answer stays the answer",
      "record WHAT failed" in _src and "never a failure report appended" in _src)

# --------------------- the prompt carries no member catalogue --------------
from longrun.core import api_v02  # noqa: E402

_tctx = api_v02.tool_context()
check("P1 the prompt maps namespaces with counts and no `ns{a,b}` member list",
      "fs(" in _tctx and "fs{" not in _tctx, len(_tctx))
check("P2 the prompt teaches list / search / schema, in that order",
      "self.tools {}" in _tctx and 'self.tools {query:' in _tctx
      and 'self.tools {tool:' in _tctx)
# A value wrapped in a sentence is not the value (2026-11-01: "…are: X (2005),
# Y (2009) and Z (2009)." to a "how many" question — right reasoning, unusable
# answer). The rule lives in the system prompt because the shape of the answer
# belongs to the request.
check("P3 the system prompt fixes the answer SHAPE for a fact question",
      "the answer IS the value" in A.SYSTEM_PROMPT
      and "Explain only when an explanation was asked for" in A.SYSTEM_PROMPT)

# -------- X. the harness acts on the action the model MEANT, not a quotation ----
# Measured 2026-11-01 on GAIA `5d0080cb`: the model's message quoted the action it had
# been accused of ("… not {"tool":"todo.update"} …") and put the REAL action last;
# `extract_json` returned the quotation, so the harness rejected the correct call four
# times in a row and the plan never closed.
from longrun.util.textkit import extract_json, extract_action_json   # noqa: E402

_quoted = ('Strange, I emitted {"tool":"todo.update"} before; now the real one:\n'
           '{"action":"todo.update","steps":[{"id":"n1","status":"done"}]}')
_a = extract_action_json(_quoted)
check("X1 the LAST action-shaped object wins over a quoted one",
      isinstance(_a, dict) and _a.get("action") == "todo.update"
      and _a.get("steps"), _a)
check("X2 extract_json still returns the FIRST object (the two are not the same job)",
      (extract_json(_quoted) or {}).get("tool") == "todo.update")

_act = A._normalize_action({"tool": "todo.update", "args": {"steps": [{"id": "n1"}]}})
check("X3 a harness action inside the tool envelope is coerced, not rejected",
      _act.get("action") == "todo.update" and _act.get("steps"), _act)

_batch_note = A._batch_note if hasattr(A, "_batch_note") else None
_src_batch = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
                  encoding="utf-8").read()
check("X4 a batch item that is a harness action says which rule it broke",
      "TOP-LEVEL harness action, not a tool" in _src_batch)

# ---- Y/Z. a turn never hands back nothing or an envelope, and discovery is small ----
check("Y1 the reply is sanitised when the turn stops on an action or on nothing",
      "The turn ended before a final answer" in _src
      and "The turn ended without producing an answer." in _src)
_oc = open(os.path.join(REPO, "benchmarks", "inspect_sandbox", "openclaw_turn.sh"),
           encoding="utf-8").read()
check("Y2 the openclaw turn carries an explicit timeout budget",
      '"timeoutSeconds": _budget' in _oc and '"timeoutSeconds": _budget, "model"' in _oc)

from longrun.tools import diag                                        # noqa: E402

_big = diag.tools_report(query="web search fetch page read write run file")
check("Z1 a broad query is CAPPED (a 27 kB discovery answer is not a search)",
      len(_big.get("tools") or {}) <= diag.TOOL_QUERY_LIMIT and _big.get("capped"),
      len(_big.get("tools") or {}))
check("Z2 every listed description is trimmed to one line",
      all(len(v.get("description") or "") <= diag.TOOL_DESC_CHARS + 1
          for v in (_big.get("tools") or {}).values()))

# ---- E. a fact is never closed on a guess (premature-answer guard) ----
# Measured 2026-11-01 on GAIA: `5d0080cb` was answered in 2 turns from memory
# (wrong), while the SAME question, when the model chose to look, was solved by
# `web.search` → `web.fetch`. The capability existed; the trigger did not.
check("E1 a factual question needs evidence",
      A._needs_evidence("What year was the first transistor invented?"))
check("E2 an imperative does not (the harness can see the work already)",
      not A._needs_evidence("fix the typo in the README"))
check("E3 a bare greeting does not",
      not A._needs_evidence("ciao"))
check("E4 a 'how many' request does",
      A._needs_evidence("how many rows does the CSV have"))
_ev = A._evidence_gate_text()
check("E5 the gate names BOTH ways out, forbids a guess, and asks for no narration",
      "web.search" in _ev and "cannot be checked" in _ev
      and "never a sentence about where it came from" in _ev
      and "say so in ONE line" not in _ev, _ev[:160])
check("E6 the gate is a MECHANICAL check wired on all three close paths",
      _src.count("_needs_evidence(message)") == 3
      and "_evidence_used = False" in _src, _src.count("_needs_evidence(message)"))
# Measured 2026-11-01 (GAIA `ec09fa32`): ONE turn, 33k tokens, an EMPTY reply — the
# model spent the whole message on its reasoning block and the harness persisted the
# empty string as the answer. An empty message is never an answer.
check("E7 an empty model message is retried (bounded), never accepted",
      "Your last message was EMPTY" in _src and "_empty_streak <= 2" in _src)
# Measured 2026-11-01 (GAIA `8e867cd7`): the tool call was written INSIDE the signed
# reasoning block and the visible part was a promise, so the harness dropped the action,
# saw "nothing open" and closed the turn mid-work.
_hidden = ('<think signature="reasoning-details://[]">\n'
           '{"action":"tool","tool":"shell.exec","args":{"command":"curl -s x"}}\n'
           '</think>\nThe wikitext is truncated. Let me curl it directly.')
_c2, _t2 = strip_think(_hidden)
check("E8 an action hidden in the reasoning block is DETECTED",
      A._reasoning_only_action(_c2, _t2), (_c2[:60], (_t2 or "")[:60]))
check("E9 a normal action in the message is not flagged",
      not A._reasoning_only_action('{"action":"tool","tool":"fs.read","args":{}}',
                                   "just thinking"))

# ---- S. a keyless search must return real, followable URLs ----
# Measured 2026-11-01: DuckDuckGo's html and lite endpoints answer every query with
# a 14 kB bot page, and the GAIA sandbox has no Tavily/Brave key — so the only path
# `web.search` had there returned nothing at all.
from longrun.tools import tools as T                                    # noqa: E402

_BING_FEED = (
    '<?xml version="1.0" encoding="utf-8" ?><rss version="2.0"><channel>'
    '<title>Bing: Ada Lovelace</title>'
    '<link>http://www.bing.com:80/search?q=Ada+Lovelace</link>'
    '<item><title>Ada Lovelace - Wikipedia</title>'
    '<link>https://en.wikipedia.org/wiki/Ada_Lovelace</link>'
    '<description>Augusta Ada King, Countess of Lovelace, was an English '
    'mathematician.</description></item>'
    '<item><title>not a result</title><link>/relative/path</link></item>'
    '</channel></rss>')
_hits = T._parse_bing_rss(_BING_FEED, 5)
check("S1 the RSS parser yields a title + a real url + a snippet",
      len(_hits) == 1 and _hits[0]["url"] == "https://en.wikipedia.org/wiki/Ada_Lovelace"
      and "mathematician" in _hits[0]["snippet"], _hits)
_src_tools = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"),
                  encoding="utf-8").read()
check("S2 bing is the LAST resort of the chain, whatever the config order",
      'order.append("bing")' in _src_tools
      and '"bing": (_search_bing, "bing")' in _src_tools)

print("---")
okc = sum(results)
print("\nv764: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
