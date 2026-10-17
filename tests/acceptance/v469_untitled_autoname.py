#!/usr/bin/env python3
"""v469 — the 🏷 button names EVERY untitled Free.* group in ONE subroutine (JAG-473).

The button used to just PROMPT the agent ("use `chapters` action=untitled …"), and
that turn always stopped after one page: `chapters action=untitled` shows at most 8
ids, and a chat turn may spend only CHAT_TOOL_MAX_STEPS (8) real tool calls before
the keepgoing loop stops — renaming creates no todo, so `keepgoing.decide` sees zero
open nodes and returns `goal_reached`.

Now the button POSTs /api/sessions/<id>/chapters/autoname, which runs a SUBROUTINE
(`httpapi.autoname_untitled`): one direct call to the session's chat model that names
ALL untitled groups at once, applied server-side, repeated until none remain — no
tool-call budget and no page cap. A deterministic fallback finishes the job when the
model is unavailable.

Deterministic, no network (the model is stubbed). Run:
    python3 tests/acceptance/v469_untitled_autoname.py
"""
import json
import os
import re
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v469-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for d in ("cfg", "sessions", "graphs", "threads"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores            # noqa: E402
from longrun.memory import threads as th     # noqa: E402
from longrun.core import server as _srv      # noqa: E402,F401  (httpapi<->server import order)
from longrun.core import httpapi             # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


def _grow(sid, n):
    """A session with `n` FREE groups (each user turn opens one) and no titles."""
    stores.save_session({"id": sid, "title": sid, "created": time.time(), "messages": []})
    sess = stores.load_session(sid)
    for i in range(n):
        stores.append_message(sess, "user", "please do thing number %d about widgets" % i)
        stores.append_message(sess, "assistant", "done thing %d" % i)
    return sess


def _stream_returning(payloads):
    """A fake `stream_with_fallback` that answers its i-th call with payloads[i]
    (or the last one), naming the ids that appear in the prompt. Records call count."""
    state = {"calls": 0}

    def fake(messages, model, role, on_delta, timeout=None, **kw):
        i = state["calls"]
        state["calls"] += 1
        ids = re.findall(r"id=(g\d+)", messages[0]["content"])
        payload = payloads[min(i, len(payloads) - 1)]
        if payload == "GARBAGE":
            return ("not json at all — sorry", "", "fake/chat")
        picked = ids[:payload] if isinstance(payload, int) else ids
        arr = [{"id": gid, "title": "request to do %s" % gid,
                "summary": "about %s" % gid} for gid in picked]
        return ("```json\n" + json.dumps(arr) + "\n```", "", "fake/chat")

    return fake, state


# ---- 1. the loop keeps going until NONE remain (no per-call cap) --------------
sid1 = "v469-loop"
_grow(sid1, 5)
check("1a five untitled Free.* groups exist",
      len(th.untitled_free(sid1)) == 5, len(th.untitled_free(sid1)))

fake, state = _stream_returning([3, 5])        # first reply names only 3 of 5
httpapi.stream_with_fallback = fake
res = httpapi.autoname_untitled(sid1)
free = [g for g in th.outline(sid1) if g["kind"] == "free"]
check("1b a single button press names EVERY group (0 remain)",
      res.get("ok") and res.get("remaining") == 0 and len(th.untitled_free(sid1)) == 0,
      res)
check("1c the model named only 3 of 5 on the first call -> the subroutine looped again",
      state["calls"] == 2 and res.get("rounds") == 2, (state["calls"], res.get("rounds")))
check("1d every free group got a title + summary from the model",
      all((g.get("title") or "").startswith("request to do g")
          and (g.get("summary") or "").startswith("about g") for g in free),
      [(g.get("title"), g.get("summary")) for g in free])
check("1e the reply used the session's CHAT model (not a separate summarizer role)",
      res.get("model") == "fake/chat", res.get("model"))

# ---- 2. one batch when the model names them all at once -----------------------
sid2 = "v469-batch"
_grow(sid2, 4)
fake, state = _stream_returning([99])          # 99 -> "all ids"
httpapi.stream_with_fallback = fake
res = httpapi.autoname_untitled(sid2)
check("2a naming all groups in ONE call needs exactly one model call",
      state["calls"] == 1 and res.get("titled") == 4 and res.get("remaining") == 0,
      (state["calls"], res))

# ---- 3. deterministic fallback when the model is unusable ---------------------
sid3 = "v469-fallback"
_grow(sid3, 3)
fake, state = _stream_returning(["GARBAGE"])
httpapi.stream_with_fallback = fake
res = httpapi.autoname_untitled(sid3)
check("3a an unusable model reply falls back so the button still names everything",
      res.get("remaining") == 0 and len(th.untitled_free(sid3)) == 0, res)
check("3b the fallback titles come from the group's own request (JAG-451)",
      all((g.get("title") or "").startswith("request to ")
          for g in th.outline(sid3) if g["kind"] == "free"),
      [g.get("title") for g in th.outline(sid3) if g["kind"] == "free"])

# a raised model call must ALSO fall back (never break the button)
sid4 = "v469-down"
_grow(sid4, 2)


def _boom(*a, **k):
    raise RuntimeError("router down")


httpapi.stream_with_fallback = _boom
res = httpapi.autoname_untitled(sid4)
check("3c the model raising never breaks the button (fallback still names all)",
      res.get("ok") and res.get("remaining") == 0, res)

# ---- 4. the agent-facing `chapters action=untitled` view is unchanged (paged) --
sid5 = "v469-page"
_grow(sid5, 10)
view = th.render_untitled(sid5, limit=8)
check("4a the chapters tool still PAGES (its 8-id batch is a tool-budget view)",
      "10 remain; showing 8" in view and "More remain after this batch." in view,
      view.splitlines()[0])

# ---- 5. the wiring: route + the button no longer prompts the agent ------------
API = _read("src", "longrun", "core", "httpapi.py")
HTML = _read("webui", "index.html")
check("5a the POST route /chapters/autoname exists",
      ".endswith(\"/chapters/autoname\")" in API and "autoname_untitled(sess" in API, "")
nt = HTML[HTML.index("async function nameThreads("):]
nt = nt[:nt.index("\n}") + 2]
check("5b the 🏷 button POSTs the subroutine instead of prompting the agent",
      "/chapters/autoname" in nt and "send(" not in nt, nt[:120])

# ---- 6. the labels actually REPAINT after the batch (JAG-474) ------------------
# The button once reported "named 11" while NO label changed: the rendered groups
# carry no chapter gid, and JAG-431p's ordinal fallback only fires when the rendered
# and ledger free-group counts match — after a compaction they don't (coder 1: 13
# vs 18 → nothing matched). The repaint must match by the group's OWN user request.
_at = HTML[HTML.index("function applyThreadTitles("):]
_at = _at[:_at.index("\nfunction _freeReqText(") if "\nfunction _freeReqText(" in _at else 4000]
check("6a the repaint matches a group by its own user REQUEST (compaction-proof)",
      "_freeReqText(det)" in _at and "startsWith(c.k)" in _at, "")
check("6b the request match does not need the counts to be identical",
      "if (!lg && same" in _at, "")
check("6c a ledger group is never stamped onto two rendered groups",
      "used[lg.id] = true" in _at and "used[c.g.id]" in _at, "")

print("---")
okc = sum(results)
print("\nv469: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
