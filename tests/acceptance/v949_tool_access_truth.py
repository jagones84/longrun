#!/usr/bin/env python3
"""v949 — the Tools panel states WHO may call each tool, from the gate itself.

Operator (2026-11-10): *"ci sono tools nominati exclusive per architect ma non è
vero, esempio agent li possono usare, se no errore anche i capi dei teams sui
loro dipendenti"*. The panel labelled all 47 built-in tools
"Architect / granted sessions only"; in code 5 tools run for ANY session and the
7 `job.*` tools run for ANY coordinator (an agent with at least one direct
report). One false label on a daily surface makes the operator grant the wrong
thing and teaches an agent to avoid tools it owns.

The fix emits ONE access class per tool, computed from the gate's own sets, and
renders it on the row:
  everyone    — read-only org/observation lookups, no grant
  coordinator — team jobs, org position decides
  architect   — needs the Architect session or `allow_architect`

Pinned here: the class the catalogue advertises IS the class the gate applies
(no second list), and the panel renders it instead of the "exclusive" wording.

Deterministic: temp dirs, no server, no model, no network, no browser.
Run: python3 tests/acceptance/v949_tool_access_truth.py
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="sf-v949-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _srv  # noqa: E402,F401 — import first: agent<->server cycle
from longrun.agent import architect as LRA  # noqa: E402
from longrun.memory import stores as STORES  # noqa: E402
from longrun.tools import registry as REG  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")

# ---------------- A: one class, computed from the gate's own sets ------------
_EVERYONE = {"agent.get", "agent.list", "team.get", "team.list", "mcp.test"}

check("A1 access_class exists", callable(getattr(LRA, "access_class", None)))
_acc_fn = getattr(LRA, "access_class", lambda _n: None)
_acc = {n: _acc_fn(n) for n in
        ("agent.get", "agent.list", "team.get", "team.list", "mcp.test",
         "job.create", "job.delete", "agent.delete", "provider.remove",
         "mcp.upsert", "fs.write", "self.info")}
check("A2 the five read-only lookups are 'everyone'",
      all(_acc[n] == "everyone" for n in _EVERYONE), _acc)
check("A3 job.* is 'coordinator', not 'exclusive'",
      _acc["job.create"] == "coordinator" and _acc["job.delete"] == "coordinator", _acc)
check("A4 writes stay 'architect'",
      _acc["agent.delete"] == "architect" and _acc["provider.remove"] == "architect"
      and _acc["mcp.upsert"] == "architect", _acc)
check("A5 a nucleus tool has NO access class (policy is its gate)",
      _acc["fs.write"] is None and _acc["self.info"] is None, _acc)
check("A6 the class is DERIVED, not a second list",
      {n for n in _acc if _acc_fn(n) == "everyone"} == set(LRA.READ_ONLY_EXCLUSIVE), _acc)

# ---------------- B: the catalogue carries the same class --------------------
# The catalogue's own collaborators, stubbed: this pin must not spawn an MCP
# client or read a live Matrix zone (deterministic, no network).
REG._external_tools = lambda: {}
REG._matrix_tools = lambda: {}
REG._promoted_tools = lambda: {}
CAT = {row["name"]: row for row in REG.catalog()}
check("B1 every catalogue row answers 'access'",
      all("access" in row for row in CAT.values()), len(CAT))
check("B2 catalogue 'everyone' == the gate's read-only set",
      {n for n, r in CAT.items() if r.get("access") == "everyone"} == set(LRA.READ_ONLY_EXCLUSIVE),
      sorted(n for n, r in CAT.items() if r.get("access") == "everyone"))
check("B3 catalogue 'coordinator' == every delegation tool",
      {n for n, r in CAT.items() if r.get("access") == "coordinator"}
      == {n for n, r in CAT.items() if r.get("origin") == "delegation"}
      and any(n.startswith("job.") for n in CAT), "")
check("B4 every 'exclusive' row is either 'everyone' (read-only) or 'architect'",
      all(r.get("access") in ("everyone", "architect")
          for r in CAT.values() if r.get("origin") == "exclusive")
      and CAT.get("agent.delete", {}).get("access") == "architect", "")
check("B5 MCP / Matrix / nucleus rows carry no access class",
      all(r.get("access") is None for r in CAT.values()
          if r.get("origin") in ("mcp", "matrix", "nucleus")), "")

# ---------------- C: the gate and the class agree, behaviourally -------------
SID = "v949-ungranted"
STORES.get_or_create_session(SID)
_ok_read, _why_read = LRA.check_dual_permission("agent.list", SID)
_ok_write, _why_write = LRA.check_dual_permission("agent.delete", SID)
check("C1 an ungranted session reads the org and is refused a write — same as the class",
      _ok_read is True and _ok_write is False
      and _acc_fn("agent.list") == "everyone"
      and _acc_fn("agent.delete") == "architect", (_why_read, _why_write))
check("C2 a job is org position, not a grant (class says so)",
      _acc_fn("job.create") == "coordinator"
      and LRA.check_delegation("job.create", "v949-nobody")[0] is False, "")

# ---------------- D: the panel renders the truth ----------------------------
check("D1 the panel has an access badge map",
      "const ACCESS_BADGE" in HTML and "everyone:" in HTML
      and "coordinator:" in HTML and "architect:" in HTML, "")
check("D2 the three labels are readable on the row",
      "any session" in HTML and "team lead" in HTML and "Architect / grant" in HTML, "")
check("D3 the false 'Exclusive built-in · Architect' wording is gone",
      "Exclusive built-in · Architect" not in HTML
      and "exclusive built-in tool — dual-permission gated (Architect / granted sessions only)" not in HTML, "")
check("D4 the section is neutral and the delegation tools have their own",
      '"exclusive", "Built-in · gated"' in HTML
      and '"delegation", "Team jobs · coordinators"' in HTML, "")
check("D5 a namespace can group AS 'delegation' (job.* leaves 'Built-in')",
      'best === "delegation"' in HTML, "")
check("D6 the tooltips state the actual rule",
      "no grant" in HTML and "does NOT bypass" in HTML
      and "at least one direct report" in HTML, "")

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
