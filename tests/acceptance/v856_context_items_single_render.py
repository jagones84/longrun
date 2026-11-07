#!/usr/bin/env python3
"""v856 — the Context panel renders the system prompt ONCE, and its numbers do not move.

Measured on the DGX (2026-11-07, `.agent/trash/prof_items.py`): `context_items` cost
107 ms warm on a 288-message session. It renders every prompt section for its token
breakdown (`prompt.section_texts`) and then called `context_usage`, which rendered the
whole prompt a SECOND time (`_system_prompt` = 42 ms) and walked the transcript again
— for `used_tokens` / `cached_tokens`, i.e. exactly the numbers it had just computed.

The panel now hands the meter what it already has (`sections=`, `transcript_tokens=`).
The values are produced by the SAME functions over the SAME inputs, so nothing moves;
what disappears is the duplicate work.

What this pins:
  A) one section render per panel request (was two);
  B) `used_tokens` still equals the meter's own definition (system prompt + full
     transcript + the live task-list block);
  C) the breakdown still adds up: sum(tokens) == tokens_total, and the `overhead`
     bucket is the real gap against the measured total;
  D) the meter itself is unchanged when called with no precomputed parts.

Deterministic, no model, no network.

Run:  python3 tests/acceptance/v856_context_items_single_render.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v856-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S  # noqa: E402
from longrun.model import context_engine as CE  # noqa: E402
from longrun.model import prompt as P  # noqa: E402
from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}
os.makedirs(S.SESSIONS_DIR, exist_ok=True)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


sid = "t856"
S.save_session({"id": sid, "title": sid, "messages": [
    {"role": "user", "content": "read the file and tell me what it does"},
    {"role": "assistant", "content": "Observation for tool fs.read: alpha beta gamma delta"},
    {"role": "user", "content": "now search the web for the release notes"},
    {"role": "assistant", "content": "Observation for tool web.search: one two three four"},
    {"role": "user", "content": "summarise it in one line"},
]})

# ---- A: exactly ONE render of the sections while the panel answers ----
_renders = []
_real_st = P.section_texts


def _counting_sections(*a, **k):
    _renders.append(1)
    return _real_st(*a, **k)


P.section_texts = _counting_sections
try:
    ci = S.context_items(sid)
finally:
    P.section_texts = _real_st

check("A1 the panel renders the sections exactly once", len(_renders) == 1,
      "renders=%d" % len(_renders))
check("A2 the panel answered", ci.get("available") is True, str(ci.get("available")))

# ---- B: the numbers are still the meter's own definition ----
sess = S.load_session(sid) or {}
sysp = S._system_prompt(sess)
aug = "\n\n" + S.state_block(session_id=sid)
want = (CE.count_tokens(sysp)
        + sum(CE.count_tokens(m.get("content", "")) for m in sess.get("messages", []))
        + CE.count_tokens(aug))
check("B1 the panel's used_tokens is the meter's definition",
      ci.get("used_tokens") == want,
      "got=%s want=%s" % (ci.get("used_tokens"), want))

u = S.context_usage(sid)          # no precomputed parts: the meter's own path
check("B2 the meter still answers the same number on its own",
      u.get("tokens_used") == want, "got=%s want=%s" % (u.get("tokens_used"), want))
_secs = P.section_texts(sess)
check("B3 the tool and plan buckets are the real sections",
      ci.get("tokens", {}).get("tools", 0) == CE.count_tokens(_secs.get("tools", ""))
      and ci.get("tokens", {}).get("plan", 0) == CE.count_tokens(S.state_block(session_id=sid)),
      "tools=%s want=%s plan=%s want=%s"
      % (ci.get("tokens", {}).get("tools"), CE.count_tokens(_secs.get("tools", "")),
         ci.get("tokens", {}).get("plan"), CE.count_tokens(S.state_block(session_id=sid))))

# ---- C: the breakdown still adds up ----
tok = ci.get("tokens") or {}
check("C1 tokens_total is the sum of the buckets",
      ci.get("tokens_total") == sum(tok.values()),
      "total=%s sum=%s" % (ci.get("tokens_total"), sum(tok.values())))
_without = {k: v for k, v in tok.items() if k != "overhead"}
check("C2 the overhead bucket is the measured gap",
      tok.get("overhead", 0) == max(0, (ci.get("used_tokens") or 0) - sum(_without.values())),
      "overhead=%s used=%s parts=%s" % (tok.get("overhead"), ci.get("used_tokens"),
                                        sum(_without.values())))
check("C3 the ordered breakdown carries the system bucket",
      isinstance(ci.get("breakdown"), list)
      and any(b.get("key") == "system" and b.get("tokens", 0) > 0 for b in ci["breakdown"]))

# ---- D: the precomputed parts change nothing the caller can see ----
_sections = P.section_texts(sess)
_tx = sum(CE.count_tokens(m.get("content", "")) for m in sess.get("messages", []))
shared = S.context_usage(sid, sections=_sections, transcript_tokens=_tx)
plain = S.context_usage(sid)
_same = ("tokens_used", "estimate_tokens_used", "system_tokens", "transcript_tokens",
         "pct", "budget_tokens", "messages", "compacted_tokens", "final_messages")
check("D1 the shared path returns the same numbers as the plain path",
      all(shared.get(k) == plain.get(k) for k in _same),
      str({k: (shared.get(k), plain.get(k)) for k in _same
           if shared.get(k) != plain.get(k)}))

print("")
print("%d/%d GREEN" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
