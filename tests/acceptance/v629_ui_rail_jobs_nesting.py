#!/usr/bin/env python3
"""v629 — LH rail organisation, justification under every todo, org-depth jobs.

Six operator items in one deterministic test (no server, no model, no network):

  A) the sessions rail is organised in named blocks and the ▲/▼ collapse tools
     sit IMMEDIATELY beside the "Sessions" label (no far-right push);
  B) a todo's JUSTIFICATION is a full-width line UNDER the row for EVERY status
     (done included) — never a squeezed suffix beside the label;
  C) project rules state the gap-analysis-first rule and the branch policy
     (Experimental is the working branch, master is a backup, never FF);
  D) an interactive descendant of a draggable row owns its click (the Control
     A-id select button was unreachable because td.aid captures the pointer);
  E) team jobs nest to ANY org depth: parent-first subjob ids (J8.1.1), natural
     path ordering, children on the engine AND on the deck payload;
  F) Jobs → session centers the LH rail through the SAME procedure as the 🎯
     button (revealActiveSession), not a second implementation.

Run: python tests/acceptance/v629_ui_rail_jobs_nesting.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v629-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
for d in ("cfg", "sessions", "graphs", "threads", "data"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = src("webui", "index.html")
ORBIT = src("src", "longrun", "orbit", "web", "orbit.html")
DRAG = src("webui", "assets", "dragsort.js")
RULES = src(".trae", "rules", "project_rules.md")

# ---- A. LH rail ---------------------------------------------------------------
check("A1 the rail is a named block (rail-head / rail-tools / rail-list)",
      '<section class="rail">' in UI and 'class="rail-head"' in UI
      and 'class="rail-tools" role="toolbar"' in UI and 'class="card rail-list"' in UI)
check("A2 the ▲/▼ tools are INSIDE the Sessions h2 (one header row)",
      '<h2>Sessions<span class="srail-tools">' in UI)
check("A3 .srail-tools no longer pushes itself to the far edge",
      "margin-left: auto" not in UI.split(".srail-tools {")[1].split("}")[0]
      if ".srail-tools {" in UI else False,
      UI.split(".srail-tools {")[1].split("}")[0].strip() if ".srail-tools {" in UI else "")
check("A4 the top block is ONE toolbar row (＋ · search · activity · filter)",
      'class="rail-tools" role="toolbar"' in UI
      and UI.index('id="railNew"') < UI.index('id="railSearch"')
      < UI.index('id="runsBar"') < UI.index('id="hide-empty"'))
check("A5 the session name is asked in the DIALOG, not in a permanent input",
      'id="railNew" data-call="newSession"' in UI
      and 'id="sessInp"' not in UI and 'id="nsTitle"' in UI)
check("A6 ONLY the list scrolls — the header tools never scroll away",
      "overflow: hidden" in UI.split("aside {")[1].split("}")[0]
      and "overflow-y: auto" in UI.split("aside .rail-list {")[1].split("}")[0])

# ---- B. justification under every todo ----------------------------------------
check("B1 the justification is a block UNDER the summary (.tcwhy)",
      ".tctree > .tcwhy" in UI and "white-space: pre-wrap" in UI.split(".tctree > .tcwhy")[1][:400])
check("B2 the old inline suffix is gone (no .tcreason rule, no DOM writer)",
      ".tctree .tcreason {" not in UI
      and 'rs.className = "tcreason"' not in UI
      and 'querySelector(".tcreason")' not in UI)
check("B3 _paintNode renders it for EVERY status (no superseded-only branch)",
      "function _whyOf(" in UI and "const why = _whyOf(node);" in UI
      and 'node.status === "superseded" || node.status === "cancelled"' not in UI)
check("B4 the why line is inserted before the children container",
      'det.insertBefore(wy, det.querySelector(":scope > .tc-kids"))' in UI)
check("B5 the status is stamped on the row so CSS can tint the why line",
      'det.dataset.st = node.status || "todo";' in UI
      and '.tctree[data-st="done"] > .tcwhy' in UI)
check("B6 _whyOf falls back to the loaded graph for slim live nodes",
      "if (!hasEv && graph)" in UI and "x.id === node.id" in UI)

# ---- C. project rules ----------------------------------------------------------
check("C1 gap analysis is a MANDATORY rule",
      "Gap analysis before any implementation" in RULES
      and "ALREADY done" in RULES and "genuinely MISSING" in RULES)
check("C2 branch policy: Experimental works, master is the backup",
      "`Experimental-Refactor` is the working branch" in RULES
      and "`master` is the BACKUP branch" in RULES
      and "Never fast-forward or merge into `master`" in RULES)

# ---- D. interactive descendants own their click -------------------------------
check("D1 DragSort ignores pointerdown on a button/link inside a drag handle",
      't.closest("button,a,input,select,textarea,label,[contenteditable=\'true\']")' in DRAG)
check("D2 touch taps get the same guard",
      DRAG.count("closest(\"button,a,input,select,textarea,label,") == 2)
check("D3 the A-id select button is still wired to focusAgent",
      'data-org="1"' in ORBIT and "this.focusAgent(tr.dataset.sid, true)" in ORBIT)

# ---- E. org-depth nesting ------------------------------------------------------
from longrun.orchestrate import jobs as J  # noqa: E402

cfg = J.config()
check("E1 config/jobs.yaml is read (generous defaults: depth 3, cap 64)",
      cfg["subjob_depth"] == 3 and cfg["max_subjobs"] == 64, cfg)

# A chain: A1 (coord) -> A2 -> A3, A4 ; A2 also a direct report of A1, A5 of A1.
tree = {"A2": "A1", "A3": "A2", "A4": "A2", "A5": "A1"}
subs = J.plan_subjobs("J8", ["A1", "A2", "A3", "A4", "A5"], "A1", None, {}, tree=tree)
ids = sorted(subs, key=J.subjob_path)
check("E2 parents are minted before children and children NEST under them",
      ids == ["J8.1", "J8.1.1", "J8.1.2", "J8.2"], ids)
check("E3 every nested subjob carries its parent_sub link",
      subs["J8.1.1"]["parent_sub"] == "J8.1"
      and subs["J8.1.2"]["parent_sub"] == "J8.1"
      and subs["J8.1"]["parent_sub"] is None,
      {k: v["parent_sub"] for k, v in subs.items()})
check("E4 flat teams are unchanged (no tree -> J8.1, J8.2, ...)",
      sorted(J.plan_subjobs("J8", ["A1", "A2", "A3"], "A1", None, {}),
             key=J.subjob_path) == ["J8.1", "J8.2"])
check("E5 path ordering keeps a child right after its parent",
      sorted(["J8.2", "J8.1.2", "J8.1", "J8.1.1", "J8.10"], key=J.subjob_path)
      == ["J8.1", "J8.1.1", "J8.1.2", "J8.2", "J8.10"])
check("E6 subjob_depth / subjob_children",
      J.subjob_depth("J8") == 0 and J.subjob_depth("J8.1.2") == 2
      and J.subjob_children(subs, "J8.1") == ["J8.1.1", "J8.1.2"]
      and J.subjob_children(subs, "J8.1.1") == [])
check("E7 the subjob cap is enforced",
      len(J.plan_subjobs("J8", ["C"] + ["A%d" % i for i in range(1, 90)],
                         "C", None, {})) == 64)

AGENTS_SRC = src("src", "longrun", "agent", "agents.py")
check("E8 one traversal serves both team_of and team_tree (no second walker)",
      "def _subtree(" in AGENTS_SRC and "def team_of(self, ref, depth=1)" in AGENTS_SRC
      and "def team_tree(self, ref, depth=1)" in AGENTS_SRC)
check("E9 a job created from an assignee uses the ONE shared org derivation",
      "jobs_mod.org_agents(assignee)" in
      src("src", "longrun", "orchestrate", "orchestration.py"))
check("E10 the deck payload carries parent_sub + depth",
      '"parent_sub": s.get("parent_sub"),' in src("src", "longrun", "orbit", "api.py")
      and '"depth": subjob_depth(s.get("id")),' in src("src", "longrun", "orbit", "api.py"))
check("E11 the Jobs panel sorts by numeric PATH, not the trailing number",
      "const _path = s => String(s).split(\".\").slice(1)" in ORBIT
      and "Object.keys(subs).sort(_cmp)" in ORBIT)
check("E12 the constellation offsets a nested subjob one lane lower",
      "y: 68 + dep * 34" in ORBIT and "s.parent_sub && spos[s.parent_sub]" in ORBIT)
SETTINGS_SRC = src("src", "longrun", "core", "settings.py")
check("E13 jobs.yaml is a Settings > Harness form with a real writer (no dead knob)",
      '"file": "jobs.yaml", "id": "jobs", "panel": "harness"' in SETTINGS_SRC
      and '_f("subjob_depth", "org depth (levels)", "int"' in SETTINGS_SRC
      and '_f("max_subjobs", "max subjobs per job", "int"' in SETTINGS_SRC
      and 'elif name == "jobs.yaml":' in SETTINGS_SRC)

# v629.1: the PANEL job and the TOOL job ("Teamorg automation" → jobs.create) must
# build the SAME team from the SAME org chart, or a tool job stays flat forever.
JOBS_SRC = src("src", "longrun", "orchestrate", "jobs.py")
TOOL_SRC = src("src", "longrun", "agent", "longrun_agent.py")
check("E14 the org team has ONE derivation and the tool uses it too",
      JOBS_SRC.count("def org_agents(") == 1
      and "jobs_mod.org_agents(coordinator)" in TOOL_SRC)
from longrun.agent import agents as _AG  # noqa: E402


class _OrgStub:
    def team_of(self, ref, depth=1):
        return {"A1": ["A1", "A2", "A3"], "A2": ["A2", "A3"]}.get(ref, [])


_orig_reg = _AG.REGISTRY
_AG.REGISTRY = _OrgStub()
try:
    got = J.org_agents("A1")
    unknown = J.org_agents("ZZZ")
finally:
    _AG.REGISTRY = _orig_reg
check("E15 org_agents returns the subtree (panel == tool team)", got == ["A1", "A2", "A3"], got)
check("E15b an UNKNOWN assignee still yields no team (the job is refused)",
      unknown == [], unknown)
check("E16 the ids nest to ANY depth (3 levels: J8.1.1.1)",
      sorted(J.plan_subjobs("J8", ["A1", "A2", "A3", "A4"], "A1", None, {},
                            tree={"A2": "A1", "A3": "A2", "A4": "A3"}),
             key=J.subjob_path)
      == ["J8.1", "J8.1.1", "J8.1.1.1"],
      sorted(J.plan_subjobs("J8", ["A1", "A2", "A3", "A4"], "A1", None, {},
                            tree={"A2": "A1", "A3": "A2", "A4": "A3"}),
             key=J.subjob_path))
check("E17 the Plan panel chip accepts/prints a full dotted id at any depth",
      r'if (/^\d+(\.\d+)*$/.test(s)) return "J" + s;' in UI
      and r'const m = s.match(/^[jJ](\d+(\.\d+)*)$/);' in UI
      and "${esc(_nodeSub(n))}</span>" in UI)

# ---- F. jobs -> session centers the rail --------------------------------------
check("F1 the bridge handler reaches the SAME reveal procedure (no duplicate)",
      'if (!d || d.type !== "longrun-open-task") return;' in UI
      and "revealActiveSession();" in UI.split('d.type !== "longrun-open-task"')[1][:900])
check("F2 revealActiveSession is the one centering implementation",
      UI.count("function revealActiveSession()") == 1
      and UI.count("function _centerActiveRow()") == 1)

print("\nv629: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
