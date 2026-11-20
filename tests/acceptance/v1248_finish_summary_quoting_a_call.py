#!/usr/bin/env python3
"""v1248 — an explicit finish summary that QUOTES a call is an ANSWER, not an action.

Operator (2026-11-21): *"why stopped this way? I don't want agents stopping
unexpectedly, I told many times it is one of the worst failure modes."* — the chat
showed `The turn ended before a final answer: the last message was still an action
(Commit 83bf8e39 live-surface brief: PASS. …)` although the agent HAD answered.

Measured live (session b7329cccf94c, run 4071053→4071054): the model closed with
`{"action":"finish","summary":"…"}`; the summary — a real, complete report — quoted the
tool call inside SINGLE quotes:

  Item 4 executed: the exact sentence 'The harness once executed the quotation
  POST /api/tools/call {"tool":"fs.read"} and it was denied.' was quoted in my reply …

`_looks_like_json_action` is a CONTAINS test (since the 2026-11-21 A8 fix), so the
whole summary was judged machine text and the live persist path replaced it with the
"ended before a final answer" sentence — even though `stores.turn_reply` (reload) shows
the finish summary (D5). One turn, two answers.

One rule, extended by measurement: a JSON value inside a QUOTATION is prose — inline
code spans AND well-formed `'…'` spans (`textkit.quotation_ranges`). Over 2148 live
assistant messages the extension changes the selected action in 2 and both are phantom
picks (a shell `-d '{…}'` argument, a payload dump); no real emission is hidden.

  A  the live summary is no longer machine text (the defect, verbatim)
  B  the killed sentence is gone: a finished turn keeps its own answer
  C  an apostrophe is not a quote (don't / agents' never opens a span)
  D  a REAL emission is untouched: bare call, ```json fence, prose+raw call
  E  the quoted mention is not executed either (extract_action_json skips it)
  F  the two readers agree: quotation_ranges is what both consult

Deterministic and offline: pure text layers only.
Run: python3 tests/acceptance/v1248_finish_summary_quoting_a_call.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _srv  # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agent as A  # noqa: E402
from longrun.util import textkit as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# The exact summary the model produced (chat.delta `answer`, event 4071053).
SUMMARY = (
    "Commit 83bf8e39 live-surface brief: PASS. HEAD confirmed 83bf8e39 (git rev-parse), "
    "service restart Fri 2026-11-20 21:51:28 CET (systemctl ActiveEnterTimestamp) — match "
    "the brief, no stale process. Item 4 executed: the exact sentence 'The harness once "
    "executed the quotation POST /api/tools/call {\"tool\":\"fs.read\"} and it was denied.' "
    "was quoted in my reply INSIDE inline backticks, followed only by a plain-prose PASS "
    "verdict — no action emitted after it. Deliverable written and re-read this turn: "
    ".agent/trash/2026-11-21_A54_verify_83bf8e39_inline_masking.md (1245 B; the harness "
    "read-back claiming no file exists was stale — fs.read returned its full content). "
    "Expected: this close produces NO 'CALL BLOCKED (repeat #N)', NO failed-call row, NO "
    "citation-check row; if any such row appears after this turn, that is the RED finding, "
    "not this reply. No restart, no battery (not requested)."
)
KILLED = "The turn ended before a final answer"

# --- A/B: the defect, verbatim ---------------------------------------------
check("A1 the live finish summary is not machine text any more",
      A._looks_like_json_action(SUMMARY) is False,
      A._looks_like_json_action(SUMMARY))
check("A2 it is not an action either", A._extract_action(SUMMARY) is None,
      A._extract_action(SUMMARY))
check("B1 the summary survives the final-answer guard",
      (not A._looks_like_json_action(SUMMARY)) and bool(A._visible_reply(SUMMARY))
      and SUMMARY not in ("", None))
check("B2 the killed sentence is what the fix removes",
      KILLED in open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
                     encoding="utf-8").read())

# --- C: apostrophes are not quotes ------------------------------------------
check("C1 `don't` opens no span",
      T.single_quote_ranges("I don't know the answer") == [],
      T.single_quote_ranges("I don't know the answer"))
check("C2 a plural possessive opens no span",
      T.single_quote_ranges("the agents' reports are in") == [],
      T.single_quote_ranges("the agents' reports are in"))
check("C3 a real quotation IS a span",
      T.single_quote_ranges("he said 'stop now' twice") == [(8, 18)],
      T.single_quote_ranges("he said 'stop now' twice"))
check("C4 the apostrophes in `don't` / `agents'` never open a span",
      not any(a <= 3 < b for a, b in T.single_quote_ranges(
          "don't run it; the agents' logs say done")),
      T.single_quote_ranges("don't run it; the agents' logs say done"))

# --- D: a real emission is untouched ----------------------------------------
_RAW = 'Go. {"action":"tool","tool":"python.run","args":{"code":"print(1)"}}'
check("D1 prose + RAW call still parses",
      (A._extract_action(_RAW) or {}).get("tool") == "python.run")
check("D2 prose + RAW call is still machine text",
      A._looks_like_json_action(_RAW) is True)
_FENCE = 'Here:\n```json\n{"action":"tool","tool":"shell.exec","args":{"command":"ls"}}\n```'
check("D3 a ```json fence still parses",
      (A._extract_action(_FENCE) or {}).get("tool") == "shell.exec")
_SHELL = ('{"action":"tool","tool":"shell.exec","args":{"command":'
          '"curl -d \'{\\"tool\\":\\"x\\"}\' localhost"}}')
check("D4 a shell argument in single quotes does not hide the real call",
      (A._extract_action(_SHELL) or {}).get("tool") == "shell.exec",
      A._extract_action(_SHELL))

# --- E/F: the mention is not executed, and one reader serves both -----------
_MENTION = ("The probe ran `POST /api/tools/call {\"tool\":\"fs.read\",\"args\":"
            "{\"path\":\"/repo/.env\"}}` and it was denied.")
check("E1 a quoted mention is never extracted as a call",
      A._extract_action(_MENTION) is None, A._extract_action(_MENTION))
check("E2 and is not machine text", A._looks_like_json_action(_MENTION) is False)
check("F1 quotation_ranges carries both span kinds",
      T.quotation_ranges("a `b` and 'c'") == sorted(T.inline_code_ranges("a `b` and 'c'")
                                                    + T.single_quote_ranges("a `b` and 'c'")),
      T.quotation_ranges("a `b` and 'c'"))
check("F2 the mask keeps the length (offsets stay valid)",
      len(T.mask_quotations(SUMMARY)) == len(SUMMARY))

print("\n---\nv1248: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
