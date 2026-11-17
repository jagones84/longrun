#!/usr/bin/env python3
"""v1111 — the classes of an issue are ordered by what did NOT recover.

Round 43. Round 41 ranked the issues by `unresolved`; one level down, the class
list of an issue (copied into `REPAIR.md` as "What fails") still sorted by raw
count. Measured 2026-11-18: `shell.exec · missing-argument` listed its 10-card
fully-recovered class first, above a 1-card class that never recovered.

  A  the class list is unresolved-first, with the count as tie-break
  B  each class row states its own `unresolved`
  C  the draft's "What fails" follows the same order
  D  the list is capped at three, and the cap keeps the hardest classes

Deterministic: temp data/session dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1111_class_order_unresolved.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1111-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
for _d in (os.environ["LONGRUN_CONFIG_DIR"], os.environ["LONGRUN_DATA_DIR"],
           os.environ["LONGRUN_SESSIONS_DIR"],
           os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")):
    os.makedirs(_d, exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S  # noqa: E402,F401 — the supported import order
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SESS = os.environ["LONGRUN_SESSIONS_DIR"]
A = "shell.exec: missing REQUIRED argument 'cmd'"     # recovered every time
B = "required: command"                               # never recovered
C = "missing REQUIRED argument 'limit'"              # 2 cards, one recovered
D = "required: 'path'"                                # 1 card, 1 recovered


def card(err, node):
    return {"tool": "shell.exec", "ok": False, "error": err, "node": node}


def okc(node):
    return {"tool": "shell.exec", "ok": True, "result": "ok", "node": node}


# A: 5 cards, all recovered (a stumble); B: 1 card, unresolved; C: 2 cards, one
# recovered; D: 1 card, recovered. All four land in the SAME family.
# The recovery rule is the trace tree's own (same tool, same node), so each class
# carries its own node: a later success on another node does not recover it.
session = ([card(A, "a"), okc("a")] * 5 + [card(B, "b")]
           + [card(C, "c"), okc("c"), card(C, "c")] + [card(D, "d"), okc("d")])
with open(os.path.join(SESS, "s_a.json"), "w", encoding="utf-8") as f:
    json.dump({"id": "s_a", "messages": [], "tool_cards": session}, f)

rep = selfevolve.failure_candidates(limit=10, include_sessions=True)
iss = next(i for i in rep["issues"] if i["family"] == "missing-argument")
classes = iss.get("classes") or []
errors = [c["error"] for c in classes]

# ------------------------------------------------- A: the order ----------------
check("A1 the never-recovered 1-card class ranks above the recovered 5-card one",
      errors.index(B) < errors.index(A), errors)
check("A2 a recovered class (unresolved 0) falls below a partly unresolved one",
      errors.index(C) < errors.index(A), errors)
check("A3 within equal unresolved, the larger count comes first",
      errors.index(C) < errors.index(B), errors)

# ------------------------------------------------- B: the field ---------------
check("B1 every class row states its own unresolved",
      [c.get("unresolved") for c in classes]
      == [1, 1, 0], [c.get("unresolved") for c in classes])
check("B2 and the emitted class rows carry it too",
      all("unresolved" in c for c in rep["classes"]), "")

# ------------------------------------------------- C: the draft ----------------
OUT = os.path.join(_tmp, "repairs")
res = selfevolve.issue_drafts(OUT, limit=1, min_severity="info")
name = (res.get("written") or [{}])[0].get("issue")
md = open(os.path.join(OUT, name, "REPAIR.md"), encoding="utf-8").read()
block = md.split("## What fails", 1)[1].split("## The remedy", 1)[0]
check("C1 the draft's `What fails` follows the same order",
      block.index(B) > -1 and block.index(B) < block.index(A), block[:400])

# ------------------------------------------------- D: the cap ----------------
check("D1 the list is capped at three", len(classes) == 3, errors)
check("D2 and the cap keeps both unresolved classes, dropping the smallest recovered one",
      D not in errors and B in errors and C in errors, errors)

print("\n---\nv1111: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
