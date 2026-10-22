#!/usr/bin/env python3
"""v507 — Mandatory <namespace>.<subtool> refactoring across base tools, MCP, Matrix, and Settings."""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import matrix  # noqa: E402
from longrun.tools import matrix_guard, registry, tools  # noqa: E402

# This test covers the local registry and Matrix loader, not operator MCP
# servers. Keep registry.catalog() deterministic and offline.
registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# A: Every tool in registry.catalog() is namespaced (<ns>.<sub> or <client>__<tool>) — zero plain tools
cat = registry.catalog()
cat_names = [t["name"] for t in cat]
plain = [n for n in cat_names if "." not in n and "__" not in n]
check("A zero plain tools in registry.catalog() (every tool has <namespace>.<subtool> or <server>__<tool>)",
      len(cat) > 30 and plain == [], plain)

# B: Base subtools exist in catalog & schemas (memory.list, memory.recall, skills.list, shell.exec, etc.)
expected_subtools = {
    "shell.exec", "fs.read", "fs.write", "fs.edit", "git.run", "http.fetch", "browser.fetch",
    "self.info", "self.diagnose", "self.logs", "self.context", "self.tools",
    "reconcile.run", "skills.list", "skills.read",
    "index.search", "index.reindex", "index.status",
    "knowledge.search", "knowledge.list_notebooks", "knowledge.status",
    "sessions.list", "sessions.read", "sessions.send", "sessions.wait",
    "chapters.list", "chapters.untitled", "chapters.read", "chapters.title",
    "context.status", "context.compact",
    "memory.list", "memory.recall", "memory.store", "memory.recent", "memory.core",
    "memory.set_core", "memory.invalidate", "memory.forget", "memory.purge", "memory.health",
    "improve.propose", "improve.review",
    "web.search", "web.fetch", "diff.files", "diff.text",
    "python.run", "process.list", "process.kill", "glob.list",
    "matrix.status", "matrix.hotload", "matrix.enable", "matrix.disable",
    "matrix.remove", "matrix.verify_target", "matrix.promote_to_nucleus",
}
missing = sorted(expected_subtools - set(cat_names))
check("B all canonical base subtools (including memory.list, skills.list, matrix.status, etc.) are registered",
      missing == [], missing)

# C: Calling namespaced subtools directly works without passing an `action` field
r_mem_store = tools.execute("memory.store", {"content": "v507 namespaced subtool fact", "kind": "test"})
r_mem_list = tools.execute("memory.list", {"limit": 5})
r_sk_list = tools.execute("skills.list", {})
r_self_info = tools.execute("self.info", {})
r_mtx_st = tools.execute("matrix.status", {})
check("C tools.execute dispatches namespaced subtools (memory.store, memory.list, skills.list, self.info, matrix.status)",
      r_mem_store.get("ok") is True
      and r_mem_list.get("ok") is True and "v507 namespaced subtool fact" in (r_mem_list.get("stdout") or "")
      and r_sk_list.get("ok") is True
      and r_self_info.get("ok") is True
      and r_mtx_st.get("ok") is True)

# D: Matrix tool loader enforces / normalizes <namespace>.<subtool> and supports multi-subtool TOOL_SCHEMAS
with tempfile.TemporaryDirectory() as tmp:
    os.environ["LONGRUN_MATRIX_SRC"] = os.path.join(tmp, "src", "Matrix")
    os.environ["LONGRUN_MATRIX_DOT"] = os.path.join(tmp, ".Matrix")
    try:
        matrix_guard.ensure_layout(tmp)
        with open(os.path.join(tmp, "src", "Matrix", "tools", "custom_suite.py"), "w", encoding="utf-8") as f:
            f.write(
                'TOOL_SCHEMAS = {\n'
                '  "custom_suite.ping": {"description": "ping", "type": "object", "properties": {}},\n'
                '  "custom_suite.pong": {"description": "pong", "type": "object", "properties": {}},\n'
                '}\n'
                'def execute(args, run_id=None, subtool=None):\n'
                '    return {"ok": True, "stdout": "ran:" + str(subtool or (args or {}).get("action"))}\n'
            )
        matrix.hotload(tmp)
        dtools = matrix.discover_tools(tmp)
        r_ping = matrix.execute_tool("custom_suite.ping", {}, repo_root=tmp)
        r_pong = matrix.execute_tool("custom_suite.pong", {}, repo_root=tmp)
        r_seams = tools.execute("matrix.seams", {})
        r_scaf_tool = matrix.scaffold("tool", "netprobe.check", "Network probe", repo_root=tmp)
        r_scaf_hook = matrix.scaffold("hook", "plan", repo_root=tmp)
        r_scaf_skill = matrix.scaffold("skill", "auto_debug", "Debug skill", repo_root=tmp)
        dtools2 = matrix.discover_tools(tmp)
        dhooks2 = matrix.discover_hooks(tmp)
        check("D Matrix loader & matrix.scaffold/matrix.seams create and hotload <ns>.<sub> tools, hooks, and skills",
              "custom_suite.ping" in dtools and "custom_suite.pong" in dtools
              and r_ping.get("ok") is True and "ran:ping" in (r_ping.get("stdout") or "")
              and r_pong.get("ok") is True and "ran:pong" in (r_pong.get("stdout") or "")
              and r_seams.get("ok") is True and "plan" in (r_seams.get("seams") or {})
              and r_scaf_tool.get("ok") is True and "netprobe.check" in dtools2
              and r_scaf_hook.get("ok") is True and "plan" in dhooks2
              and r_scaf_skill.get("ok") is True and os.path.isfile(r_scaf_skill.get("path", "")))
    finally:
        os.environ.pop("LONGRUN_MATRIX_SRC", None)
        os.environ.pop("LONGRUN_MATRIX_DOT", None)

