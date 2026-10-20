#!/usr/bin/env python3
"""v295 — bug-hunt fixes (JAG-298): WebUI + backend defects found in a live audit.

Locked here:
  * index.html: `copyText`/`copyBtn` are no longer shadowed (a later 1-arg
    `copyText` used to hoist over the 2-arg button copy → "[object HTMLButtonElement]");
  * index.html: renderTools escapes tool name/description (MCP-controlled strings);
  * index.html: loadApprovals is guarded (polled every 4s, was an unhandled rejection);
  * orbit.html: the 5s auto-poll no longer rebuilds the agent table mid-edit;
  * console.html: the event stream subscribes to NAMED /api/feed frames (onmessage never fired);
  * editor.js: closeTab keeps the right active tab; refreshAll warns before discarding edits;
  * editor.js (JAG-499b): closing the last file keeps the dock open on an empty state;
  * longrun/orbit/api.py: POST routes map `{"ok": false}` to HTTP 400 (were always 200);
  * server.publish: the payload's own `id`/`ts` are renamed BEFORE the DB insert, so replay
    from SQLite no longer clobbers the integer envelope id;
  * server: raw audio/zip uploads cap the Content-Length read (memory-DoS).

Deterministic, no live model. Run: python3 tests/v295_bugfix.py
"""
import io
import json
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


# ---------------------------------------------------------------- index.html
gui = read("webui", "index.html")
_gui_lines = gui.splitlines()
check("copyText/copyBtn no longer shadowed",
      any(l.startswith("function copyBtn(btn, text)") for l in _gui_lines)
      and sum(1 for l in _gui_lines if l.startswith("function copyText(")) == 1)
check("button copy call sites use copyBtn",
      'copyBtn(d.querySelector(".copy")' in gui and "copyBtn(btn, r.value" in gui
      and gui.count("copyBtn(") >= 3)  # definition + 2 call sites
check("renderTools escapes description", "esc(t.description)" in gui and "${t.description}" not in gui)
check("loadApprovals is guarded",
      'try { out = await api("GET", "/api/approvals?status=pending"); }' in gui)

# ---------------------------------------------------------------- orbit.html
orbit = read("src", "longrun", "orbit", "web", "orbit.html")
check("agent-table rebuild is deferred while editing",
      "const editing =" in orbit and "if (editing || roleDirty) return;" in orbit)

# ---------------------------------------------------------------- console.html
con = read("webui", "console.html")
_con_lines = con.splitlines()
check("event stream subscribes to named frames",
      "const FEED_KINDS" in con
      and not any(l.strip().startswith("es.onmessage") for l in _con_lines))
check("feed handles the backlog frame", 'addEventListener("backlog"' in con)

# ---------------------------------------------------------------- editor.js
ed = read("webui", "assets", "editor.js")
check("closeTab keeps the correct active tab",
      "if (i < state.active) state.active -= 1;" in ed)
check("refreshAll warns before discarding edits", "discard unsaved changes" in ed)
# JAG-499b: closing the last file keeps the dock open on a "no file open" empty
# state (the tree stays reachable) instead of collapsing the whole editor.
check("closing the last tab keeps the editor open on an empty state",
      "function showEmpty()" in ed and "showEmpty();" in ed
      and "state.emptyEl = dock.querySelector" in ed
      and "no file open" in ed)

# ------------------------------------------------------------- longrun/orbit api
from longrun.orbit import api as oapi  # noqa: E402

check("orbit api exposes _ok helper", hasattr(oapi, "_ok"))


class _FakeHandler:
    def __init__(self):
        self.code = None

    def _send(self, code, obj, **kw):
        self.code = code


h1 = _FakeHandler()
oapi._ok(h1, {"ok": False, "error": "goal required"})
h2 = _FakeHandler()
oapi._ok(h2, {"ok": True, "job": "j1"})
h3 = _FakeHandler()
oapi._ok(h3, {"sessions": []})  # no `ok` key -> success
check("orbit _ok maps ok=false to 400", h1.code == 400)
check("orbit _ok keeps success at 200", h2.code == 200 and h3.code == 200)
oapi_src = read("src", "longrun", "orbit", "api.py")
check("orbit POST routes use _ok", oapi_src.count("_ok(handler,") >= 3)

# ------------------------------------------------------------- server.publish
from longrun.core import server as srv  # noqa: E402

