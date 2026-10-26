#!/usr/bin/env python3
"""v678 — the Teamorg automate is scoped, empty-only by default, relations yes / models no (I-8).

The ⚡ automate (Teamorg) control writes ROLE.md files, so what it is ALLOWED to
touch must be decided by the backend, not inferred by the model:

  A) the control carries a checkbox DIRECTLY UNDER the run button (stacked, not
     beside it), checked by default = only the EMPTY ROLE.md, and the run sends
     that flag plus the scope
  B) the teamorg section prompt states the three rules: scope (the Team filter),
     only-empty prompts, and reporting lines YES / models NEVER
  C) "only empty" is DECIDABLE from the snapshot: `webui.inspect section agents`
     carries each agent's `prompt_chars`, so the automation checks instead of guesses
  D) the endpoint still refuses a non-automatable section and an empty instruction

Deterministic, no model, no network, no server.
Run: python3 tests/acceptance/v678_teamorg_scope.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-678-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_ROLES_DIR"] = os.path.join(TMP, "roles")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


ORBIT = read("src", "longrun", "orbit", "web", "orbit.html")
LRA = read("src", "longrun", "agent", "longrun_agent.py")

from longrun.agent import agents as agents_mod  # noqa: E402
from longrun.agent import longrun_agent as lra  # noqa: E402
from longrun.orchestrate import roles as roles_mod  # noqa: E402

# ---- A: the control itself -------------------------------------------------
bar_start = ORBIT.find('id="lraAutoBar"')
stack_i = ORBIT.find('<span class="stack">', bar_start)
run_i = ORBIT.find('id="lraAutoRun"', stack_i)
chk_i = ORBIT.find('id="lraAutoEmpty"', stack_i)
stack_end = ORBIT.find("</span>", chk_i)
check("A1 the checkbox lives in a stack block with the run button",
      -1 < bar_start < stack_i < run_i < chk_i, "bar=%d stack=%d run=%d chk=%d" % (bar_start, stack_i, run_i, chk_i))
check("A2 the checkbox comes AFTER the button in the markup (so it renders under it)",
      run_i < chk_i, "run=%d chk=%d" % (run_i, chk_i))
check("A3 the checkbox is checked by default (empty-only is the safe default)",
      'id="lraAutoEmpty" checked' in ORBIT and 'id="lraAutoEmpty"' in ORBIT)
check("A4 the stack is a COLUMN (under, never beside)",
      ".toolbar>.stack{display:inline-flex;flex-direction:column" in ORBIT)
check("A5 the run button keeps its primary skin inside the stack",
      ".toolbar>.stack>.btn.primary{background:var(--acc)" in ORBIT)
check("A6 the box is labelled with what it does, both ways",
      "only empty ROLE.md" in ORBIT
      and "unchecked" in ORBIT.lower() and "MAY rewrite the prompt" in ORBIT)
scope_src = ORBIT[ORBIT.find("labelTeamorgScope"):ORBIT.find("async runTeamorgAutomate")]
check("A7 the scope is stated (team name + how many agents, how many have no ROLE.md)",
      "scope: " in scope_src and "without ROLE.md" in scope_src
      and "this.team === \"ALL\"" in scope_src and "this.teamById(this.team)" in scope_src)
post_src = ORBIT[ORBIT.find("async runTeamorgAutomate"):ORBIT.find("renderTeams")]
check("A8 the run sends the scope AND the empty-only flag",
      "team_scope: this.team" in post_src and "only_empty: onlyEmpty" in post_src
      and "scope_agents:" in post_src)
check("A9 the flag is read FROM the checkbox (unchecked = may rewrite every prompt)",
      'const onlyEmpty = !($("lraAutoEmpty")' in post_src and ".checked === false" in post_src)

# ---- B: the section prompt carries the rules -------------------------------
# Read the EVALUATED prompt (the source splits it across string literals, so a
# raw-source grep would test the formatting instead of the instruction).
block = lra.SECTION_PROMPTS["teamorg"]
check("B0 the prompt the automate actually sends is the one under test",
      "teamorg" in lra.SECTION_PROMPTS and "Orbit Control / AGENTS & TEAMS" in block)
check("B1 the scope rule is stated (team filter, ALL, __none__, outside = forbidden)",
      "SCOPE" in block and "context.team_scope" in block and "context.scope_agents" in block
      and "NEVER write to an agent outside the scope" in block)
check("B2 the prompt rule: empty-only when asked, never overwrite otherwise",
      "context.only_empty" in block and "prompt_chars == 0" in block
      and "never overwrite it" in block)
check("B3 relations YES / models NEVER",
      "reports_to" in block and "NEVER change an agent's model" in block)
check("B4 the reporting-line rule also forbids cycles and out-of-scope managers",
      "never create a cycle" in block and "outside the scope" in block)

# ---- C: the snapshot makes "empty" decidable -------------------------------
agents_mod.REGISTRY.designate("sessX", name="Filled")
agents_mod.REGISTRY.designate("sessY", name="Empty")
roles_mod.write("sessX", "Role: keep the API surface stable\n- answer with the schema")
snap = lra._webui_inspect({"section": "agents"})
by_name = {a.get("name"): a for a in (snap.get("agents", {}).get("agents") or [])}
check("C1 the snapshot carries prompt_chars per agent",
      by_name.get("Filled", {}).get("prompt_chars", None) is not None
      and by_name.get("Empty", {}).get("prompt_chars", None) is not None,
      str({k: v.get("prompt_chars") for k, v in by_name.items()}))
check("C2 a written ROLE.md counts as filled, an untouched one as EMPTY",
      by_name.get("Filled", {}).get("prompt_chars", 0) > 0
      and by_name.get("Empty", {}).get("prompt_chars", 1) == 0,
      str({k: v.get("prompt_chars") for k, v in by_name.items()}))
check("C3 the scope is decidable too (teams travel with the tree)",
      "teams" in (by_name.get("Filled") or {}))

# ---- D: the guards still hold ---------------------------------------------
refused = lra.automate("models", "make it fast")
check("D1 a non-automatable section is refused (no model call, no write)",
      refused.get("ok") is False and refused.get("disabled") is True
      and "disabled for section" in str(refused.get("error")), str(refused)[:120])
empty = lra.automate("teamorg", "   ")
check("D2 an empty instruction is refused", empty.get("ok") is False
      and "instruction required" in str(empty.get("error")), str(empty)[:80])
check("D3 teamorg stays in the allowlist", "teamorg" in lra.AUTOMATE_ALLOWED_SECTIONS)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
