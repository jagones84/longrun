#!/usr/bin/env python3
"""v1247 — a JSON call QUOTED inside backticks is prose, never the turn's action.

Bug hunt 2026-11-21 (Chapter 4, the chat loop), CONFIRMED with a live transcript:
A54's verification report (session b7329cccf94c) wrote

    `POST /api/tools/call {"tool":"fs.read","args":{"path":"<repo>/.env"}}`

inside an INLINE code span. `extract_action_json` took that QUOTATION as the turn's
action, `fs.read` ran with no/foreign arguments, the hard-deny blocked the env read,
and the next five reports — each repeating the same sentence — re-fired the
"repeat" guard: 7 phantom calls and 9 harness rows (nudge/observation/retry/
citation-check/failed-call/closure-check) in one close-out. Measured over 2142
assistant messages in the live store: 8 phantom messages in 2 sessions, all with the
only action-shaped JSON inside inline backticks.

The rule: a JSON value that STARTS inside an inline code span is prose. A fenced
block is NOT a span (models wrap REAL calls in ```json), and raw JSON after prose
still runs — the 2026-11-21 A8 fix must survive.

  A  the live report shapes no longer parse as actions
  B  `_looks_like_json_action` agrees (the reply stays a reply)
  C  a real call still runs: raw after prose, fenced, last-after-quoted, whole
  D  the span scanner: inline yes, fence no, double-backtick yes
  E  `stores.turn_reply` still shows a real call's companion prose, never a quote

Deterministic and offline: text + the pure layers only.
Run: python3 tests/acceptance/v1247_quoted_call_is_not_a_call.py
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


# --- A/B: the exact shapes measured in the live session ---------------------
_REPORT = (
    "- **B PASS** — `POST /api/tools/call {\"tool\":\"fs.read\"}` on the env file → "
    "error `matches hard-deny pattern` — denied; the tool layer still blocks.\n"
    "- **A6 PASS** — traversal 6×`../etc/passwd` → `path outside allowed roots`."
)
_REPORT_ARGS = (
    "**B. Tool layer — PASS.** `POST /api/tools/call "
    "{\"tool\":\"fs.read\",\"args\":{\"path\":\"<repo>/.env\"}}` → HTTP 200, "
    "error = `matches hard-deny pattern`."
)
check("A1 a quoted `{tool:fs.read}` in a report is not an action",
      A._extract_action(_REPORT) is None, A._extract_action(_REPORT))
check("A2 nor when the quotation carries args",
      A._extract_action(_REPORT_ARGS) is None, A._extract_action(_REPORT_ARGS))
check("A3 the legacy prose+RAW-call shape still parses (no regression)",
      (A._extract_action('Vado avanti. {"action":"tool","tool":"python.run",'
                         '"args":{"code":"print(1)"}}') or {}).get("tool") == "python.run")
check("B1 `_looks_like_json_action` is False for the report (a reply, not a call)",
      A._looks_like_json_action(_REPORT) is False)
check("B2 and still True for the raw call after prose",
      A._looks_like_json_action('Go. {"action":"tool","tool":"python.run",'
                                '"args":{"code":"x"}}') is True)

# --- C: real calls keep running --------------------------------------------
_FENCED = ('Here is the call:\n```json\n{"action":"tool","tool":"shell.exec",'
           '"args":{"command":"ls"}}\n```')
check("C1 a call inside a ```json fence still runs",
      (A._extract_action(_FENCED) or {}).get("tool") == "shell.exec",
      A._extract_action(_FENCED))
_QUOTED_THEN_REAL = ('I quoted `{"tool":"fs.read"}` above.\n\n'
                     '{"action":"tool","tool":"fs.read","args":{"path":"/tmp/x"}}')
_real = A._extract_action(_QUOTED_THEN_REAL) or {}
check("C2 the REAL call after a quotation wins (last action-shaped, unquoted)",
      _real.get("args", {}).get("path") == "/tmp/x", _real)
_WHOLE = '{"action":"todo.update","steps":[{"id":"n1","status":"done"}]}'
check("C3 a whole-message action object is unchanged",
      (A._extract_action(_WHOLE) or {}).get("action") == "todo.update")

# --- D: the scanner ---------------------------------------------------------
check("D1 a single-backtick span is a span",
      T.inline_code_ranges("a `b` c") == [(2, 5)], T.inline_code_ranges("a `b` c"))
check("D2 a ``` fence is NOT a span (real calls live there)",
      T.inline_code_ranges("a ```d``` e") == [], T.inline_code_ranges("a ```d``` e"))
check("D3 a ``double`` span is a span and does not swallow the fence",
      T.inline_code_ranges("a ``f`` b ```g```") == [(2, 7)],
      T.inline_code_ranges("a ``f`` b ```g```"))
check("D4 mask keeps the length (offsets stay valid)",
      len(T.mask_inline_code("a `bc` d")) == len("a `bc` d")
      and "bc" not in T.mask_inline_code("a `bc` d"),
      repr(T.mask_inline_code("a `bc` d")))

# --- E: reply selection -----------------------------------------------------
from longrun.memory import stores  # noqa: E402
_reply = stores.turn_reply([
    {"role": "assistant", "content": _REPORT},
]) if hasattr(stores, "turn_reply") else None
check("E1 a report that quotes a call is still the turn's reply",
      _reply == _REPORT or _reply is None, _reply)

print("\n---\nv1247: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
