#!/usr/bin/env python3
"""v727 — the abstraction step: a repeat is NAMED before it becomes code (EV-22).

The operator's diagnosis of ring ③: "il forge produce bundle da pattern di
sequenza, non capisce il significato". `selfevolve.abstract` is now the ONE
single-shot call that reads a repeated sequence as a PROCEDURE and answers
`{compact, name, goal, why, confidence}` (arXiv 2606.02994 ARISE; Agent Workflow
Memory: a workflow is a goal + a routine). The record lands on the draft, and
`forge_from_draft` names the module after the MEANING.

  A  a capability is named, recorded on the draft, and its namespace is semantic
  B  a habit/retry is refused and offers no name at all
  C  the answer is parsed out of prose and never trusted (name, confidence, goal)
  D  every failure is a verdict, and a dead model fails OPEN on naming
  E  the forge USES the name (module + description), and the tool is live
  F  evolve honours the verdict, the bound, and falls back to the step name
  G  measurement: what the step changes (precision of what becomes code)

Deterministic: the model is a queue of scripted answers (no network, no router).
Section G's judge is SIMULATED on purpose — it measures the lane's plumbing
(filter honoured, name used, bound respected), not a model's accuracy.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v727-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.environ["LONGRUN_MATRIX_SRC"] = os.path.join(TMP, "src", "Matrix")
os.environ["LONGRUN_MATRIX_DOT"] = os.path.join(TMP, ".Matrix")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve as SE  # noqa: E402
from longrun.util import improve  # noqa: E402
from longrun.core import matrix as MTX  # noqa: E402
from longrun.tools import registry  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


def set_selfevolve(**kw):
    cfg = registry.load_config()
    sec = cfg.setdefault("selfevolve", {})
    sec.update(kw)
    registry.save_config(cfg)
    registry.load_config(reload=True)


def set_matrix_policy(value):
    cfg = registry.load_config()
    kinds = cfg.setdefault("approvals", {}).setdefault("kinds", {})
    if value:
        kinds["matrix"] = value
    else:
        kinds.pop("matrix", None)
    registry.save_config(cfg)
    registry.load_config(reload=True)


def queue(answers):
    """A scripted model: one reply per call, and the calls are counted."""
    seen = []

    def call(msgs, model, timeout):
        seen.append(str(msgs[1]["content"]))
        return answers[min(len(seen) - 1, len(answers) - 1)], "fake-reviewer"

    return call, seen


P1 = ["fs.read", "fs.edit", "shell.exec"]
P2 = ["fs.read", "fs.write", "memory.recall"]
D = improve.DRAFT_DIR
CAP = ('{"compact": true, "name": "Repo Edit And Test", '
       '"goal": "Edit a file and run its tests.", '
       '"why": "the same three calls repeated in 4 runs", "confidence": 0.9}')
NOT = ('{"compact": false, "name": "", "goal": "", '
       '"why": "the sequence is one tool retried", "confidence": 0.4}')
HASH = SE._forge_slug(P1).rsplit("_", 1)[-1]

# ------------------------------------- A: a capability is named ----------
d1 = SE.draft(P1, 4, D)
call, seen = queue([CAP])
r = SE.abstract(P1, support=4, draft=d1, call=call)
check("A1 one call, one verdict", r.get("ok") is True and len(seen) == 1, r)
check("A2 the name is snake_case", r.get("name") == "repo_edit_and_test", r)
check("A3 the namespace is semantic and sequence-bound",
      r.get("namespace") == "learned_repo_edit_and_test_" + HASH, r.get("namespace"))
check("A4 goal, why and confidence survive normalisation",
      r.get("goal") == "Edit a file and run its tests."
      and r.get("confidence") == 0.9 and bool(r.get("why")), r)
stored = SE.draft_abstract(d1)
check("A5 the record is ON the draft", stored.get("name") == "repo_edit_and_test"
      and stored.get("compact") is True, stored)
try:
    prop = json.load(open(os.path.join(d1, "proposal.json"), encoding="utf-8"))
except (OSError, ValueError):
    prop = {}
check("A6 the draft now states its purpose", prop.get("purpose") == "Edit a file and run its tests.",
      prop.get("purpose"))
check("A7 the prompt carried the sequence and every step name",
      all(t in seen[0] for t in P1) and "repeated_across_runs" in seen[0], seen[0][:240])

# ------------------------------------- B: a habit is refused -------------
d2 = SE.draft(P2, 3, D)
call, seen = queue([NOT])
r2 = SE.abstract(P2, support=3, draft=d2, call=call)
check("B1 a retry is not a capability", r2.get("ok") is True and r2.get("compact") is False, r2)
check("B2 no name and no namespace are offered",
      r2.get("name") == "" and r2.get("namespace") == "", r2)
check("B3 the verdict says why", "retried" in str(r2.get("why")), r2)
check("B4 the draft keeps no goal", not SE.draft_abstract(d2).get("goal"), SE.draft_abstract(d2))

# ------------------------------------- C: never trust the text -----------
NOISY = ('Sure! Here it is:\n```json\n{"compact": true, "name": "../../ETC Passwd!", '
         '"goal": "  Do   the thing  ", "why": "x", "confidence": 7}\n```\nDone.')
call, _ = queue([NOISY])
r3 = SE.abstract(P1, call=call, write=False)
check("C1 prose and a fenced block are still parsed", r3.get("ok") is True, r3)
check("C2 a hostile name is sanitised", r3.get("name") == "etc_passwd", r3)
check("C3 confidence is clamped to 1.0", r3.get("confidence") == 1.0, r3)
check("C4 whitespace in the goal is collapsed", r3.get("goal") == "Do the thing", r3)


# ------------------------------------- D: every failure is a verdict ----
def _boom(msgs, model, timeout):
    raise RuntimeError("router down")


r4 = SE.abstract(P1, call=_boom, write=False)
check("D1 a dead model fails OPEN on naming",
      r4.get("ok") is False and r4.get("compact") is True, r4)
check("D2 the error says what happened", "router down" in str(r4.get("error")), r4)
call, _ = queue(["I cannot help with that."])
r5 = SE.abstract(P1, call=call, write=False)
check("D3 an answer with no JSON is a verdict, not a crash",
      r5.get("ok") is False and bool(r5.get("error")), r5)
r6 = SE.abstract(["fs.read"], call=queue([CAP])[0])
check("D4 a single step is refused before any call",
      r6.get("ok") is False and bool(r6.get("error")), r6)

# ------------------------------------- E: the forge uses the name --------
d3 = SE.draft(P1, 5, D)
SE.abstract(P1, support=5, draft=d3, call=queue([CAP])[0])
fr = SE.forge_from_draft(d3)
ns = str(fr.get("namespace") or "")
check("E1 the forged module is named after the capability",
      ns == "learned_repo_edit_and_test_" + HASH and fr.get("ok") is True, fr)
try:
    body = open(fr.get("path") or "", encoding="utf-8").read()
except OSError:
    body = ""
check("E2 the description is the stated goal", "Edit a file and run its tests." in body, body[:200])
check("E3 the semantic tool is live and discovered",
      ("%s.run" % ns) in MTX.discover_tools(), sorted(MTX.discover_tools())[:8])
check("E4 the recorded draft points at that namespace",
      str((SE.draft_abstract(d3) or {}).get("namespace")) == ns, SE.draft_abstract(d3))
MTX.remove("tool", ns)

# ------------------------------------- F: evolve honours the verdict ----
_old_mine, _old_pipe = SE.mine, SE.pipeline


def _pipe(pattern, out, support=0, **kw):
    return {"ok": True, "dir": SE.draft(pattern, support, out) or "",
            "verify": {"green": True}, "archived": None}


SE.mine = lambda hist, c: [{"pattern": list(P1), "support": 3},
                           {"pattern": list(P2), "support": 3}]
SE.pipeline = _pipe
_old_ss = improve.single_shot


def _scripted(answers):
    def ss(msgs, model=None, role="reviewer", timeout=180, max_tokens=4000):
        ss.calls += 1
        return answers[min(ss.calls - 1, len(answers) - 1)], "fake-reviewer"
    ss.calls = 0
    return ss


try:
    improve.single_shot = _scripted([CAP])
    set_matrix_policy("")
    set_selfevolve(abstract_on_evolve=True, abstract_per_run=1,
                   forge_on_evolve=True, forge_per_run=1)
    rep = improve.evolve_once(allow_code=True)
    check("F1 the abstraction bound is one call", improve.single_shot.calls == 1,
          improve.single_shot.calls)
    check("F2 the report carries the abstraction",
          (rep[0].get("abstract") or {}).get("name") == "repo_edit_and_test", rep[0])
    check("F3 the forged tool carries the semantic name",
          (rep[0].get("matrix") or {}).get("matrix_tool")
          == "learned_repo_edit_and_test_%s.run" % HASH, rep[0].get("matrix"))
    MTX.remove("tool", "learned_repo_edit_and_test_%s" % HASH)
    # The verdict that says "not a capability" must stop the forge — and the lane
    # must still name/forge the NEXT pattern with the derived name (fail-open).
    improve.single_shot = _scripted([NOT])
    rep2 = improve.evolve_once(allow_code=True)
    check("F4 a refusal spends the naming bound, not the forge bound",
          str((rep2[0].get("matrix") or {}).get("skipped", ""))
          .startswith("not a capability"), rep2[0])
    check("F5 the next pattern is still forged without a name",
          (rep2[1].get("matrix") or {}).get("matrix_tool")
          == "learned_%s.run" % SE._forge_slug(P2), rep2[1].get("matrix"))
    check("F6 nothing with a refused name landed in the zone",
          not [n for n in MTX.discover_tools() if "repo_edit" in n],
          sorted(MTX.discover_tools())[:8])
finally:
    improve.single_shot = _old_ss
    SE.mine, SE.pipeline = _old_mine, _old_pipe
    set_selfevolve(abstract_on_evolve=True, abstract_per_run=1)

# ------------------------------------- G: what the step changes ----------
# A labelled corpus of eight repeats. The judge is simulated from the label, so
# the table measures the LANE (does a "no" really stop code? does a "yes" really
# name it?), not a model's accuracy — and the honest headline is that the lane's
# precision becomes the judge's, where before it was 3/8.
CORPUS = [
    (["fs.read", "fs.edit", "shell.exec"], True, "edit_and_test"),
    (["fs.read", "fs.write", "memory.recall"], True, "write_and_remember"),
    (["web.search", "web.fetch", "fs.write"], True, "research_and_save"),
    (["fs.read", "fs.read", "fs.read"], False, ""),
    (["shell.exec", "shell.exec"], False, ""),
    (["fs.read", "fs.write", "fs.read", "fs.write"], False, ""),
    (["memory.recall", "memory.recall"], False, ""),
    (["web.search", "web.search", "web.search"], False, ""),
]


def _judge(seq, label):
    if not label:
        return NOT
    return json.dumps({"compact": True, "name": seq[0].split(".")[0] + "_and_more",
                       "goal": "A capability for %s." % seq[0], "why": "repeated",
                       "confidence": 0.8})


called = {"n": 0}


def _corpus_call(msgs, model, timeout):
    payload = json.loads(msgs[1]["content"])
    seq = payload.get("sequence") or []
    for row in CORPUS:
        if row[0] == seq:
            called["n"] += 1
            return _judge(seq, row[1]), "fake-reviewer"
    return NOT, "fake-reviewer"


rows, tp, fp, fn, named = [], 0, 0, 0, 0
for seq, is_cap, _tag in CORPUS:
    got = SE.abstract(seq, support=4, call=_corpus_call, write=False)
    took = bool(got.get("ok") and got.get("compact"))
    if took and is_cap:
        tp += 1
    elif took and not is_cap:
        fp += 1
    elif is_cap and not took:
        fn += 1
    if took:
        named += 1 if str(got.get("name") or "") else 0
    rows.append((len(seq), is_cap, took, str(got.get("name") or "")[:26]))
prec = tp / float(tp + fp) if (tp + fp) else 0.0
rec = tp / float(tp + fn) if (tp + fn) else 0.0
print("  steps  capability  became_code  name")
for n, is_cap, took, nm in rows:
    print("  %5d  %-10s  %-11s  %s" % (n, is_cap, took, nm or "-"))
print("  judged=%d precision=%.2f recall=%.2f named=%d/%d (before the step: 8/8 "
      "became code, precision 0.38)" % (called["n"], prec, rec, named, tp + fp))
check("G1 every sequence was judged", called["n"] == len(CORPUS), called["n"])
check("G2 nothing labelled a habit became code", fp == 0, rows)
check("G3 every capability was kept", fn == 0, rows)
check("G4 every kept capability carries a name", named == tp and tp == 3, rows)

bad = [r for r in results if not r]
print("%d/%d checks passed" % (len(results) - len(bad), len(results)))
sys.exit(1 if bad else 0)
