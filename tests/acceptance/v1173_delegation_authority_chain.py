#!/usr/bin/env python3
"""v1173 — a child's tool grant is bound along the delegation chain (round 106).

Source: Agent-ZTA, arXiv:2611.18999 ("A chain-aware Zero Trust model for
bidirectional security-state propagation and runtime containment in
multi-agent delegation"). Its rule: an agent's *path-specific delegated
authority* is what the chain grants AND the trusted policy permits, never the
role's static grant on its own.

Before this test, `subagent.spawn` set `st.tool_allow = role_tools(role)`. A
read-only parent (role `researcher`) could therefore spawn a child with the
`coder` role (no `tools` key = unrestricted, by I-1) and the child regained
every write tool two levels down. Fail-safe also matters: a parent whose grant
cannot be resolved must not silently inherit the catalogue.

Deterministic: no model, no network, no server; `agent_run_v2` is replaced by a
two-line fake so the child thread finishes immediately.

Run: python3 tests/acceptance/v1173_delegation_authority_chain.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1173-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR",
             "SUBAGENT_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry                # noqa: E402
registry._external_tools = lambda: {}             # noqa: E731
from longrun.core import api_v02                  # noqa: E402
from longrun.agent import subagent as SUB         # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


NAMES = ["fs.read", "fs.write", "fs.edit", "grep.search", "glob", "shell.exec",
         "web.search", "memory.store"]

# ---- 1. pure binder: the three authority decisions ---------------------------
eff, ev = SUB.bind_authority(None, ["fs.read", "shell"], names=NAMES)
check("unrestricted parent keeps the role grant",
      eff == ["fs.read", "shell.exec"] and ev["decision"] == "unrestricted-parent",
      (eff, ev["decision"]))

eff, ev = SUB.bind_authority(["fs.read"], None, names=NAMES)
check("unrestricted role under a restricted parent binds to the parent",
      eff == ["fs.read"] and ev["decision"] == "bound-to-parent",
      (eff, ev["decision"]))

eff, ev = SUB.bind_authority(["fs.read"], ["fs", "shell.exec"], names=NAMES)
check("namespace intersection keeps only the parent's tools",
      eff == ["fs.read"] and ev["clamped"] == ["fs.write", "fs.edit", "shell.exec"],
      (eff, ev["clamped"]))

eff, ev = SUB.bind_authority([], ["fs.read"], names=NAMES)
check("an empty parent grant delegates nothing",
      eff == [] and ev["decision"] == "intersection-clamped", (eff, ev["decision"]))

eff, ev = SUB.bind_authority(["plugin.custom"], ["plugin.custom"], names=NAMES)
check("a tool outside the catalogue is kept literally",
      eff == ["plugin.custom"], eff)

# ---- 2. fail-closed when the chain signal is missing -------------------------
SUB._DEPTH["orphan_parent"] = 1       # a subagent parent with no live state
res = SUB.spawn("child", parent_run_id="orphan_parent")
check("missing parent authority refuses the spawn",
      not res.get("subagent_id") and "fail-closed" in str(res.get("error")),
      res.get("error"))

# ---- 3. a live parent run bounds the child's effective grant ----------------
api_v02.agent_run_v2 = lambda *a, **k: {"ok": True, "status": "done",
                                        "summary": "fake child", "trace": []}
parent = api_v02.new_run("parent goal")
parent.tool_allow = ["fs.read", "grep.search"]
out = SUB.spawn("delegated", parent_run_id=parent.id, role="researcher")
sid = out.get("subagent_id")
check("spawn succeeds under a restricted parent", bool(sid), out)
if sid:
    rec = SUB.collect(sid, timeout=10) or {}
    disk = SUB.load_record(sid) or {}
    child = api_v02.run_get(out["run_id"])
    allowed = getattr(child, "tool_allow", None)
    check("child cannot exceed the parent's grant",
          isinstance(allowed, list) and set(allowed) <= {"fs.read", "grep.search"},
          allowed)
    check("child grant is the intersection, not the role list",
          "shell.exec" not in (allowed or []), allowed)
    chain = (getattr(child, "delegation", {}) or {}).get("chain") or []
    check("the delegation chain names the parent and the child",
          parent.id in chain and sid in chain, chain)
    check("the durable record carries the decision",
          (disk.get("authority") or "") in ("intersection", "intersection-clamped",
                                            "bound-to-parent"), disk.get("authority"))

# ---- 4. a child of a child stays bounded ------------------------------------
if sid:
    out2 = SUB.spawn("grandchild", parent_run_id=out["run_id"], role="coder")
    gid = out2.get("subagent_id")
    if gid:
        SUB.collect(gid, timeout=10)
        gchild = api_v02.run_get(out2["run_id"])
        g_allowed = getattr(gchild, "tool_allow", None)
        check("grandchild inherits the grandparent's bound, not the catalogue",
              isinstance(g_allowed, list)
              and set(g_allowed) <= {"fs.read", "grep.search"}, g_allowed)
    else:
        check("grandchild spawn under a bound parent", False, out2.get("error"))

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
