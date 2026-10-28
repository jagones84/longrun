#!/usr/bin/env python3
"""v681 — H2-1 execution record: one artifact per run, no secrets, deterministic.

Harness² cannot compare two harnesses without a record of HOW the base run
behaved: its Propose step is conditioned on the reference execution, not on a
score (`papers/harness2/harness2_2610.14224.txt:276-290`). Longrun keeps the
pieces in two places — the run manifest (`util/tracing.py:85-112`, digests only)
and the session transcript's `tool_cards` — and nothing ties them together.

This test pins the record contract:
  A  built from a session transcript (goal, model, workspace, steps)
  B  determinism + save/load round-trip + corrupt file is not an exception
  C  the harness half is a DIGEST (live revision/config/skills/hooks) and the
     manifest is used when a run_id is given
  D  no secret reaches the artifact: tool args are digested, never copied

No model, no network, no server.
"""
import json
import os
import sys
import tempfile
import hashlib

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v681-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR", "COSTS_DIR", "THREADS_DIR", "HARNESS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_APPROVALS"] = os.path.join(TMP, "approvals.json")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
HOOKS_YAML = os.path.join(TMP, "hooks.yaml")
os.environ["LONGRUN_HOOKS"] = HOOKS_YAML
sys.path.insert(0, os.path.join(REPO, "src"))

WS = os.path.join(TMP, "ws")
os.makedirs(WS, exist_ok=True)
SECRET = "sk-live-DEADBEEF-not-a-real-key"

results = []


