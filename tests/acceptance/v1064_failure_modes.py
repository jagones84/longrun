#!/usr/bin/env python3
"""v1064 — every failure MODE has its own harness message, and nothing is hidden.

Operator rule (2026-11-16): "all that goes to llm I want to see in chat history …
chat session shall be chronological and no hiding things … every failure mode
triggers a specific harness message".

Pins:
  A  the transport records WHY a reply was empty (`finish_reason`, `reasoning_tokens`)
  B  a reasoning-only / output-limit reply first gets ONE same-model round that
     keeps the thinking and asks for the answer (never "think less")
  C  a second failure names the failover explicitly
  D  a completely blank reply has its OWN message (provider defect)
  E  the failed attempt is persisted as a UI-only card (`model.attempt`) and emitted
     live, so a reload shows the same chronological chat
  F  the card is labelled and does not count as a work step
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


agent = _read("src/longrun/agent/agent.py")
rllm = _read("src/longrun/model/rllm.py")
html = _read("webui/index.html")

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


check("A1 finish_reason captured",
      'usage["finish_reason"] = _choices[0]["finish_reason"]' in rllm)
check("A2 reasoning tokens captured",
      'usage["reasoning_tokens"] = _details["reasoning_tokens"]' in rllm)
check("B1 one same-model round keeps the thinking", "_reasoning_retry_used = False" in agent
      and "if not _reasoning_retry_used and not _is_aborted" in agent)
check("B2 the message names the mode and asks for the ANSWER, never for less thinking",
      "Keep the thinking" in agent and "it was reasoning-only" in agent
      and "Think LESS" not in agent
      and "the reply hit the completion envelope (max_tokens=" in agent)
check("C1 the second failure names the failover", "continues on the next configured model" in agent)
check("D1 a blank reply has its own message", "The provider returned a BLANK message" in agent)
check("E1 the failed attempt is persisted as a UI-only card",
      '"model.attempt", True' in agent)
check("E2 the same record is emitted live", 'tool="model.attempt"' in agent)
check("E3 the reasoning is the card body", 'result=str(think or "")[:4000]' in agent)
check("F1 the card has a human label", "Model attempt · " in html)
check("F2 it carries its own icon", "alert: '<svg" in html)
check("F3 it is not counted as a work step",
      't === "model.attempt") return;   // plan bookkeeping / a record, not work' in html)

print("\n%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
