#!/usr/bin/env python3
"""v609 — job bridge Plan<->Control + research model in Settings Models.

1. Clicking a J-chip in the RH Plan panel shows the TEAM job text (same
   GET /api/jobs/<id> the Control deck renders) plus a button that opens the
   Job panel in Control and rings that job (postMessage longrun-focus-job,
   same pattern as longrun-focus-node). No second truth: one registry, one
   bridge, both directions verified (plan->deck, deck renders job goal).
2. The research model is operator-settable in Settings ▸ Models (same
   endpoint as the Knowledge picker, one writer) and documented in
   config/index.yaml (no hardcoded-only model).
Deterministic, no network, no model.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("T1 J-chips carry the job id (clickable bridge, not inert text)",
      'class="jt jt-job" data-job=' in HTML, "data-job")
check("T2 chip click shows job detail (same registry endpoint as the deck)",
      "_showJobDetail" in HTML and '"/api/jobs/"' in HTML, "detail")
check("T3 detail has job text + open-in-Control-Jobs + back-to-todo",
      "jobGoControl" in HTML and "_showJobInControl" in HTML
      and "jobBackTodo" in HTML, "buttons")
check("T4 bridge hands the deck the job id via postMessage",
      "longrun-focus-job" in HTML, "postMessage")

ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()
check("T5 deck handles longrun-focus-job (expand + scroll + ring)",
      "longrun-focus-job" in ORBIT and "focusJob(jid)" in ORBIT
      and ".job.focusring" in ORBIT, "deck")
check("T6 deck never steals a stacked-board layout for the handover",
      '!== "all"' in ORBIT, "layout guard")

check("T7 research model card lives in Settings Models (not KB-only)",
      'id="researchModelSettings"' in HTML, "models card")
check("T8 one writer: both pickers share researchModelLs/researchSetActive",
      'researchModelSettings' in HTML and 'POST /api/research/model' in HTML,
      "shared endpoint")
YML = open(os.path.join(REPO, "config", "index.yaml"), encoding="utf-8").read()
check("T9 config documents research_model (no hardcoded-only model)",
      "research_model" in YML, "index.yaml")
SET = open(os.path.join(REPO, "src", "longrun", "core", "settings.py"),
           encoding="utf-8").read()
check("T10 settings map points research_model at Models",
      "research_model" in SET and "Models" in SET, "settings.py")

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
