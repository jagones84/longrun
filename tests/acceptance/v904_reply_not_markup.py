#!/usr/bin/env python3
"""v904 — a reply is PROSE: native tool-call markup never becomes the answer (2026-11-08).

Operator: *"in chat session … li vedo invece nel RH panel ma cliccandoli ottengo
info strane"* — and the job panel showed `J30.1 → A179  tasked: <｜｜DSML｜｜
parameter name="args" …>`.

Measured on job J30: the coordinator's planning turn emitted `<｜｜DSML｜｜
invoke name="fs.write">` (the model's native tool dialect) and a proper per-agent
bullet list. `stores.turn_reply(..., longest=True)` counted BOTH as prose and
returned the LONGER one — the envelope. Consequences: the same 2.8 KB of markup
was stored as `subjobs[J30.1..3].assignment` (every worker was handed it as its
brief) and `runs[A88].result` was the envelope instead of A88's report.

The rule this pins: markup is a CALL the loop already parsed and executed, never
an answer. Detection has ONE owner (`textkit.DSML_MARK` / `is_tool_markup`), asked
by the agent loop and by reply selection.

Deterministic, no model, no server. Run: python3 tests/acceptance/v904_reply_not_markup.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-904-")
for k, v in {
    "LONGRUN_AGENTS_FILE": os.path.join(TMP, "agents.json"),
    "LONGRUN_SESSIONS_DIR": os.path.join(TMP, "sessions"),
    "LONGRUN_GRAPH_DIR": os.path.join(TMP, "graphs"),
    "LONGRUN_DB": os.path.join(TMP, "events.db"),
    "LONGRUN_CONFIG_DIR": os.path.join(TMP, "cfg"),
    "LONGRUN_JOBS_FILE": os.path.join(TMP, "jobs.json"),
    "LONGRUN_TEAMS_FILE": os.path.join(TMP, "teams.json"),
}.items():
    os.environ[k] = v
for d in ("sessions", "graphs", "cfg"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import textkit as TK                  # noqa: E402
from longrun.memory import stores                      # noqa: E402
from longrun.orchestrate import jobs as J              # noqa: E402
from longrun.core import server as _server             # noqa: E402  (first: breaks the agent<->server cycle)
from longrun.agent import agent as A                   # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# ---- fixtures: the three dialects + prose ----------------------------------
DSML = ('<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="fs.write">\n'
        '<｜｜DSML｜｜ parameter name="args" string="false">'
        '{"path": "notes/brief.md", "content": "# Assignment brief"}\n'
        '</｜｜DSML｜｜ parameter>\n</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>')
ONE_BAR = '<|DSML| invoke name="fs.read">\n<|DSML| parameter name="path">a</|DSML| parameter>'
HERMES = '<tool_call><function=fs.write><parameter=path>a.py</parameter></function></tool_call>'
ARGKV = ('<tool_call>action</arg_key><arg_value>fs.write</arg_value>'
         '<arg_key>path</arg_key><arg_value>a.py</arg_value></tool_call>')
PLAN = ("Plan recorded.\n"
        "- **A87**: research adherence support and mental health care.\n"
        "- **A88**: research stigma reduction and psychosocial supports.\n"
        "- **A179**: draft the report from A87 + A88. (after A87, A88)\n")

# ---- A) one detector, three dialects ---------------------------------------
check("A1 the DSML marker has ONE owner in the text layer",
      "DSML_MARK" in read("src", "longrun", "util/textkit.py"))
check("A2 the agent loop no longer owns its own copy of the regex",
      "_DSML_MARK = r\"" not in read("src", "longrun", "agent/agent.py"))
check("A3 double-bar DSML is markup", TK.is_tool_markup(DSML))
check("A4 one-bar DSML is markup (JAG-534 drift)", TK.is_tool_markup(ONE_BAR))
check("A5 the Hermes template is markup", TK.is_tool_markup(HERMES))
check("A6 the arg_key/arg_value dialect is markup", TK.is_tool_markup(ARGKV))
check("A7 prose is NOT markup", not TK.is_tool_markup(PLAN))
check("A8 an empty/None message is not markup",
      not TK.is_tool_markup("") and not TK.is_tool_markup(None))
check("A9 the agent's own predicates still answer (compat)",
      A._looks_like_dsml(DSML) and A._looks_like_tool_markup(HERMES)
      and not A._looks_like_dsml("just an answer"))

# ---- B) reply selection: prose wins, markup is skipped ---------------------
TURN = [{"role": "user", "content": "Plan the work"},
        {"role": "assistant", "content": DSML, "internal": True},
        {"role": "assistant", "content": PLAN, "internal": True},
        {"role": "assistant", "content": "Short final note."}]
check("B1 the longest reply is the PLAN, not the envelope",
      stores.turn_reply(TURN, longest=True) == PLAN.strip(),
      repr(stores.turn_reply(TURN, longest=True)[:80]))
check("B2 the last reply is still the last message",
      stores.turn_reply(TURN) == "Short final note.")
check("B3 markup counts as work, not as prose", stores._starts_work(DSML))
check("B4 a turn of markup only has NO reply (never the envelope)",
      stores.turn_reply([{"role": "assistant", "content": DSML}]) == "")
check("B5 a bare finish envelope is still shown (v303 contract)",
      stores.turn_reply([{"role": "assistant", "content": '{"action":"finish"}'}])
      == '{"action":"finish"}')
check("B6 a finish summary still wins over a later gate message",
      stores.turn_reply([{"role": "assistant",
                          "content": '{"action":"finish","summary":"the real result"}'},
                         {"role": "assistant", "content": "gate prose"}]) == "the real result")

# ---- C) the assignment: the plan line, never the envelope ------------------
check("C1 a markup plan yields NO assignment (caller falls back to the goal)",
      J.JobRegistry._assignment_for(DSML, "A87") == "")
check("C2 each agent gets ITS OWN bullet",
      J.JobRegistry._assignment_for(PLAN, "A87").startswith("- **A87**")
      and J.JobRegistry._assignment_for(PLAN, "A179").startswith("- **A179**"),
      J.JobRegistry._assignment_for(PLAN, "A179")[:60])
check("C3 a plan carrying markup is not trusted as a brief (goal fallback)",
      J.JobRegistry._assignment_for(DSML + "\n" + PLAN, "A88") == "")
check("C4 an unnamed agent still gets the whole (prose) plan",
      J.JobRegistry._assignment_for(PLAN, "A9") == PLAN.strip())
subs = J.plan_subjobs("J30", ["A87", "A88", "A179"], "A84", DSML, {})
check("C5 plan_subjobs records NO markup brief",
      all(not s["assignment"] for s in subs.values()),
      [s["assignment"][:30] for s in subs.values()])
subs2 = J.plan_subjobs("J31", ["A87", "A88"], "A84", PLAN, {})
check("C6 plan_subjobs records the per-agent bullet",
      subs2["J31.1"]["assignment"].startswith("- **A87**"),
      subs2["J31.1"]["assignment"][:40])

# ---- D) what the UIs print: legacy rows are LABELLED, not leaked -----------
check("D1 readable_text labels markup",
      J.readable_text(DSML).startswith("(a raw tool call"), J.readable_text(DSML))
check("D2 readable_text leaves prose untouched", J.readable_text(PLAN) == PLAN)
RAW = {"id": "J30", "runs": {"A88": {"state": "done", "result": DSML}},
       "subjobs": {"J30.3": {"id": "J30.3", "agent": "A88", "assignment": DSML,
                            "result": DSML, "status": "done"}}}
VIEW = J.readable_job(RAW)
check("D3 the view's subjob brief is readable",
      VIEW["subjobs"]["J30.3"]["assignment"].startswith("(a raw tool call"))
check("D4 the view's run result is readable",
      VIEW["runs"]["A88"]["result"].startswith("(a raw tool call"))
check("D5 the STORE is untouched (the runner still reads the real data)",
      RAW["subjobs"]["J30.3"]["assignment"] == DSML and RAW["runs"]["A88"]["result"] == DSML)
check("D6 list() and detail() print through the view",
      "readable_job(j)" in read("src", "longrun", "orchestrate/jobs.py")
      and "readable_text(s.get(\"assignment\"))" in read("src", "longrun", "orchestrate/jobs.py"))

# ---- source locks ----------------------------------------------------------
src_stores = read("src", "longrun", "memory", "stores.py")
check("E1 reply selection asks the shared detector",
      "is_tool_markup(text)" in src_stores)
check("E2 both reply branches exclude work messages",
      src_stores.count("if not _starts_work(m.get(\"content\"))") == 2,
      src_stores.count("if not _starts_work(m.get(\"content\"))"))

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
