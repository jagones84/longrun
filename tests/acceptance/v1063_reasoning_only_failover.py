#!/usr/bin/env python3
"""v1063 — a REASONING-ONLY reply can fail over to the next model.

Measured live, session b7329cccf94c (2026-11-15 22:32–22:33): deepseek-v4.1-flash
streamed a long chain-of-thought and returned NO content and NO tool call on every
attempt. `stream_with_fallback` deliberately treats "empty answer + non-empty
think" as a valid reply (v770), so the agent loop answered it with the same text
nudge, four times, then a CONTINUE and three closure rounds — a wall of harness
messages and no work.

The caller can now ask for the failover:
  `reasoning_only_is_blank=True` makes that reply count as blank,
  `advance_from=<model>` drops the model that just proved it stops at the reasoning.

  A1 default: reasoning-only is returned as-is (v770 behaviour preserved)
  A2 reasoning_only_is_blank: the next candidate answers
  A3 advance_from skips the failed model (it is not called again)
  A4 a real answer is never treated as blank
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1063-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


REPLIES = {}
CALLS = []


def stub(messages, alias, on_delta, timeout, usage, guard, cancel,
         no_reasoning=False, max_tokens=None, temperature=None, seed=None):
    CALLS.append(alias)
    r = REPLIES.get(alias)
    if isinstance(r, Exception):
        raise r
    return r if r is not None else ("ok:" + alias, "")


S._router_stream = stub
S.routing.model_chain = lambda role: ["m2", "m3"]
S.routing.order_candidates = lambda c: c


def run(**kw):
    CALLS.clear()
    return S.stream_with_fallback([{"role": "user", "content": "x"}], "m1", "chat",
                                  lambda *a: None, **kw)


REPLIES = {"m1": ("", "long reasoning"), "m2": ("ANSWER-2", "")}
ans, think, used = run()
check("A1 default keeps reasoning-only as the reply (v770)",
      used == "m1" and ans == "" and think == "long reasoning", "%s/%s" % (used, ans))

ans, think, used = run(reasoning_only_is_blank=True)
check("A2 reasoning-only fails over", used == "m2" and ans == "ANSWER-2",
      "%s/%s" % (used, ans))

ans, think, used = run(reasoning_only_is_blank=True, advance_from="m1")
check("A3 advance_from skips the failed model", CALLS == ["m2"] and used == "m2", CALLS)

REPLIES = {"m1": ("real answer", "some reasoning"), "m2": ("WRONG", "")}
ans, think, used = run(reasoning_only_is_blank=True)
check("A4 a real answer is never blank", used == "m1" and ans == "real answer",
      "%s/%s" % (used, ans))

print("\n%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