# E: Matrix system prompt & MANUAL.md instruct the agent to create tools in <namespace>.<subtool> syntax
from longrun.core import api_v02  # noqa: E402
from longrun.util import paths as _paths  # noqa: E402
tctx = api_v02.tool_context()
prompt_txt = matrix.MATRIX_SYSTEM_PROMPT
# JAG-533: the runtime checkout lives in the USER DATA HOME, not in the repo. The
# manual is a generated artifact, so fall back to the shipped text when this
# machine has not initialised it yet.
_manual_path = os.path.join(_paths.MATRIX_DOT_DIR, "docs", "MANUAL.md")
if os.path.isfile(_manual_path):
    with open(_manual_path, encoding="utf-8") as f:
        manual_txt = f.read()
else:
    from longrun.tools import matrix_guard as _mguard
    manual_txt = _mguard._DEFAULT_MANUAL
check("E Matrix prompt, MANUAL.md, and api_v02.tool_context() expose <namespace>.<subtool> syntax",
      "<namespace>.<subtool>" in prompt_txt
      and "<namespace>.<subtool>" in manual_txt
      # JAG-513: the prompt index groups them as `namespace{a,b,c}`.
      and "Tool discovery" in tctx and "memory{" in tctx and "matrix{" in tctx)

# F: sessions can TALK to each other (JAG-532).
# A running peer gets the message inside its current turn (the operator's steer
# inbox); an idle peer gets a REAL server-side turn through the Orchestrator, so
# the message is never queued forever. The reply is read back with sessions.read.
from longrun.core import server  # noqa: E402
from longrun.orbit import api as orbit_api  # noqa: E402
from longrun.util import steering  # noqa: E402

_KNOWN = {"peer-run", "peer-idle", "peer-poll"}
_orig_load = server.load_session
_orig_active = server._ACTIVE_CHAT
_orig_dispatch = orbit_api.dispatch_message
_orig_job_status = getattr(orbit_api, "job_status", None)
dispatched = []
fake_sessions = {sid: {"id": sid, "messages": []} for sid in _KNOWN}
job_states = {"job-peer-idle": {
    "job": "job-peer-idle", "session": "peer-idle", "state": "error",
    "ended": 100, "error": "provider failed",
}, "job-peer-poll": [
    {"job": "job-peer-poll", "session": "peer-poll", "state": "running"},
    {"job": "job-peer-poll", "session": "peer-poll", "state": "done", "ended": 200},
]}


def _fake_dispatch(session: str, message: str, model: str | None = None) -> dict:
    dispatched.append({"session": session, "message": message, "model": model})
    return {"ok": True, "count": 1,
            "jobs": [{"job": "job-" + session, "session": session, "state": "running"}]}


def _fake_job_status(job_id: str) -> dict | None:
    status = job_states.get(job_id)
    if isinstance(status, list):
        return status.pop(0) if len(status) > 1 else status[0]
    return status


