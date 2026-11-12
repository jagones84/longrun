#!/usr/bin/env python3
"""v969 — a zero-tool reply that CLAIMS a change earns one round (HD-3).

Source: `S-2026-11-13-023` (*Fidelity Is Not Enough*, the dispatch-record paper).
Its silent-failure detector reads only WHICH tools a run called, never the value it
produced, and it caught what every value-based check missed: a run whose
structured-output constraint silently disabled tool use answered anyway, with
fabricated source text, and was graded a success.

Longrun already holds BOTH of the paper's rules on the REQUEST side — the evidence
gate (`_needs_evidence`, ≈ the paper's *tool-bypass*) and the verify gate / read-back
(≈ *verification-skipped*). Neither reads the ANSWER, so the unguarded quadrant is a
turn that ANSWERS an imperative request with a done-claim ("I've updated the
config") and ran ZERO tools: no mutation was recorded, so nothing fires.

Contract:
  A) `_claims_action` reads first-person past-tense claims, and only those;
  B) it complements `_needs_evidence` — the imperative + done-claim quadrant;
  C) the gate text asks for a DECISION, never for a narration;
  D) it is wired on all three close paths, one kind, guarded by zero tools;
  E) one round per turn, never a loop.

Deterministic: temp dirs, no live model, no network, no server.

Run: python3 tests/acceptance/v969_action_claim_gate.py
"""
import os
import re
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v969-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for d in ("cfg", "sessions", "data"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _srv   # noqa: E402,F401  (import order)
from longrun.agent import agent as A       # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()

# ---- A. what counts as a claim -----------------------------------------------
check("A1 a first-person past-tense change claim is caught",
      A._claims_action("I've updated the config"))
check("A2 it is not tied to one verb",
      A._claims_action("I created the file")
      and A._claims_action("I ran the migration"))
check("A3 a FUTURE-tense promise is not a claim (that is the intent gate's job)",
      not A._claims_action("Let me update the config")
      and A._narrates_intent("Let me update the config"))
check("A4 a bare prose sentence is not a claim",
      not A._claims_action("The config sets retries to 3"))
check("A5 empty and None are never a claim",
      not A._claims_action("") and not A._claims_action(None))
check("A6 it reads the TAIL, like `_narrates_intent`",
      A._claims_action(("x " * 260) + "I've updated the config.")
      and not A._claims_action("I've updated the config. " + ("x " * 260)))

# ---- B. it covers the quadrant the evidence gate never did -------------------
# The evidence gate fires on a QUESTION with no tool; the action gate on a
# DONE-claim with no tool. The imperative request ends with a claim about work.
_IMPERATIVE = "fix the typo in the README"
check("B1 an imperative needs no evidence (the harness sees the work)",
      not A._needs_evidence(_IMPERATIVE))
check("B2 yet its done-claim, with zero tools, is exactly what was unguarded",
      A._claims_action("I've fixed the typo in the README"))

# ---- C. the gate asks for a DECISION, not a narration ------------------------
_G = A._action_gate_text()
check("C1 it names itself and asks for one decision",
      "ACTION GATE" in _G and "Decide ONCE" in _G, _G[:60])
check("C2 it points at the tools that perform the change",
      "fs.write" in _G and "fs.edit" in _G and "shell.exec" in _G)
check("C3 it closes the hole explicitly",
      "Never report a change this turn did not make" in _G)

# ---- D. wiring: three close paths, one kind, guarded by zero tools -----------
check("D1 the gate injects as its own kind on all three close paths",
      SRC.count('_inject(_action_gate_text(), "action-gate")') == 3,
      SRC.count('_inject(_action_gate_text(), "action-gate")'))
check("D2 the kind is used for nothing else",
      SRC.count('"action-gate"') == 3, SRC.count('"action-gate"'))
check("D3 every call site is guarded by a zero-tool turn",
      SRC.count("and _claims_action(answer) and not _is_aborted") == 3,
      SRC.count("and _claims_action(answer) and not _is_aborted"))
check("D4 it is the same shape as the evidence gate it complements",
      SRC.count("_inject(_evidence_gate_text(), \"evidence-gate\")") == 3)

# ---- E. one round per turn, never a loop -------------------------------------
# `(?<![A-Za-z0-9_])` so the count is the flag itself, never `_think_action_used`.
_N_INIT = len(re.findall(r"(?<![A-Za-z0-9_])_action_used = False", SRC))
_N_SET = len(re.findall(r"(?<![A-Za-z0-9_])_action_used = True", SRC))
check("E1 the flag starts unset and is spent once",
      _N_INIT == 1 and _N_SET == 3, (_N_INIT, _N_SET))

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
