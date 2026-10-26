#!/usr/bin/env python3
"""v671 — F5 cross-feature contract suite, with Doc2Harness positive controls.

`v576` proves five guardrails ONE AT A TIME. This suite drives the composition
the product actually runs — plan -> approval gate -> tool -> mutation mark ->
evidence close -> compaction — and reads the effect on the channels Doc2Harness
names (`papers/doc2harness_2610.20344.txt:87-95`): files on disk, the tool
observation (what the model is sent), the exit status, the command output.

Positive controls (§2.4, `papers/doc2harness_2610.20344.txt:509-553`): a control
shares the scenario and the fixture, changes only the route/input, and asserts
that the effect the case inspects is OBSERVABLE at all. If a control fails, every
case gated by it is recorded FAIL regardless of its own result — that is what
stops a vacuous green. Controls do not count toward the pass rate (§2.5).

  CTRL-gate    the gate was really consulted: an approval row exists for the
               write, approved, and spent (`uses_left == 0`).
  CTRL-write   the same tool, same workspace, really writes: the file exists
               with the exact payload (so "it was marked" is not a no-op).
  CTRL-channel a read of that file puts its content in the tool observation,
               i.e. the channel the cases read is live.

Composition (SpecBench view, `papers/specbench_2605.21384.txt:50-57`): C1-C7 are
the visible single behaviours; C8-C10 are the HELD-OUT composition — the same
features in one flow, which is where a harness breaks while every single feature
still passes on its own.

Scope, honestly: "resume" here means the plan is still the plan after compaction
(same node id, still transmitted in the current turn). Resuming an interrupted
LIVE loop is parked in the master (it needs per-tool idempotency).
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v671-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_APPROVALS"] = os.path.join(TMP, "approvals.json")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: F401,E402 — breaks the import cycle
from longrun.agent import agent as AG          # noqa: E402
from longrun.core import api_v02 as API        # noqa: E402
from longrun.model import context_engine as CE  # noqa: E402
from longrun.plan import taskgraph as TG       # noqa: E402
from longrun.plan import verify as VF          # noqa: E402
from longrun.tools import approvals            # noqa: E402
from longrun.tools import registry             # noqa: E402
from longrun.tools import tools as toolmod     # noqa: E402

registry._external_tools = lambda: {}
results = []
controls = {}


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def control(name, ok, detail=""):
    """A positive control: printed, NOT counted in the pass rate (§2.5)."""
    controls[name] = bool(ok)
    print(("PASS " if ok else "FAIL ") + "control " + name
          + ((" :: " + str(detail)) if detail else ""))


def _gated(gates, ok):
    """The Doc2Harness rule as a pure predicate: a broken control voids the case."""
    return bool(ok) and all(controls.get(g) for g in gates)


def case(name, gates, ok, detail=""):
    broken = [g for g in gates if not controls.get(g)]
    if broken:
        check(name + " [vacuous: " + ",".join(broken) + " failed]", False, detail)
        return
    check(name, ok, detail)


os.chdir(TMP)   # the tool roots are relative ("."): the workspace is the temp dir
GOAL = "v671 composed contract run"
LABEL = "write the composed fixture"
COMMIT = "Do not touch src/longrun; report the fixture path when done."
RID = "run_v671composed"
PAYLOAD = "composed payload"

# ---------------------------------------------------------------- the flow --
graph = TG.ensure(RID, goal=GOAL)
TG.apply_write_todos(graph, [{"label": LABEL}, {"label": "report the result"}],
                     source="test:v671")
# The run id IS the graph key the loop reads, so the state must carry it.
st = API.new_run(GOAL, model="m", max_steps=2, script=[])
st.id = RID
API.RUNS[RID] = st
# Fixture source, written before the gated action (so the action is a plain copy).
toolmod.execute("shell", {"command": "printf '%s' > v671-src.txt" % PAYLOAD,
                          "cwd": TMP}, run_id=RID)
_waits = []
_orig_wait = approvals.wait


def _approve_all(aid, timeout=None, checkpoint=None, **_k):
    _waits.append(aid)
    return approvals.decide(aid, "approve", by="v671")


approvals.wait = _approve_all
try:
    out = API.agent_run_v2(
        GOAL, max_steps=2, model="m", run_id=RID, workspace=TMP,
        script=[{"action": "tool", "tool": "shell",
                 "args": {"command": "cp v671-src.txt v671-fixture.txt", "cwd": TMP}}])
finally:
    approvals.wait = _orig_wait

graph = TG.load(RID) or graph
target = TG.find(graph, label=LABEL)
tid = (target or {}).get("id")

# ------------------------------------------------------------- the controls --
_rec = [r for r in approvals.list_all(None, 100000) if r.get("tool") == "shell"]
control("gate", len(_rec) == 1 and _rec[0].get("status") == "approved"
        and _rec[0].get("uses_left") == 0,
        [(r.get("status"), r.get("uses_left")) for r in _rec])
try:
    with open(os.path.join(TMP, "v671-fixture.txt"), encoding="utf-8") as f:
        _disk = f.read()
except OSError as e:
    _disk = "unreadable: %s" % e
control("write", _disk == PAYLOAD, _disk)
_obs = str(toolmod.execute("shell", {"command": "cat v671-fixture.txt", "cwd": TMP},
                           run_id=RID).get("stdout") or "")
control("channel", PAYLOAD in _obs, _obs[:120])

# ------------------------------------------------- C1-C7: single behaviours --
case("C1 the composed run finishes", ["gate"],
     str(out.get("termination")) == "completed", out.get("termination"))
case("C2 the plan survives the run with both steps", [],
     bool(target) and len(TG.plan_nodes(graph)) == 2,
     [n.get("label") for n in TG.plan_nodes(graph)])
case("C3 the write marks the step it ran under, and that step needs proof (F1)",
     ["gate", "write"], bool(target) and target.get("mutated") is True
     and TG.needs_closeout_proof(target), (target or {}).get("mutations"))

# ------------------------------- C4-C6: the held-out composition (mid-run) --
# The loop closes the plan when the run ends, so a mid-run continuation means a
# fresh OPEN step — this is what compaction must still transmit.
VERIFY = "verify the fixture on disk"
graph = TG.load(RID)
TG.add_node(graph, VERIFY, source="test:v671")
_hist = []
for _i in range(20):
    _hist.append({"role": "user", "content": "filler %d %s" % (_i, "x" * 180)})
    _hist.append({"role": "assistant", "content": "ack %d %s" % (_i, "y" * 180)})
_hist.append({"role": "user", "content": "Observation: " + _obs})
_sb = AG.state_block(graph_key=RID)
_msgs, _stats = CE.build("you are the v671 harness", _hist,
                         "continue\n\n" + _sb + "\n\nCommitment: " + COMMIT,
                         budget_tokens=900, keep_recent=2, retrieve_memory=False)
_cstat = _stats.get("compaction") or {}
case("C4 compaction really fires on the composed transcript", ["channel"],
     bool(_cstat.get("compacted") or _cstat.get("dropped")
          or _cstat.get("truncated")) and _stats.get("final_messages") < len(_hist) + 2,
     _cstat)
_last_user = (_msgs[-1].get("content") or "") if _msgs else ""
case("C5 after compaction the open plan and the commitment are still transmitted", [],
     VERIFY in _last_user and COMMIT in _last_user and PAYLOAD in (_obs or ""),
     _last_user[-160:])
case("C6 the plan ids survive compaction (same step, no re-numbering)", [],
     (TG.find(TG.load(RID), label=LABEL) or {}).get("id") == tid,
     (TG.find(TG.load(RID), label=LABEL) or {}).get("id"))

# -------------------------------- C7-C10: the close contract on the same step --
TG.complete_node(graph, node_id=tid, evidence="wrote the fixture by hand",
                 source="test:v671")
graph = TG.load(RID)
target = TG.find(graph, node_id=tid)
_cur = TG.current_evidence(target)
_first_claim = _cur[-1] if _cur else {}
case("C7 a sentence-only close is a CLAIM (F3)", [],
     target.get("status") == "done" and _first_claim.get("claim") is True
     and not _first_claim.get("sources"), _first_claim)
case("C8 a CLAIM is not environment proof, so the step still needs it (F1+F3)",
     [], TG.needs_closeout_proof(target), target.get("mutations"))

TG.complete_node(graph, node_id=tid, evidence="fixture content verified on disk",
                 source="test:v671", sources=["v671-fixture.txt:1"])
graph = TG.load(RID)
target = TG.find(graph, node_id=tid)
_cur = TG.current_evidence(target)
_last = _cur[-1] if _cur else {}
_claims = [e for e in (target.get("evidence") or []) if e.get("claim")]
case("C9 a sourced close carries the ref and is not a claim (F3)", [],
     _last.get("sources") and not _last.get("claim")
     and _last["sources"][0].get("path") == "v671-fixture.txt"
     and _last["sources"][0].get("start") == 1, _last)
case("C10 the sourced close retires the earlier claim and keeps one current entry",
     [], bool(_claims) and all(e.get("superseded") for e in _claims)
     and len(_cur) == 1 and target.get("status") == "done",
     [(e.get("claim"), e.get("superseded")) for e in (target.get("evidence") or [])])

# ------------------------------------------- C11-C12: closeout on that step --
_ok, _rep, _obs_flag = VF.closeout_gate(target, c={"closeout": True, "command": ""})
case("C11 closeout is fail-closed: on with no command refuses the close (F1)", [],
     _ok is False and _rep.get("ran") is False and "empty" in str(_rep.get("error")),
     _rep)
_ok2, _rep2, _obs2 = VF.closeout_gate(
    target, c={"closeout": True, "command": "true"},
    check=lambda **kw: (True, "ok"))
case("C12 closeout with a green check records an OBSERVED proof (F1)", [],
     _ok2 is True and _obs2 is True and _rep2.get("ran") is True, _rep2)

# the gate mechanic itself is not allowed to be decorative
check("C13 a broken control voids its case (no vacuous pass)",
      _gated(["_missing-control"], True) is False
      and _gated(["gate"], True) is True and _gated(["gate"], False) is False)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
