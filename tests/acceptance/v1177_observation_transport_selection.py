#!/usr/bin/env python3
"""v1177 — keep the decisive observation, measure evidence transport, select under budget (round 108).

Sources:
  * arXiv:2611.19056 "Run, Read Back, Refine" — observation fidelity is the axis
    where a harness beats a model; a preview that hides the decisive line is the
    same defect as losing the output.
  * arXiv:2611.18471 "Do Verifier Judgments Survive Abstraction?" — verifier
    evidence can die at a compaction boundary; restoring provenance recovers it.
  * arXiv:2611.21515 "Beyond Leaderboard Ranks" — overlapping intervals mean the
    rank is not a decision; successive halving buys the cheapest separation.

Deterministic: strings and dicts; one real `compact()` call on a COPY; no model,
no network, no server.

Run: python3 tests/acceptance/v1177_observation_transport_selection.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1177-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry                # noqa: E402
registry._external_tools = lambda: {}             # noqa: E731
from longrun.core import server                   # noqa: E402,F401  (import order)
from longrun.harness import observation as OBS  # noqa: E402
from longrun.harness import verification_transport as VT  # noqa: E402
from longrun.util import selection as SEL         # noqa: E402
from longrun.agent import agent as A              # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# ---- 1. observation: the middle line survives -------------------------------
filler = "\n".join("step %d ok" % i for i in range(400))
LOG = ("build started\n" + filler + "\nERROR: cannot resolve symbol RTL_42\n"
       + filler + "\nexit code: 2\n")
preview = OBS.preview(LOG, head_chars=600, tail_chars=400)
check("the decisive middle line is kept in the preview",
      "ERROR: cannot resolve symbol RTL_42" in preview, preview[:120])
check("the exit code line is kept too", "exit code: 2" in preview)
check("the preview stays bounded", len(preview) < len(LOG) / 2, len(preview))
fid = OBS.fidelity(LOG, preview)
check("fidelity is 1.0 for that preview", fid["fidelity"] == 1.0 and not fid["missing"],
      fid)
check("a decisive-free log keeps the old head+tail shape",
      "decisive lines" not in OBS.preview("a\nb\nc\n", 2, 2))
check("fidelity counts a lost line",
      OBS.fidelity("boom\nFATAL: x\n", "boom\n")["fidelity"] < 1.0)

# ---- 2. the offload preview uses it -----------------------------------------
sess = {"id": "s_test"}
obs = A._offload_observation(sess, "shell.exec", LOG)
check("the offloaded observation names the decisive lines", "Decisive lines" in obs)
check("the offloaded observation still carries the error and the path",
      "ERROR: cannot resolve symbol RTL_42" in obs and "FULL OUTPUT FILE" in obs)

# ---- 3. verification transport ----------------------------------------------
native = ("cmd: pytest\nFAILED tests/test_x.py\nFileNotFoundError: /work/data.csv\n"
          "exit=1\n")
abstracted = "cmd: pytest ran and one test failed.\n"
tr = VT.transport(native, abstracted)
check("the transport names the lost evidence",
      {i["value"] for i in tr["missing"]} >= {"1", "FileNotFoundError", "/work/data.csv"},
      tr["missing"])
check("fidelity drops below 1.0", tr["fidelity"] < 1.0, tr["fidelity"])
block = VT.restore_block(tr["missing"])
check("the restore block is citable provenance",
      block.startswith("PROVENANCE") and "FileNotFoundError" in block and "/work" in block)
full = VT.transport(native, native)
check("native evidence transports 1.0", full["fidelity"] == 1.0)
aud = VT.audit_messages(
    [{"role": "user", "content": native * 40},
     {"role": "assistant", "content": "done"}], budget_tokens=200,
    summarizer=lambda old: "summary: the tests were run.")
check("auditing a compacted copy reports stats and a restore",
      "stats" in aud and aud["restore"] != "" and aud["fidelity"] <= 1.0,
      (aud.get("fidelity"), aud.get("restore")[:80]))

# ---- 4. selection under budget ---------------------------------------------
check("Wilson interval is stable at n=0",
      SEL.wilson(0, 0)["p"] is None and SEL.wilson(0, 0)["hi"] == 1.0)
w = SEL.wilson(15, 20)
check("Wilson interval brackets the point estimate",
      w["lo"] <= w["p"] <= w["hi"], w)

CAND = [
    {"name": "expensive", "cost": 170.0, "passes": 14, "n": 20},
    {"name": "cheap", "cost": 34.0, "passes": 12, "n": 20},
    {"name": "middling", "cost": 60.0, "passes": 13, "n": 20},
]
out = SEL.select(CAND, eval_budget=100.0)
check("an unresolved field picks the cheapest candidate",
      out["winner"] == "cheap", (out["winner"], out["reason"]))
check("the ranking is by lower bound then cost",
      out["ranking"][0]["name"] in ("expensive", "cheap", "middling"))
check("successive halving plans only what fits",
      out["spent"] <= 100.0, out["spent"])
check("the rounds name what to evaluate next",
      all("evaluate_next" in r for r in out["rounds"]))

SEP = [
    {"name": "good", "cost": 50.0, "passes": 19, "n": 20},
    {"name": "bad", "cost": 5.0, "passes": 2, "n": 20},
]
sep = SEL.select(SEP, eval_budget=100.0)
check("a separated field picks the better agent", sep["winner"] == "good",
      sep["reason"])

capped = SEL.select(CAND, eval_budget=100.0, cost_cap=70.0)
check("the deployment cost cap drops the expensive agent",
      "expensive" in capped["dropped_by_cap"] and capped["winner"] != "expensive",
      capped["dropped_by_cap"])
zero = SEL.select(CAND, eval_budget=0.0)
check("a zero budget buys nothing", zero["spent"] == 0.0)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
