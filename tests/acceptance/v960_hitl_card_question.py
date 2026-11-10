#!/usr/bin/env python3
"""v960 — the HUMAN IN THE LOOP card carries the DECISION, not a generic form.

Operator, 2026-11-11: *"quando esce la finestra human in the loop la domanda fatta
scompare dalla chat history, non la vedo più"*. Two holes, one decision:

  * the card rendered only "Stopped with N open steps …". The QUESTION and the
    OPTIONS the agent proposed are persisted on the message (`question`/`options`)
    but the card never read them — neither live nor on reload;
  * the synthesized "⏸ Your decision is needed: …" reply is built AFTER the model
    stream, persisted, and never streamed; the WebUI does not reload the chat on
    `done`, so the live chat asked the operator to decide without showing what was
    asked. (Verified on the live home: no `chat.delta` in the answer channel
    carries that text; session `b7329cccf94c` msg 417 holds the question and its 5
    options.)

Locks:
  A  the `hitl.request` event carries the question, the open steps AND the options;
  B  the card renders the question and one button per proposed option, every button
     with an accessible name, and the empty slots are collapsed;
  C  a reload rebuilds the card from the persisted fields, and the canned reply is
     NOT drawn as a second copy of the same decision;
  D  the transcript still persists the decision (nothing is lost server-side).

Deterministic: source pins, no server, no model, no network.
Run: python3 tests/acceptance/v960_hitl_card_question.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
results = []


def check(name, ok, detail=None):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


AGENT = read("src/longrun/agent/agent.py")
GUI = read("webui/index.html")

# --- A: the event carries the decision --------------------------------------
check("A1 the hitl.request event carries the question",
      'on_event("hitl.request"' in AGENT and "question=_q" in AGENT)
check("A2 ... and the proposed options",
      'options=_hitl["options"]' in AGENT)
check("A3 the options are the agent's own `human.ask` list, capped at 6",
      '"options": [str(o) for o in (_ask.get("options") or [])][:6]' in AGENT)
check("A4 exactly ONE place emits hitl.request",
      AGENT.count('on_event("hitl.request"') == 1,
      AGENT.count('on_event("hitl.request"'))

# --- B: the card IS the question ---------------------------------------------
_card = GUI[GUI.index("function hitlCard(d)"):GUI.index("function hitlCard(d)") + 3200]
check("B1 the card has a slot for the question", 'class="hitl-q"' in _card)
check("B2 ... filled from d.question", 'String(d.question || "")' in _card and "qe.textContent = _q" in _card)
check("B3 the proposed options become buttons", 'class="hitl-opts"' in _card and "_opts.forEach" in _card)
check("B4 every option button has an accessible name",
      'b.setAttribute("aria-label", "answer: " + o)' in _card)
check("B5 an option click sends THAT decision", "send(n ? o + \" — \" + n : o)" in _card)
check("B6 both slots start hidden (no empty reserved row)",
      '<div class="hitl-q" hidden>' in _card and '<div class="hitl-opts" hidden>' in _card)
check("B7 the hidden slots are collapsed in CSS",
      ".hitl-q[hidden], .hitl-opts[hidden] { display: none; }" in GUI)

# --- C: a reload rebuilds the SAME decision, once ----------------------------
_replay = GUI[GUI.index("// JAG-295 + 2026-11-11"):GUI.index("// JAG-295 + 2026-11-11") + 1400]
check("C1 the reload passes the persisted question and options",
      "question: m.question || \"\"" in _replay and "options: m.options || []" in _replay)
check("C2 the canned reply is not drawn as a second copy",
      "} else {\n        d = who(\"ai\", reply" in _replay and "hitlCard({" in _replay)

# --- D: the transcript still keeps the decision ------------------------------
check("D1 the stop is persisted with question, reason and the open list",
      '"hitl": True' in AGENT and '"question": _hitl.get("question") or ""' in AGENT
      and '"hitl_open": _hitl["open"]' in AGENT)
check("D2 the persisted reply still names the question",
      '("⏸ Your decision is needed: %s" % _hitl["question"]' in AGENT)

ok = sum(1 for r in results if r)
print("\n%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
