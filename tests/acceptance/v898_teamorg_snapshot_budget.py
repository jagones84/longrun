#!/usr/bin/env python3
"""v898 — the Teamorg automation snapshot is BUILT to a budget, never cut to one.

Operator-approved proposal `.agent/docs/proposals/2026-11-08_teamorg-automation-context.html`.

Measured 2026-11-08 on the live org (94 agents): the `agents` inspect section was
32,162 characters and `automate()` handed the model only the first 6,000 — a
TRUNCATED JSON (mid-array), with no teams and no ROLE.md text, so a job assignment
could only be guessed from short role labels.

  A  the snapshot is COMPACT: teams with their ROLE.md head, one row per agent
  B  it carries the SCOPE (only the agents in scope; the org size says how many more)
  C  it carries the in-scope ROLE.md heads, and `prompt_chars` stays (only-empty)
  D  it always serializes to VALID JSON within the budget — with a fallback chain
  E  `automate()` no longer slices the snapshot at 6000

Deterministic: temp dirs, no model, no network, no server.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-898-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_ROLES_DIR"] = os.path.join(TMP, "roles")
os.environ["LONGRUN_TEAMS_FILE"] = os.path.join(TMP, "teams.json")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


LRA_SRC = read("src", "longrun", "agent", "architect.py")

from longrun.agent import agents as agents_mod      # noqa: E402
from longrun.agent import architect as A            # noqa: E402
from longrun.orchestrate import roles as roles_mod  # noqa: E402
from longrun.orchestrate import teams as teams_mod  # noqa: E402

# ---- fixture: one team, 3 agents in scope (2 with a ROLE.md), 30 outside ------
created = teams_mod.REGISTRY.create(name="Snapshot Team", description="X" * 500)
team_id = ((created or {}).get("team") or {}).get("id")
for i in range(3):
    agents_mod.REGISTRY.designate("sid-in-%d" % i, name="Scoped %d" % i, role="builder")
roles_mod.write("sid-in-0", "You build the API surface.\n" + "line\n" * 200)
roles_mod.write("sid-in-1", "You write the release notes.\n" + "note\n" * 200)
for i in range(30):
    agents_mod.REGISTRY.designate("sid-out-%d" % i, name="Outside %d" % i, role="other")

rows = (agents_mod.REGISTRY.tree() or {}).get("agents") or []
ids_in = [a.get("id") for a in rows if str(a.get("session") or "").startswith("sid-in-")]
scope = {"team_scope": team_id, "only_empty": True, "scope_agents": ids_in}

snap = A._webui_inspect({"section": "teamorg", "scope": scope})
blob = json.dumps({k: v for k, v in snap.items() if k not in ("ok", "stdout")},
                  ensure_ascii=False, default=str)

# ---- A: compact shape --------------------------------------------------------
check("A1 the team carries its ROLE.md head (not the raw dump)",
      bool(team_id) and any(t.get("id") == team_id and t.get("role_md")
                            for t in (snap.get("teams") or []))
      and all(len(t.get("role_md") or "") <= A.TEAM_ROLE_HEAD_CHARS
              for t in (snap.get("teams") or [])), team_id)
rowkeys = set((snap.get("agents") or [{}])[0].keys())
check("A2 one COMPACT row per agent (the tree's weight is gone)",
      rowkeys == {"id", "name", "role", "model", "manager", "teams", "prompt_chars"},
      sorted(rowkeys))
check("A3 no heavy tree field leaks into the snapshot",
      not ({"children", "n", "created", "day", "runs_today"} & rowkeys))

# ---- B: the scope, not the whole org -----------------------------------------
got = [r.get("id") for r in (snap.get("agents") or [])]
check("B1 only the agents IN SCOPE are listed",
      got and set(got) == set(ids_in), "scope=%s got=%s" % (ids_in, got))
check("B2 the org size still travels (so the model knows it is not the whole org)",
      snap.get("agents_total") == len(rows)
      and (snap.get("scope") or {}).get("agents_in_scope") == len(got),
      "total=%s scope=%s got=%s" % (snap.get("agents_total"),
                                    (snap.get("scope") or {}).get("agents_in_scope"), len(got)))

# ---- C: the ROLE.md heads are what a job assignment needs ---------------------
heads = snap.get("prompts") or {}
check("C1 the in-scope agents carry their ROLE.md head (only those that have one)",
      set(heads) <= set(ids_in) and len(heads) == 2, sorted(heads))
cap = int(snap.get("prompt_head_chars") or 0)
check("C2 the head is capped by the declared budget (≤400 chars)",
      0 < cap <= A.AUTOMATE_PROMPT_HEAD_CHARS
      and all(len(v) <= cap for v in heads.values()), "cap=%s" % cap)
check("C3 prompt_chars stays per agent (only-empty remains decidable)",
      all(isinstance(r.get("prompt_chars"), int) for r in (snap.get("agents") or []))
      and any(r.get("prompt_chars", 0) > 0 for r in (snap.get("agents") or [])))

# ---- D: always valid JSON, never cut mid-structure ---------------------------
check("D1 the real snapshot fits the budget and parses",
      len(blob) <= A.AUTOMATE_SNAPSHOT_MAX_CHARS and isinstance(json.loads(blob), dict),
      "%d/%d" % (len(blob), A.AUTOMATE_SNAPSHOT_MAX_CHARS))
wide = A._teamorg_snapshot({"team_scope": "ALL", "scope_agents": []}, budget=3000)
wide_blob = json.dumps(wide, ensure_ascii=False, default=str)
check("D2 under pressure the chain degrades the SHAPE, not the JSON",
      isinstance(json.loads(wide_blob), dict) and wide.get("agents_compact") is True,
      "bytes=%d compact=%s" % (len(wide_blob), wide.get("agents_compact")))
check("D3 the degraded roster still names every agent (id + name)",
      all(isinstance(r, str) and r.split(" · ")[0] for r in (wide.get("agents") or []))
      and len(wide.get("agents") or []) == len(rows))
default_budget = A._teamorg_snapshot({"team_scope": "ALL", "scope_agents": []})
default_blob = json.dumps(default_budget, ensure_ascii=False, default=str)
check("D4 the WHOLE roster fits the default budget (the measured defect)",
      len(default_blob) <= A.AUTOMATE_SNAPSHOT_MAX_CHARS
      and len(default_budget.get("agents") or []) == len(rows)
      and isinstance(json.loads(default_blob), dict),
      "%d/%d" % (len(default_blob), A.AUTOMATE_SNAPSHOT_MAX_CHARS))

# ---- E: the blind slice is gone from the teamorg path -----------------------
check("E1 automate() slices at the NAMED budget, not at 6000",
      "[:AUTOMATE_SNAPSHOT_MAX_CHARS]" in LRA_SRC
      and "default=str)[:6000]" not in LRA_SRC)
check("E2 the teamorg section gets the SCOPE from the request",
      '"scope": context if inspect_section == "teamorg" else None' in LRA_SRC
      and 'out.update(_teamorg_snapshot(args.get("scope") or {}))' in LRA_SRC)
check("E3 the prompt tells the model to read the heads before assigning a job",
      "prompts[<agent id>]" in A.SECTION_PROMPTS["teamorg"]
      and "prompt_head_chars" in A.SECTION_PROMPTS["teamorg"]
      and "belongs to the agent whose ROLE.md names that work" in A.SECTION_PROMPTS["teamorg"])

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
