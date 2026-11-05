#!/usr/bin/env python3
"""v816 — one classified failure cause per run (B-4).

The cause of a failed run was only inferable from several separate fields
(`costs.record.status`, `runs.status`, `runmetrics.stop_reason`, events), so the
benchmark rule "classify the cause before touching code" was done by hand and
sometimes skipped. `runmetrics.classify_cause` joins the classifiers that already
exist into ONE bucket — provider | budget | model | harness — and `finish()` writes
it on the run record. ("Failure Attribution Standard", 2026-11-05.)

  A) the four buckets are reachable and distinct;
  B) a clean run is `None`, a user abort is `None`;
  C) `finish()` stores the field and the server failure path feeds it the code.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v816-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "data", "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                 # noqa: E402,F401 — breaks the import cycle
from longrun.model import runmetrics            # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


cc = runmetrics.classify_cause

# ------------------------------------------------------------- A. four buckets ---
check("A1 provider: a diagnostics code names it",
      cc("error", "error", code="provider.rate_limited") == "provider")
check("A2 provider: a 429 in the text names it",
      cc("error", "error", error="HTTP 429 rate limit exceeded") == "provider")
check("A3 budget: a wall-clock stop names it",
      cc("done", "budget") == "budget")
check("A4 model: an unusable reply names it",
      cc("done", "empty_reply") == "model")
check("A5 harness: anything left over is the loop",
      cc("error", "error", error="unexpected state after tool batch") == "harness")

# ------------------------------------------------------------- B. no failure ----
check("B1 a clean run has no cause", cc("done") is None, cc("done"))
check("B2 a user abort is not a failure", cc("user_abort") is None, cc("user_abort"))

# ------------- B3-B6. a CLEAN tool turn ends with the KEEPER's own stop reason ---
# Keying the residual bucket on "the stop reason is unknown" labelled every
# tool-using success a harness failure (found in independent review 2026-11-05).
for _stop in ("goal_reached", "plan_only", "blocked", "need_input"):
    check("B3 a clean turn with stop_reason=%s is not a failure" % _stop,
          cc("done", _stop) is None, cc("done", _stop))
check("B4 a real failure with no other signal is the harness",
      cc("error", "error") == "harness", cc("error", "error"))

# ------------- B5. the loop's own "I got nowhere" stop is a HARNESS failure ------
# Every agent turn ends with outcome="done", so the residual bucket could not see
# it and `no_progress` was reported as a CLEAN run (found in review 2026-11-05).
check("B5 a stuck turn (no_progress) is the harness, not a clean run",
      cc("done", "no_progress") == "harness", cc("done", "no_progress"))

# --------------------------------------------------- C. stored on the record ----
runmetrics.start("S1", model="m")
rec = runmetrics.finish("S1", outcome="error", stop_reason="error",
                        error="HTTP 503 service unavailable")
check("C1 finish stores the classified cause", rec.get("failure_cause") == "provider",
      rec.get("failure_cause"))
runmetrics.start("S2", model="m")
rec2 = runmetrics.finish("S2", outcome="done")
check("C2 a clean run stores None, not a missing key",
      "failure_cause" in rec2 and rec2["failure_cause"] is None, rec2.get("failure_cause"))
http = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
            encoding="utf-8").read()
check("C3 the server failure path passes the diagnostics code",
      'code=issue.get("code")' in http)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
