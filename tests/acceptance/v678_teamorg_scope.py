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
import re
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
# The checkbox lives in the AGENTS toolbar, stacked under the ⚡ button, so the
# mode reads before the run bar is opened (and there is exactly ONE of it).
result_btn = ORBIT.find('id="agPolicy"')
toolbar_btn = ORBIT.find('id="lraAutoBtn"')
chk_i = ORBIT.find('id="lraAutoEmpty"')
bar_i = ORBIT.find('id="lraAutoBar"')
stack_i = ORBIT.rfind('<span class="stack">', 0, toolbar_btn)
check("A1 the checkbox is in the toolbar stack that holds the ⚡ button",
      -1 < stack_i < toolbar_btn < chk_i < result_btn, "stack=%d btn=%d chk=%d" % (stack_i, toolbar_btn, chk_i))
check("A2 it comes AFTER the button in the markup (so it renders under it)",
      toolbar_btn < chk_i, "btn=%d chk=%d" % (toolbar_btn, chk_i))
check("A3 exactly ONE such checkbox exists (no second control, no duplicate truth)",
      ORBIT.count('id="lraAutoEmpty"') == 1, str(ORBIT.count('id="lraAutoEmpty"')))
check("A4 the run bar no longer carries a checkbox of its own",
      'id="lraAutoEmpty"' not in ORBIT[bar_i:ORBIT.find("</div>", bar_i)])
check("A5 it is checked by default (empty-only is the safe default)",
      'id="lraAutoEmpty" checked' in ORBIT)
check("A6 the stack is a COLUMN (under, never beside)",
      ".toolbar>.stack{display:inline-flex;flex-direction:column" in ORBIT)
check("A7 the box is labelled with what it does, both ways",
      "only empty ROLE.md" in ORBIT
      and "unchecked" in ORBIT.lower() and "MAY rewrite the prompt" in ORBIT)
scope_src = ORBIT[ORBIT.find("labelTeamorgScope"):ORBIT.find("async runTeamorgAutomate")]
check("A8 the scope is stated (team name + how many agents, how many have no ROLE.md)",
      "scope: " in scope_src and "without ROLE.md" in scope_src
      and "this.team === \"ALL\"" in scope_src and "(this.teams || [])" in scope_src)
post_src = ORBIT[ORBIT.find("async runTeamorgAutomate"):ORBIT.find("renderTeams")]
check("A9 the run sends the scope AND the empty-only flag",
      "team_scope: this.team" in post_src and "only_empty: onlyEmpty" in post_src
      and "scope_agents:" in post_src)
check("A10 the flag is read from the toolbar checkbox (unchecked = may rewrite every prompt)",
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

# ---- F: the control cannot die on a member it cannot reach -----------------
# The first version of this control called `this.teamById(...)` and `this.agents
# .filter(...)` from OrbitApp, where `teamById` belongs to AgentsView and
# `this.agents` is that VIEW, not a list: the label threw, the click handler died
# before `addBar`, and the button "did nothing" (operator report).
APP = "class OrbitApp {"
app_body = ORBIT[ORBIT.find(APP):]
app_body = app_body[:app_body.find("\nclass ", 3)] if "\nclass " in app_body[3:] else app_body
label_src = ORBIT[ORBIT.find("labelTeamorgScope(){"):ORBIT.find("async runTeamorgAutomate")]
used = set(re.findall(r"this\.([A-Za-z_$][\w$]*)", label_src + post_src))
assigned = set(re.findall(r"this\.([A-Za-z_$][\w$]*)\s*=", app_body))
methods = set(re.findall(r"^  (?:async )?([A-Za-z_$][\w$]*)\(", app_body, re.M))
unreachable = sorted(used - assigned - methods)
check("F1 every `this.…` the control touches really exists on OrbitApp",
      not unreachable, "unreachable: %s" % unreachable)
check("F2 it never calls a method of another view (the exact trap)",
      "this.teamById" not in (label_src + post_src) and "this.agents.filter" not in post_src)
check("F3 the scope comes from this app's own scoped roster, prompt sizes included",
      "this.lastAgents" in label_src and "this.lastAgents" in post_src
      and "this.lastAgents = fTree.agents" in app_body
      and "a.prompt_chars = promptChars[a.session]" in ORBIT)
check("F4 a label failure cannot swallow the click (the bar still opens)",
      "try { this.labelTeamorgScope(); } catch (_) {}" in ORBIT)


def class_body(marker):
    """The body of a `class X {` block: from the marker to the next top-level class."""
    i = ORBIT.find(marker)
    if i < 0:
        return ""
    j = ORBIT.find("\nclass ", i + len(marker))
    return ORBIT[i:j if j > 0 else len(ORBIT)]


# The same defect in general form: a call into a SIBLING view must name a member
# that view actually defines (the first version called AgentsView's own method
# from OrbitApp, which does not exist there).
VIEW_CLASS = {"agents": "class AgentsView", "org": "class OrgChartView",
              "jobs": "class JobsView", "routines": "class RoutinesView",
              "feed": "class FeedView", "tac": "class Constellation"}
unknown = []
for view, marker in VIEW_CLASS.items():
    body = class_body(marker)
    members = (set(re.findall(r"this\.([A-Za-z_$][\w$]*)\s*=", body))
               | set(re.findall(r"^  (?:async )?([A-Za-z_$][\w$]*)\(", body, re.M)))
    for member in sorted(set(re.findall(r"this\.%s\.([A-Za-z_$][\w$]*)" % view, app_body))):
        if member not in members:
            unknown.append("%s.%s" % (view, member))
check("F5 no call into a sibling view that does not define that member",
      not unknown, str(unknown))

# ---- E: the deck cannot go stale silently ---------------------------------
from longrun.orbit import api as oapi  # noqa: E402

INDEX = read("webui", "index.html")
ver = oapi.shell_version()
check("E1 the backend reports a REAL version of the shell it would serve",
      isinstance(ver, str) and ver.count(".") == 1
      and ver == "%d.%d" % (int(os.stat(os.path.join(REPO, "src", "longrun", "orbit",
                                                     "web", "orbit.html")).st_mtime),
                            os.path.getsize(os.path.join(REPO, "src", "longrun", "orbit",
                                                         "web", "orbit.html"))),
      ver)
check("E2 the served shell is not cacheable (a stale byte-level copy is impossible)",
      "no-store" in read("src", "longrun", "core", "httpapi.py"))
check("E3 the deck's url carries the theme AND the version when known",
      "function _ctlShellUrl(v)" in INDEX and '"&v=" + encodeURIComponent(v)' in INDEX)
check("E4 opening a stale deck re-navigates exactly once, to the CURRENT shell",
      "async function _ctlShellWatch(f)" in INDEX and "_ctlShellSeen !== v" in INDEX
      and 'api("GET", "/api/orbit/shell")' in INDEX)
check("E5 the watcher is wired into the Control entry point",
      "_ctlShellWatch(f);" in INDEX[INDEX.find("function showControl()"):])

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
