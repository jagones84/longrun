#!/usr/bin/env python3
"""v770 — a COMPLETELY blank provider reply fails OVER, it does not kill the turn.

Found by monitoring (operator request 2026-11-02): `chat.error` "the model returned
an empty message three times" fired 6× in one day — three turns lost — because
`stream_with_fallback` only walked the model chain on an EXCEPTION. A provider that
answers with nothing at all (no text AND no reasoning) is a defect, not an answer.
The chain is walked for it; the last candidate still returns the blank so the
agent loop keeps its own nudge-then-error path, and a REASONING-ONLY reply is left
alone (it has its own recovery rule).

Deterministic: the router is replaced by a stub (no model, no network).
Run: python3 tests/acceptance/v770_model_blank_failover.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v770-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "ROLES_DIR", "DB",
           "COSTS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR"):
    val = os.path.join(TMP, _k.lower() + (".json" if _k.endswith("_FILE") else ""))
    if not _k.endswith("_FILE") and _k != "DB":
        os.makedirs(val, exist_ok=True)
    os.environ["LONGRUN_" + _k] = val
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S               # noqa: E402

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- stub the router: one model per alias, answers from `REPLIES` ----------------
REPLIES = {}
CALLS = []


def stub_stream(messages, alias, on_delta, timeout, usage, guard, cancel,
                no_reasoning=False, max_tokens=None):
    CALLS.append(alias)
    r = REPLIES.get(alias, ("ok:%s" % alias, ""))
    if isinstance(r, Exception):
        raise r
    return r


S._router_stream = stub_stream
S.routing.model_chain = lambda role: ["m2", "m3"]      # chain: primary, m2, m3
S.routing.order_candidates = lambda c: c


def run(primary):
    CALLS.clear()
    return S.stream_with_fallback([{"role": "user", "content": "hi"}],
                                  primary, "chat", lambda *a: None)


# 1. A blank primary fails over to the next candidate.
REPLIES = {"m1": ("", ""), "m2": ("ANSWER-2", "")}
ans, think, used = run("m1")
check("A1 a blank reply falls over to the next model", used == "m2" and ans == "ANSWER-2",
      "%s/%s" % (used, ans))
check("A2 the primary was tried first", CALLS == ["m1", "m2"], CALLS)

# 2. Blank on EVERY candidate: the last one's blank is returned, no raise.
REPLIES = {"m1": ("", ""), "m2": ("", ""), "m3": ("", "")}
ans, think, used = run("m1")
check("A3 an all-blank chain returns the blank (upstream nudges/errors) ",
      used == "m3" and ans == "" and CALLS == ["m1", "m2", "m3"], "%s/%s" % (used, CALLS))

# 3. A REASONING-ONLY reply is NOT blank: it keeps its own recovery path.
REPLIES = {"m1": ("", "thinking about it"), "m2": ("SHOULD-NOT-RUN", "")}
ans, think, used = run("m1")
check("A4 a reasoning-only reply is NOT failed over",
      used == "m1" and think == "thinking about it" and CALLS == ["m1"], "%s/%s" % (used, CALLS))

# 4. A normal answer is returned untouched.
REPLIES = {"m1": ("hello", "")}
ans, think, used = run("m1")
check("A5 a normal answer is returned as-is", used == "m1" and ans == "hello")

# 5. An exception still fails over (behaviour that existed before).
REPLIES = {"m1": RuntimeError("provider 503"), "m2": ("RECOVERED", "")}
ans, think, used = run("m1")
check("A6 an exception still falls over", used == "m2" and ans == "RECOVERED")

# 6. Whitespace-only is blank.
REPLIES = {"m1": ("   \n ", ""), "m2": ("REAL", "")}
ans, think, used = run("m1")
check("A7 a whitespace-only reply counts as blank", used == "m2" and ans == "REAL")

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
