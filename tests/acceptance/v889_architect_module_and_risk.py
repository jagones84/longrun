#!/usr/bin/env python3
"""v889 — the module is `architect.py`, and only RISKY tools ask for approval.

Operator, 2026-11-08:
  *"the default allowances of the tools relevant to add model provider are that required
    approval. you told grant still required for many but not true, for example architect
    created agents and teams. but by default I mean only the risky tools shall require
    approval. the FULL unlock everything except permissions."*
  *"also longrun agent scripts shall be changed in architect.py and mod all dependencies
    in the codebase."*
  *"for the role checkbox I don't know … decide by your own."*

Pinned here:
  A) the module is `src/longrun/agent/architect.py`; no import of the retired
     module name is left anywhere in `src/` or `tests/`, and the module still imports;
  B) the identity is ONE word everywhere: session id, /api/architect/*, roles key,
     `allow_architect`, event names;
  C) the DEFAULT approval class of every exclusive tool is risk-based: designing the org
     is `auto`, deleting data or rewiring the harness is `required`;
  D) an explicit entry in config/tools.yaml still overrides the default, and
     `approvals.mode=full` is a policy that lifts `required` — never a permission.

Deterministic: temp dirs, no model, no network.
"""
import glob
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-889-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_ROLES_DIR"] = os.path.join(TMP, "roles")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(TMP, "ws")
for _d in ("sessions", "graphs", "roles", "ws"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: one module, one name ----------------------------------------------
_OLD_MODULE = "longrun_agent"     # the retired FILE name (the id is `architect` now)
check("A1 the module is architect.py",
      os.path.exists(os.path.join(REPO, "src", "longrun", "agent", "architect.py"))
      and not os.path.exists(os.path.join(
          REPO, "src", "longrun", "agent", _OLD_MODULE + ".py")))

_importers = []
for base in ("src", "tests"):
    for p in glob.glob(os.path.join(REPO, base, "**", "*.py"), recursive=True):
        t = open(p, encoding="utf-8").read()
        if re.search(r"import\s+" + _OLD_MODULE + r"\b", t) or re.search(
                r"from\s+longrun\.agent\s+import\s+" + _OLD_MODULE + r"\b", t):
            _importers.append(os.path.relpath(p, REPO))
check("A2 no import of the retired module name is left", not _importers, _importers)

from longrun.agent import architect as A                       # noqa: E402
check("A3 the new module imports and owns the same surface",
      callable(A.automate) and callable(A.execute) and "teamorg" in A.SECTION_PROMPTS)

# ---- B: ONE spelling for the identity -------------------------------------
check("B1 the stored session id and the title are the canonical ones",
      A.ARCHITECT_SESSION_ID == "architect" and A.ARCHITECT_TITLE == "Architect")
_src = open(os.path.join(REPO, "src", "longrun", "agent", "architect.py"), encoding="utf-8").read()
check("B2 the grant flag, the routing role key and the event names share that word",
      "allow_architect" in _src and '"architect"' in _src
      and '"architect.start"' in _src and '"architect.done"' in _src)

# ---- C: only risky tools ask ----------------------------------------------
from longrun.tools import registry                              # noqa: E402

DESIGN = ["agent.create", "agent.update", "agent.prompt_set", "team.create", "team.update",
          "team.member_add", "team.member_remove", "job.create", "job.update",
          "routine.create", "routine.update", "session.create", "session.rename"]
RISKY = ["agent.delete", "team.delete", "job.delete", "routine.delete", "session.delete",
         "agent.prompt_clear", "provider.upsert", "provider.remove", "provider.add_model",
         "provider.remove_model", "provider.set_default", "provider.reload",
         "mcp.upsert", "mcp.remove", "mcp.reload", "skill.remove", "kb.reembed",
         "webui.configure"]

_bad = [(t, (registry.tool_spec(t) or {}).get("approval")) for t in DESIGN
        if (registry.tool_spec(t) or {}).get("approval") != "auto"]
check("C1 designing the org runs without a prompt", not _bad, _bad)
_bad = [(t, (registry.tool_spec(t) or {}).get("approval")) for t in RISKY
        if (registry.tool_spec(t) or {}).get("approval") != "required"]
check("C2 deleting data or rewiring the harness asks first", not _bad, _bad)
check("C3 the classification lives in ONE place (the module that owns the tools)",
      callable(A.exclusive_default_approval)
      and A.exclusive_default_approval("agent.delete") == "required"
      and A.exclusive_default_approval("agent.create") == "auto")

# ---- D: policy, not permission -------------------------------------------
_decl = registry.classify("agent.delete", {"_session": "some-other-session"})
check("D1 an ungranted session is still DENIED whatever the mode says",
      _decl[0] == "denied" and "authorized" in _decl[1], _decl)
check("D2 approvals.mode=full is a POLICY: one fast path lifts every `required`",
      'if str(ap.get("mode", "normal")).lower() in ("full", "auto", "yolo"):' in open(
          registry.__file__, encoding="utf-8").read())
check("D3 the permission switches are not in the tool risk table (never a tool call)",
      not any("allow_" in t for t in A.EXCLUSIVE_NEEDS_APPROVAL))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
