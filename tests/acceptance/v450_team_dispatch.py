#!/usr/bin/env python3
"""v450 — an orchestrator can DISTRIBUTE work to its ORG-CHART team (JAG-450),
and the Improvement panel shows SIGNAL (JAG-450).

Operator feedback:
  * "Master is a team orchestrator — why has he never called their ORG CHART
    sessions agents to help to distribute work?"  The chat had NO way to hand a
    subtask to a teammate's OWN session: the prompt never listed the team and
    `subagent` spawns an anonymous child. Now the orchestrator's role prompt lists
    its direct reports and a `dispatch` action runs a real turn in a teammate's
    session and returns the reply (only a DIRECT report, no recursion).
  * "Improvement panel still useless — file changed, see diff, monitoring nothing
    clearly".  The panel now DE-DUPES proposals and shows only MEANINGFUL ledger
    events (no more 'turn wrote=[]' noise), plus a methodology block with the
    thresholds.

Deterministic, no model, no server. Run: python3 tests/acceptance/v450_team_dispatch.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-450-")
for k, v in {
    "LONGRUN_AGENTS_FILE": os.path.join(TMP, "agents.json"),
    "LONGRUN_SESSIONS_DIR": os.path.join(TMP, "sessions"),
    "LONGRUN_GRAPH_DIR": os.path.join(TMP, "graphs"),
    "LONGRUN_DB": os.path.join(TMP, "events.db"),
    "LONGRUN_CONFIG_DIR": os.path.join(TMP, "cfg"),
}.items():
    os.environ[k] = v
for d in ("sessions", "graphs", "cfg"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S              # noqa: E402
from longrun.agent import agents as A             # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- mock the session/turn machinery so no model runs -----------------------
_store = {}


def _goc(sid):
    _store.setdefault(sid, {"id": sid, "messages": []})
    return _store[sid]


def _load(sid):
    return _store.get(sid) or {"id": sid, "messages": []}


def _stream(sess, message, model, *a, **k):
    sess.setdefault("messages", []).append({"role": "user", "content": message})
    sess["messages"].append({"role": "assistant",
                             "content": "ACK from %s" % sess.get("id")})
    return iter(())


S.get_or_create_session = _goc
S.load_session = _load
S.chat_stream_gen = _stream

ev = []
on_event = lambda kind, **kw: ev.append((kind, kw))  # noqa: E731

# ---- build an org chart: Master (A1) -> coder 1 (A2) ------------------------
M = A.REGISTRY.designate("sess_master", name="Master", role="orchestrator")["agent"]
C = A.REGISTRY.designate("sess_coder1", name="coder 1", role="coding agent",
                         reports_to=M["id"])["agent"]
_ = A.REGISTRY.designate("sess_other", name="unrelated")   # not on the team
master_sess = {"id": "sess_master", "messages": []}

check("A1 the master's team lists its direct report",
      A.REGISTRY.team_of(M["id"]) == [M["id"], C["id"]], A.REGISTRY.team_of(M["id"]))

# ---- A) dispatch to a teammate runs a real turn in THEIR session ------------
ev.clear()
out = S._apply_chat_dispatch(master_sess,
                             {"action": "dispatch", "agent": C["id"], "goal": "write the parser"},
                             on_event)
check("A2 dispatch returns the teammate's reply", "ACK from sess_coder1" in out, out[:120])
check("A3 the teammate's OWN session received the turn",
      any(m.get("role") == "assistant" and "ACK from sess_coder1" in (m.get("content") or "")
          for m in _store["sess_coder1"]["messages"]))
check("A4 the delegated user message is attributed to the dispatcher",
      any(m.get("role") == "user" and "delegated by" in (m.get("content") or "")
          for m in _store["sess_coder1"]["messages"]))
check("A5 a dispatch tool.result event is emitted",
      any(k == "tool.result" and kw.get("tool") == "dispatch" for k, kw in ev))

# ---- B) guard rails ---------------------------------------------------------
res_b = S._apply_chat_dispatch(master_sess,
                               {"action": "dispatch", "agent": "A99", "goal": "x"}, on_event)
check("B1 dispatching to a NON-report is refused", "not one of your direct reports" in res_b, res_b)
res_c = S._apply_chat_dispatch({"id": "sess_nobody", "messages": []},
                               {"action": "dispatch", "agent": C["id"], "goal": "x"}, on_event)
check("B2 a non-agent session cannot dispatch", "not an org agent" in res_c, res_c)
res_d = S._apply_chat_dispatch(master_sess, {"action": "dispatch", "agent": C["id"]}, on_event)
check("B3 a goal is required", "goal required" in res_d, res_d)

# ---- C) the static wiring: prompt roster + loop branch + tool prompt ---------
agent_src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
prompt_src = open(os.path.join(REPO, "src", "longrun", "model", "prompt.py"), encoding="utf-8").read()
check("C1 the loop has the dispatch action branch",
      'act.get("action") == "dispatch"' in agent_src and "_apply_chat_dispatch(sess, act" in agent_src)
check("C2 a delegated/plan-only turn cannot dispatch (no recursion)",
      "plan_only or autonomous" in agent_src)
check("C3 the chat tool prompt advertises dispatch",
      '"action":"dispatch"' in agent_src and "DISTRIBUTE work" in agent_src)
check("C4 the role prompt lists the team (org chart) for an orchestrator",
      "## Your team (org chart" in prompt_src and "team_of(" in prompt_src
      # EV-43: the roster is rebuilt at prompt time and says so, so an orchestrator
      # never trusts a stale copy of its own team.
      and "rebuilt from live state every turn" in prompt_src)
check("C5 the dispatch handler is re-exported by server",
      "_apply_chat_dispatch" in open(os.path.join(REPO, "src", "longrun", "core", "server.py"),
                                     encoding="utf-8").read())

# ---- D) improvement panel shows SIGNAL --------------------------------------
htt = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
idx = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("D1 /api/improvement de-duplicates proposals",
      "Collapse DUPLICATE proposals" in htt and '"proposals_total"' in htt)
check("D2 /api/improvement drops no-op ledger rows",
      "no-op" in htt and "meaningful = [e for e in all_ledger" in htt)
check("D3 it exposes the methodology config",
      '"importance_threshold"' in htt and '"auto_kinds"' in htt)
check("D4 the panel renders the methodology + thresholds",
      # v641: the disclosure is titled "How the loop works" now that the panel is a
      # list of disclosures instead of caps headings.
      "impHow" in idx and "How the loop works" in idx
      and "importance_threshold" in idx)
check("D5 the panel shows per-section counts",
      "impRecCount" in idx and "impLedCount" in idx)
# JAG-534: the improvement files live under the DATA HOME now, so the API exposes
# the home as the absolute base and the panel resolves `data/...` links against it.
check("D6 /api/improvement exposes an absolute root + harness files",
      '"root": _paths.HOME_DIR' in htt and '"data/memory/agent_notes.md"' in htt)
check("D7 the panel resolves repo-relative file links against that root",
      "let _impRoot" in idx and "_impRoot = d.root" in idx and "function _impAbs" in idx
      and "data-p=\"' + _attr(_impAbs(" in idx)
check("D8 the history is grouped by DAY (collapsible) + states retention",
      "_impByDay(lg)" in idx and "_impByDay(records)" in idx and "Retention:" in idx)

print("---")
ok = sum(results)
print("\nv450: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
