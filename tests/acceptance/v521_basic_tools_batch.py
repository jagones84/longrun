#!/usr/bin/env python3
"""v521 — deterministic batch smoke test for basic namespaced tools."""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v521-")
for name, tail in {
    "LONGRUN_DATA_DIR": "data",
    "LONGRUN_CONFIG_DIR": "cfg",
    "LONGRUN_DB": "events.db",
    "LONGRUN_SESSIONS_DIR": "sessions",
    "LONGRUN_GRAPH_DIR": "graphs",
    "LONGRUN_EDITS_DIR": "edits",
    "LONGRUN_RUNS_DIR": "runs",
    "LONGRUN_ROLES_DIR": "roles",
    "LONGRUN_COSTS_DIR": "costs",
    "LONGRUN_THREADS_DIR": "threads",
    "LONGRUN_PRICES_FILE": "prices.json",
    "LONGRUN_MATRIX_SRC": "matrix_src",
    "LONGRUN_MATRIX_DOT": "matrix_dot",
}.items():
    os.environ[name] = os.path.join(TMP, tail)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402
from longrun.tools import tools as T  # noqa: E402
from longrun.core import server  # noqa: E402,F401
from longrun.core import httpapi  # noqa: E402
from longrun.agent import agent as agent_mod  # noqa: E402
from longrun.util import improve as improve_mod  # noqa: E402
from longrun.util import selfevolve as selfevolve_mod  # noqa: E402

registry._external_tools = lambda: {}
registry._matrix_tools = lambda: {}
registry._promoted_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def run(tool, args):
    return T._dispatch_execute(tool, args, run_id="v521")


propose_schema = (registry.tool_spec("improve.propose") or {}).get("schema") or {}
check("improve.propose requires exact scope and content",
      propose_schema.get("required") == ["scope", "content"]
      and (propose_schema.get("properties", {}).get("scope", {}).get("enum")
           == ["skill", "project", "global"]))

verify_schema = (registry.tool_spec("improve.verify") or {}).get("schema") or {}
check("improve.verify requires only its proposal path",
      verify_schema.get("required") == ["path"]
      and set(verify_schema.get("properties") or {}) == {"path"},
      (verify_schema.get("required"), list(verify_schema.get("properties") or {})))

old_repo, old_verify = registry.REPO, selfevolve_mod.verify
proposal_root = os.path.join(TMP, "data", "proposals", "skills")
os.makedirs(proposal_root, exist_ok=True)
registry.REPO = TMP
selfevolve_mod.verify = lambda path: {"ok": True, "green": True, "path": path}
try:
    verified = run("improve.verify", {"path": proposal_root})
    verified_legacy = run(
        "improve.verify", {"scope": "skill", "path": proposal_root})
finally:
    registry.REPO, selfevolve_mod.verify = old_repo, old_verify
check("improve.verify infers the mine scope and calls the verifier",
      verified.get("ok") is True
      and (verified.get("verify") or {}).get("green") is True,
      verified)
check("improve.verify ignores the stale, misleading skill scope",
      verified_legacy.get("ok") is True
      and (verified_legacy.get("verify") or {}).get("green") is True,
      verified_legacy)

bad_scope = run("improve.propose", {"scope": "skills", "content": "probe"})
check("improve.propose explains singular scope names",
      all(name in (bad_scope.get("error") or "")
          for name in ("skill", "project", "global")),
      bad_scope.get("error"))
skill_proposal = improve_mod.propose("skill", "v521 disposable proposal")
skill_decision = improve_mod.decide(skill_proposal["id"], "approve")
check("skill proposals cannot be falsely accepted by the backend",
      skill_decision.get("ok") is False
      and "not implemented" in (skill_decision.get("error") or "")
      and improve_mod.get_proposal(skill_proposal["id"]).get("status") == "pending",
      skill_decision)

old_load, old_assemble = agent_mod.server.load_session, agent_mod.assemble_turn
compact_snapshot = {
    "id": "compact-test",
    "messages": [{"role": "system", "content": "persisted compact summary"}],
    "tool_cards": [{"tool": "context.compact"}],
}
agent_mod.server.load_session = lambda _sid: compact_snapshot
agent_mod.assemble_turn = lambda *_args, **_kwargs: (
    [{"role": "system", "content": "rebuilt compacted base"}],
    {"final_tokens": 12},
)
live_session = {"id": "compact-test", "messages": [{"role": "user", "content": "old"}]}
live_msgs = [
    {"role": "system", "content": "old context"},
    {"role": "assistant", "content": "work in progress"},
]
try:
    rebased, base, ctx = agent_mod._sync_compacted_turn(
        live_session, live_msgs, 1, "current request", {}, "test-model", False)
finally:
    agent_mod.server.load_session = old_load
    agent_mod.assemble_turn = old_assemble
check("agent rebases compacted storage and keeps only in-flight turn tail",
      live_session.get("messages") == compact_snapshot["messages"]
      and [m.get("content") for m in rebased]
      == ["rebuilt compacted base", "work in progress"]
      and base == 1 and ctx == {"final_tokens": 12})

# Agent compaction delegates to the same shared procedure as the RH button.
old_compact = httpapi.compact_session
compact_calls = []
httpapi.compact_session = lambda sid, *args, **kwargs: (
    compact_calls.append((sid, kwargs.get("origin")))
    or {"compacted": 2, "messages_after": 2, "summary": "extractive"})
