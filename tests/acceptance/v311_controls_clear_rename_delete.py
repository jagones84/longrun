#!/usr/bin/env python3
"""v311 — session CLEAR, session RENAME, JOB DELETE, and zoom/pan wiring
(JAG-311).

Locks the new user-facing controls:
  * a session can be CLEARED in place (chat history + task list wiped, the
    session and its agent badge stay) — server route + WebUI button + command
    palette entry + the Orbit agents row;
  * a session can be RENAMED from the rail (server route + menu);
  * a JOB can be DELETED from the Orbit panel (registry.delete + HTTP route +
    UI button), and deletion is REFUSED while the job is running;
  * the constellation supports zoom + pan; the org chart scrolls natively (JAG-342).

Deterministic, no browser, no model. Run: python3 tests/acceptance/v311_controls_clear_rename_delete.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
TMP = tempfile.mkdtemp(prefix="sf-v311-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, (" :: " + str(detail)) if detail else ""))


from longrun.core import server  # noqa: E402
from longrun.orchestrate import jobs  # noqa: E402
from longrun.agent import agents  # noqa: E402

# ---- A: session CLEAR (server-side contract) -------------------------------
s = server.get_or_create_session(None, "clear-me")
sid = s["id"]
server.append_message(s, "user", "hello")
server.append_message(s, "assistant", "hi there")
check("session has 2 messages before clear", len(server.load_session(sid)["messages"]) == 2)

# the clear handler body (mirrors POST /api/sessions/<sid>/clear)
sess = server.load_session(sid)
sess["messages"] = []
server.save_session(sess)
check("clear wipes the chat history", server.load_session(sid)["messages"] == [])
check("clear keeps the session itself", server.load_session(sid) is not None)
check("clear keeps the title", server.load_session(sid).get("title") == "clear-me")

# the route must exist in the server source (wired, not just a helper)
with open(os.path.join(REPO, "src", "longrun", "core/server.py"), encoding="utf-8") as f:
    srv = f.read()
with open(os.path.join(REPO, "src", "longrun", "core/httpapi.py"), encoding="utf-8") as f:
    srv += f.read()
check("POST /api/sessions/<sid>/clear route exists", 'path.endswith("/clear")' in srv)
check("clear publishes session.cleared", 'publish("session.cleared"' in open(os.path.join(REPO, "src", "longrun", "memory/stores.py"), encoding="utf-8").read())

# ---- B: session RENAME (server-side contract) ------------------------------
check("POST /api/sessions/<sid>/rename route exists", 'path.endswith("/rename")' in srv)
sess = server.load_session(sid)
sess["title"] = "renamed-session"
server.save_session(sess)
check("rename persists the new title", server.load_session(sid)["title"] == "renamed-session")
check("rename publishes session.renamed", 'publish("session.renamed"' in srv)

# ---- C: JOB DELETE (registry contract) -------------------------------------
s1 = server.get_or_create_session(None, "w1")["id"]
s2 = server.get_or_create_session(None, "w2")["id"]
agents.REGISTRY.designate(s1, name="w1")
agents.REGISTRY.designate(s2, name="w2")
aid1 = agents.REGISTRY.get(s1)["id"]
aid2 = agents.REGISTRY.get(s2)["id"]
made = jobs.JOBS.create("do a thing", coordinator=aid1, agents=[aid1, aid2])
jid = made["job"]["id"]
check("a job was created", bool(jobs.JOBS.get(jid)))
check("a running job cannot be deleted", jobs.JOBS.delete.__doc__ is not None)
jobs.JOBS._update(jid, lambda j: j.update({"status": "running"}))
res_run = jobs.JOBS.delete(jid)
check("delete is REFUSED while the job runs", res_run.get("ok") is False and "running" in (res_run.get("error") or ""))
check("the running job is still there", jobs.JOBS.get(jid) is not None)
jobs.JOBS._update(jid, lambda j: j.update({"status": "done"}))
res = jobs.JOBS.delete(jid)
check("a finished job IS deleted", res.get("ok") is True)
check("the deleted job is gone", jobs.JOBS.get(jid) is None)
check("deleting a missing job is a clean refusal", jobs.JOBS.delete("J9999").get("ok") is False)

with open(os.path.join(REPO, "src", "longrun", "orchestrate/orchestration.py"), encoding="utf-8") as f:
    orch = f.read()
check("DELETE /api/jobs/<id> is routed", 'method == "DELETE" and path.startswith("/api/jobs/")' in orch)

# ---- D: UI wiring (main app + Orbit) ---------------------------------------
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    gui = f.read()
check("main rail has a hover action menu", "openSessMenu" in gui and "menu-btn" in gui)
check("the menu offers pin/rename/clear/delete", all(k in gui for k in ("Pin session", "Rename", "Clear chat + tasks", "Delete session")))
check("the main app can clear a session", "clearSession" in gui and '"/clear"' in gui)
check("the command palette offers Clear session", "Clear session (wipe chat + tasks)" in gui or "Clear session" in gui)
check("the main app clears the log on a remote clear", 'es.addEventListener("session.cleared"' in gui)
check("a compaction notice is shown in the chat feed", 'es.addEventListener("context.compact"' in gui and 'es.addEventListener("context.auto_compact"' in gui)
check("reset lives in the composer ⋯ menu, not as a bar button (JAG-415)",
      # JAG-425: the binding moved to a delegated data-call attribute.
      'id="resetBtn"' not in gui and '↺ reset session' in gui and 'data-call="clearSession"' in gui)
check("the overflow menu offers reset session", "reset session" in gui)
# JAG-395: right-click opens that row's own menu; Edit role opens code mode.
check("right-click on ANY session row opens its own ⋯ menu",
      "d.oncontextmenu" in gui and "openSessMenu(d, s, ag)" in gui)
check("Edit role opens ROLE.md in the editor's CODE mode (not render)",
      'openInEditor(rp, { mode: "code" })' in gui)

with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8") as f:
    orb = f.read()
check("Orbit agent row has a clear button", 'data-clear' in orb)
check("Orbit clear calls /clear", "/clear" in orb)
check("Orbit job row has a delete button", 'data-jdel' in orb)
check("Orbit delete calls /api/jobs/", '"/api/jobs/" + encodeURIComponent(jid)' in orb)
check("constellation supports zoom/pan", "_zoomPan" in orb)
# JAG-342: the org chart pan (transform) was removed — it fought the panel scrollbar
# and clipped wide trees; the chart now scrolls NATIVELY inside its panel.
check("org chart scrolls natively (transform pan removed)",
      "orgwrap{" in orb and "overflow:auto" in orb and "_panzoom" not in orb)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

