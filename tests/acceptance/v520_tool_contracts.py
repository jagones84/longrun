#!/usr/bin/env python3
"""v520 — canonical tools expose action-specific schemas and isolated failure coaching."""
import os
import sys
import tempfile
import importlib.util

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v520-")
os.environ.setdefault("LONGRUN_DATA_DIR", os.path.join(TMP, "data"))
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(TMP, "cfg"))
os.environ.setdefault("LONGRUN_DB", os.path.join(TMP, "events.db"))
os.environ.setdefault("LONGRUN_SESSIONS_DIR", os.path.join(TMP, "sessions"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402
from longrun.tools import diag  # noqa: E402
from longrun.tools import tools as tool_executor  # noqa: E402
from longrun.core import server  # noqa: E402,F401
from longrun.core import matrix as matrix_core  # noqa: E402
from longrun.agent import agent  # noqa: E402
from longrun.memory import memory as memory_store  # noqa: E402

registry._external_tools = lambda: {}
_ruleaudit_path = os.path.join(REPO, "src", "Matrix", "tools", "ruleaudit.py")
_ruleaudit_spec = importlib.util.spec_from_file_location(
    "_v520_ruleaudit", _ruleaudit_path)
_ruleaudit_module = importlib.util.module_from_spec(_ruleaudit_spec)
_ruleaudit_spec.loader.exec_module(_ruleaudit_module)
_matrix_snapshot = matrix_core._extract_module_subtools(
    "ruleaudit", _ruleaudit_module, _ruleaudit_path, origin="matrix")
registry._matrix_tools = lambda: _matrix_snapshot

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def schema(name):
    return (registry.tool_spec(name) or {}).get("schema") or {}


knowledge = schema("knowledge.read_source")
check("knowledge.read_source requires its source reference",
      knowledge.get("required") == ["ref"], knowledge.get("required"))
check("knowledge source scope accepts listed notebook IDs or exact names",
      "exact name" in (knowledge.get("properties", {}).get("notebook", {})
                       .get("description", "")))
check("knowledge.discover requires its search query",
      schema("knowledge.discover").get("required") == ["query"])
check("knowledge.add_source declares its accepted input alternatives",
      {"refs", "ref", "url", "query"} <= set(
          (schema("knowledge.add_source").get("properties") or {})))
check("knowledge.add_source requires at least one source input",
      len(schema("knowledge.add_source").get("anyOf") or []) == 4)
missing_source = tool_executor._dispatch_execute("knowledge.add_source", {})
check("knowledge.add_source empty input reports its alternatives",
      "refs" in (missing_source.get("error") or "")
      and "url" in (missing_source.get("error") or ""),
      missing_source.get("error"))

missing_ref = tool_executor._dispatch_execute(
    "knowledge.read_source", {"notebook": "default"})
check("knowledge.read_source rejects a missing ref before database lookup",
      missing_ref.get("missing_args") == ["ref"], missing_ref.get("error"))

rule_schema = schema("ruleaudit.scan")
check("ruleaudit.scan schema requires prompt_text or prompt_file",
      [set(a.get("required") or []) for a in rule_schema.get("anyOf") or []]
      == [{"prompt_text"}, {"prompt_file"}],
      rule_schema.get("anyOf"))
missing_prompt = tool_executor._dispatch_execute("ruleaudit.scan", {})
check("ruleaudit.scan missing-input error names the alternatives",
      "prompt_text" in (missing_prompt.get("error") or "")
      and "prompt_file" in (missing_prompt.get("error") or ""),
      missing_prompt.get("error"))

matrix = schema("matrix.git_commit")
check("matrix.git_commit exposes only commit arguments",
      set(matrix.get("properties") or {}) == {"message"},
      sorted(matrix.get("properties") or {}))
check("Matrix commit description identifies its separate repository",
      ".Matrix/git" in matrix.get("description", "")
      and "src/Matrix" in matrix.get("description", ""),
      matrix.get("description"))
check("Matrix git log exposes its supported limit",
      "limit" in (schema("matrix.git_log").get("properties") or {}))
check("destructive Matrix subtools override namespace auto-approval",
      all((registry.tool_spec(name) or {}).get("approval") == "required"
          for name in ("matrix.git_reset", "matrix.checkpoint_rollback",
                       "matrix.clean_trash", "matrix.webui_reset", "matrix.remove")))
check("destructive memory subtools override namespace auto-approval",
      all((registry.tool_spec(name) or {}).get("approval") == "required"
          for name in ("memory.set_core", "memory.clear_core",
                       "memory.forget", "memory.purge")))
check("memory.forget requires target or query in its discovered schema",
      len(schema("memory.forget").get("anyOf") or []) == 2,
      schema("memory.forget").get("anyOf"))
blocked_forget = tool_executor._dispatch_execute("memory.forget", {})
check("memory.forget empty args fail schema validation before execution",
      len(blocked_forget.get("missing_any_of") or []) == 2,
      blocked_forget.get("error"))
_cfg = registry.load_config()
_approval_cfg = _cfg.setdefault("approvals", {})
_old_mode = _approval_cfg.get("mode")
_approval_cfg["mode"] = "normal"
try:
    _required_calls = {
        "matrix.git_reset": {"rev": "HEAD"},
        "matrix.checkpoint_rollback": {"slot": 1},
        "matrix.clean_trash": {"keep_recent": 0},
        "matrix.webui_reset": {},
        "memory.set_core": {"content": "probe"},
        "memory.clear_core": {},
        "memory.forget": {"target": "probe"},
        "memory.purge": {},
    }
    _classified = {name: registry.classify(name, args)[0]
                   for name, args in _required_calls.items()}
finally:
    if _old_mode is None:
        _approval_cfg.pop("mode", None)
    else:
        _approval_cfg["mode"] = _old_mode
check("destructive tools are actually classified as approval-required",
      all(value == "required" for value in _classified.values()), _classified)

_purge_calls = []
_original_purge = memory_store.purge_invalidated
memory_store.purge_invalidated = lambda: (
    _purge_calls.append(True) or {"ok": True, "removed": 0})
try:
    missing_forget_target = tool_executor._memory({"action": "forget"}, "v520")
finally:
    memory_store.purge_invalidated = _original_purge
check("memory.forget without target/query never falls through to bulk purge",
      missing_forget_target.get("ok") is False and not _purge_calls,
      missing_forget_target)

clear_schema = schema("memory.clear_core")
check("memory.clear_core is an explicit, approved no-argument action",
      not (clear_schema.get("properties") or {})
      and "clear" in clear_schema.get("description", "").lower()
      and (registry.tool_spec("memory.clear_core") or {}).get("approval") == "required",
      clear_schema)
_core_clear_calls = []
_original_core_write = memory_store.core_write
memory_store.core_write = lambda content: (
    _core_clear_calls.append(content) or {"ok": True, "chars": 0})
try:
    cleared_core = tool_executor._memory({"action": "clear_core"}, "v520")
finally:
    memory_store.core_write = _original_core_write
check("memory.clear_core clears only when explicitly called",
      cleared_core.get("ok") is True and _core_clear_calls == [""],
      cleared_core)

memory = schema("memory.recall")
check("memory.recall requires query and documents keyword-only default",
      memory.get("required") == ["query"]
      and "keyword" in memory.get("description", "").lower(),
      (memory.get("required"), memory.get("description")))
check("memory.recent excludes unrelated action arguments",
      set((schema("memory.recent").get("properties") or {})) == {"kind", "limit"},
      sorted((schema("memory.recent").get("properties") or {})))

tools = schema("self.tools")
check("self.tools discovery keeps both supported lookup arguments",
      set(tools.get("properties") or {}) == {"tool", "query"},
      sorted((tools.get("properties") or {})))

streak = agent._advance_tool_failure_streak
check("same failing tool increments the stuck streak",
      streak("http.fetch", 1, "http.fetch", True) == 2)
check("changing tools starts a fresh failure streak",
      streak("http.fetch", 2, "browser.fetch", True) == 1)
check("success or a non-executed approval gate resets the streak",
      streak("http.fetch", 2, "http.fetch", False) == 0
      and streak("http.fetch", 2, "http.fetch", True, gate_only=True) == 0)

print("---")
passed = sum(results)
print("\nv520: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