ev = srv.publish("approval.request", id="ap_regress", tool="fs.write")
check("in-memory event id is int", isinstance(ev.get("id"), int))
check("payload id moved to id_id", ev.get("id_id") == "ap_regress")

row = srv.db().execute("SELECT data FROM events WHERE kind='approval.request' ORDER BY id DESC LIMIT 1").fetchone()
stored = json.loads(row[0])
check("durable row does NOT store a payload `id`", "id" not in stored and stored.get("id_id") == "ap_regress")

replayed = [e for e in srv.events_since(0) if e.get("kind") == "approval.request"]
check("replayed event id stays int", bool(replayed) and isinstance(replayed[-1].get("id"), int),
      "got %r" % (replayed[-1].get("id") if replayed else None))

# ------------------------------------------------------------- raw upload cap
httpapi_src = read("src", "longrun", "core/httpapi.py")
s = read("src", "longrun", "core/server.py") + httpapi_src
check("raw body reader bounds allocation and drains oversize payloads",
      "def _read_bounded_body(stream: BinaryIO, length: int, limit: int)" in httpapi_src
      and "size = min(65536, remaining, room)" in httpapi_src
      and "chunk = stream.read(size)" in httpapi_src
      and "data.extend(chunk[:room])" in httpapi_src
      and "if length > limit" in httpapi_src)
check("raw upload routes reject oversized bodies instead of accepting truncated data",
      httpapi_src.count("_read_bounded_body(self.rfile, n, MAX_BODY_BYTES)") >= 2
      and "_read_bounded_body(self.rfile, n, cap)" in httpapi_src
      and httpapi_src.count("code = 413 if n >") >= 3
      and httpapi_src.count("return self._send(code,") >= 3)
from longrun.core import httpapi as httpapi_mod  # noqa: E402

_oversize = io.BytesIO(b"abcdefgh")
_bounded = httpapi_mod._read_bounded_body(_oversize, 8, 4)
check("bounded upload reader rejects oversize payloads after draining the request",
      _bounded is None and _oversize.read() == b"")
_complete = httpapi_mod._read_bounded_body(io.BytesIO(b"abc"), 3, 3)
check("bounded upload reader preserves complete in-limit payloads", _complete == b"abc")
_short = httpapi_mod._read_bounded_body(io.BytesIO(b"abc"), 5, 10)
check("bounded upload reader rejects incomplete payloads", _short is None)

# --------------------------------------------------- feed replay is bounded
check("feed replay cap constant exists", isinstance(srv.FEED_REPLAY_MAX, int) and srv.FEED_REPLAY_MAX > 0)
for i in range(8):
    srv.publish("feed.regress", n=i)
cap = srv.events_since(0, limit=5)
check("events_since(limit) returns at most N", 0 < len(cap) <= 5)
check("events_since(limit) keeps the NEWEST rows",
      bool(cap) and cap[-1]["id"] == max(e["id"] for e in srv.events_since(0)))
check("feed_gen caps the backlog", "events_since(since, limit=FEED_REPLAY_MAX)" in s)

# -------------------------------------- JAG-500: tree <-> tab highlight sync
check("editor tree rows carry their path as the sync key",
      "row.dataset.path = f.path;" in ed)
check("one sync function drives the tree highlight from the active tab",
      "function syncTreeActive()" in ed
      and 'r.classList.toggle("active", !!want && r.dataset.path === want)' in ed
      and ed.count("syncTreeActive();") >= 2)   # renderTabs + loadTree
check("revealInTree keeps the revealed row highlighted",
      "function activePath()" in ed and 'hit.classList.add("active")' in ed)

# ---------------------- JAG-500: no chat blanking / restart at the end of a turn
check("build watcher no longer restarts the page",
      "location.reload(); }" not in gui and "function _offerReload()" in gui
      and "t.onclick = () => location.reload();" in gui)
check("click-to-reload chip opts back into pointer events",
      ".sf-toast.action { pointer-events: auto;" in gui)
check("feed chat.done rebuilds only for a turn this tab did not stream",
      "function _rebuildOnFeedDone(sid)" in gui
      and "if (_streamedDone[sid] || turnSSE[sid] || sid !== sessionId) return;" in gui
      and gui.count("_rebuildOnFeedDone(") >= 3)   # definition + _feedReplay + connectFeed
check("a streamed turn is recorded so the feed cannot re-render it",
      "_streamedDone[turnSession] = true;" in gui and "_streamedDone[sid] = true;" in gui
      and gui.count("_streamedDone[d.session] = false;") >= 2)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
