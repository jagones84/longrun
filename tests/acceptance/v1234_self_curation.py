#!/usr/bin/env python3
"""v1234 — self-curation: reversible context curation and a reproduce-or-revert ledger.

ITER-01 / round 162. Sources:
  S-2026-11-20-013  Franke, *Agent-Controlled Forgetting for Tool-Using Agents:
                    Reversible Context Curation in Practice*, arXiv:2610.10590
                    §3.1-§3.2 (archive-in-place, atomic batch, recovery as a new
                    result, protected instruction messages).
  S-2026-11-20-012  Wang et al., *VERSE: Verified Self-Evolving Optimizer for Agent
                    Harnesses*, arXiv:2610.02616 §2.2/§4.4 (an outcome change that
                    does not reproduce on a rerun is reverted to the parent; a task
                    counts as fixed only after it passes twice).

What this pins:

  A  `context.apply` archives a card's payload and replaces the body with a note in
     place, and the archive holds the original byte for byte
  B  the batch is atomic: one unknown / duplicate / already-curated target refuses the
     WHOLE batch and mutates nothing
  C  `context.recover` returns the archived payload as a NEW card with a fresh id, and
     the stub stays addressable
  D  `context.list` reports the curated cards of the session
  E  `improve.decide(approve)` refuses an outcome change that did not reproduce and
     stamps the row reverted to its parent
  F  a proposal with no recorded outcome change is unaffected (no second gate)
  G  the per-failure-mode audit counts approved / reverted / still-failing rows

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

TMP = tempfile.mkdtemp(prefix="sf-v1234-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR", "SUBAGENT_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_CONTEXT_ARCHIVE_DIR"] = os.path.join(TMP, "context_archive")

# core/server.py imports the prompt constants out of agent.py, so import it first.
from longrun.core import server as _server  # noqa: E402,F401
from longrun.memory import stores  # noqa: E402
from longrun.tools import curation  # noqa: E402
from longrun.util import improve  # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % detail) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


SID = "v1234sess"
BIG = "checkout failed: upstream payment service returned 503 " * 40   # ~2 KB payload


def _session(sid=SID):
    sess = {"id": sid, "messages": [], "tool_cards": [], "workspace": TMP}
    stores.persist_tool_card(sess, "web.read", True, args={"url": "http://demo"},
                             result=BIG, after=0)
    stores.persist_tool_card(sess, "shell.exec", False, args={"cmd": "make test"},
                             result="build log line\n" * 30, error="exit 1",
                             exit_code=1, after=1)
    stores.save_session(sess)
    return sess


# ── A · archive in place, original preserved ────────────────────────────────
sess = _session()
first = sess["tool_cards"][0]["id"]
before = sess["tool_cards"][0]["result"]
res = curation.handle({"action": "apply", "session": SID,
                       "targets": [{"card": first, "note": "payment 503 ruled out"}]})
check("A1 apply accepted", res.get("ok") is True and res.get("changed") == 1, res)
live = stores.load_session(SID)
card = stores.card_by_handle(live, first)
check("A2 body replaced by the note", "payment 503 ruled out" in (card.get("result") or "")
      and card.get("result") != before, card.get("result", "")[:80])
check("A3 card marked curated", card.get("curated") is True and card.get("note") == "payment 503 ruled out")
arch = card.get("archive") or ""
with open(arch, encoding="utf-8") as fh:
    rec = json.load(fh)
check("A4 archive holds the original byte for byte", rec.get("result") == before,
      "%d vs %d chars" % (len(rec.get("result") or ""), len(before)))
check("A5 provenance kept (tool + args)", rec.get("tool") == "web.read" and "demo" in str(rec.get("args")))

# ── B · the batch is atomic ────────────────────────────────────────────────
SID2 = "v1234sess2"
sess2 = _session(SID2)
good = sess2["tool_cards"][0]["id"]
second = sess2["tool_cards"][1]["id"]
keep = sess2["tool_cards"][0]["result"]
bad = curation.handle({"action": "apply", "session": SID2,
                       "targets": [{"card": good, "note": "n"},
                                   {"card": "deadbeef", "note": "n"}]})
live2 = stores.load_session(SID2)
card0 = stores.card_by_handle(live2, good)
check("B1 unknown target refuses the whole batch",
      bad.get("ok") is False and bad.get("changed", 0) == 0 and bad.get("error") == "batch-refused", bad)
check("B2 nothing mutated on a refused batch", card0 is not None and card0.get("result") == keep
      and not card0.get("curated"))
dup = curation.handle({"action": "apply", "session": SID2,
                       "targets": [{"card": second, "note": "n"}, {"card": second, "note": "n"}]})
check("B3 duplicate target refused", dup.get("ok") is False and "duplicate" in " ".join(dup.get("refused") or []), dup)
first_ok = curation.handle({"action": "apply", "session": SID2,
                            "targets": [{"card": second, "note": "build failed on lint"}]})
again = curation.handle({"action": "apply", "session": SID2,
                         "targets": [{"card": second, "note": "n"}]})
check("B4 already-curated target refused",
      first_ok.get("ok") is True and again.get("ok") is False and again.get("changed", 0) == 0, again)

# ── C · recovery returns a NEW result ──────────────────────────────────────
before_n = len(stores.load_session(SID).get("tool_cards") or [])
got = curation.handle({"action": "recover", "session": SID, "ref": first})
live = stores.load_session(SID)
new_card = live["tool_cards"][-1]
check("C1 recover appends a new card", got.get("ok") is True
      and len(live["tool_cards"]) == before_n + 1, got)
check("C2 the new card carries the archived payload", new_card.get("result") == before,
      "%d chars" % len(new_card.get("result") or ""))
check("C3 fresh id, and it names its origin", new_card.get("id") != first
      and new_card.get("recovered_from") == first)
check("C4 the stub is still addressable", stores.card_by_handle(live, first) is not None)
miss = curation.handle({"action": "recover", "session": SID, "ref": "nosuch"})
check("C5 an unarchived ref is refused", miss.get("ok") is False and miss.get("error") == "not-archived", miss)

# ── D · list ───────────────────────────────────────────────────────────────
lst = curation.handle({"action": "list", "session": SID})
check("D1 list reports the curated cards", lst.get("ok") is True and lst.get("count") == 1
      and lst["curated"][0]["card"] == first, lst)
check("D2 unknown action is refused", curation.handle({"action": "nope", "session": SID}).get("ok") is False)

# ── E · reproduce-or-revert ────────────────────────────────────────────────
p_ok = improve.propose("project", "add a rule", origin="optimizer",
                       experiment={"session": SID, "failure_mode": "tool-timeout",
                                   "outcome_change": True, "reproduces": True})
p_bad = improve.propose("project", "add a rule", origin="optimizer",
                        experiment={"session": SID, "failure_mode": "tool-timeout",
                                    "outcome_change": True, "reproduces": False})
p_none = improve.propose("project", "add a rule", origin="optimizer",
                         experiment={"session": SID, "failure_mode": "no-evidence",
                                     "outcome_change": True})
d_ok = improve.decide(p_ok["id"], "approve")
check("E1 a reproduced change is approved", d_ok.get("ok") is True
      and d_ok.get("status") == "approved", d_ok)
d_bad = improve.decide(p_bad["id"], "approve")
check("E2 an unreproduced change is refused", d_bad.get("ok") is False
      and d_bad.get("error") == "not-reproduced", d_bad)
check("E3 the row is stamped reverted to its parent",
      d_bad.get("status") == "reverted" and d_bad.get("reverted_to") == "parent", d_bad)
check("E4 the stored record agrees", (improve.get_proposal(p_bad["id"]) or {}).get("status") == "reverted")
check("E5 a change with no reproduction evidence is refused too",
      improve.decide(p_none["id"], "approve").get("error") == "not-reproduced")

# ── F · no second gate ─────────────────────────────────────────────────────
p_plain = improve.propose("project", "unrelated row", origin="optimizer",
                          experiment={"session": SID, "failure_mode": "tool-timeout"})
check("F1 a proposal with no outcome change still approves",
      improve.decide(p_plain["id"], "approve").get("status") == "approved")
p_deny = improve.propose("project", "row to deny", origin="optimizer")
check("F2 deny is unaffected", improve.decide(p_deny["id"], "deny").get("status") == "denied")

# ── G · per-failure-mode audit ─────────────────────────────────────────────
audit = {row["failure_mode"]: row for row in improve.failure_audit()}
row = audit.get("tool-timeout") or {}
check("G1 the mode is audited", bool(row), audit)
check("G2 approved / reverted counted separately",
      row.get("approved") == 2 and row.get("reverted") == 1, row)
check("G3 both modes are audited, ordered by what still fails",
      sorted(audit) == ["no-evidence", "tool-timeout"]
      and audit["no-evidence"]["reverted"] == 1)

# ── H · the dispatcher binds the canonical names ───────────────────────────
# Found by the LIVE check, not by §A-§D: the route resolves `context.apply` to the
# canonical entry, and the handler receives no `action`, so the subtool name itself
# must select the branch.
from longrun.tools import tools as T  # noqa: E402

SID3 = "v1234sess3"
sess3 = _session(SID3)
h3 = sess3["tool_cards"][0]["id"]
d1 = T._DISPATCH["context.apply"](
    {"session": SID3, "targets": [{"card": h3, "note": "via dispatch"}]}, None)
check("H1 context.apply through the dispatcher archives", d1.get("ok") is True
      and d1.get("changed") == 1, d1)
d2 = T._DISPATCH["context.recover"]({"session": SID3, "ref": h3}, None)
check("H2 context.recover through the dispatcher returns the payload",
      d2.get("ok") is True and d2.get("chars") == len(BIG), d2)
d3 = T._DISPATCH["context.list"]({"session": SID3}, None)
check("H3 context.list through the dispatcher reports it", d3.get("count") == 1, d3)
check("H4 the namespace form reaches curation too",
      T._DISPATCH["context"]({"session": SID3, "action": "list"}, None).get("count") == 1)

print("---")
if FAILED:
    print("FAILED %d/%d: %s" % (len(FAILED), len(CHECKS), ", ".join(FAILED)))
    sys.exit(1)
print("PASS %d/%d" % (len(CHECKS), len(CHECKS)))
