#!/usr/bin/env python3
"""v859 — "ho finito" is a CLAIM: the harness grades the close against the
operator's REQUEST THREAD, not against the last sentence.

The operator: "se l'agente dice HO FINITO l'harness lo deve bloccare e chiedergli
verifica rispetto al prompt originale e i successivi dell'user e alle aspettative
… sugli artefatti ad esempio". Before this, the bounded closure verdict quoted
`message` — the current turn's sentence — and it only fired when steps were still
open; a turn that closed every step with no artefact was accepted unverified.

  A) `_request_thread` returns the ORIGINAL ask plus the later user messages;
  B) harness injections (`[harness] …`) are NOT the operator's request;
  C) the current turn's message is included exactly once;
  D) the verdict built from the thread names the original request and the
     follow-ups, and still asks for `finish`;
  E) every close path carries the request-anchored verdict, one round per turn;
  F) the no-argument prompt is unchanged (v584 pin).

Deterministic, no live model, no network, no server.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server          # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agent as A     # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


SESS = {"id": "v859", "messages": [
    {"role": "user", "content": "build the report from the two sheets"},
    {"role": "assistant", "content": "working"},
    {"role": "user", "content": "[harness] closure check (harness — do not skip)"},
    {"role": "user", "content": "and make it one page"},
    {"role": "user", "content": "also name the totals"},
]}

thread = A._request_thread(SESS, "also name the totals")
check("A1 the ORIGINAL request is in the thread",
      "build the report from the two sheets" in thread, thread[:120])
check("A2 the later user messages are in the thread",
      "one page" in thread and "name the totals" in thread, thread[-160:])
check("B1 a harness injection is never quoted as a user request",
      "[harness]" not in thread, thread)
check("C1 the current message appears exactly once",
      thread.count("also name the totals") == 1, thread.count("also name the totals"))

p = A._closure_check_prompt(thread)
check("D1 the verdict names the original request", "build the report from the two sheets" in p)
check("D2 the verdict names the follow-ups", "one page" in p and "name the totals" in p)
check("D3 the verdict still asks for finish", "finish" in p)

# a session with no history: the current message alone is the thread
solo = A._request_thread({"id": "x", "messages": []}, "do the thing")
check("C2 an empty transcript falls back to the current message", solo == "do the thing", solo)

src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("E1 one round per turn is enforced by a flag",
      "_request_verified = False" in src and src.count("_request_verified = True") >= 3,
      src.count("_request_verified = True"))
check("E2 the verdict is anchored to the thread, not the last sentence",
      src.count("_closure_check_prompt(_request_thread_text)") >= 5,
      src.count("_closure_check_prompt(_request_thread_text)"))
check("E3 the close paths fire even when nothing is open (real work only)",
      src.count("not _request_verified and _total_work_steps") >= 4,
      src.count("not _request_verified and _total_work_steps"))
check("F1 the no-argument verdict keeps its legacy wording",
      "COMPLETE and final answer" in A._closure_check_prompt()
      and "keep working" in A._closure_check_prompt())

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
