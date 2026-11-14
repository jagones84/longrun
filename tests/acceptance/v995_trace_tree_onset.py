#!/usr/bin/env python3
"""v995 — a turn's trace TREE and the FIRST step that went wrong (HD-2).

A failed turn was diagnosed by reading a flat ordered transcript and guessing
which call broke the run (`_render_transcript`, tools.py:2274). The stores already
hold everything needed: every tool call is a card with `ok`, `error`, `exit_code`,
`node` and `after`, and the plan's steps are graph nodes. `util/runtree` is the
read model: STAGE (one plan step) → STEP (one tool call), plus an onset verdict.

  A  steps(): execution order, a bad verdict OR a non-zero exit is a failure
  B  build(): one stage per plan node, steps nested, orphan todos kept as a stage
  C  build(): no plan still answers — one stage, never an empty tree
  D  onset(): the FIRST failure, whether it was recovered, how often retried
  E  verdict: one operator-readable line naming step, tool and stage
  F  describe(): an unknown session is an error, a known one is a tree
  G  the surface exists: route + CLI verb + the CLI docs row + the shared class

Deterministic: no model, no network, no server.
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v995-")
for _k in ("SESSIONS_DIR", "DATA_DIR", "CONFIG_DIR", "GRAPH_DIR", "DB", "HELDOUT_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import runtree as RT  # noqa: E402
from longrun.util import selfevolve as SE  # noqa: E402
from longrun.memory import stores  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       "" if ok else "  -> %r" % (detail,)))


def card(tool, ok=True, error="", exit_code=None, node=None, after=0, ts=None):
    return {"tool": tool, "ok": ok, "error": error, "exit_code": exit_code,
            "node": node, "after": after, "ts": ts if ts is not None else after}


# ------------------------------------------------- A: steps and their failures ---
sess = {"id": "sA", "tool_cards": [
    card("fs.read", after=2),
    card("shell.exec", ok=False, error="no such file: /a/b", exit_code=1, after=5),
    card("fs.write", after=9),
    card("shell.exec", exit_code=2, after=11),          # ok but a non-zero exit
]}
flat = RT.steps(sess)
check("A1 steps come back in execution order", [s["tool"] for s in flat]
      == ["fs.read", "shell.exec", "fs.write", "shell.exec"], flat)
check("A2 a bad verdict is a failure", flat[1]["failed"] is True, flat[1])
check("A3 a non-zero exit is a failure even when ok is True", flat[3]["failed"] is True, flat[3])
check("A4 a success carries no reason", flat[0]["reason"] == "" and flat[0]["failed"] is False, flat[0])
check("A5 the failure class is the SHARED one, normalized",
      flat[1]["reason"] == SE.error_class("no such file: /a/b")
      == "no such file: <path>", flat[1]["reason"])
check("A6 ordering follows ts before after, matching the transcript renderer",
      [s["tool"] for s in RT.steps({"tool_cards": [
          card("late", after=1, ts=9), card("early", after=99, ts=1)]})]
      == ["early", "late"], "ts wins over after")

# ------------------------------------------------ B: stages from the plan ---
graph = {"nodes": [
    {"id": "n1", "label": "read the file", "status": "done"},
    {"id": "n2", "label": "write the fix", "status": "doing"},
]}
b = RT.build({"id": "sB", "tool_cards": [
    card("fs.read", node="n1", after=2),
    card("fs.edit", node="n2", after=4, ok=False, error="permission denied", exit_code=1),
    card("shell.exec", node="n9", after=6),          # todo replaced by a replan
]}, graph)
check("B1 one stage per plan node, in plan order",
      [s["id"] for s in b["stages"]] == ["n1", "n2", "n9"], [s["id"] for s in b["stages"]])
check("B2 a stage holds its own steps", b["stages"][0]["n"] == 1
      and b["stages"][0]["steps"][0]["tool"] == "fs.read", b["stages"][0])
check("B3 the plan's label and status ride along",
      b["stages"][1]["label"] == "write the fix" and b["stages"][1]["status"] == "doing",
      b["stages"][1])
check("B4 a card whose todo is gone is KEPT, in its own stage",
      b["stages"][2]["status"] == "orphan" and b["stages"][2]["n"] == 1,
      b["stages"][2])
check("B5 the counts add up", b["counts"] == {"steps": 3, "failed": 1, "stages": 3,
                                             "open": 0}, b["counts"])
b5 = RT.build({"id": "sB2", "tool_cards": [card("fs.read", node="n1", after=1)]},
              {"nodes": [{"id": "n1", "label": "ran", "status": "done"},
                         {"id": "n2", "label": "claimed, never executed", "status": "done"},
                         {"id": "n3", "label": "no call either", "status": "todo"}]})
check("B6 a plan step with NO tool call is not a stage of the tree",
      [s["id"] for s in b5["stages"]] == ["n1"], [s["id"] for s in b5["stages"]])
check("B7 it is kept, separated, because a claim without work is a finding",
      [s["id"] for s in b5["open"]] == ["n2", "n3"]
      and b5["counts"]["open"] == 2, b5["open"])

# ------------------------------------------------------ C: no plan at all ---
c = RT.build({"id": "sC", "tool_cards": [card("fs.read", after=1), card("fs.write", after=3)]})
check("C1 a session with no plan still answers", c["planned"] is False
      and len(c["stages"]) == 1 and c["stages"][0]["n"] == 2, c["stages"])
check("C2 and its stage is named for what it is",
      c["stages"][0]["id"] == "(unplanned)" and c["stages"][0]["status"] == "orphan",
      c["stages"][0])
check("C3 no failure means no onset and no verdict",
      c["onset"] is None and c["verdict"] == "", (c["onset"], c["verdict"]))

# ------------------------------------------------------------ D: the onset ---
d = RT.build({"id": "sD", "tool_cards": [
    card("fs.read", node="n1", after=2),
    card("shell.exec", ok=False, error="boom", exit_code=1, node="n1", after=4),
    card("shell.exec", node="n1", after=6),           # the retry that worked
    card("shell.exec", ok=False, error="boom", exit_code=1, node="n1", after=8),
]}, {"nodes": [{"id": "n1", "label": "run it", "status": "doing"}]})
ond = d["onset"]
check("D1 the onset is the FIRST failure, not the last", ond and ond["i"] == 2, ond)
check("D2 a later success of the same tool in the same stage counts as recovery",
      ond and ond["recovered"] is True, ond)
check("D3 the retries are counted", ond and ond["retries"] == 2, ond)
check("D4 the totals are the whole turn's", ond and ond["failed_total"] == 2
      and ond["steps_total"] == 4, ond)
check("D5 the class rides on the onset", ond and ond["reason"] == "boom", ond)
notrec = RT.onset(RT.steps({"tool_cards": [
    card("fs.read", after=1),
    card("shell.exec", ok=False, error="x", exit_code=1, after=2)]}))
check("D6 a failure nobody retried is reported as not recovered",
      notrec and notrec["recovered"] is False and notrec["retries"] == 0, notrec)

# ------------------------------------------------------------ E: the verdict ---
check("E1 the verdict names the step position, the tool and the stage",
      d["verdict"].startswith("first failure at step 2 of 4 in 'run it': shell.exec (exit 1)"),
      d["verdict"])
check("E2 it says recovery in words a reader can act on",
      "recovered by a later shell.exec that succeeded" in d["verdict"], d["verdict"])
check("E3 an unrecovered failure says so",
      "was never retried successfully" in RT.build({"tool_cards": [
          card("shell.exec", ok=False, error="x", exit_code=1, after=1)]})["verdict"],
      RT.build({"tool_cards": [card("shell.exec", ok=False, error="x",
                                    exit_code=1, after=1)]})["verdict"])

# ----------------------------------------------------------- F: describe() ---
check("F1 an unknown session is an error, never an empty tree",
      RT.describe("nope-995").get("error") == "session not found", RT.describe("nope-995"))
stores.save_session({"id": "s995", "title": "v995", "created": time.time(),
                     "messages": [{"role": "user", "content": "go", "ts": 1}],
                     "tool_cards": [card("fs.read", node="n1", after=1),
                                    card("shell.exec", ok=False, error="nope",
                                         exit_code=1, node="n1", after=2)]})
got = RT.describe("s995")
check("F2 a real session gives a tree with an onset",
      got.get("session") == "s995" and (got.get("onset") or {}).get("tool") == "shell.exec",
      got.get("onset"))
check("F3 describe() reads the graph itself when none is passed",
      got.get("planned") is False and len(got.get("stages") or []) == 1,
      [s["id"] for s in got.get("stages") or []])

# ------------------------------------------------------------- G: the surface ---
HTTP = open(os.path.join(REPO, "src/longrun/core/httpapi.py"), encoding="utf-8").read()
FORGE = open(os.path.join(REPO, "src/longrun/core/forge.py"), encoding="utf-8").read()
DOC = open(os.path.join(REPO, "docs/CLI.md"), encoding="utf-8").read()
check("G1 the route is served", "/trace-tree" in HTTP and "_runtree.describe" in HTTP, "httpapi")
check("G2 the CLI verb exists and calls it",
      'req("GET", "/api/sessions/%s/trace-tree" % args.value)' in FORGE
      and 'args.action == "tree"' in FORGE, "forge")
check("G3 the CLI documents the verb", "sessions tree ID" in FORGE and "sessions tree" in DOC, "docs")
check("G4 the failure class has ONE owner (no second normalizer)",
      "def error_class(" in open(os.path.join(REPO, "src/longrun/util/selfevolve.py"),
                                 encoding="utf-8").read()
      and "_error_class" not in open(os.path.join(REPO, "src/longrun/util/runtree.py"),
                                     encoding="utf-8").read(), "selfevolve")

print("\n%d/%d PASS" % (sum(results), len(results)))
sys.stdout.flush()
sys.exit(0 if all(results) else 1)
