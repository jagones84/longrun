#!/usr/bin/env python3
"""v937 — an evaluation SEES a candidate config without WRITING it (RSI-H-2).

The meta-harness saved the candidate into the live policy overlay and restored the
old one in a `finally`. A crash, kill or OOM between the two left the candidate
installed, and a concurrent turn ran under it. Now the candidate is applied to a
copy and exposed through `registry.scoped_config()`: nothing is written, nothing
has to be restored, and the cache is never mutated.

Deterministic: the eval runner is stubbed to raise, no model, no network.

Run: python3 tests/acceptance/v937_eval_scoped_config.py
"""
import copy
import hashlib
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v937-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "config")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as R  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _hash(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except FileNotFoundError:
        return "absent"


CFG = os.path.join(REPO, "config", "tools.yaml")
BEFORE = (_hash(CFG), _hash(R.OVERLAY_YAML))
BASE = R.load_config(reload=True)
ORIG_BACKEND = BASE["sandbox"]["backend"]

CAND = copy.deepcopy(BASE)
CAND["sandbox"]["backend"] = "docker"
CAND["tools"].setdefault("shell", {})["approval"] = "auto"

# --- A) the scope shows the candidate and leaves no trace -------------------
SEEN = {}
try:
    with R.scoped_config(CAND):
        SEEN["backend"] = R.load_config()["sandbox"]["backend"]
        SEEN["approval"] = R.load_config()["tools"]["shell"]["approval"]
        raise RuntimeError("simulated crash inside the evaluation")
except RuntimeError:
    pass

check("A1 the scoped candidate is visible while the block runs",
      SEEN.get("backend") == "docker" and SEEN.get("approval") == "auto", SEEN)
check("A2 after a CRASH the live config is the original one",
      R.load_config()["sandbox"]["backend"] == ORIG_BACKEND, R.load_config()["sandbox"]["backend"])
check("A3 no config file changed (header + overlay)",
      (_hash(CFG), _hash(R.OVERLAY_YAML)) == BEFORE, (BEFORE, (_hash(CFG), _hash(R.OVERLAY_YAML))))

# --- B) evaluate_candidate writes nothing, even when the eval fails ---------
from longrun.core import server as SRV  # noqa: E402
from longrun.util import meta as META  # noqa: E402


def _boom(**_kw):
    raise RuntimeError("eval boom")


_orig = SRV.eval_run
SRV.eval_run = _boom
try:
    res = META.evaluate_candidate(
        {"model": None, "max_steps": 1, "sandbox_backend": "docker",
         "tool_approval": "auto"}, "v937")
finally:
    SRV.eval_run = _orig

check("B1 the failure is reported on the result", "eval boom" in str(res.get("error")), res.get("error"))
check("B2 evaluate_candidate wrote no config file",
      (_hash(CFG), _hash(R.OVERLAY_YAML)) == BEFORE, (_hash(CFG), _hash(R.OVERLAY_YAML)))
check("B3 the live config is untouched after the failed eval",
      R.load_config()["sandbox"]["backend"] == ORIG_BACKEND
      and R.load_config()["tools"].get("shell", {}).get("approval") != "auto",
      R.load_config()["tools"].get("shell"))
check("B4 the cached object was not mutated by the candidate",
      R.load_config()["sandbox"]["backend"] == ORIG_BACKEND, R.load_config()["sandbox"])

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
