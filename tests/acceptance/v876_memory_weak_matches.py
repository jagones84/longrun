#!/usr/bin/env python3
"""v876 — a weak recall SAYS it is weak, instead of answering `ok:true` silently.

Measured 2026-11-08 on an isolated store: a 4-word query against 5 records that
each hold ONE of the words came back as five rows at 0.25 with `ok:true` and no
verdict — the caller read "I remembered" while no record contained the query.
The score was visible, the meaning was not.

A1 such a recall is still a success (the records are real) but flags `weak`
A2 its stdout carries the verdict in words
A3 a record that holds EVERY query word is not called weak

Run: python3 tests/acceptance/v876_memory_weak_matches.py
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v876-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
for _d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import memory as mem           # noqa: E402
from longrun.tools import tools as T               # noqa: E402

mem.DATA_DIR = os.path.join(TMP, "memory")
mem.CORE_PATH = os.path.join(mem.DATA_DIR, "core.md")
os.makedirs(mem.DATA_DIR, exist_ok=True)
mem._vector_db = {}
mem._writes_since_index = 0

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


try:
    for text in ("alpha lesson one", "beta lesson two", "gamma lesson three",
                 "delta lesson four", "alpha lesson five"):
        mem.store("lesson", text)

    weak = T._memory({"action": "recall", "query": "alpha beta gamma delta"}, None)
    check("A1 a partial-match recall is still ok but flagged `weak`",
          weak.get("ok") is True and weak.get("weak") is True
          and weak.get("count", 0) > 1,
          "ok=%s weak=%s count=%s" % (weak.get("ok"), weak.get("weak"), weak.get("count")))
    check("A2 its stdout states the verdict in words",
          "weak matches" in (weak.get("stdout") or "")
          and "no memory contains all the query words" in (weak.get("stdout") or ""),
          (weak.get("stdout") or "").splitlines()[-1:])

    mem.store("lesson", "alpha beta gamma delta — every word of the query")
    strong = T._memory({"action": "recall", "query": "alpha beta gamma delta"}, None)
    check("A3 a record holding EVERY query word is not called weak",
          strong.get("ok") is True and not strong.get("weak"),
          "weak=%r" % strong.get("weak"))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("---")
okc = sum(results)
print("\nv876: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
