#!/usr/bin/env python3
"""v492 — the LLM backlog audit: obsolete / implemented / needs an update (JAG-491).

The self-improvement backlog (rule/skill proposals + distilled lessons) grows on
its own. This test pins the audit feature:

  A. artifact collection: proposals + non-user memory, deduped, bounded;
  B. the lenient JSON verdict parser (prose, fences, nested braces in strings);
  C. review(): counts, unknown ids, rewritten text only for `update`, a persisted
     report and one audit-ledger entry — with the model STUBBED;
  D. the `improve` base tool exposes `scope=review` (any session agent can call it);
  E. the panel button + endpoint wiring.

Deterministic: no network, no model.

Run: python3 tests/acceptance/v492_improvement_review.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v492-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for d in ("data", "sessions"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import improve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(name):
    with open(os.path.join(REPO, name), encoding="utf-8") as f:
        return f.read()


# ---- A) artifact collection -------------------------------------------------
_props = [
    {"id": "p1", "scope": "project", "content": "Always run pytest -q",
     "origin": "agent", "status": "pending", "reason": "tests"},
    {"id": "p2", "scope": "project", "content": "Always run pytest -q",
     "origin": "agent", "status": "denied", "reason": "dup"},     # same text -> dedupe
    {"id": "p3", "scope": "skill", "content": "mine a build skill",
     "origin": "mining", "status": "pending", "reason": ""},
]
_mem = [
    {"mid": "m1", "kind": "note", "content": "the verifier rolls back on red",
     "source": "reflect"},
    {"mid": "m2", "kind": "note", "content": "I prefer tabs", "source": "user"},
    {"mid": "m3", "kind": "pref", "content": "keep answers short", "source": ""},
]
_orig_props = improve.list_proposals
_orig_query = None
try:
    from longrun.memory import memory as memory_mod
    _orig_query = memory_mod.query
    memory_mod.query = lambda *a, **k: list(_mem)
    improve.list_proposals = lambda status=None: list(_props)
    items = improve._artifact_items(limit=20)
    limited = improve._artifact_items(limit=2)
finally:
    improve.list_proposals = _orig_props
    if _orig_query is not None:
        memory_mod.query = _orig_query
ids = [i["id"] for i in items]
check("A1 proposals are collected and exact duplicates collapse",
      ids.count("p1") == 1 and "p2" not in ids and "p3" in ids, ids)
check("A2 user memory is out of scope, unattributed memory is kept",
      "m2" not in ids and "m3" in ids and "m1" in ids, ids)
check("A3 the limit is honoured", len(limited) == 2, len(limited))

# ---- B) lenient JSON parsing ------------------------------------------------
_prose = ('Sure! Here is the audit:\n```json\n'
          '{"verdicts":[{"id":"p1","verdict":"implemented","confidence":0.9,'
          '"why":"v489 already proves it {curly}"}]}\n```\nHope it helps.')
_v = improve._parse_verdicts(_prose)
check("B1 JSON inside prose/fences is parsed", len(_v) == 1 and _v[0]["id"] == "p1", _v)
_v = improve._parse_verdicts('[{"id":"x","verdict":"keep"}]')
check("B2 a bare array is accepted", _v and _v[0]["verdict"] == "keep", _v)
check("B3 garbage yields no verdicts", improve._parse_verdicts("no json here") == [])

# ---- C) review() with a stubbed model --------------------------------------
_orig_ev, _orig_batch = improve._evidence, improve._review_batch
_orig_items = improve._artifact_items


def _fake_batch(batch, model):
    out = []
    for it in batch:
        if it["id"] == "m4":
            continue                        # simulate a skipped artifact
        verdict = {"p1": "implemented", "p3": "update"}.get(it["id"], "keep")
        out.append({"id": it["id"], "verdict": verdict, "confidence": 0.8,
                    "why": "stub evidence",
                    "rewritten": "NEW TEXT" if verdict == "update" else ""})
    return out, "stub:model"


try:
    improve._evidence = lambda text, k=3: [{"path": "src/x.py", "line": 3,
                                            "snippet": "proof"}]
    improve._review_batch = _fake_batch
    improve._artifact_items = lambda limit=40: [
        {"id": "p1", "kind": "proposal", "scope": "project", "origin": "agent",
         "text": "Always run pytest -q", "reason": "", "target": ""},
        {"id": "p3", "kind": "proposal", "scope": "skill", "origin": "mining",
         "text": "mine a build skill", "reason": "", "target": ""},
        {"id": "m3", "kind": "memory", "scope": "pref", "origin": "unattributed",
         "text": "keep answers short", "reason": "", "target": "data/memory"},
        {"id": "m4", "kind": "memory", "scope": "note", "origin": "reflect",
         "text": "an artifact the model forgets", "reason": "", "target": ""},
    ]
    rep = improve.review(limit=10, model="stub:model")
finally:
    improve._evidence, improve._review_batch = _orig_ev, _orig_batch
    improve._artifact_items = _orig_items
by = {i["id"]: i for i in rep["items"]}
check("C1 the review is OK and carries every artifact", rep["ok"] and len(rep["items"]) == 4, rep.get("error"))
check("C2 verdicts are counted", rep["counts"]["implemented"] == 1
      and rep["counts"]["update"] == 1 and rep["counts"]["keep"] == 1, rep["counts"])
check("C3 a skipped artifact is counted as unrated", rep["unrated"] == 1, rep["unrated"])
check("C4 rewritten text is kept only for update",
      by["p3"]["rewritten"] == "NEW TEXT" and by["p1"]["rewritten"] == "", by)
check("C5 evidence is attached to every item",
      all(i.get("evidence") for i in rep["items"]))
check("C6 the report is persisted and reloadable by latest_review",
      rep.get("report") and os.path.isfile(rep["report"])
      and (improve.latest_review() or {}).get("items") is not None)
_led = [e for e in improve.ledger_tail(50) if e.get("kind") == "review"]
check("C7 one audit-ledger entry records the run",
      bool(_led) and _led[0].get("reviewed") == 4, _led[:1])

# ---- D) the base tool exposes the review -----------------------------------
from longrun.tools import tools as toolmod  # noqa: E402
_orig_review = improve.review
try:
    improve.review = lambda limit=0, model=None: {
        "ok": True, "counts": {"obsolete": 1}, "unrated": 0, "model": "stub:model",
        "report": "/tmp/x.json",
        "items": [{"id": "p1", "kind": "proposal", "scope": "project",
                   "verdict": "obsolete", "confidence": 0.9,
                   "why": "replaced by JAG-490", "rewritten": ""}]}
    got = toolmod._improve({"scope": "review", "limit": 5}, "run-v492")
finally:
    improve.review = _orig_review
check("D1 the improve tool runs a review and returns a readable report",
      got.get("ok") and got.get("counts", {}).get("obsolete") == 1
      and "obsolete" in (got.get("stdout") or ""), got)
TOOLS_SRC = _read("src/longrun/tools/tools.py")
check("D2 action=review works without scope=review",
      'scope == "review" or action == "review"' in TOOLS_SRC)
REG = _read("src/longrun/tools/registry.py")
check("D3 the tool schema documents scope/action=review",
      '"review"' in REG and "limit" in REG and "backlog" in REG)

# ---- E) panel + endpoint wiring --------------------------------------------
UI = _read("webui/index.html")
API = _read("src/longrun/core/httpapi.py")
check("E1 POST /api/improvement/review exists",
      '"/api/improvement/review"' in API)
check("E2 GET /api/improvement returns the last review",
      '"review": improve_mod.latest_review()' in API)
check("E3 the panel has the button and renders the verdicts",
      "runImprovementReview" in UI and "impReview" in UI
      and "review with LLM" in UI)
check("E4 a rewrite is shown for update verdicts", "rewritten" in UI)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
