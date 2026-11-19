#!/usr/bin/env python3
"""v1193 — operational policy, execution policy, skill adapters, intake gate (round 124).

Sources:
  * arXiv:2611.15006 "EvoX" — the harness as an Operational Policy (Γ guidance,
    Δ deterministic control), a disposition instead of a reinterpretation,
    outcome grounding, and MODEL-CONDITIONAL harness effectiveness.
  * arXiv:2611.21688 "DeltaHarness" — hidden runtime state reverses plan order;
    only a separate FROZEN confirmation panel may replace an incumbent;
    delivery failures are counted, never priced as latency; acquisition cost is
    amortized over tasks.
  * arXiv:2611.17007 "Skill Adapter" — adapters bound to a general skill under
    applicability conditions, preloaded candidates RE-CHECKED on real inputs,
    and evidence that ages.
  * YouTube `OrcsMi2-IcM` (Sam Witteveen, 2026-11-03) — a deterministic intake
    gate before any model call, a bounded mandate per ticket, direct worker
    subscription, a stripped worker preset, record-first unrequested work.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1193_operational_policy_execution_intake.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1193-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import operational_policy as OP  # noqa: E402
from longrun.harness.checks import execution_policy as EP  # noqa: E402
from longrun.harness.checks import skill_adapter as SA  # noqa: E402
from longrun.harness.checks import intake_gate as IG  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. Action Realization (Δ) ----------------------------------------------
TOOLS = [
    {"name": "fs.read", "args": {"path": {"type": "string", "required": True},
                                 "offset": {"type": "integer"}}},
    {"name": "web.search", "args": {"q": {"type": "string", "required": True},
                                    "fresh": {"type": "boolean"}}},
]
ok = OP.realize({"tool": "fs.read", "args": {"path": "a.txt"}}, TOOLS)
check("a schema-valid call is realized unchanged",
      ok["decision"] == "execute" and ok["action"] == {"tool": "fs.read", "args": {"path": "a.txt"}}
      and not ok["findings"], ok)
coerced = OP.realize({"tool": "fs.read", "args": {"path": "a.txt", "offset": "12"}}, TOOLS)
check("a numeric string is coerced to the declared integer",
      coerced["decision"] == "execute" and coerced["action"]["args"]["offset"] == 12
      and kinds(coerced) == ["normalized"], coerced)
check("a string-typed argument given as a number is normalized, not rejected",
      OP.realize({"tool": "fs.read", "args": {"path": 7}}, TOOLS)["action"]["args"]["path"] == "7")
bool_ok = OP.realize({"tool": "web.search", "args": {"q": "x", "fresh": "true"}}, TOOLS)
check("a boolean spelled as a string is coerced",
      bool_ok["decision"] == "execute" and bool_ok["action"]["args"]["fresh"] is True, bool_ok)
truthy = OP.realize({"tool": "web.search", "args": {"q": "x", "fresh": 1}}, TOOLS)
check("an integer is NOT accepted for a boolean (the 1-is-True trap)",
      truthy["decision"] == "diagnose" and "schema-mismatch" in kinds(truthy), truthy)
check("an unknown tool is a diagnostic, never a guessed adapter",
      kinds(OP.realize({"tool": "ghost"}, TOOLS)) == ["unknown-tool"])
missing = OP.realize({"tool": "fs.read", "args": {}}, TOOLS)
check("a missing required argument blocks execution",
      missing["decision"] == "diagnose" and "missing-argument" in kinds(missing), missing)
check("a diagnosis without Γ guidance is reported as guidance-missing",
      "guidance-missing" in kinds(missing))
guided = OP.realize({"tool": "fs.read", "args": {}}, TOOLS, {"diagnose": "say what is missing"})
check("Γ guidance removes the guidance-missing finding",
      kinds(guided) == ["missing-argument"], guided)
leak = "I will call web.search with {\"q\": \"harness\"} now"
check("a prose call is refused unless the caller enables recovery",
      OP.realize({"text": leak}, TOOLS)["decision"] == "diagnose"
      and "text-leaked-call" in kinds(OP.realize({"text": leak}, TOOLS)))
recovered = OP.realize({"text": leak}, TOOLS, {"recover_leaked": True})
check("one named tool with parseable arguments is recovered when enabled",
      recovered["decision"] == "execute"
      and recovered["action"] == {"tool": "web.search", "args": {"q": "harness"}}, recovered)
ambiguous = OP.realize({"text": "use fs.read and web.search"}, TOOLS, {"recover_leaked": True})
check("two named tools are ambiguous, not a choice",
      "ambiguous-leak" in kinds(ambiguous), ambiguous)
unparseable = OP.realize({"text": "call fs.read with path a.txt"}, TOOLS, {"recover_leaked": True})
check("a prose call without a JSON object is not recovered",
      "unparseable-leak" in kinds(unparseable), unparseable)
check("output with neither a call nor a named tool is no-action",
      kinds(OP.realize({"text": "thinking"}, TOOLS)) == ["no-action"])

# ---- 2. Outcome Grounding ---------------------------------------------------
OBS = [{"id": "o1", "ok": True, "operation": "write"},
       {"id": "o2", "ok": False, "operation": "test"}]
grounded = OP.ground({"text": "done", "cites": ["o1"]}, OBS, required=["write"])
check("a claim citing a passing observation is supported",
      grounded["supported"] is True and grounded["findings"] == [], grounded)
check("a claim with no citation is ungrounded",
      "ungrounded-claim" in kinds(OP.ground({"text": "done"}, OBS)))
check("a citation of an unknown observation is reported",
      "unknown-evidence" in kinds(OP.ground({"cites": ["o9"]}, OBS)))
check("a claim resting on a failed observation is claimed-on-failure",
      "claimed-on-failure" in kinds(OP.ground({"cites": ["o2"]}, OBS)))
check("a required operation with no passing observation is missing-operation",
      "missing-operation" in kinds(OP.ground({"cites": ["o1"]}, OBS, required=["test"])))
check("a withheld claim says a report is not proof",
      OP.ground({"text": "done"}, OBS)["supported"] is False)

# ---- 3. Model-conditional affinity and routing ------------------------------
ROWS = []
for i in range(6):
    ROWS.append({"model": "m1", "harness": "default", "task": "t%d" % i, "ok": False})
    ROWS.append({"model": "m1", "harness": "A", "task": "t%d" % i, "ok": True})
    ROWS.append({"model": "m2", "harness": "default", "task": "t%d" % i, "ok": True})
    ROWS.append({"model": "m2", "harness": "A", "task": "t%d" % i, "ok": i < 3})
ROWS.append({"model": "m3", "harness": "default", "task": "x", "ok": True})
ROWS.append({"model": "m3", "harness": "B", "task": "y", "ok": True})
learned = OP.affinity(ROWS)
m1 = learned["models"]["m1"]["harnesses"]["A"]
check("m1: six discordant wins reach the 0.05 sign-test level",
      m1["wins"] == 6 and m1["losses"] == 0 and m1["p"] == 0.0312, m1)
check("m1: the paired delta is computed on the shared tasks only",
      m1["pairs"] == 6 and m1["delta"] == 1.0, m1)
m2 = learned["models"]["m2"]["harnesses"]["A"]
check("m2: the SAME harness loses on another model (model is the key)",
      m2["delta"] < 0 and m2["losses"] == 3, m2)
check("a harness with no shared task gets no estimate",
      learned["models"]["m3"]["harnesses"]["B"]["unmeasured"] is True)
routes = OP.route(["m1", "m2", "m3"], learned)
check("m1 is routed to the measured winner", routes["routes"]["m1"]["harness"] == "A",
      routes["routes"]["m1"])
check("m2 keeps the default because its measured delta is not positive",
      routes["routes"]["m2"]["harness"] == "default")
check("m3 keeps the default and says why",
      routes["routes"]["m3"]["harness"] == "default"
      and "unmeasured" in [f["kind"] for f in routes["routes"]["m3"]["findings"]])
loose = OP.affinity([{"model": "m", "harness": "default", "task": "a", "ok": True},
                     {"model": "m", "harness": "X", "task": "a", "ok": True},
                     {"model": "m", "harness": "default", "task": "b", "ok": True},
                     {"model": "m", "harness": "X", "task": "b", "ok": True}])
check("two tied tasks produce no proposal and no false significance",
      OP.route(["m"], loose)["routes"]["m"]["harness"] == "default"
      and "no-discordant-pairs" in [f["kind"] for f in
                                    OP.route(["m"], loose)["routes"]["m"]["findings"]])

# ---- 4. Plan-order reversal ------------------------------------------------
agree = EP.reversal({"p1": 10, "p2": 20}, {"c1": {"p1": 11, "p2": 21}})
check("a measured order that agrees with the declared one is identified",
      agree["identified"] is True and agree["reversals"] == [], agree)
flip = EP.reversal({"p1": 10, "p2": 20}, {"c1": {"p1": 25, "p2": 12}})
check("hidden state reverses the declared order in a cell",
      flip["identified"] is False and len(flip["reversals"]) == 1, flip)
check("the reversal names the cell and the pair",
      flip["reversals"][0]["cell"] == "c1" and flip["reversals"][0]["a"] == "p1")
check("no measurement is reported, not assumed",
      "no-measurement" in kinds(EP.reversal({"p1": 1, "p2": 2}, {})))
check("a measured plan with no declared cost is reported",
      "unpriced-plan" in kinds(EP.reversal({"p1": 1}, {"c1": {"p1": 1, "p9": 2}})))

# ---- 5. Confirmation gate ---------------------------------------------------
PANEL = [{"cell": "a", "candidate_s": 9.74, "incumbent_s": 14.06, "candidate_ok": True, "incumbent_ok": True},
         {"cell": "b", "candidate_s": 9.75, "incumbent_s": 14.27, "candidate_ok": True, "incumbent_ok": True},
         {"cell": "c", "candidate_s": 9.73, "incumbent_s": 13.42, "candidate_ok": True, "incumbent_ok": True}]
won = EP.confirm(PANEL, {"frozen_at": "2026-11-03", "selected_cells": ["z"]})
check("a frozen candidate that wins every pair replaces the incumbent",
      won["decision"] == "replace" and won["ratio"] < 0.75 and won["upper"] < 1.0, won)
check("the ratio matches the paired geometric mean",
      abs(won["ratio"] - 0.700) < 0.002, won["ratio"])
check("an unfrozen candidate can never replace the incumbent",
      EP.confirm(PANEL, {"selected_cells": ["z"]})["decision"] == "retain"
      and "unfrozen-candidate" in kinds(EP.confirm(PANEL, {"selected_cells": ["z"]})))
check("a panel cell used to select the candidate contaminates the verdict",
      EP.confirm(PANEL, {"frozen_at": "x", "selected_cells": ["a"]})["decision"] == "retain"
      and "contaminated-panel" in kinds(
          EP.confirm(PANEL, {"frozen_at": "x", "selected_cells": ["a"]})))
flat = [{"cell": "a", "candidate_s": 10.0, "incumbent_s": 10.0, "candidate_ok": True, "incumbent_ok": True},
        {"cell": "b", "candidate_s": 10.0, "incumbent_s": 10.0, "candidate_ok": True, "incumbent_ok": True}]
check("a flat panel does not separate the candidate",
      EP.confirm(flat, {"frozen_at": "x"})["decision"] == "retain")
failed = PANEL + [{"cell": "d", "candidate_s": 0, "incumbent_s": 0,
                   "candidate_ok": True, "incumbent_ok": False}]
mixed = EP.confirm(failed, {"frozen_at": "x"})
check("a failed delivery is counted, never priced as latency",
      mixed["decision"] == "replace" and mixed["pairs"] == 3
      and "delivery-failure" in kinds(mixed), mixed)
check("a single complete pair cannot authorize replacement",
      EP.confirm(PANEL[:1], {"frozen_at": "x"})["decision"] == "retain"
      and "no-panel" in kinds(EP.confirm(PANEL[:1], {"frozen_at": "x"})))

# ---- 6. Batching efficiency and acquisition cost ----------------------------
eff = EP.efficiency([{"label": "1/min", "batch": 1.0, "call_s": 2.5},
                     {"label": "40/min", "batch": 2.8, "call_s": 3.9}])
check("per-decision time is the call time divided by the batch",
      eff["rows"][1]["per_decision_s"] == 1.3929, eff["rows"][1])
check("a slower call that is a faster decision is reported as such",
      "slower-call-faster-decision" in kinds(eff), kinds(eff))
check("the acquisition break-even is ceil(acquisition / gain)",
      EP.amortize(100, 10)["break_even"] == 10)
check("a deployment below break-even is reported as unamortized",
      "unamortized" in kinds(EP.amortize(100, 10, tasks=5)))
check("a deployment above break-even carries no finding and a net gain",
      EP.amortize(100, 10, tasks=20)["findings"] == []
      and EP.amortize(100, 10, tasks=20)["net_s"] == 100.0)
check("no gain means no break-even",
      EP.amortize(100, 0)["break_even"] is None
      and "no-gain" in kinds(EP.amortize(100, 0)))

# ---- 7. Skill adapters: binding -------------------------------------------
SKILL = {"id": "pdf.extract", "procedure": ["read", "extract"]}
ADAPTERS = [
    {"id": "ad1", "skill": "pdf.extract", "when": {"preserve_layout": True},
     "changes": {"extract": "with_positions"}, "evidence": ["t1"]},
    {"id": "ad2", "skill": "other.skill", "when": {}, "changes": {}, "evidence": []},
    {"id": "ad3", "skill": "pdf.extract", "when": {"preserve_layout": True},
     "changes": {"check": "pagination"}, "evidence": ["t2"]},
]
bound = SA.bind(SKILL, ADAPTERS, {"preserve_layout": True})
check("two applicable adapters with disjoint changes are merged",
      bound["changes"] == {"check": "pagination", "extract": "with_positions"}
      and bound["adapters"] == ["ad1", "ad3"], bound)
check("an adapter bound to another skill is an orphan",
      "adapter-orphan" in kinds(bound))
unmet = SA.bind(SKILL, ADAPTERS, {"preserve_layout": False})
check("an unmet condition excludes the adapter and says so",
      unmet["changes"] == {} and "condition-unmet" in kinds(unmet), unmet)
conflict = SA.bind(SKILL, ADAPTERS + [
    {"id": "ad4", "skill": "pdf.extract", "when": {"preserve_layout": True},
     "changes": {"extract": "plain"}, "evidence": ["t3"]}], {"preserve_layout": True})
check("two applicable adapters editing one field are refused",
      conflict["changes"] == {} and "conflicting-adapters" in kinds(conflict), conflict)
noev = SA.bind(SKILL, [{"id": "ad5", "skill": "pdf.extract", "when": {},
                        "changes": {"x": 1}, "evidence": []}], {})
check("an adapter with no evidence still applies but is flagged",
      noev["changes"] == {"x": 1} and "no-evidence" in kinds(noev), noev)

# ---- 8. Skill adapters: re-check, expiry, maintenance -----------------------
PRE = [{"node": "n1", "skill": "pdf.extract", "adapter": "ad1", "assumed": {"preserve_layout": True}},
       {"node": "n2", "skill": "pdf.extract", "adapter": "ad1", "assumed": {"preserve_layout": False}},
       {"node": "n3", "skill": "pdf.extract", "adapter": "ad1", "requires": ["pdf_path"]},
       {"node": "n4", "skill": "pdf.extract", "adapter": "ad1"},
       {"node": "n5", "skill": "pdf.extract", "adapter": "ad1", "requires": ["legacy_pdf"]}]
re = SA.recheck(PRE, {"preserve_layout": False, "pdf_path": "a.pdf"})
check("a preload whose assumption still holds is kept",
      [r["node"] for r in re["keep"]] == ["n2", "n3"], re["keep"])
check("a preload whose assumed input changed is dropped as stale",
      [r["node"] for r in re["drop"]] == ["n1", "n4", "n5"]
      and "stale-preload" in kinds(re), re["drop"])
check("a preload whose required input never arrived is dropped",
      "input-unavailable" in kinds(re))
check("a preload with no recorded condition is unverifiable",
      "unverifiable-preload" in kinds(re))
exp = SA.expire([{"id": "e1", "last_supported": "2026-10-01"},
                 {"id": "e2", "last_supported": "2026-11-17"},
                 {"id": "e3"},
                 {"id": "e4", "last_supported": "yesterday"}], "2026-11-19", ttl_days=30)
check("evidence older than the TTL is retired",
      "e1" in exp["retire"] and "evidence-expired" in kinds(exp), exp)
check("recent evidence is kept", exp["keep"] == ["e2", "e4"], exp["keep"])
check("an adapter with no support record is retired, not renewed",
      "e3" in exp["retire"] and "no-evidence" in kinds(exp))
check("an unparseable date is reported and NOT expired",
      "e4" in exp["keep"] and "bad-date" in kinds(exp))
mnt = SA.maintain(
    [{"node": "n1", "skill": "s", "adapter": "a"},
     {"node": "n2", "skill": "s", "adapter": "a"},
     {"node": "n3", "skill": "s", "adapter": "a"},
     {"node": "n4", "skill": "s", "adapter": "a"}],
    [{"node": "n1", "skill": "s", "adapter": "a", "status": "ok"},
     {"node": "n2", "skill": "s", "adapter": "a", "status": "failed"},
     {"node": "n3", "skill": "s", "adapter": "a", "status": "input-changed"}])
check("a successful entry is reused", [r["node"] for r in mnt["reuse"]] == ["n1", "n4"],
      mnt["reuse"])
check("a failed entry is removed", [r["node"] for r in mnt["remove"]] == ["n2"])
check("an entry with new inputs is revalidated",
      [r["node"] for r in mnt["revalidate"]] == ["n3"])
check("an entry with no feedback is flagged, not silently trusted",
      "unconfirmed-entry" in kinds(mnt))

# ---- 9. Intake gate --------------------------------------------------------
POLICY = {"allowed": {"github": ["alice"], "slack": ["bob"]},
          "require_address": True, "shadow_unrequested": True}
check("an author outside the allow-list is ignored before any model call",
      IG.admit({"source": "github", "author": "mallory"}, POLICY)["decision"] == "ignore")
check("an allowed, addressed trigger is routed",
      IG.admit({"source": "github", "author": "alice", "addresses": "agent"},
               POLICY)["decision"] == "route")
check("an already answered trigger is ignored",
      IG.admit({"source": "github", "author": "alice", "addresses": "agent",
                "already_answered": True}, POLICY)["decision"] == "ignore")
shadowed = IG.admit({"source": "github", "author": "alice", "addresses": "team"}, POLICY)
check("allowed but unaddressed work starts in shadow mode",
      shadowed["decision"] == "shadow" and "unrequested-work" in kinds(shadowed), shadowed)
check("shadowing off turns unaddressed work into an ignore",
      IG.admit({"source": "github", "author": "alice", "addresses": "team"},
               {**POLICY, "shadow_unrequested": False})["decision"] == "ignore")
full = {"id": "T1", "requester": "alice", "rules": ["only repo X"],
        "scope": {"tools": ["fs.read"], "paths": ["x/"]}, "expires": "2026-12-01"}
check("a bounded, attributable, unexpired ticket is valid",
      IG.mandate(full, today="2026-11-19")["valid"] is True)
bad = IG.mandate({"id": "T2", "scope": {"tools": []}}, today="2026-11-19")
check("a ticket with no requester, rules or scope is rejected with every reason",
      bad["valid"] is False and {"missing-requester", "no-rules", "unbounded-scope"}
      <= set(kinds(bad)), kinds(bad))
check("an expired mandate is rejected",
      "expired" in kinds(IG.mandate(full, today="2026-12-02")))
sub = IG.subscribe([{"ticket": "T1", "kind": "comment"},
                    {"ticket": "T9", "kind": "comment"}], {"T1": "W1"})
check("an owned ticket reaches its worker directly",
      [r["ticket"] for r in sub["direct"]] == ["T1"])
check("an unowned event keeps the router hop and says so",
      [r["ticket"] for r in sub["via_router"]] == ["T9"]
      and "router-hop" in kinds(sub))
check("the router share is reported, not hidden", sub["router_share"] == 0.5, sub)
base = {"capabilities": ["ask", "plan", "webfetch", "shell"],
        "tools": [{"name": "web.fetch", "capabilities": ["webfetch"]}]}
worker = IG.preset(base, ["ask", "plan", "webfetch"])
check("the worker preset keeps only the unstripped capabilities",
      worker["capabilities"] == ["shell"], worker)
check("a stripped capability still reachable through a tool is a leak",
      "capability-leak" in kinds(worker), kinds(worker))
check("long shell commands are pushed to the background by default",
      worker["background_shell_s"] == 5)
rec = IG.shadow([{"id": "s1", "kind": "edit", "would": "rename x"}])
check("unconfirmed unrequested work only records",
      rec["mode"] == "record" and "no-confirmation" in kinds(rec), rec)
check("a confirmed result is worth speaking about",
      IG.shadow([{"id": "s1", "kind": "edit", "would": "rename x"}],
                confirmed=True)["mode"] == "speak")
check("an action the shadow never recorded is reported",
      "unrecorded-action" in kinds(IG.shadow([{"id": "s2", "recorded": False}])))

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
