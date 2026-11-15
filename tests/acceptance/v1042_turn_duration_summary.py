#!/usr/bin/env python3
"""v1042 — every turn prints how long it took, and the line STAYS in the history.

Operator: *"after a work of the session i need to know how much time that turn took
to be completed — this shall remain printed as a summary in the chat session, i
don't like things that appear and disappear from the chat history."*

The numbers existed (the run ledger already recorded `duration_s`), but the chat
only drew them as a transient bubble on `run.metrics`: a reload rebuilt the
transcript from messages/tool-cards/injects, where no turn summary lived, so the
line vanished.

Contract pinned here:

  A) ONE clock per turn: the chat loop measures it once, persists
     `duration_s`/`iterations`/`steps`/`tokens` ON the assistant message (after
     every `meta = {...}` branch, before `append_message`) and feeds the SAME
     number to the run ledger;
  B) `chat.final` carries the same fields, so the live answer and the reloaded
     transcript can print one identical footer;
  C) the WebUI renders it as `.turnfoot` under the answer — on reload
     (loadHistory) and live (`_applyFinalReply`), never as a new transient
     bubble (`runFooter` is gone; `run.metrics` only fills the footer).

Deterministic: reads the sources; no server, no model, no network.
Run: python3 tests/acceptance/v1042_turn_duration_summary.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    UI = f.read()
with open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8") as f:
    AGENT = f.read()
with open(os.path.join(REPO, "src", "longrun", "model", "runmetrics.py"), encoding="utf-8") as f:
    METRICS = f.read()

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """Record one deterministic turn-summary contract."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def _body(source: str, name: str, next_name: str) -> str:
    start = source.find(name)
    end = source.find(next_name, start + len(name))
    return source[start:end] if start >= 0 and end > len(name) else ""


# --- A: one clock, persisted on the answer ---------------------------------
check("A1 the turn clock starts where the run ledger starts",
      "_turn_t0 = time.time()" in AGENT
      and AGENT.find("_turn_t0 = time.time()") < AGENT.find("runmetrics.start("))
stats = _body(AGENT, '_turn_stats = {"duration_s"', "meta = {\"model\": model")
check("A2 the summary carries duration, rounds, steps and tokens",
      all(k in stats for k in ('"duration_s"', '"iterations"', '"steps"', '"tokens"')))
meta_pos = AGENT.find("meta.update(_turn_stats)")
append_pos = AGENT.find('reply = append_message(sess, "assistant"')
check("A3 it survives every meta branch and is persisted BEFORE the write",
      meta_pos > 0 and append_pos > 0 and meta_pos < append_pos
      and 'meta.update(_turn_stats)' in AGENT)
check("A4 the ledger records the SAME duration (one truth)",
      "duration_s=_turn_stats.get(\"duration_s\")" in AGENT
      and "duration_s=None" in METRICS
      and 'rec["duration_s"] = round(float(duration_s), 1)' in METRICS)

# --- B: the live echo carries the numbers -----------------------------------
emit = _body(AGENT, "def _emit_final_reply", "def chat_once")
check("B1 chat.final carries duration, rounds, steps and tokens",
      all(k + "=" + k in emit for k in ("duration_s", "iterations", "steps", "tokens")))
check("B2 the call site passes the persisted stats",
      "**_turn_stats" in AGENT and "duration_s=duration_s" in emit)

# --- C: one footer, live and reloaded ---------------------------------------
foot = _body(UI, "function _turnFoot(el, m)", "/* 2026-11-11")
check("C1 _turnFoot writes ONE .turnfoot line under the message",
      'className = "turnfoot"' in foot and 'f.textContent = bits.join(" · ")' in foot)
check("C2 the reloaded transcript paints it from the message meta",
      "_turnFoot(d, m);" in _body(UI, "d = who(\"ai\", reply, m.ts", "const cot ="))
apply = _body(UI, "function _applyFinalReply(d)", "function _resetChatTree")
check("C3 the live reply paints it too (same shape, no second bubble)",
      "const _foot = el => _turnFoot(el, d);" in apply
      and apply.count("_foot(") >= 2)
check("C4 the transient run-footer bubble is GONE; metrics only fills the footer",
      "function runFooter" not in UI
      and '_turnFoot(last, m); });' in UI)
check("C5 the footer is styled and survives a theme (no colour emoji)",
      ".msg .turnfoot" in UI and "var(--dim)" in _body(UI, ".msg .turnfoot", "details.think"))
check("C6 the stop label rides on the SAME persisted summary",
      "stopLabel(m.stop_reason)" in foot
      and 'stop_reason' in stats)
check("C7 plan.stopped is no longer a transient chat bubble",
      "function planStopped" not in UI
      and 'planStopped(JSON.parse' not in UI)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
