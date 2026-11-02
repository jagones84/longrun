#!/usr/bin/env python3
"""v773 — three operator-reported defects (2026-11-02).

1. "why doesn't automatic codebase indexing work?" — the background indexer was
   armed ONLY for the DEFAULT workspace (at boot) and for a workspace set through
   the API. A session-scoped workspace therefore never had a worker: live, 48
   sessions on one folder showed "no watcher for this workspace" with 92 files
   newer than the index. `autoidx.start_for_sessions()` arms every workspace the
   known sessions USE, and `_session_ws()` arms lazily for one created later.

2. "if I change the chat LLM while a run is in progress, it switches back to the
   previous one" — a turn loads the session at its START and writes the whole dict
   at its end, so the end-of-turn write reverted the operator's mid-run choice.
   `stores.adopt_live_choices()` re-reads the operator-owned fields first.

3. "queued messages must be editable like the goal" — the queue chip had only ⇢
   (steer) and × (remove). The ✎ returns the message to the composer WITH its
   attachment snapshot (no second editor).

Deterministic: no live model, no network, no server.
Run: python3 tests/acceptance/v773_live_choices_and_watcher_and_queue_edit.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v773-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "ROLES_DIR", "DB", "COSTS_DIR",
           "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "WORKSPACES_ROOT", "GOALS_DIR",
           "AGENTS_FILE", "TEAMS_FILE"):
    val = os.path.join(TMP, _k.lower() + (".json" if _k.endswith("_FILE") else ""))
    if not _k.endswith("_FILE") and _k != "DB":
        os.makedirs(val, exist_ok=True)
    os.environ["LONGRUN_" + _k] = val
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import autoidx                            # noqa: E402
from longrun.memory import stores                             # noqa: E402

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as _f:
    HTML = _f.read()
with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8") as _f:
    API = _f.read()
with open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8") as _f:
    HTTP = _f.read()
with open(os.path.join(REPO, "src", "longrun", "memory", "stores.py"), encoding="utf-8") as _f:
    STORES_SRC = _f.read()

# ============================================================================
# A — the turn must not revert a choice made DURING it
# ============================================================================
check("A1 LIVE_OPERATOR_FIELDS names the fields an operator can change mid-run",
      stores.LIVE_OPERATOR_FIELDS == ("model", "workspace"), stores.LIVE_OPERATOR_FIELDS)

stores.save_session({"id": "sessA", "model": "old:model", "workspace": "/old/ws",
                     "messages": []})
stores.live_fields_changed("sessA", model="new:model", workspace="/new/ws")
# a turn that loaded the session at its START writes the WHOLE stale dict
stores.save_session({"id": "sessA", "model": "old:model", "workspace": "/old/ws",
                     "messages": [{"role": "user", "content": "hi"}]})
_row = stores.load_session("sessA")
check("A2 a stale write CANNOT resurrect the model/workspace the operator chose mid-run",
      _row["model"] == "new:model" and _row["workspace"] == "/new/ws", _row)
check("A2b that stale write still persists the transcript it was actually carrying",
      _row["messages"] == [{"role": "user", "content": "hi"}], _row["messages"])

stores.save_session({"id": "sessC", "model": "keep:me", "messages": []})
stores.save_session({"id": "sessC", "model": "keep:me",
                     "messages": [{"role": "user", "content": "x"}]})
check("A3 a session nobody changed live is written exactly as given (no invention)",
      stores.load_session("sessC")["model"] == "keep:me")

bad = {"id": "../../etc/passwd", "model": "keep"}
check("A4 an unsafe session id is a no-op (never raises, never writes outside the store)",
      stores.adopt_live_choices(bad) is bad and bad["model"] == "keep")

check("A5 the defence lives in the ONE writer every turn path goes through",
      "adopt_live_choices(sess)" in STORES_SRC
      and STORES_SRC.index("def save_session(") < STORES_SRC.index("adopt_live_choices(sess)"))
check("A5b the model endpoint RECORDS the choice its own writer made",
      "live_fields_changed(sid, model=ref)" in STORES_SRC)
check("A5c the tool-card / inject writers are covered because they call save_session",
      "save_session(sess)" in STORES_SRC)

# ============================================================================
# B — the background indexer covers every workspace IN USE, not only the default
# ============================================================================
ws1 = os.path.join(TMP, "ws_one")
ws2 = os.path.join(TMP, "ws_two")
os.makedirs(ws1, exist_ok=True)
os.makedirs(ws2, exist_ok=True)
rows = [{"id": "s1", "workspace": ws1}, {"id": "s2", "workspace": ws1},
        {"id": "s3", "workspace": ws2}, {"id": "s4", "workspace": ""},
        {"id": "s5"}, {"id": "s6", "workspace": os.path.join(TMP, "gone")}]
started = autoidx.start_for_sessions(rows)
check("B1 one worker per DISTINCT real workspace (dedup, empty/absent/gone ignored)",
      started == 2, started)
check("B1b both workspaces are watched now",
      autoidx.watch_state(ws1)["watched"] and autoidx.watch_state(ws2)["watched"],
      (autoidx.watch_state(ws1), autoidx.watch_state(ws2)))
check("B1c the reader's workspace (not in the list) is NOT watched",
      not autoidx.watch_state(os.path.join(TMP, "never"))["watched"])
check("B2 a second pass is idempotent (never two workers for one tree)",
      autoidx.start_for_sessions(rows) == 0)
autoidx.stop_all()

check("B3 boot arms every session workspace, not only the default",
      "_autoidx.start_for_sessions()" in HTTP)
check("B4 resolving a session's workspace arms its indexer (covers a folder made after boot)",
      "_autoidx.start(ws)" in API and "def _session_ws(" in API
      and API.index("def _session_ws(") < API.index("_autoidx.start(ws)"))

# ============================================================================
# C — a queued message is editable, and its attachments ride the queue
# ============================================================================
check("C1 the queue chip carries an ✎ edit control",
      "function editQueued(" in HTML
      and 'ed.textContent = "✎"' in HTML
      and "ed.onclick = () => editQueued(i);" in HTML
      and "chip.appendChild(ed)" in HTML)
check("C2 edit RETURNS the message to the composer (no second editor box)",
      "inp.value = it.text || \"\"" in HTML
      and "inp.focus();" in HTML
      and 'createElement("textarea")' not in HTML.split("function editQueued(")[1].split("function steerQueued(")[0])
check("C3 the item leaves the queue when it is edited (no duplicate send)",
      "q.splice(i, 1)" in HTML.split("function editQueued(")[1].split("function steerQueued(")[0])
check("C4 its attachments come back to the composer with it",
      "_attachments.push(a)" in HTML.split("function editQueued(")[1].split("function steerQueued(")[0]
      and "_renderAttach(); _renderPendingCtxItems();" in HTML)
check("C5 a queued message ALREADY carries its attachment snapshot (parity with the composer)",
      "atts: _attSnap" in HTML and "const _attSnap = (Array.isArray(atts) && atts.length) ? atts.slice() : _attachments.slice();" in HTML)
check("C6 flushing a queued item re-sends it WITH those attachments",
      "send(it.raw, it.text, it.atts);" in HTML)

print()
print("%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
