#!/usr/bin/env python3
"""v214 — compaction must not silently drop turns; the ctx meter is per-session.

Regression for the reported bugs (JAG-214):
  * auto-compaction "did nothing" at the threshold and a short session's manual
    "compact" finished instantly WITHOUT the model;
  * switching sessions left the ctx bar unchanged.

Root cause (one): `context_engine.compact` never summarized when the transcript
was `keep_recent` messages or fewer, and the over-budget shrink DROPPED turns
instead of summarizing them; `context_usage` then measured the post-compaction
build size, which can never exceed the threshold — so auto-compact could never
fire and every short session collapsed to the system prompt.

Deterministic, no model. Run:  python3 tests/v214_context_session.py
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-214-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
os.environ["LONGRUN_CONTEXT_BUDGET"] = "5000"   # small, deterministic
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import context_engine  # noqa: E402
from longrun.core import server          # noqa: E402
from longrun.core import httpapi         # noqa: E402

context_engine.retrieve = lambda *a, **k: []   # skip the embedder
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- A: compact() on 2 messages must summarize, not swallow -----------------
m = [{"role": "user", "content": "U" * 400}, {"role": "assistant", "content": "A" * 400}]
out, st = context_engine.compact(m, 150, keep_recent=2,
                                 summarizer=lambda old: "SUM(%d)" % len(old), force=True)
check("A1 older turns summarized (keep_recent no longer swallows all)",
      st["compacted"] == 1, "compacted=%s" % st["compacted"])
check("A2 newest message kept verbatim", bool(out) and out[-1]["content"] == "A" * 400, "")
check("A3 a summary block is present",
      bool(out) and out[0]["role"] == "system" and "SUM(" in out[0]["content"], "")

# ---- B: a SINGLE over-budget message is summarized, never dropped -----------
big = [{"role": "user", "content": "X" * 40000}]
out2, st2 = context_engine.compact(big, 100, summarizer=lambda old: "SUM", force=False)
check("B1 single over-budget message summarized (not dropped)",
      st2["compacted"] == 1 and st2["dropped"] == 0 and bool(out2)
      and out2[0]["role"] == "system", "compacted=%s dropped=%s" % (st2["compacted"], st2["dropped"]))

# ---- C: a retained turn bigger than the budget is TRUNCATED, not dropped ----
m3 = [{"role": "assistant", "content": "Q" * 100}, {"role": "user", "content": "Z" * 40000}]
out3, st3 = context_engine.compact(m3, 200, keep_recent=1, summarizer=lambda old: "S", force=True)
kept = [x for x in out3 if x["role"] != "system"]
check("C1 the huge retained turn is kept (truncated)",
      bool(kept) and "truncated" in kept[-1]["content"], "truncated=%s" % st3["truncated"])
check("C2 nothing silently dropped", st3["dropped"] == 0, "dropped=%s" % st3["dropped"])

# ---- D: legacy contracts preserved -----------------------------------------
m6 = [{"role": "user", "content": ("m%d" % i) * 10} for i in range(6)]
_, st4 = context_engine.compact(m6, 10 ** 9, keep_recent=2, summarizer=lambda old: "S", force=True)
check("D1 keep_recent=2 compacts 4 of 6", st4["compacted"] == 4, "compacted=%s" % st4["compacted"])
out5, st5 = context_engine.compact(m6, 10 ** 9, keep_recent=2, summarizer=lambda old: "S", force=False)
check("D2 under budget + no force -> untouched", st5["compacted"] == 0 and out5 == m6, "")

# ---- E: server — manual compact on a SHORT session calls the model ----------
calls = {"n": 0}


def fake_llm(messages, model=None, meta=None, cancel=None):
    calls["n"] += 1
    if meta is not None:
        meta["model"] = "fake-sum"
    return "SUMMARY"


server._summarize_with_llm = fake_llm
server.publish = lambda *a, **k: None
httpapi._summarize_with_llm = fake_llm   # JAG-379: compact_session + its summarizer live in httpapi
httpapi.publish = lambda *a, **k: None


def mk(sid, pairs):
    s = server.get_or_create_session(sid)
    for role, content in pairs:
        server.append_message(s, role, content)


mk("sE", [("user", "A" * 400), ("assistant", "B" * 400)])
res = server.compact_session("sE")
check("E1 manual compact on 2 messages calls the model summarizer",
      calls["n"] >= 1 and res.get("summary") == "llm", "calls=%s summary=%s" % (calls["n"], res.get("summary")))
check("E2 reports the real message count after",
      res.get("messages_after") == len(server.load_session("sE")["messages"]),
      str(res.get("messages_after")))
check("E3 newest message preserved verbatim",
      server.load_session("sE")["messages"][-1]["content"] == "B" * 400, "")

# ---- F: the ctx meter is per-session (raw, not post-compaction) -------------
server._REAL_PROMPT_TOKENS.clear()
mk("sF1", [("user", "short")])
mk("sF2", [("user", "Y" * 8000)])
u1, u2 = server.context_usage("sF1"), server.context_usage("sF2")
check("F1 two sessions report DIFFERENT tokens_used",
      u1["tokens_used"] != u2["tokens_used"], "%s vs %s" % (u1["tokens_used"], u2["tokens_used"]))
check("F2 the meter counts the FULL transcript (not a dropped build)",
      u2["tokens_used"] > 2000, str(u2["tokens_used"]))
check("F3 pct derives from the raw usage",
      abs(u2["pct"] - u2["tokens_used"] / server.context_budget() * 100) < 0.2, str(u2["pct"]))

# ---- G: auto-compact triggers from the estimate (no router hint) ------------
server._REAL_PROMPT_TOKENS.pop("sG", None)
mk("sG", [("user", "Z" * 40000)])
uG = server.context_usage("sG")
check("G1 a raw-huge session is over_threshold WITHOUT a router hint",
      uG["over_threshold"] is True, "pct=%s" % uG["pct"])

shutil.rmtree(tmp, ignore_errors=True)
ok = sum(results)
print("\nv214: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

