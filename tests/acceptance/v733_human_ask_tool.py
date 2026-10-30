#!/usr/bin/env python3
"""v733 — the HUMAN IN THE LOOP card is the AGENT's call, not a harness reflex.

Operator, 2026-10-30: *"HUMAN IN THE LOOP che chiede a me in chat quando si
avvia? perche? … solo l'agente puo lanciarlo, quello no, l'harness da sola.
dev'essere un tool proprio baseline. adesso si avvia da solo perche?"*

Measured: it DID start on its own. Two call sites (`keepgoing` stop and turn
end) turned "turn ends with open plan steps" into a card with no model decision
involved, and the operator's answer was replaced by "⏸ Paused: N open step(s)".

Now there is one door — the baseline tool `human.ask`:

  A  the tool exists, is enabled, and its contract is question-shaped
  B  the handler validates and answers honestly (no question → refused)
  C  the turn recognises the call in all three spellings a model uses
  D  the call becomes the card: reason `asked`, the model's own question, the
     plan's open steps as the fallback list
  E  nothing else raises the card (no `hitl_gate` call site, one `hitl.request`)
  F  a headless turn is refused the door instead of parked for nobody

Deterministic and offline: temp dirs, no model, no network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v733-")
for name, tail in {
    "LONGRUN_DATA_DIR": "data",
    "LONGRUN_CONFIG_DIR": "cfg",
    "LONGRUN_DB": "events.db",
    "LONGRUN_SESSIONS_DIR": "sessions",
    "LONGRUN_GRAPH_DIR": "graphs",
}.items():
    os.environ[name] = os.path.join(TMP, tail)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402,F401  (import order: agent needs it)
from longrun.agent import agent as A  # noqa: E402
from longrun.tools import registry, tools as T  # noqa: E402

SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
           encoding="utf-8").read()
CFG = open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# A — the tool exists ---------------------------------------------------------
check("A1 human.ask is in the catalog", "human.ask" in registry.tool_names())
_spec = registry.tool_spec("human.ask") or {}
_schema = _spec.get("schema") or {}
check("A2 its question is REQUIRED (a card with no question is noise)",
      _schema.get("required") == ["question"], _schema.get("required"))
check("A3 it is enabled and auto-approved (a gated ask is unreachable)",
      "human:" in CFG and "enabled: true" in CFG.split("human:")[1][:120],
      CFG.split("human:")[1][:120] if "human:" in CFG else "missing")

# B — the handler ------------------------------------------------------------
_ok = T._human({"question": "Which region first?", "steps": ["n1 pick a region"]}, None)
check("B1 a question becomes an honest observation",
      _ok.get("ok") is True and "HUMAN IN THE LOOP requested" in
      str(_ok.get("observation")), _ok)
check("B2 the handler carries the steps + options for the card",
      _ok.get("steps") == ["n1 pick a region"] and _ok.get("options") == [], _ok)
check("B3 no question → refused, never an empty card",
      T._human({}, None).get("ok") is False, T._human({}, None))

# C — the three spellings ----------------------------------------------------
_bare = {"action": "human.ask", "question": "Pick one"}
_env = {"action": "tool", "tool": "human.ask", "args": {"question": "Pick two"}}
_bat = {"action": "batch", "calls": [
    {"action": "tool", "tool": "fs.read", "args": {"path": "x"}},
    {"action": "tool", "tool": "human.ask", "args": {"question": "Pick three"}}]}
check("C1 a bare action is recognised",
      A._human_ask_args(_bare) == {"question": "Pick one"}, A._human_ask_args(_bare))
check("C2 the tool envelope is recognised",
      A._human_ask_args(_env) == {"question": "Pick two"}, A._human_ask_args(_env))
check("C3 a call buried in a batch is recognised",
      A._human_ask_args(_bat) == {"question": "Pick three"}, A._human_ask_args(_bat))
check("C4 an ordinary tool call is NOT a human ask",
      A._human_ask_args({"action": "tool", "tool": "fs.read",
                         "args": {"path": "x"}}) is None)

# D — the call becomes the card ----------------------------------------------
check("D1 the turn turns the call into the card (reason `asked`)",
      '_hitl = {"reason": "asked"' in SRC and 'on_event("hitl.request"' in SRC)
check("D2 the visible reply is the model's own QUESTION",
      'content = ("\u23f8 Your decision is needed: %s" % _hitl["question"]' in SRC)
check("D3 with no explicit steps the card lists the plan's OPEN steps",
      "if not _steps:" in SRC and "OPEN_STATUSES" in SRC.split("if not _steps:")[1][:400])
check("D4 the turn ENDS on the call (no forced answer after it)",
      "not final_answer and not _hitl" in SRC)

# E — nothing else raises it -------------------------------------------------
check("E1 the harness no longer calls the gate on its own",
      '_kg.hitl_gate(_dec["reason"]' not in SRC)
check("E2 exactly ONE place emits hitl.request", SRC.count('on_event("hitl.request"') == 1,
      SRC.count('on_event("hitl.request"'))
check("E3 a stop with open steps still publishes plan.stopped",
      'on_event("plan.stopped"' in SRC)
check("E4 the closure nudge points at the door (ask instead of guessing)",
      "call human.ask instead of closing it on a" in SRC)

# F — headless ---------------------------------------------------------------
check("F1 a headless turn is refused the door, not parked for nobody",
      "nobody is attached" in SRC and "HUMAN IN THE LOOP is unavailable here" in SRC)
check("F2 the refusal is a nudge the operator can see, not a silent drop",
      '_inject("HUMAN IN THE LOOP is unavailable here' in SRC)

print("\n---")
print("v733: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