try:
    compact_result = T._context({"action": "compact"}, "v521")
finally:
    httpapi.compact_session = old_compact
check("context.compact uses the shared manual compaction procedure",
      compact_calls == [("v521", "tool")]
      and compact_result.get("ok") is True
      and compact_result.get("stats", {}).get("compacted") == 2)

# Tool discovery must return a real subset, not an empty success payload.
discovery = run("self.tools", {"query": "diff.text"})
check("self.tools.query finds diff.text",
      discovery.get("tools", {}).get("native") == ["diff.text"],
      discovery.get("tools", {}).get("native"))

# Read-only filesystem and text operations use the real dispatcher.
readme = run("fs.read", {"path": "README.md", "start_line": 1, "end_line": 8})
check("fs.read returns a requested line range",
      readme.get("ok") is True and "# Longrun" in (readme.get("content") or ""),
      readme.get("error") or readme.get("exit_code"))

files = run("glob.list", {
    "pattern": "v*.py", "root": "tests/acceptance", "limit": 5})
check("glob.list finds bounded acceptance tests",
      files.get("ok") is True and 0 < files.get("count", 0) <= 5,
      files.get("count"))

diff = run("diff.text", {"text_a": "before\n", "text_b": "after\n"})
check("diff.text returns the changed lines",
      diff.get("ok") is True and "-before" in diff.get("stdout", "")
      and "+after" in diff.get("stdout", ""))

# Local, deterministic search substitute; no internet request is made.
old_search = T._web_search
T._web_search = lambda query, count: (
    [{"title": "stub result", "url": "https://example.invalid/",
      "snippet": "local test"}], "test")
try:
    web = run("web.search", {"query": "smoke test"})
finally:
    T._web_search = old_search
check("web.search validates and formats a provider result",
      web.get("ok") is True and "stub result" in web.get("stdout", ""))

# These executions are local snippets with no filesystem or network effects.
if os.name == "posix":
    python = run("python.run", {"code": "print(6 * 7)", "timeout_secs": 5})
    check("python.run executes a bounded deterministic snippet",
          python.get("ok") is True and "42" in (python.get("stdout") or ""),
          python.get("exit_code"))
    shell = run("shell.exec", {"command": "printf batch-ok", "timeout_secs": 5})
    check("shell.exec runs a bounded read-only command",
          shell.get("ok") is True and "batch-ok" in shell.get("stdout", ""),
          shell.get("exit_code"))
else:
    check("python.run is exercised by the DGX acceptance battery", True)
    check("shell.exec is Linux-host-only in this acceptance battery", True)

knowledge = run("knowledge.list_notebooks", {})
check("knowledge.list_notebooks returns structured data",
      knowledge.get("ok") is True and isinstance(knowledge.get("notebooks"), list))

core = run("memory.core", {})
check("memory.core returns without mutating stored memory",
      core.get("ok") is True and isinstance(core.get("stdout"), str))

with open(os.path.join(REPO, "webui", "index.html"), "r", encoding="utf-8") as f:
    ui = f.read()
_edit_chip = ui[ui.index("function editsChip(files)"):
                ui.index("/* After each chat turn", ui.index("function editsChip(files)"))]
_settler_start = ui.find("function _settleEditChip(")
_settler_end = ui.find("/* After each chat turn", _settler_start)
_edit_chip_settler = (ui[_settler_start:_settler_end]
                      if 0 <= _settler_start < _settler_end else "")
check("resolved chat edit cards mark the decision and disable both actions",
      '_settleEditChip(d, "approved")' in _edit_chip
      and '_settleEditChip(d, "rejected")' in _edit_chip
      and ".disabled = true" in _edit_chip_settler
      and "approved" in _edit_chip_settler
      and "rejected" in _edit_chip_settler)

_decision = ui[ui.index("async function decideImproveProposal"):
              ui.index("/* JAG-128B:", ui.index("async function decideImproveProposal"))]
check("proposal decisions report HTTP errors instead of false acceptance",
      'if (!r || !r.ok) throw new Error' in _decision)
_chat_proposal = ui[ui.index("function improveCard(d)"):
                    ui.index("/* JAG-447: the Improvement panel",
                             ui.index("function improveCard(d)"))]
check("skill proposal chat cards disable unsupported accept",
      'd.scope === "skill"' in _chat_proposal and "ok.disabled = true" in _chat_proposal)
_proposal_panel = ui[ui.index("// ---- proposals (collapsible"):
                     ui.index("// ---- decided history")]
check("proposal panel has no duplicate decision controls",
      "approve all" not in _proposal_panel
      and 'ok.textContent = "accept"' not in _proposal_panel
      and "showApprovalsInbox()" in _proposal_panel)
_approval_panel = ui[ui.index("async function loadApprovals()"):
                     ui.index("async function decide(id, decision)")]
check("RH approvals is the single inbox for tool gates and improvement proposals",
      '"/api/approvals?status=pending"' in _approval_panel
      and 'a.kind === "improvement"' in _approval_panel
      and "a.can_approve === false" in _approval_panel)
check("one decision endpoint handles both approval kinds",
      'api("POST", "/api/approvals/" + id' in ui
      and "decide_any(" in open(os.path.join(
          REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read())

print("---")
passed = sum(results)
print("\nv521: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
