#!/usr/bin/env python3
"""v305 — a generous, explicit output budget so long deliverables are not truncated (JAG-305).

Observed live on J2: the coordinator's synthesis turn reported completion_tokens
pinned at exactly 4096 with `finish_reason` unset and think_chars 12k — the
llama.cpp router's DEFAULT completion cap when the request omits `max_tokens`
(the harness sent none, `LONGRUN_MAX_TOKENS` default 0). A reasoning model
spends most of that budget on hidden thinking, so the answer was cut mid-table
and the job's deliverable came out incomplete. Probe proved the router honours an
explicit larger cap (max_tokens=6000 -> 5044 tokens, finish_reason=stop).

Locked here:
  * the default `MAX_TOKENS` is generous (> 4096) and still bounded;
  * `_completion_body` sends `max_tokens` when set and omits it when None.

Deterministic, no live model. Run: python3 tests/v305_output_budget.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


from longrun.core import server  # noqa: E402

# --- the default cap must clear the router's 4096 ---------------------------------
check("the output cap is generous (> 4096)", server.MAX_TOKENS > 4096,
      "MAX_TOKENS=%d" % server.MAX_TOKENS)
check("the output cap is still bounded (not 0/unlimited)", server.MAX_TOKENS > 0)
# a heavy-reasoning turn must fit: ~12k-char think + a full multi-section answer
check("the cap leaves room for reasoning + a long answer", server.MAX_TOKENS >= 8192)

# --- the body carries the cap; None omits it (old behaviour) ----------------------
body = server._completion_body("m", [], True, server.MAX_TOKENS or None)
check("a set cap is sent as max_tokens", body.get("max_tokens") == server.MAX_TOKENS,
      "max_tokens=%r" % body.get("max_tokens"))
off = server._completion_body("m", [], True, None)
check("a None cap is omitted (router decides)", "max_tokens" not in off)

# ------------------------------------------------------------------ source locks
s = read("src", "longrun", "model/rllm.py")
check("the default is 16384 and env-overridable",
      'os.environ.get("LONGRUN_MAX_TOKENS", "16384")' in s)
# RH-15: the chat call passes the cap through `_max_tokens()`, which prefers
# `reasoning.max_tokens` from config/tools.yaml and falls back to this constant — the
# cap stopped being a constant that a config could not raise.
check("the chat call passes the cap", "_max_tokens() or None" in s
      and "def _max_tokens()" in s and "MAX_TOKENS" in s)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

