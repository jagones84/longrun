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
tool-call budget and no page cap. A label is a SUMMARY of the request: a model answer
that only reprints the prompt is refused (`threads.set_title`), retried once with a
stricter instruction, and otherwise the group stays untitled — the old deterministic
fallback filled the rail with copied prompts (operator, 2026-11-07).

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
        arr = [{"id": gid, "title": "do %s" % gid,
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
      all((g.get("title") or "").startswith("do g")
          and (g.get("summary") or "").startswith("about g") for g in free),
      [(g.get("title"), g.get("summary")) for g in free])
check("1e the reply used the session's CHAT model (not a separate summarizer role)",
      res.get("model") == "fake/chat", res.get("model"))
# RH-25: the label is the ASK, never "request to <ask>" — the prefix cost rail width
# and said nothing the title did not already say. A model that still writes it is
# normalised at the ONE write choke point (`set_title`).
_gid = free[0]["id"]
th.set_title(sid1, _gid, "request to  swap the embeddings model", summary="s")
check("1f a title that still carries the legacy 'request to ' prefix is normalised on write",
      (th.get(sid1, _gid) or {}).get("title") == "swap the embeddings model",
      (th.get(sid1, _gid) or {}).get("title"))

# ---- 2. one batch when the model names them all at once -----------------------
sid2 = "v469-batch"
_grow(sid2, 4)
fake, state = _stream_returning([99])          # 99 -> "all ids"
httpapi.stream_with_fallback = fake
res = httpapi.autoname_untitled(sid2)
check("2a naming all groups in ONE call needs exactly one model call",
      state["calls"] == 1 and res.get("titled") == 4 and res.get("remaining") == 0,
      (state["calls"], res))

# ---- 3. no copy is ever stored: the model is the ONLY namer -------------------
# A "title" built from the request's first words is the prompt again (operator,
# 2026-11-07: "fa schifo e solo una copia"). The old deterministic fallback is gone:
# when no usable model answer arrives the group stays UNTITLED and the button says so.
sid3 = "v469-fallback"
_grow(sid3, 3)
fake, state = _stream_returning(["GARBAGE"])
httpapi.stream_with_fallback = fake
res = httpapi.autoname_untitled(sid3)
check("3a an unusable model reply stores NOTHING and reports the untitled groups",
      res.get("ok") and res.get("titled") == 0 and res.get("remaining") == 3
      and len(th.untitled_free(sid3)) == 3, res)
check("3b no title was derived from the request text (the old fallback)",
      all(not g.get("title") and not g.get("summary")
          for g in th.outline(sid3) if g["kind"] == "free"),
      [(g.get("title"), g.get("summary")) for g in th.outline(sid3) if g["kind"] == "free"])

# a raised model call must never break the button (and never invent a copy)
sid4 = "v469-down"
_grow(sid4, 2)


def _boom(*a, **k):
    raise RuntimeError("router down")


httpapi.stream_with_fallback = _boom
res = httpapi.autoname_untitled(sid4)
check("3c the model raising never breaks the button (nothing named, nothing broken)",
      res.get("ok") and res.get("titled") == 0 and res.get("remaining") == 2, res)

# a model that only REPRINTS the requests is refused (twice), then leaves them unnamed
sid6 = "v469-echo"
_grow(sid6, 2)


def _echo(messages, model, role, on_delta, timeout=None, **kw):
    body = messages[0]["content"]
    reqs = dict(re.findall(r'id=(g\d+) request="([^"]*)"', body))
    arr = [{"id": gid, "title": (reqs.get(gid) or "")[:40],
            "summary": reqs.get(gid) or ""} for gid in re.findall(r"id=(g\d+)", body)]
    return (json.dumps(arr), "", "fake/chat")


httpapi.stream_with_fallback = _echo
res = httpapi.autoname_untitled(sid6)
check("3d a model that copies the request text is refused — the groups stay untitled",
      res.get("titled") == 0 and res.get("remaining") == 2, res)
check("3e the copy never reached the ledger (title AND summary)",
      all(not g.get("title") and not g.get("summary")
          for g in th.outline(sid6) if g["kind"] == "free"),
      [(g.get("title"), g.get("summary")) for g in th.outline(sid6) if g["kind"] == "free"])
check("3f a refused round is retried ONCE with a stricter instruction, not looped",
      res.get("rounds") == 2, res.get("rounds"))

# ---- 3g. the 🏷 route answers AT ONCE; the model call runs in the background ----
# The call takes minutes on a local reasoning model. Holding the HTTP request open
# made the button look dead (the operator clicked and saw no model start at all,
# 2026-11-07). The labels arrive through `threads.updated`, the run closes with
# `threads.named`.
sid7 = "v469-async"
_grow(sid7, 1)
_events = []
httpapi.publish = lambda kind, **kw: _events.append(dict(kind=kind, **kw))


def _slow_name(sess, model=None, cancel=None):
    # v862: `autoname_async` now passes a Stop-aware cancel — the fake mirrors the
    # real signature, otherwise the call raises inside the background thread and
    # the run reports `threads.named` with an error instead of its totals.
    time.sleep(0.5)
    return {"ok": True, "session": (sess or {}).get("id"), "titled": 1,
            "remaining": 0, "model": "fake/chat"}


httpapi.autoname_untitled = _slow_name
_t0 = time.time()
res = httpapi.autoname_async(stores.load_session(sid7))
_took = time.time() - _t0
check("3g the 🏷 route answers AT ONCE — the model call runs in the background",
      res.get("started") is True and _took < 0.25, _took)
check("3h a second click while the run is in flight starts nothing",
      httpapi.autoname_async(stores.load_session(sid7)).get("started") is False, "")
time.sleep(1.2)
_named = [e for e in _events if e.get("kind") == "threads.named"]
check("3i the run closes with `threads.named` (titled/remaining totals)",
      len(_named) == 1 and _named[0].get("titled") == 1
      and _named[0].get("remaining") == 0,
      _events[-1] if _events else None)

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
check("5c the naming prompt asks for a PARAPHRASE, never a copy of the request",
      "PARAPHRASE" in API and "Never reuse the request" in API, "")
check("5d the button answers AT ONCE (the naming model runs in the background)",
      "r.started" in nt and "naming" in nt, nt[-240:])
check("5e the route hands the work to `autoname_async` (a background thread)",
      "autoname_async(sess" in API and "Thread(target=_run" in API, "")
check("5f the finished run reports its totals on the feed (`threads.named`)",
      '"threads.named"' in API and "threads.named" in HTML, "")

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
check("6d for a MATCHED group the LEDGER wins over its chapter (a rename must repaint)",
      "lg.id ? (lg.title" in _at and "lg.id ? (lg.summary" in _at, "")

# ---- 7. a ledger written BEFORE RH-25 is normalised on READ (not just rendered) --
# Cleaning only the rendered value would leave the ledger and the UI spelling one
# title two ways, so the stored title is normalised instead — once, then persisted.
_mig = "v469-legacy-prefix"
_grow(_mig, 1)
th.outline(_mig)                                   # materialise the ledger
_p = th.path_for(_mig)
with open(_p, encoding="utf-8") as f:
    _doc = json.load(f)
_doc["groups"][0]["title"] = "request to audit the longrun codebase"
with open(_p, "w", encoding="utf-8") as f:
    json.dump(_doc, f)
check("7a a stored legacy 'request to …' title is stripped when the ledger is read",
      (th.outline(_mig)[0].get("title") or "") == "audit the longrun codebase",
      th.outline(_mig)[0].get("title"))
with open(_p, encoding="utf-8") as f:
    _after = f.read()
check("7b the cleanup is PERSISTED (one truth: the ledger spells it clean too)",
      "request to" not in _after, _after[:120])

# ---- 8. the copy rule has ONE owner and no deterministic titler survives ------
_TH = _read("src", "longrun", "memory", "threads.py")
check("8a the deterministic copy titler is gone from the ledger module",
      "def autotitle_untitled" not in _TH and "def _short_ask" not in _TH, "")
check("8b the copy detector + the read-time ledger repair are the one rule",
      "def _is_copy(" in _TH and "def _is_copy_summary(" in _TH
      and "def _normalise_titles(" in _TH, "")
check("8c the title write point REFUSES a copy (every namer goes through it)",
      "_is_copy(title, src)" in _TH and "is only the request's own words" in _TH, "")
check("8d no runtime path re-introduces a pre-compaction copy title",
      "autotitle_untitled" not in API and "_short_ask" not in API, "")

print("---")
okc = sum(results)
print("\nv469: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