r_send_run = r_send_idle = r_send_poll = None
r_send_missing = r_send_self = r_send_empty = None
r_wait = r_wait_error = r_wait_poll = r_wait_poll_retry = None
try:
    server.load_session = lambda sid: fake_sessions.get(sid)
    server._ACTIVE_CHAT = {"peer-run": {"ev0": 0, "ts": 0, "tok": object()}}
    orbit_api.dispatch_message = _fake_dispatch
    orbit_api.job_status = _fake_job_status
    steering.STEER_INBOX.clear()
    r_send_run = tools._sessions(
        {"action": "send", "session": "peer-run", "message": "status?"}, "me-1")
    r_send_idle = tools._sessions(
        {"action": "send", "to": "peer-idle", "text": "status?"}, "me-1")
    r_send_poll = tools._sessions(
        {"action": "send", "session": "peer-poll", "message": "status?"}, "me-1")
    r_send_missing = tools._sessions(
        {"action": "send", "session": "nope", "message": "x"}, "me-1")
    r_send_self = tools._sessions(
        {"action": "send", "session": "peer-run", "message": "x"}, "peer-run")
    r_send_empty = tools._sessions(
        {"action": "send", "session": "peer-run", "message": "   "}, "me-1")
    steered = steering.drain_steer("peer-run")
    fake_sessions["peer-run"]["messages"].append(
        {"role": "assistant", "content": "pong", "ts": 99})
    server._ACTIVE_CHAT = {}
    r_wait = tools._sessions(
        {"action": "wait", "message_id": r_send_run.get("message_id"),
         "timeout_secs": 0}, "me-1")
    r_wait_error = tools._sessions(
        {"action": "wait", "message_id": r_send_idle.get("message_id"),
         "timeout_secs": 0}, "me-1")
    fake_sessions["peer-poll"]["messages"].append(
        {"role": "assistant", "content": "poll reply", "ts": 100})
    r_wait_poll = tools._sessions(
        {"action": "wait", "message_id": r_send_poll.get("message_id"),
         "timeout_secs": 0.4}, "me-1")
    job_states["job-peer-poll"] = None
    r_wait_poll_retry = tools._sessions(
        {"action": "wait", "message_id": r_send_poll.get("message_id"),
         "timeout_secs": 0}, "me-1")
finally:
    server.load_session = _orig_load
    server._ACTIVE_CHAT = _orig_active
    orbit_api.dispatch_message = _orig_dispatch
    if _orig_job_status is None:
        delattr(orbit_api, "job_status")
    else:
        orbit_api.job_status = _orig_job_status
    steering.STEER_INBOX.clear()
    with tools._SESSION_SENDS_LOCK:
        for _mid in (r_send_run.get("message_id"), r_send_idle.get("message_id"),
                     r_send_poll.get("message_id")):
            tools._SESSION_SENDS.pop(_mid, None)

_send_spec = (registry.tool_spec("sessions.send") or {}).get("schema") or {}
_wait_spec = (registry.tool_spec("sessions.wait") or {}).get("schema") or {}
check("F a RUNNING peer gets the message through the steer inbox",
      r_send_run.get("ok") is True and r_send_run.get("mode") == "steer"
      and r_send_run.get("message_id")
      and any("[message from session me-1]" in t for t in steered), str(steered))
check("F2 an IDLE peer gets a real server-side turn (Orchestrator dispatch)",
      r_send_idle.get("ok") is True and r_send_idle.get("mode") == "turn"
      and r_send_idle.get("message_id")
      and dispatched and dispatched[0]["session"] == "peer-idle"
      and "[message from session me-1]" in dispatched[0]["message"], str(dispatched))
check("F3 a missing session, a self-send and an empty message are refused",
      r_send_missing.get("ok") is False and "no such session" in r_send_missing.get("error", "")
      and r_send_self.get("ok") is False
      and r_send_empty.get("ok") is False and r_send_empty.get("exit_code") == 64,
      " ".join(str(r.get("error")) for r in (r_send_missing, r_send_self, r_send_empty)))
check("F4 send schema declares every alias and paired target/message alternatives",
      {"session", "to", "message", "text"} <= set(_send_spec.get("properties") or {})
      and len(_send_spec.get("anyOf") or []) == 4, str(_send_spec)[:200])
check("F5 wait returns the peer's final assistant reply after the turn ends",
      r_wait.get("ok") is True and r_wait.get("state") == "done"
      and r_wait.get("reply") == "pong" and r_wait.get("message_id")
      and "sessions.read" in _wait_spec.get("description", ""), str(r_wait))
check("F6 wait reports an idle job failure even when no assistant reply was persisted",
      r_wait_error.get("ok") is False and r_wait_error.get("exit_code") == 1
      and r_wait_error.get("state") == "error"
      and r_wait_error.get("error") == "provider failed",
      str(r_wait_error))
bad_send = tools._dispatch_execute(
    "sessions.send", {"action": "send", "text": "message without recipient"}, "me-1")
check("F7 anyOf rejects a send without a target before session lookup",
      bad_send.get("exit_code") == 64
      and bad_send.get("missing_any_of") == [
          ["session", "message"], ["session", "text"],
          ["to", "message"], ["to", "text"],
      ], str(bad_send))
check("F8 wait observes an idle job transition from running to done",
      r_wait_poll.get("ok") is True and r_wait_poll.get("state") == "done"
      and r_wait_poll.get("ended") == 200 and r_wait_poll.get("reply") == "poll reply",
      str(r_wait_poll))
check("F9 repeating wait returns the cached reply after Orbit evicts the job",
      r_wait_poll_retry.get("ok") is True and r_wait_poll_retry.get("state") == "done"
      and r_wait_poll_retry.get("ended") == 200
      and r_wait_poll_retry.get("reply") == "poll reply", str(r_wait_poll_retry))

print("---")
okc = sum(results)
print("v507: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
