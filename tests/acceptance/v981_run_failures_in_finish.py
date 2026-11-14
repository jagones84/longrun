#!/usr/bin/env python3
"""v981 — failed tool calls are part of the run's closure record (H5).

`run_44ea468b` (2026-11-14) closed `completed` with two shell calls that had
exited 1 and 126. The finish summary — the only artifact a reader sees — said
nothing about them, so a failed call was absorbed by a successful-sounding
sentence.

Contract:
  A) the harness's own line names every failed call, LABELLED `[harness]`, so it
     cannot be mistaken for the agent's words;
  B) the run result carries the same rows as DATA (`failures`), and the finish
     event carries them too — one run, one truth;
  C) a clean run is untouched — no suffix, no noise;
  D) the legacy loop's entries (no `tool_result` meta) are read from the
     deterministic `[tool] … ok=False` observation line.

Deterministic: scripted actions, no model, no server, isolated temp dirs.

Run: python3 tests/acceptance/v981_run_failures_in_finish.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="sf-v981-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as API  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- A/B: a failed call reaches the summary and the record ------------------
EVENTS = []
res = API.agent_run_v2(
    "goal H5", max_steps=3,
    script=[{"action": "tool", "tool": "fs.read", "args": {"path": "no-such-file-v981.txt"}},
            {"action": "finish", "summary": "all good, everything checked"}],
    on_event=lambda kind, **d: EVENTS.append((kind, d)))
summary = str(res.get("summary") or "")
check("A1 the model's claim is still first", summary.startswith("all good"), summary[:40])
check("A2 the failed call is named in the summary", "tool calls failed" in summary, summary)
check("A3 it is LABELLED as the harness's observation", "[harness]" in summary, summary)
check("A4 the step and the tool are named", "fs.read" in summary, summary)
fails = res.get("failures") or []
check("B1 the result carries the rows as data",
      len(fails) == 1 and fails[0].get("tool") == "fs.read", fails)
check("B2 the exit code is recorded", fails and fails[0].get("exit_code") == 1, fails)
fin = [d for k, d in EVENTS if k == "agent.finish"]
check("B3 agent.finish carries the same rows",
      bool(fin) and (fin[-1].get("failures") or [{}])[0].get("tool") == "fs.read",
      fin[-1].get("failures") if fin else None)

# --- C: a clean run is untouched -------------------------------------------
res2 = API.agent_run_v2("goal clean", max_steps=2,
                        script=[{"action": "finish", "summary": "nothing failed"}])
check("C1 a clean summary gets no suffix", res2.get("summary") == "nothing failed",
      res2.get("summary"))
check("C2 and no failure rows", res2.get("failures") == [], res2.get("failures"))

# --- D: the legacy entry shape is understood ------------------------------
legacy = [{"i": 4, "action": "tool", "tool": "shell.exec",
           "observation": "[shell.exec] exit=1 ok=False backend=host sandboxed=False\n"
                          "ERROR: command failed"}]
rows = API.failed_tool_calls(legacy)
check("D1 a meta-less failure is still found", len(rows) == 1, rows)
check("D2 its exit code and error text survive",
      rows and rows[0].get("exit_code") == 1 and "command failed" in rows[0].get("error", ""),
      rows)
check("D3 a success-looking entry is ignored",
      API.failed_tool_calls([{"i": 1, "action": "tool", "tool": "fs.read",
                              "observation": "[fs.read] exit=0 ok=True"}]) == [])

ok = sum(RESULTS)
print("\nv981: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
