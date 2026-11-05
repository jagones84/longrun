#!/usr/bin/env python3
"""v815 — one token truth per run (B-3).

`RunTrace.llm_call` counted characters/4 while the run streamed (the only number
available before the provider answers) and `finish()` already took the run's USD
from the provider-priced ledger. So `runs.tokens_in/out` and `GET /api/costs` were
two different totals for the same run, and a consumer adding them counted roughly
double ("Silent Instrument Errors", 2026-11-05). `finish()` now takes the tokens
from the SAME ledger, keeping the estimate only when there is no session or no
matching ledger row.

  A) with a ledger, the run's tokens are the provider's real counts;
  B) a session-less run keeps the chars/4 estimate;
  C) a session whose ledger has no row for this run keeps the estimate, never 0.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v815-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(TMP, "data", "costs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server              # noqa: E402,F401 — breaks the import cycle
from longrun.util import tracing             # noqa: E402
from longrun.model import costs              # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


USER = "x" * 4000        # -> chars/4 estimate 1000, never the 1234 below
ASSIST = "y" * 400       # -> estimate 100

# ------------------------------------------------------ A. the ledger wins -----
tr = tracing.RunTrace("chat", model="m", session="S1")
tr.llm_call([{"role": "user", "content": USER}], ASSIST)
costs.record("S1", "m", {"prompt_tokens": 1234, "completion_tokens": 56,
                         "total_tokens": 1290}, run=tr.id)
tr.finish()
rec = tracing.get_run_trace(tr.id)
check("A1 tokens_in is the provider's real count", rec["tokens_in"] == 1234, rec["tokens_in"])
check("A2 tokens_out is the provider's real count", rec["tokens_out"] == 56, rec["tokens_out"])

# ------------------------------------------------ B. no session -> estimate ----
tr2 = tracing.RunTrace("plan", model="m")
tr2.llm_call([{"role": "user", "content": USER}], ASSIST)
tr2.finish()
rec2 = tracing.get_run_trace(tr2.id)
check("B1 a session-less run keeps the chars/4 estimate",
      rec2["tokens_in"] == 1000 and rec2["tokens_out"] == 100,
      (rec2["tokens_in"], rec2["tokens_out"]))

# ------------------------------- C. session, but no ledger row for THIS run ---
tr3 = tracing.RunTrace("chat", model="m", session="S2")
tr3.llm_call([{"role": "user", "content": USER}], ASSIST)
tr3.finish()
rec3 = tracing.get_run_trace(tr3.id)
check("C1 an unmatched ledger keeps the estimate, not zero",
      rec3["tokens_in"] == 1000 and rec3["tokens_out"] == 100,
      (rec3["tokens_in"], rec3["tokens_out"]))

# ------------------------- D. a TOKENLESS ledger row must not zero it (review) -
# `calls` counts a FAILED attempt too, and a failed row is written with 0 tokens,
# so keying the override on `calls` alone replaced a real estimate with a zero.
tr4 = tracing.RunTrace("chat", model="m", session="S4")
tr4.llm_call([{"role": "user", "content": USER}], ASSIST)
costs.record("S4", "m", {}, run=tr4.id, status="failed", error="provider down")
tr4.finish()
rec4 = tracing.get_run_trace(tr4.id)
check("D1 a tokenless (failed) row keeps the estimate, never a zero",
      rec4["tokens_in"] == 1000 and rec4["tokens_out"] == 100,
      (rec4["tokens_in"], rec4["tokens_out"]))

# ------------- E. a provider that reported only ONE side must not zero the other --
tr5 = tracing.RunTrace("chat", model="m", session="S5")
tr5.llm_call([{"role": "user", "content": USER}], ASSIST)
costs.record("S5", "m", {"completion_tokens": 42}, run=tr5.id)
tr5.finish()
rec5 = tracing.get_run_trace(tr5.id)
check("E1 only the reported side comes from the ledger; the other keeps the estimate",
      rec5["tokens_in"] == 1000 and rec5["tokens_out"] == 42,
      (rec5["tokens_in"], rec5["tokens_out"]))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
