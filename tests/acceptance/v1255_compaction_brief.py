#!/usr/bin/env python3
"""v1255 — the compaction must carry the work (round 165).

Sources (2026-11-19 batch, read in full from the archive):
  S-2026-11-22-005  Chen et al., *CompAct-Bench: A Benchmark for Working-Context
                    Compaction in Long-Horizon Agent Tasks*, arXiv:2611.25673 —
                    200 solved-before trajectories, 56.7% average post-compaction
                    accuracy (best 68.5%); omissions and distortions are the two
                    failure pathways.
  S-2026-11-22-006  Tian et al., *Context as a Resource (ClonAct)*, arXiv:2611.26346
                    — isolated branches pass while the merge collapses (33.3%).
  S-2026-11-22-007  Liu et al., *MemFolder*, arXiv:2611.26427 — pruning discards
                    evidence; folding keeps 99.0% at 50% fewer records.
  S-2026-11-22-008  Pan et al., *DriftGuard*, arXiv:2611.25583 — content features
                    are not causal; attribution needs replays, so this check is
                    retention, never salience.

What this pins:

  A  the anchors: the task statement (never a `[harness]` turn), its hard
     constraints, the last failure and the named paths
  B  the audit: complete / lossy / warnings / no-anchors
  C  the carry-forward block names what is missing and `fit` puts it in the
     summary the continuation reads, once
  D  the per-session ledger is append-only and joins the delete cascade
  E  the forge group runs headless
  F  the live seam audits BEFORE the compacted list is saved

Deterministic: temp stores, no model, no network, no server.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

TMP = tempfile.mkdtemp(prefix="sf-v1255-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR", "SUBAGENT_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")

from longrun.core import server as _server  # noqa: E402,F401
from longrun.harness import compaction_brief as cb  # noqa: E402
from longrun.memory import stores  # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


TASK = ("Please fix the parser in `src/p.py`. You must never touch the production "
        "database. Never rewrite git history.")
MSGS = [{"role": "user", "content": "[harness] continue"},
        {"role": "user", "content": TASK},
        {"role": "assistant", "content": "working"}]
CARDS = [{"ok": False, "args": {"command": "pytest -q tests"},
          "error": "FAILED test_parse - assertion error"}]

# ── A · the anchors ─────────────────────────────────────────────────────────
rec = cb.anchors(MSGS, CARDS)
kinds = [a["kind"] for a in rec["anchors"]]
check("A1 the task statement is the first real user turn",
      rec["anchors"][0]["kind"] == "task" and rec["anchors"][0]["text"] == TASK,
      rec["anchors"][0]["text"][:60])
check("A2 a [harness] turn is not the task",
      all("[harness]" not in a["text"] for a in rec["anchors"]))
check("A3 both hard constraints are anchors", kinds.count("constraint") == 2, kinds)
check("A4 the last failure carries its command",
      any(a["kind"] == "last-error" and "pytest" in a["text"] for a in rec["anchors"]))
check("A5 mechanical paths are not duplicated here (context_engine owns them)",
      "path" not in kinds, kinds)
check("A6 no task means no anchors",
      cb.anchors([{"role": "user", "content": "[harness] x"}], [])["anchors"] == [])
# 2026-11-22 (review): the old 40-char gate dropped a concise instruction — exactly
# the task the feature exists to carry — so it produced no anchor at all.
SHORT = "Fix the crash in src/x.py."
sr = cb.anchors([{"role": "user", "content": SHORT}], [])
check("A7 a concise task is still the anchor (no length gate)",
      bool(sr["anchors"]) and sr["anchors"][0]["kind"] == "task"
      and sr["anchors"][0]["text"] == SHORT, json.dumps(sr["anchors"])[:160])

# ── B · the audit ───────────────────────────────────────────────────────────
GOOD = [{"role": "system", "content":
         "Summary: please fix the parser in src/p.py. You must never touch the "
         "production database. Never rewrite git history. Last failure: pytest -q "
         "tests — FAILED test_parse - assertion error."}]
r = cb.audit(MSGS, GOOD, CARDS)
check("B1 a summary that carries every key is complete", r["verdict"] == "complete",
      json.dumps(r["missing"])[:160])
BAD = [{"role": "system", "content": "Summary: unrelated work on styling."}]
r = cb.audit(MSGS, BAD, CARDS)
check("B2 a summary that lost the task is lossy",
      r["verdict"] == "lossy" and any(a["kind"] == "task" for a in r["missing_critical"]),
      r["verdict"])
r2 = cb.audit(MSGS, [{"role": "system", "content":
                      "Summary: please fix the parser in src/p.py. You must never "
                      "touch the production database. Never rewrite git history."}], [])
check("B3 a summary that carries the task and constraints has no critical miss",
      r2["verdict"] in ("warnings", "complete") and not r2["missing_critical"],
      r2["verdict"])
check("B4 an empty history has no anchors", cb.audit([], GOOD, [])["verdict"] == "no-anchors")

# ── C · the carry-forward ──────────────────────────────────────────────────
carry = r["carry"]
check("C1 the carry names the task and the last failure",
      "carry-forward" in carry and "src/p.py" in carry and "pytest" in carry,
      carry[:140])
check("C2 the carry is bounded", len(carry) <= 1200, len(carry))
post = [{"role": "system", "content": "Summary: unrelated work."},
        {"role": "assistant", "content": "ok"}]
check("C3 fit appends to exactly one system summary", cb.fit(post, r) == 1)
check("C4 the continuation now sees the task phrase",
      "please fix the parser" in post[0]["content"].lower())
check("C5 fit is a no-op when nothing is missing",
      cb.fit([{"role": "system", "content": "s"}], {"carry": ""}) == 0)

# ── D · the ledger ─────────────────────────────────────────────────────────
SID = "v1255sess"
p = stores.append_compaction_audit(SID, cb.audit(MSGS, BAD, CARDS))
check("D1 the audit lands in a per-session jsonl",
      bool(p) and p.endswith(".compactions.jsonl"), p)
rows = [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]
check("D2 the row keeps the verdict and a timestamp",
      rows and rows[0]["verdict"] == "lossy" and "ts" in rows[0])
# 2026-11-22 (review): a large audit must stay valid JSONL — the old bound sliced
# the serialised text and could split a string.
big = {"verdict": "lossy", "anchors": 3,
       "missing": [{"kind": "task", "text": "z" * 5000} for _ in range(10)]}
p = stores.append_compaction_audit(SID, big)
lines = [x for x in open(p, encoding="utf-8") if x.strip()]
try:
    parsed = [json.loads(x) for x in lines]
except Exception:  # noqa: BLE001 — the point of the check
    parsed = []
check("D3 a large record is still valid JSONL, never a byte slice",
      len(parsed) == len(lines) and parsed[-1].get("truncated") is True,
      "%d lines, %d parsed" % (len(lines), len(parsed)))
stores._purge_session_artifacts(SID)
check("D4 the ledger joins the delete cascade", not os.path.exists(p))

# ── E · the forge group ────────────────────────────────────────────────────
import subprocess  # noqa: E402
doc = os.path.join(TMP, "brief.json")
with open(doc, "w", encoding="utf-8") as fh:
    json.dump({"messages": MSGS, "after": BAD, "tool_cards": CARDS}, fh)
env = dict(os.environ, PYTHONPATH=SRC)
out = subprocess.run([sys.executable, os.path.join(SRC, "longrun", "core", "forge.py"),
                      "compaction", "audit", doc], capture_output=True, text=True,
                     env=env, timeout=60)
check("E1 compaction audit runs headless",
      out.returncode == 0 and '"verdict": "lossy"' in out.stdout, out.stdout[:160])

# ── F · the live seam ──────────────────────────────────────────────────────
api = open(os.path.join(SRC, "longrun", "core", "httpapi.py"), encoding="utf-8").read()
at = api.find('sess["messages"] = msgs')
before = api[:at]
check("F1 the brief is audited before the compacted list is saved",
      "compaction_brief.audit(messages, msgs" in before[-4000:])
check("F2 a missing critical anchor is repaired, not just logged",
      "compaction_brief.fit(msgs" in before[-4000:])
check("F3 the compaction cannot be broken by the brief",
      'stats["carry_forward"]' in before[-4000:]
      and "except Exception" in before[-4000:])

print("\n%d/%d checks passed" % (len(CHECKS) - len(FAILED), len(CHECKS)))
if FAILED:
    print("FAILED: " + ", ".join(FAILED))
    sys.exit(1)
