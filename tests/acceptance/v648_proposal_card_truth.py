#!/usr/bin/env python3
"""v648 — an approval card must say WHAT it decides, and only while it is open.

Source (operator, on a screenshot full of identical proposal cards): "la lista di
approve senza scrivere COSA devo approvare? e perche no appaiono dentro approvals
nel RH panel? e inoltre non posso approvare".

Three defects behind that one screen:

  1. `improve.proposal` and `approval.request` were bound on BOTH the per-turn
     stream and the always-on feed stream, so every proposal rendered TWICE
     (five identical cards on screen);
  2. the card body was `d.content || draft path` — an event with neither printed
     nothing at all, i.e. two buttons and no object;
  3. the buttons were drawn once and never re-checked: a proposal already denied
     kept two live-looking buttons whose click could only fail, and the failure
     was swallowed (unhandled rejection) so the button looked dead.

Contract:
  A) one binding per event kind (feed only) — no duplicate cards;
  B) one card per proposal id, whatever the number of events;
  C) the body always states the object, or says that the event carries none;
  D) the card follows the STORE: a non-pending proposal loses its buttons;
  E) a decision taken elsewhere (RH inbox) settles the chat card too;
  F) a failed approval decision reports its reason instead of failing silently;
  G) the RH inbox row explains a blank proposal instead of rendering empty.

Deterministic: static contract checks on webui/index.html. No server, no model.
Run: python3 tests/acceptance/v648_proposal_card_truth.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = os.path.join(REPO, "webui", "index.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


ui = open(UI, encoding="utf-8").read()


def block(start, end):
    """The source slice between two anchors (anchors must exist)."""
    assert start in ui, "missing anchor: " + start
    i = ui.index(start)
    assert end in ui[i:], "missing end anchor: " + end
    return ui[i:ui.index(end, i)]


# ---- A. one binding per event kind ------------------------------------------
for kind in ("improve.proposal", "approval.request"):
    n = ui.count('addEventListener("%s"' % kind)
    check("A1 %s is bound exactly once (feed), not on both streams" % kind, n == 1, n)
_stream = block("function _bindRenderStream(es, live, adopt)", "async function api(method")
check("A2 the per-turn stream no longer renders approvals or proposals",
      "approvalCard(" not in _stream and "improveCard(" not in _stream)

# ---- B/C/D/E. the proposal card ---------------------------------------------
card = block("let _impCache = { t: 0, by: {} };", "/* JAG-447: the Improvement panel")
check("B1 one card per proposal id", 'document.querySelector(\'#log .msg[data-pid="' in card
      and "card.dataset.pid = pid" in card)
check("C1 a blank event says so instead of rendering an empty card",
      "this event carries no description — nothing to review" in card)
check("C2 the body carries the content and the draft path",
      'const what = String(d.content || "").trim()' in card
      and 'const draft = String(d.target_path || d.path || "").trim()' in card)
check("D1 the store decides the buttons, not the draw call",
      "async function _impStatus(pid, force)" in card
      and 'if (p.status !== "pending") { ok.remove(); no.remove(); feedback.textContent = "already " + p.status; }' in card)
check("D2 a proposal that vanished from the store loses its buttons",
      "no longer in the store — nothing to decide" in card)
check("E1 a decision made elsewhere settles the open cards",
      "async function _settleProposalCards(force)" in card
      and "document.querySelectorAll(\"#log .msg[data-pid]\")" in card)
check("E2 the failed decision prints the reason",
      "String(e && e.message ? e.message : e)" in card)

_decide = block("async function decide(id, decision)", "/* The single decision inbox")
check("E3 the RH inbox relays its decision to the chat cards",
      "_settleProposalCards(true)" in _decide and "loadApprovals()" in _decide)

# ---- F. the tool-gate card ---------------------------------------------------
_approval = block("function approvalCard(d) {", "/* JAG-127f: at end of turn")
check("F1 an approval card is unique per approval id", "card.dataset.aid = aid" in _approval)
check("F2 a failed approve/deny reports the error instead of a dead button",
      ".catch(fail)" in _approval and 'feedback.className = "remaining"' in _approval)

# ---- G. the RH inbox row -----------------------------------------------------
_inbox = block("async function loadApprovals()", "async function decide(id, decision)")
check("G1 a blank proposal is described, not left empty",
      '"no description recorded"' in _inbox and "install the drafted skill: " in _inbox)
check("G2 the row shows the reason and the draft",
      'a.reason ? "reason: " + a.reason : ""' in _inbox
      and 'a.draft && a.summary ? "draft: " + a.draft : ""' in _inbox)
check("G3 the blocked reason still disables approve with a tooltip",
      "a.can_approve === false" in _inbox and "a.blocked_reason" in _inbox)

print("---")
passed = sum(results)
print("\nv648: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