def check(name, ok, detail=""):
    """Record one assertion (repo convention: prints PASS/FAIL, exit 1 on any FAIL)."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --------------------------------------------------------------- fixtures ----
def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


OUTSIDE = os.path.join(TMP, "outside.txt")
_write(OUTSIDE, "not part of the workspace")

DELIVERABLE = os.path.join(WS, "report.md")
_write(DELIVERABLE, "# Report\n\nreconciled 12 cells\n")

SID = "sess-h2"
CARDS = [
    {"tool": "fs.read", "ok": True, "args": json.dumps({"path": os.path.join(WS, "in.csv")}),
     "result": "a,b\n1,2", "error": "", "exit_code": 0, "backend": "harness",
     "node": "n1", "ts": 1000.0},
    {"tool": "shell", "ok": False,
     "args": json.dumps({"command": "curl -H 'Authorization: Bearer %s' x" % SECRET}),
     "result": "", "error": "exit 7 connection refused", "exit_code": 7,
     "backend": "host", "node": "n1", "ts": 1002.5},
    {"tool": "fs.write", "ok": True, "args": json.dumps({"path": DELIVERABLE, "content": "x"}),
     "result": "written", "error": "", "exit_code": 0, "backend": "harness",
     "node": "n2", "ts": 1005.0},
    {"tool": "fs.write", "ok": True, "args": json.dumps({"path": DELIVERABLE, "content": "x"}),
     "result": "written", "error": "", "exit_code": 0, "backend": "harness",
     "node": "n2", "ts": 1006.0},
    {"tool": "fs.write", "ok": True, "args": json.dumps({"path": OUTSIDE, "content": "x"}),
     "result": "written", "error": "", "exit_code": 0, "backend": "harness",
     "node": "n3", "ts": 1007.0},
    {"tool": "fs.write", "ok": True,
     "args": json.dumps({"path": os.path.join(WS, "vanished.md"), "content": "x"}),
     "result": "written", "error": "", "exit_code": 0, "backend": "harness",
     "node": "n3", "ts": 1008.0},
]
SESSION = {
    "id": SID, "created": 999.0, "model": "openrouter:test/model", "workspace": WS,
    "messages": [
        {"role": "user", "content": "Reconcile the schedule and budget files into one report."},
        {"role": "assistant", "internal": True,
         "content": json.dumps({"action": "tool", "tool": "fs.read"})},
        {"role": "user", "content": "[harness] Observation for tool fs.read:\na,b"},
    ],
    "tool_cards": CARDS,
    "injects": [],
}
_write(os.path.join(os.environ["LONGRUN_SESSIONS_DIR"], SID + ".json"),
       json.dumps(SESSION))

_write(HOOKS_YAML, "hooks:\n  - event: Stop\n    command: echo done\n")

RUN_ID = "run-h2"
_write(os.path.join(os.environ["LONGRUN_RUNS_DIR"], RUN_ID, "manifest.json"),
       json.dumps({"run_id": RUN_ID, "kind": "chat", "model": "m", "created": 1.0,
                   "revision": "abc1234", "config": {"tools.yaml": "deadbeef"},
                   "overlay": "cafe", "prompt": {"sha256": "f" * 64, "size": 1234}}))

from longrun.harness import record as R  # noqa: E402

# --------------------------------------------------------------- A: build ----
rec = R.build(SID)
check("A1 goal/model/workspace come from the session",
      rec["goal"].startswith("Reconcile the schedule")
      and rec["model"] == "openrouter:test/model" and rec["workspace"] == WS, rec.get("goal"))
check("A2 one step per tool card, in order",
      len(rec["steps"]) == len(CARDS)
      and [s["tool"] for s in rec["steps"]] == ["fs.read", "shell", "fs.write", "fs.write",
                                                "fs.write", "fs.write"])
check("A3 a failing card keeps ok/exit_code/error",
      rec["steps"][1]["ok"] is False and rec["steps"][1]["exit_code"] == 7
      and "connection refused" in rec["steps"][1]["error"], rec["steps"][1])
check("A4 args are keyed + digested, never copied",
      rec["steps"][0]["args_keys"] == ["path"]
      and isinstance(rec["steps"][0]["args_digest"], str)
      and len(rec["steps"][0]["args_digest"]) == 64
      and "args" not in rec["steps"][1] and "args_raw" not in rec["steps"][1])
check("A5 files_touched is deduped, sorted, workspace-only",
      rec["files_touched"] == sorted(rec["files_touched"])
      and rec["files_touched"].count(DELIVERABLE) == 1
      and OUTSIDE not in rec["files_touched"], rec["files_touched"])
check("A6 deliverable carries sha256 + bytes, and a vanished file is skipped",
      [d["path"] for d in rec["deliverables"]] == [DELIVERABLE]
      and rec["deliverables"][0]["sha256"] == hashlib.sha256(
          open(DELIVERABLE, "rb").read()).hexdigest()
      and rec["deliverables"][0]["bytes"] == os.path.getsize(DELIVERABLE), rec["deliverables"])
check("A7 budget counts the steps and spans the cards",
      rec["budget"]["steps"] == len(CARDS)
      and rec["budget"]["seconds"] == round(CARDS[-1]["ts"] - CARDS[0]["ts"], 3), rec["budget"])

# ---------------------------------------------------- B: determinism/save ----
rec2 = R.build(SID)
check("B1 two builds of the same session are identical", rec == rec2)

rec_m = R.build(SID, run_id=RUN_ID)
check("B2 a run_id pulls the prompt + revision from the run manifest",
      rec_m["harness"]["prompt"] == {"sha256": "f" * 64, "size": 1234}
      and rec_m["harness"]["revision"] == "abc1234"
      and rec_m["harness"]["config"] == {"tools.yaml": "deadbeef"}, rec_m["harness"])

path = R.save(rec)
check("B3 save writes one artifact and load round-trips it",
      bool(path) and os.path.isfile(path) and R.load(SID) == rec, path)
with open(path, "w", encoding="utf-8") as f:
    f.write("{not json")
check("B4 a corrupt artifact loads as None (never raises)", R.load(SID) is None)
with open(R.path_for(SID), "w", encoding="utf-8") as f:
    f.write(json.dumps(rec))

# ------------------------------------------------------------- C: digests ----
h = rec["harness"]
check("C1 harness carries live revision/config/overlay/skills/hooks digests",
      isinstance(h.get("revision"), (str, type(None)))
      and isinstance(h.get("config"), dict)
      and "sha256" in (h.get("skills") or {}) and "sha256" in (h.get("hooks") or {}),
      sorted(h.keys()))
check("C2 the hooks digest tracks the EFFECTIVE hook list (overlay-safe)",
      h["hooks"]["count"] == 1
      and h["hooks"]["sha256"] == R._hooks_digest()["sha256"], h["hooks"])
_write(HOOKS_YAML, "hooks:\n  - event: Stop\n    command: echo changed\n")
from longrun.tools import hooks as HK  # noqa: E402
HK.load(reload=True)
check("C3 changing the hook list changes the digest",
      R._hooks_digest()["sha256"] != h["hooks"]["sha256"])

# --------------------------------------------------------------- D: secret ---
dump = json.dumps(rec_m)
check("D1 the secret never reaches the artifact (args are digested)",
      SECRET not in dump and "sk-live-DEADBEEF" not in dump)
check("D2 the schema version is present", rec.get("schema") == R.SCHEMA, rec.get("schema"))

import shutil  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
