#!/usr/bin/env python3
"""v817 — best-of-N samples that can actually differ (B-5).

The adaptive fan-out re-sent the SAME messages with the SAME sampling parameters,
so the extra candidates were near-identical and the ring spent 3-6x tokens to
re-rank one answer (turn-level best-of-N, 2026-11-05: +5-10% at 3-6x cost — the
gain needs candidates that differ; samples from one model are correlated, so a
majority vote is worthless and the deterministic ranker stays).

`_completion_body`/`_router_stream`/`stream_with_fallback` accept a per-call
`temperature`/`seed`; the fan-out asks each extra candidate warm, with its own seed.

  A) the body carries the override and the default is unchanged;
  B) each extra candidate gets a DIFFERENT seed;
  C) the fan-out threads the parameters through and the ranker is untouched.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v817-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                      # noqa: E402,F401 — import cycle
from longrun.model import rllm                       # noqa: E402
from longrun.plan import bestofn                     # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


msgs = [{"role": "user", "content": "hi"}]

# ------------------------------------------------------------------ A. body ----
base = rllm._completion_body("m", msgs, True)
check("A1 the default temperature is unchanged", base.get("temperature") == 0.7,
      base.get("temperature"))
check("A2 no seed by default", "seed" not in base, sorted(base))

warm = rllm._completion_body("m", msgs, True, temperature=1.0, seed=1001)
check("A3 the override reaches the body",
      warm.get("temperature") == 1.0 and warm.get("seed") == 1001,
      (warm.get("temperature"), warm.get("seed")))

# ------------------------------------------------------------- B. the seeds ----
s1 = bestofn.sample_params(1)
s2 = bestofn.sample_params(2)
check("B1 candidate 1 is warm", s1[0] > 0.7, s1)
check("B2 two candidates get different seeds", s1[1] != s2[1], (s1, s2))

# --------------------------------------------------- C. the fan-out threads it --
import inspect                                       # noqa: E402
sig = inspect.signature(server.stream_with_fallback)
check("C1 stream_with_fallback accepts temperature/seed",
      "temperature" in sig.parameters and "seed" in sig.parameters,
      sorted(sig.parameters))
sig2 = inspect.signature(rllm._router_stream)
check("C2 _router_stream accepts temperature/seed",
      "temperature" in sig2.parameters and "seed" in sig2.parameters)
ag = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("C3 the best-of-N loop asks for a different sample",
      "_bn.sample_params(_si)" in ag and "temperature=_btemp, seed=_bseed" in ag)
check("C4 the ranker is still deterministic (no vote)",
      "def choose(" in open(os.path.join(REPO, "src", "longrun", "plan", "bestofn.py"),
                            encoding="utf-8").read())

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
