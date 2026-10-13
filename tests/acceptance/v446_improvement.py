#!/usr/bin/env python3
"""v446 — self-improvement: effective, segregated, auditable, visible (JAG-447).

The old `improve.nudge` was cosmetic: the MODEL never saw it (it was only an SSE
event), the USER had nothing to click, and the improvement products (distilled
lessons, rule/skill proposals) were neither segregated from user knowledge nor
recorded anywhere. This pins the new contract:

  A) PROVENANCE   — every improvement product carries an `origin`
                    (user|agent|reflect|mining|harness).
  B) LEDGER       — every artifact the loop writes is appended to the audit
                    ledger, newest-first on read, bounded.
  C) DIFF PREVIEW — approving a rule proposal shows the exact append patch; a
                    skill proposal tells the truth (not applied on approve).
  D) DECIDE       — approve appends the rule + ledgers; deny ledgers.
  E) LIST FILTER  — list_proposals(status=...) + newest-first.
  F) PROVENANCE   — memory groups auto-generated vs. user-authored.
  G) SEGREGATION  — the prompt injects user facts and self lessons in two
                    clearly-labelled buckets.
  H) IMPORTANCE   — the harness-computed gate + correction detector.
  I) EFFECTIVE    — the end-of-turn pass distills a lesson (when significant) and
                    emits an ENRICHED nudge carrying what was written + is ledgered.
  J) WIRING       — the /api/improvement route and the WebUI panel exist.

Deterministic, no model, no server. Run: python3 tests/acceptance/v446_improvement.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v446-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_REQUIRE_HELDOUT"] = "0"   # not the scope of this test
for d in ("cfg", "data", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import improve                     # noqa: E402
from longrun.memory import memory, rules             # noqa: E402
from longrun.model import prompt                     # noqa: E402
from longrun.core import server                      # noqa: E402
from longrun.agent import agent as agent_mod         # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# isolate the memory store in the temp dir (memory.py anchors DATA_DIR at import,
# so patch the module globals — the same trick v204 uses)
memory.DATA_DIR = os.path.join(TMP, "memory")
memory.CORE_PATH = os.path.join(memory.DATA_DIR, "core.md")
os.makedirs(memory.DATA_DIR, exist_ok=True)
WS = os.path.join(TMP, "ws")
os.makedirs(WS, exist_ok=True)

# ---------------------------------------------------------------- A provenance
rec = improve.propose("project", "- Preferisci il tema Kindle", reason="r", ws=WS)
check("A1 propose stamps origin=agent by default", rec.get("origin") == "agent", rec)
rec2 = improve.propose("skill", "pattern x", origin="mining")
check("A2 an explicit origin is kept", rec2.get("origin") == "mining")

# ---------------------------------------------------------------- B ledger
tail = improve.ledger_tail(50)
check("B1 a proposal appends a ledger entry",
      any(e.get("kind") == "proposal" and e.get("proposal") == rec["id"] for e in tail))
check("B2 ledger_tail is newest-first",
      len(tail) >= 2 and tail[0].get("ts", 0) >= tail[-1].get("ts", 0))
check("B3 every ledger entry carries an origin", all("origin" in e for e in tail))
_omax = improve.LEDGER_MAX
improve.LEDGER_MAX = 5
for i in range(12):
    improve.ledger_add("test", origin="harness", i=i)
check("B4 the ledger is bounded to LEDGER_MAX", len(improve.ledger_tail(100)) <= 5)
improve.LEDGER_MAX = _omax

# ---------------------------------------------------------------- C diff preview
pv = improve.diff_preview(rec)
check("C1 a project proposal previews the append diff",
      pv.get("applies") is True and pv.get("added", 0) >= 1 and "Kindle" in pv.get("diff", ""),
      pv.get("added"))
pv2 = improve.diff_preview(rec2)
check("C2 a skill preview is HONEST (not applied on approve)", pv2.get("applies") is False)

# ---------------------------------------------------------------- D decide
d = improve.decide(rec["id"], "approve")
rp = rules.project_rules_path(WS)
on_disk = ""
try:
    with open(rp, encoding="utf-8") as f:
        on_disk = f.read()
except OSError:
    pass
check("D1 approving a project proposal appends the rule",
      d.get("ok") is True and "Kindle" in on_disk, rp)
check("D2 the approve decision is ledgered",
      any(e.get("kind") == "decide" and e.get("decision") == "approve"
          and e.get("proposal") == rec["id"] for e in improve.ledger_tail(50)))
dn = improve.decide(rec2["id"], "deny")
check("D3 deny works and is ledgered",
      dn.get("ok") is True and any(e.get("kind") == "decide" and e.get("decision") == "deny"
                                   for e in improve.ledger_tail(50)))
check("D4 a decided proposal leaves the pending list",
      all(p["id"] != rec["id"] for p in improve.list_proposals(status="pending")))

# ---------------------------------------------------------------- E list filter
check("E1 list_proposals(status='approved') returns the decided one",
      any(p["id"] == rec["id"] for p in improve.list_proposals(status="approved")))

# ---------------------------------------------------------------- F memory prov.
memory.store("memory.store", "All'utente piace il tema Kindle", origin="user", source="user")
memory.store("agent.note", "lesson: usa docling per i PDF scansionati",
             origin="reflect", source="reflect")
prov = memory.provenance()
check("F1 provenance counts the auto bucket", prov.get("auto", 0) >= 1, prov)
check("F2 provenance counts the user bucket", prov.get("user", 0) >= 1)
check("F3 provenance groups by source", "reflect" in prov.get("by_source", {}))

# ---------------------------------------------------------------- G segregation
blk = prompt._provider_memory(None, None, None)
check("G1 the prompt labels USER facts", "user facts" in blk, blk[:120])
check("G2 the prompt labels SELF-distilled lessons", "self-distilled lessons" in blk)
check("G3 both buckets are separate sections", blk.count("## Memory") == 2, blk.count("## Memory"))

# ---------------------------------------------------------------- H importance
check("H1 a correction is detected", server._is_correction("no, non va bene cosi") is True)
check("H2 a normal message is not a correction",
      server._is_correction("grazie, procedi pure") is False)
check("H3 importance grows with errors + tools + steps",
      server._turn_importance(["a", "b", "c", "d", "e"], True, False, 3) >= 11)
check("H4 a trivial turn scores below the threshold",
      server._turn_importance([], False, False, 0) < improve.IMPORTANCE_THRESHOLD)

# ---------------------------------------------------------------- I effective pass
events = []
agent_mod.publish = lambda ev, **kw: events.append({"ev": ev, **kw})
agent_mod.maybe_reflect = lambda *a, **k: "Preferisci il tema Kindle per sessioni lunghe."
sess = {"id": "imp446", "messages": []}
server._improvement_pass(sess, "fai X", "fatto", ["t"] * 6, 4, "m", {})
nud = [e for e in events if e["ev"] == "improve.nudge"]
check("I1 the pass emits an enriched improve.nudge", len(nud) == 1, nud)
check("I2 the nudge carries the harness importance score", nud and nud[0].get("importance", 0) >= 5)
check("I3 the nudge lists what was written (origin=reflect)",
      nud and any(w.get("origin") == "reflect" for w in nud[0].get("wrote", [])))
check("I4 the turn is recorded in the audit ledger",
      any(e.get("kind") == "turn" for e in improve.ledger_tail(20)))

called = {"n": 0}


def _mr(*a, **k):
    called["n"] += 1
    return "x"


agent_mod.maybe_reflect = _mr
server._improvement_pass(sess, "ciao", "ciao", [], 0, "m", {})
check("I5 a trivial turn does NOT reflect (the gate holds)", called["n"] == 0)

# ---------------------------------------------------------------- J wiring
with open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8") as f:
    _htt = f.read()
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    _idx = f.read()
check("J1 GET /api/improvement is registered", '"/api/improvement"' in _htt)
check("J2 the WebUI has an Improvement panel (Settings category)",
      'data-cat="improvement"' in _idx and "impRecords" in _idx)
check("J3 the WebUI loads /api/improvement", '"/api/improvement"' in _idx)
check("J4 the WebUI renders the enriched nudge (wrote) ",
      "improve.nudge" in _idx and "wrote" in _idx)

print("---")
ok = sum(results)
print("\nv446: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)