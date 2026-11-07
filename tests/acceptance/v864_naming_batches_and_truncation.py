#!/usr/bin/env python3
"""v864 — labelling a chat with MANY untitled groups: batch the ask, salvage the cut.

Live report 2026-11-07: on the "Master" chat (372 groups, 144 untitled) the 🏷 button
finished at once and named NOTHING (`threads.named {titled: 0, remaining: 144}`).

Measured with a probe that replays the exact prompt, same model, same budget:
  * all 144 items in one call  -> prompt 34989 chars, completion 8000/8000 REASONING
    tokens, answer 0 chars (`autoname_untitled` then stopped);
  * the same ask cut to 24 items -> a real answer, but CUT MID-ARRAY at 4812 chars
    (no closing `]`), and `json.loads` threw the complete objects away.

So two defects, both mechanical:
  A) one call for everything — the item count must be bounded (`_NAME_BATCH`);
  B) all-or-nothing parsing — the complete objects before the cut must survive;
  C) an empty answer with a thinking block must SHRINK the batch (asking for a bigger
     budget cannot help when the provider cap IS the budget; the old retry asked for
     less than the first attempt: `min(6000, budget*3)`).

Deterministic: temp dirs, no model, no network.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time
import atexit

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v864-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for d in ("cfg", "sessions", "threads", "graphs"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores                # noqa: E402
from longrun.memory import threads as th         # noqa: E402
from longrun.core import server as _srv          # noqa: E402,F401  (import order)
from longrun.core import httpapi as H            # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _grow(sid, n):
    stores.save_session({"id": sid, "title": sid, "created": time.time(), "messages": []})
    sess = stores.load_session(sid)
    for i in range(n):
        stores.append_message(sess, "user", "please do thing number %d about widgets" % i)
        stores.append_message(sess, "assistant", "done thing %d" % i)
    return sess


# ---- A. the parser survives a reply cut mid-array ------------------------------
FULL = ('[{"id":"g1","title":"Outsource the identity lookup","summary":"delegated"},'
        '{"id":"g2","title":"Check the final answer","summary":"asked for the answer"}]')
# the shape the model really produced: object 1 complete, object 2 cut mid-word
CUT = FULL[:FULL.index('{"id":"g2"') + 20]
got = H._parse_name_json(CUT)
check("A1 a truncated array keeps the COMPLETE objects before the cut",
      len(got) >= 1 and got[0]["id"] == "g1" and got[0]["title"].startswith("Outsource"), got)
check("A2 a complete array still parses whole",
      [g["id"] for g in H._parse_name_json(FULL)] == ["g1", "g2"])
check("A3 a fenced, truncated reply is salvaged the same way",
      [g["id"] for g in H._parse_name_json("```json\n" + CUT)] == ["g1"],
      H._parse_name_json("```json\n" + CUT))
check("A4 an object cut BEFORE its closing brace is not invented",
      not any(g["id"] == "g2" for g in H._parse_name_json(CUT)))
check("A5 prose with no array is still nothing", H._parse_name_json("sorry, no json") == [])
check("A6 a non-list JSON answer is nothing", H._parse_name_json('{"id":"g1"}') == [])
check("A7 ids inside a string brace do not confuse the scanner",
      [g["id"] for g in H._parse_name_json(
          '[{"id":"g1","title":"Braces } { in a title","summary":"s"}]')] == ["g1"])

# ---- B. a big chat is asked in bounded batches --------------------------------
N = 60
sid = "v864-big"
_grow(sid, N)
check("B1 sixty untitled groups exist", len(th.untitled_free(sid)) == N,
      len(th.untitled_free(sid)))

calls = []


def _batch_fake(messages, model, role, on_delta, timeout=None, **kw):
    ids = re.findall(r"id=(g\d+)", messages[0]["content"])
    calls.append(ids)
    arr = [{"id": gid, "title": "paraphrase of %s" % gid,
            "summary": "about %s" % gid} for gid in ids]
    return (json.dumps(arr), "", "fake/chat")


H.stream_with_fallback = _batch_fake
res = H.autoname_untitled(sid)
biggest = max(len(c) for c in calls)
check("B2 the ask is bounded: no call carries more than _NAME_BATCH items",
      biggest <= H._NAME_BATCH, (biggest, H._NAME_BATCH))
check("B3 a 60-group chat is named COMPLETELY (0 remain)",
      res.get("titled") == N and res.get("remaining") == 0 and not th.untitled_free(sid), res)
check("B4 it took several passes over the batch, not one oversized call",
      len(calls) >= 3, len(calls))
check("B5 no group is asked twice in the same run",
      len({gid for c in calls for gid in c}) == len([gid for c in calls for gid in c]),
      len(calls))

# ---- C. an empty answer with a thinking block SHRINKS the batch ----------------
sid2 = "v864-think"
_grow(sid2, 40)
calls2 = []
state2 = {"n": 0}


def _think_then_name(messages, model, role, on_delta, timeout=None, **kw):
    ids = re.findall(r"id=(g\d+)", messages[0]["content"])
    calls2.append(ids)
    state2["n"] += 1
    if state2["n"] == 1:
        # the real failure: the whole completion budget went to reasoning
        return ("", "x" * 4000, "fake/chat")
    arr = [{"id": gid, "title": "paraphrase of %s" % gid,
            "summary": "about %s" % gid} for gid in ids]
    return (json.dumps(arr), "", "fake/chat")


H.stream_with_fallback = _think_then_name
res2 = H.autoname_untitled(sid2)
check("C1 a thinking-only answer does not end the run", res2.get("titled", 0) > 0, res2)
check("C2 the next ask is SMALLER, not merely repeated",
      len(calls2) > 1 and len(calls2[1]) < len(calls2[0]),
      [len(c) for c in calls2[:3]])
check("C3 the smaller ask still names everything in the end",
      res2.get("remaining") == 0, res2)
check("C4 the batch goes back to full size after a usable answer",
      max(len(c) for c in calls2) == H._NAME_BATCH, [len(c) for c in calls2])

# ---- D. the loop stays bounded ------------------------------------------------
sid3 = "v864-garbage"
_grow(sid3, 3)


def _garbage(messages, model, role, on_delta, timeout=None, **kw):
    return ("not json at all", "", "fake/chat")


H.stream_with_fallback = _garbage
res3 = H.autoname_untitled(sid3)
check("D1 an unusable reply names nothing and stops (one strict retry, no loop)",
      res3.get("titled") == 0 and res3.get("remaining") == 3 and res3.get("rounds") == 2,
      res3)

# ---- E. the constants are the ones the loop uses ------------------------------
API = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
check("E1 the batch bound is a named constant, used by the loop",
      "_NAME_BATCH = 24" in API and "chunk = groups[:max(1, min(batch, len(groups)))]" in API)
check("E2 the budget follows the CHUNK, not the whole backlog",
      "700 + 320 * len(chunk)" in API)
check("E3 the old 'retry with less room' is gone",
      "min(6000, budget * 3)" not in API)
check("E4 the parser owns the salvage of a cut reply",
      "def _salvage_objects(" in API and "_salvage_objects(body)" in API)

print("---")
okc = sum(results)
print("\nv864: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
