#!/usr/bin/env python3
"""v979 — a run's tool observation is sized by CONFIG, and never silently cut (H4).

`config/tools.yaml` says one tool observation is pasted verbatim up to
`context.tool_obs_limit` (6000) and above it the FULL text goes to
`data/offload/<id>/` with a reference. The CHAT path honours that (JAG-181); the
AGENT RUN loop called `toolmod.observation()` with its 1600-char default, so a
middle-sized read reached the model as a fragment with a `…[truncated N chars]`
marker and a large one lost its tail. `run_44ea468b` read one skill file 8 times.

Contract:
  A) a read that fits the limit arrives WHOLE (not a 1600-char fragment);
  B) a read above the limit is offloaded — the full text is on disk and the
     model gets a reference, never a silent truncation marker;
  C) the batch path uses the SAME rule (no per-item 1500-char cut);
  D) the old default still truncates — that is the defect this pins.

Deterministic: repo files, temp data dirs, no model, no server, no network.

Run: python3 tests/acceptance/v979_run_observation_budget.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="v979_")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITs_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(_TMP, _k.lower())
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(_TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as API  # noqa: E402
from longrun.model import context_limits as CTX  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


class _St:
    id = "run_v979"


LIMIT = CTX.get("tool_obs_limit")

# --- A: a read between 1600 and the config limit arrives whole --------------
_small = os.path.join(REPO, "config", "subagents.yaml")
res = T._dispatch_execute_raw("fs.read", {"path": _small}) or {}
content = str(res.get("content") or "")
obs = API._run_observation(_St(), "fs.read", res)
check("A1 the fixture is above the OLD 1600-char default", 1600 < len(content) < LIMIT,
      len(content))
check("A2 the whole content reached the model", content and content in obs, len(obs))
check("A3 no truncation marker", "[truncated" not in obs)

# --- B: above the config limit the FULL text is offloaded, not cut ----------
_big = os.path.join(REPO, "config", "tools.yaml")
res2 = T._dispatch_execute_raw("fs.read", {"path": _big}) or {}
obs2 = API._run_observation(_St(), "fs.read", res2)
check("B1 the big read is over the limit", len(str(res2.get("content") or "")) > LIMIT,
      len(str(res2.get("content") or "")))
check("B2 the model gets a reference, not a cut", "FULL OUTPUT FILE" in obs2, obs2[:120])
_ref = ""
for line in obs2.splitlines():
    if line.startswith("FULL OUTPUT FILE:"):
        _ref = line.split(":", 1)[1].strip()
_on_disk = os.path.getsize(_ref) if _ref and os.path.isfile(_ref) else -1
check("B3 the referenced file holds the whole observation", _on_disk >= LIMIT, _on_disk)
check("B4 no silent truncation marker", "[truncated" not in obs2)

# --- C: the batch path uses the same rule ----------------------------------
_BATCH = "\n".join(["batch: 1 call(s) — 1 tool, 0 other",
                    "1. fs.read -> " + ("y" * (LIMIT + 2000))])
batch_obs = API._run_observation(_St(), "batch", None, text=_BATCH)
check("C1 a big batch is offloaded too", "FULL OUTPUT FILE" in batch_obs, batch_obs[:120])
check("C2 a small batch stays verbatim",
      API._run_observation(_St(), "batch", None,
                           text="batch: 1 call(s)\n1. fs.read -> ok") ==
      "batch: 1 call(s)\n1. fs.read -> ok")

# --- D: the old default is the defect, documented --------------------------
check("D1 the tool default still truncates at 1600",
      "[truncated" in T.observation(res2), T.observation(res2)[:80])

ok = sum(RESULTS)
print("\nv979: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
