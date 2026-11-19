#!/usr/bin/env python3
"""v1224 — intent audit, write integrity, context regime (round 155).

Sources:
  * arXiv:2611.11305 — the intent DAG, the four checks, the read-only bypass, the
    guardian boundary and the rejected identity coupling.
  * arXiv:2611.17115 — the schema-derived policy, exact request grounding, the
    committed-write prefix, the Mediator's checks and the ablations.
  * arXiv:2611.05306 — FHA/EoCC/SAC, the execution-brief recap, selective reads,
    the context-factor price model and the single-action collapse.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1224_intent_write_context.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1224-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import intent_audit as IA  # noqa: E402
from longrun.harness.checks import write_integrity as WI  # noqa: E402
from longrun.harness.checks import context_regime as CR  # noqa: E402
from longrun.tools import registry as REG            # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. least-privilege intent audit (arXiv:2611.11305) ---------------
GRAPH = {
    "nodes": [
        {"id": "n1", "tools": ["search_emails", "get_event"]},
        {"id": "n2", "tools": ["send_email"],
         "scope": "recipient in ['bob@x.com']"},
    ],
    "edges": [["n1", "n2"]],
}
G = IA.graph(GRAPH)
check("the intent graph is valid", G["verdict"] == "valid")
check("only the root is on the frontier", G["frontier"] == ["n1"])
check("a duplicate node is refused",
      IA.graph({"nodes": [{"id": "a"}, {"id": "a"}]})["verdict"] == "duplicate-node")
check("an unknown edge is refused",
      IA.graph({"nodes": [{"id": "a"}], "edges": [["a", "b"]]})["verdict"]
      == "unknown-edge")
check("a cycle is refused",
      IA.graph({"nodes": [{"id": "a"}, {"id": "b"}],
                "edges": [["a", "b"], ["b", "a"]]})["verdict"] == "cycle")
check("an empty graph is refused", IA.graph({})["verdict"] == "empty-graph")
A1 = IA.audit({"tool": "search_emails", "params": {}}, G)
check("a planned read is allowed", A1["verdict"] == "ALLOW")
check("an allow carries the full alignment score", close(A1["gamma"], 1.0))
A2 = IA.audit({"tool": "send_email", "params": {"recipient": "bob@x.com"}}, G)
check("a call before its precondition is out of order",
      A2["type"] == "OUT_OF_ORDER" and A2["verdict"] == "BLOCK")
A3 = IA.audit({"tool": "send_email", "params": {"recipient": "bob@x.com"}},
              IA.graph(dict(GRAPH, satisfied=["n1"])))
check("an ordered call in scope is allowed", A3["verdict"] == "ALLOW")
A4 = IA.audit({"tool": "send_email", "params": {"recipient": "evil@x.com"}},
              IA.graph(dict(GRAPH, satisfied=["n1"])))
check("an out-of-scope recipient is flagged", A4["type"] == "SCOPE_VIOLATION")
check("a scope flag carries gamma 0.2", close(A4["gamma"], 0.2))
A5 = IA.audit({"tool": "wire_money", "params": {}}, G)
check("an unplanned tool is blocked as unknown", A5["type"] == "UNKNOWN")
check("an unknown tool blocks at 0.95", close(A5["confidence"], 0.95))
check("scope evaluates a simple predicate",
      IA.scope("len(recipients) > 0", {"recipients": ["a"]})["ok"] is True)
check("scope rejects a private attribute",
      IA.scope("x.__class__", {"x": 1})["verdict"] == "scope-rejected")
check("scope rejects an imported function",
      IA.scope("__import__('os').getcwd()", {})["verdict"] == "scope-rejected")
check("scope errors follow fail-closed",
      IA.scope("1/0", {})["verdict"] == "scope-error")
check("scope can fail open when configured",
      IA.scope("1/0", {}, policy="fail-open")["decision"] == "allow")
P1 = IA.policy({"name": "get_channels", "description": "get channels"})
check("a local read is classified", P1["kind"] == "local-read")
check("a local read may bypass", P1["bypass_allowed"] is True)
P2 = IA.policy({"name": "get_webpage", "description": "fetch a page at a url",
                "args": [{"name": "url", "type": "string"}]})
check("an external read is classified", P2["kind"] == "external-read")
check("an external read may not bypass", P2["bypass_allowed"] is False)
check("a write is classified",
      IA.policy({"name": "send_email", "description": "send an email"})["kind"]
      == "write")
check("an unknown verb is unclassified",
      IA.policy({"name": "frobnicate", "description": "do the thing"})["kind"]
      == "unclassified")
check("a local read bypasses the audit",
      IA.audit({"tool": "get_channels", "kind": "local-read"}, G,
               bypass=True)["bypassed"] is True)
check("a bypassed external read is not allowed",
      IA.audit({"tool": "get_webpage", "kind": "external-read",
                "params": {}}, G, bypass=True)["verdict"] == "BLOCK")
A6 = IA.audit({"tool": "search_emails", "params": {"q": "evil.com"}}, G,
              state={"tainted": ["evil.com"]})
check("a tainted call is flagged", A6["type"] == "TAINT")
check("taint keeps the call authorized", A6["verdict"] == "FLAG")
A7 = IA.audit({"tool": "send_email", "params": {"recipient": "bob@x.com"}},
              IA.graph(dict(GRAPH, satisfied=["n1"])),
              severity={"n2": 0.995})
check("a simulated future violation blocks", A7["type"] == "FUTURE_VIOLATION")
check("the severity threshold is 0.99", close(0.995 >= 0.99, 1.0))

# ---- 1b. the objective-scoped producer the app now runs --------------------
# `from_objective` is the trusted-objective producer: a declared mutating tool
# is authorized only by a namespace/verb the objective names; reads and untyped
# tools stay authorized; generic prose authorizes everything.
TOOLS = ["fs.read", "fs.write", "shell.exec", "agent.delete", "web.search",
         "sessions.send", "todo.update"]
EFFECTS = {"fs.read": {"effect": "read", "reads": ["file"]},
           "fs.write": {"effect": "write", "idempotent": False},
           "shell.exec": {"effect": "external", "idempotent": False},
           "agent.delete": {"effect": "delete", "idempotent": False},
           "web.search": {"effect": "read", "reads": ["network"]},
           "sessions.send": {"effect": "external", "idempotent": False}}


def _authorized(objective):
    g = IA.graph(IA.from_objective(objective, TOOLS, EFFECTS))
    return g, g["nodes"]["objective"]["tools"]


OG, _ok = _authorized("edit the report")
check("the objective producer yields a valid graph", OG["verdict"] == "valid", OG)
check("a write verb authorizes the declared write", "fs.write" in _ok, _ok)
check("an unmentioned external tool is withheld", "shell.exec" not in _ok, _ok)
check("the unmentioned delete tool is withheld", "agent.delete" not in _ok, _ok)
check("a declared read stays authorized", "fs.read" in _ok, _ok)
check("an untyped control tool stays authorized", "todo.update" in _ok, _ok)
_, _ok = _authorized("delete the stale logs")
check("the delete verb authorizes a destructive tool", "agent.delete" in _ok, _ok)
_, _ok = _authorized("fix the failing test")
check("generic prose authorizes every tool rather than inventing a restriction",
      set(_ok) == set(TOOLS), _ok)
_, _ok = _authorized("audit the fs tree")
check("a named namespace authorizes all of its tools", "fs.write" in _ok, _ok)

_og, _ = _authorized("edit the report")
A8 = IA.audit({"tool": "shell.exec", "params": {"command": "ls"}, "kind": "write"},
              _og, bypass=True)
check("a mutating call outside the objective is blocked as unknown",
      A8["verdict"] == "BLOCK" and A8["type"] == "UNKNOWN", A8)
A9 = IA.audit({"tool": "fs.write", "params": {"path": "a"}, "kind": "write"},
              _og, bypass=True)
check("a mutating call the objective authorized passes", A9["verdict"] == "ALLOW", A9)
A10 = IA.audit({"tool": "fs.write", "params": {"path": "a"}, "kind": "write"},
               _og, state={"untrusted": True}, bypass=True)
check("a boolean untrusted state flags a write", A10["type"] == "TAINT", A10)

M = IA.metrics([
    {"attacked": True, "compromised": True, "flagged_first": False,
     "harmful": True, "flagged_harmful": False},
    {"attacked": True, "compromised": True, "flagged_first": True,
     "harmful": True, "flagged_harmful": True},
    {"attacked": True, "compromised": True, "flagged_first": True,
     "harmful": False, "flagged_harmful": False},
    {"attacked": True, "compromised": True, "flagged_first": True,
     "harmful": False, "flagged_harmful": False},
    {"benign": True, "calls": 10, "flagged_calls": 2, "flagged": True,
     "blocked": False},
    {"benign": True, "calls": 10, "flagged_calls": 0, "flagged": True,
     "blocked": True},
    {"benign": True, "calls": 10, "flagged_calls": 0, "flagged": False,
     "blocked": False},
])
check("ASR at the first call is measured", close(M["asr_first"], 0.25))
check("ASR at the harmful call is measured", close(M["asr_harmful"], 0.25))
check("benign flagged tasks are measured", close(M["benign_flagged_tasks"], 2 / 3))
check("benign blocked tasks are measured", close(M["benign_blocked_tasks"], 1 / 3))
check("benign flagged calls are measured", close(M["benign_flagged_calls"], 2 / 30))
CP = IA.coupling({"splice_delta": -0.047, "drift_delta": -0.036,
                  "hijack_delta": 0.049, "audit_tpr": 0.762,
                  "behavioural_tpr": 0.12})
check("the alignment score does not help identity detection",
      CP["verdict"] == "verdict-dominates-behaviour")
check("the coupling verdict names the failure",
      IA.coupling({"splice_delta": -0.047, "drift_delta": -0.036})["verdict"]
      == "coupling-fails")
check("the intent audit names its misreadings",
      set(kinds(IA.audit_record({"replay_read_as_live": True,
                                 "read_bypass_extended_to_external": True})))
      == {"replay-read-as-live", "read-bypass-extended-to-external"})
check("the intent advice lists six habits", len(IA.advise({})["findings"]) == 6)

# ---- 2. write integrity (arXiv:2611.17115) ----------------------------
check("a read tool is classified from its name",
      WI.policy({"name": "get_most_recent_transactions",
                 "description": "get recent"})["kind"] == "read")
check("a write tool is classified from its name",
      WI.policy({"name": "send_money", "description": "send money"})["kind"]
      == "write")
check("an unclassified tool is denied",
      WI.policy({"name": "frobnicate"})["denied"] is True)
WP = WI.policy({"name": "send_email", "description": "send an email",
                "args": [{"name": "recipient"}, {"name": "body"},
                         {"name": "date"}, {"name": "mode", "type": "enum",
                                            "enum": ["fast", "slow"]}]})
check("recipients are authority fields", WP["roles"]["recipient"] == "authority")
check("the body is a payload field", WP["roles"]["body"] == "payload")
check("a date is temporal", WP["roles"]["date"] == "temporal")
check("an enum is control", WP["roles"]["mode"] == "control")
GQ = WI.grounding("Send 100 to bob@x.com on 2026-11-20 from www.example.com")
check("the grounding set catches the email", "bob@x.com" in GQ["values"])
check("the grounding set catches the number", "100" in GQ["values"])
check("the grounding set strips the URL scheme", "www.example.com" in GQ["values"])
check("exact grounding admits a stated value", WI.grounded("100", GQ) is True)
check("a substring of a value is not grounded", WI.grounded("1", GQ) is False)
check("an unstated recipient asks for confirmation",
      WI.mediate({"tool": {"name": "send_email",
                           "description": "send an email",
                           "args": [{"name": "recipient"}]},
                  "params": {"recipient": "evil@x.com"}}, GQ)["decision"]
      == "ask")
MED = WI.mediate({"tool": {"name": "send_email",
                           "description": "send an email",
                           "args": [{"name": "recipient"},
                                    {"name": "amount"},
                                    {"name": "body", "payload": True}]},
                  "params": {"recipient": "bob@x.com", "amount": 100,
                             "body": "anything at all"}}, GQ)
check("a grounded write executes", MED["decision"] == "execute")
check("the payload is not grounding-checked", MED["verdict"] == "admitted")
check("a placeholder denies",
      WI.mediate({"tool": {"name": "send_email"}, "params": {"to": "$event_id"}},
                 GQ)["reason"] == "placeholder")
check("an unclassified tool denies",
      WI.mediate({"tool": {"name": "frobnicate"}, "params": {}}, GQ)["reason"]
      == "unclassified-tool")
READ = WI.mediate({"tool": {"name": "get_webpage",
                            "description": "fetch a page at a url",
                            "args": [{"name": "url"}]},
                   "params": {"url": "www.example.com"}}, GQ)
check("a grounded destination executes", READ["decision"] == "execute")
BAD = WI.mediate({"tool": {"name": "get_webpage",
                           "description": "fetch a page at a url",
                           "args": [{"name": "url"}]},
                  "params": {"url": "www.attacker.com"}}, GQ)
check("an ungrounded destination denies", BAD["reason"] == "ungrounded-destination")
check("a missing required argument denies",
      WI.mediate({"tool": {"name": "send_email",
                           "description": "send an email"},
                  "params": {"recipient": "bob@x.com"}}, GQ,
                 schema=["recipient", "amount"])["reason"] == "schema")
check("an out-of-enum control denies",
      WI.mediate({"tool": {"name": "send_email", "description": "send an email",
                           "args": [{"name": "mode", "type": "enum",
                                     "enum": ["fast"]}]},
                  "params": {"mode": "slow"}}, GQ)["reason"] == "control-value")

# ---- 2b. ONE schema normalizer, ONE classifier -----------------------------
# The registry bridge turns a live spec into the record both checkers read, and
# the shared classifier owns the verb lists, so the two cannot disagree.
REC_W = REG.tool_record("fs.write")
check("the registry normalizer exposes the flat argument list",
      REC_W["name"] == "fs.write"
      and {"path", "content"} <= {a["name"] for a in REC_W["args"]}
      and REC_W["required"] == ["path", "content"], REC_W)
REC_R = REG.tool_record("fs.read")
check("both checkers classify a live write the same way",
      IA.policy(REC_W)["kind"] == "write" and WI.policy(REC_W)["kind"] == "write")
check("both checkers classify a live read the same way",
      IA.policy(REC_R)["kind"] == "local-read"
      and WI.policy(REC_R)["kind"] == "read")
check("the verb lists are shared objects, so they cannot drift",
      IA.READ_VERBS is WI.READ_VERBS and IA.EFFECT_VERBS is WI.EFFECT_VERBS)
check("the merged lists carry both modules' verbs",
      "download" in IA.READ_VERBS and "invite" in WI.EFFECT_VERBS)
check("a dotted live tool is classified, not left unclassified",
      IA.policy(REC_R)["kind"] == "local-read"
      and WI.policy(REC_R)["denied"] is False)
REAL = WI.mediate({"tool": REC_W, "params": {"path": "a.py", "content": "x"}},
                  WI.grounding('write "a.py"'))
check("mediate classifies a live registry record instead of denying it",
      REAL["decision"] == "execute", REAL)
ASK = WI.mediate({"tool": REC_W,
                  "params": {"path": "elsewhere.py", "content": "x"}},
                 WI.grounding('write "a.py"'))
check("an ungrounded authority argument still asks",
      ASK["decision"] == "ask" and ASK["argument"] == "path", ASK)

PLAN = WI.commit({"calls": [
    {"tool": {"name": "send_email", "description": "send an email"},
     "params": {"recipient": "bob@x.com"}},
    {"tool": {"name": "get_events", "description": "get events"}, "params": {}},
    {"tool": {"name": "update_password", "description": "update the password"},
     "params": {"password": "x"}},
]})
check("the plan commits its writes", PLAN["count"] == 2)
check("the plan is fixed before reading", PLAN["fixed"] is True)
check("a plan over ten calls is refused",
      WI.commit({"calls": [{}] * 11})["verdict"] == "too-many-calls")
check("appending a write is refused", WI.append(PLAN, {})["appended"] is False)
CLEAN = WI.integrity({"committed": PLAN["writes"],
                      "executed": PLAN["writes"],
                      "ground": WI.grounding("bob@x.com x 100")})
check("a matching trace is clean", CLEAN["verdict"] == "trace-clean")
DIRTY = WI.integrity({"committed": PLAN["writes"][:1],
                      "executed": PLAN["writes"],
                      "ground": GQ})
check("an extra write is a violation", DIRTY["violations"][0]["kind"]
      == "uncommitted-write")
AB = WI.ablate({"base": {"episodes": 7432},
                "variants": {
                    "mediator": {"attacks": 106, "bu": 31.2, "ua": 29.6},
                    "commitment": {"attacks": 53, "bu": 27.7, "ua": 27.0},
                    "binder": {"attacks": 0, "bu": 23.6, "ua": 24.5},
                    "reporter": {"attacks": 0, "bu": 12.5, "ua": 11.0}}})
check("the Mediator is the load-bearing component", AB["load_bearing"] == "mediator")
check("the Mediator ablation ASR is 106 over 7,432",
      close(AB["variants"]["mediator"]["asr"], 106 / 7432))
check("removing the reporter halves utility",
      close(12.5 / 25.6, 0.48828125))
check("the write audit names its misreadings",
      set(kinds(WI.audit_record({"model_written_policy": True,
                                 "substring_grounding": True})))
      == {"model-written-policy", "substring-grounding"})
check("the write advice lists six habits", len(WI.advise({})["findings"]) == 6)

# ---- 3. context regime (arXiv:2611.05306) -----------------------------
L = CR.length({"stretches": [8000, 9000, 7000]})
check("the total sums the stretches", close(L["total_k"], 24.0))
check("the peak is the largest stretch", close(L["peak_k"], 9.0))
check("a 9K peak is a short context", L["kind"] == "short")
check("a 300K peak is a long context",
      CR.length({"stretches": [300000]})["kind"] == "long")
CH16 = CR.charge({"w": 16000, "w_max": 200000, "standard_price": 25})
check("16K is priced at the floor", close(CH16["output"], 5.0))
check("the input price is one fifth", close(CH16["input"], 1.0))
check("the cached price is one tenth of input", close(CH16["cached"], 0.1))
check("16K has no ratio penalty", close(CH16["ratio_vs_16k"], 1.0))
CH256 = CR.charge({"w": 256000, "w_max": 200000, "standard_price": 25})
check("a clamped full window is priced at standard", close(CH256["output"], 25.0))
check("the longest window costs five times 16K", close(CH256["ratio_vs_16k"], 5.0))
CH100 = CR.charge({"w": 100000, "w_max": 200000, "standard_price": 25})
check("an intermediate window interpolates", close(CH100["output"], 14.1304347826, 1e-6))
SV = CR.savings({"long_cost": 420.0, "short_cost": 62.53})
check("the optimized saving is a ratio", close(SV["saving"], 6.7167759, 1e-6))
BRIEF = CR.compaction({"text": "objective facts changes verification dead_ends plan",
                       "task_verbatim": True, "completion_criterion": True})
check("a six-section recap is an execution brief",
      BRIEF["verdict"] == "execution-brief")
check("a brief scores one", close(BRIEF["score"], 1.0))
NARR = CR.compaction({"text": "we worked on the task and made progress",
                      "narrative": True})
check("a narrative summary is named", NARR["verdict"] == "narrative-summary")
REG = CR.regimes({"rows": [
    {"regime": "FHA", "accuracy": 70.0, "peak_k": 32, "cost": 420},
    {"regime": "EOCC", "accuracy": 74.8, "peak_k": 19, "cost": 130.2},
    {"regime": "SAC", "accuracy": 70.2, "peak_k": 8, "cost": 62.5},
]})
check("EoCC gains 4.8 points here", close(REG["deltas"]["EOCC"], 4.8))
check("SAC is within 0.2 points", close(REG["deltas"]["SAC"], 0.2))
check("short-context parity holds", REG["parity"] is True)
check("the best regime is EoCC", REG["best"]["regime"] == "EOCC")
SEL = CR.selective({"reads": [6000, 8000, 12000], "cap": 8000,
                    "search_before_read": True,
                    "growth": [[100000, 20000], [1000000, 30000]]})
check("a read over the cap is counted", SEL["over_cap"] == 1)
check("conversation growth is bounded", close(SEL["slope"], 0.1760912591, 1e-6))
check("the selective verdict names the cap breach", SEL["verdict"] == "read-over-cap")
BOUND = CR.selective({"reads": [6000], "growth": [[100000, 20000],
                                                  [1000000, 30000]]})
check("a bounded reading plan is accepted", BOUND["verdict"] == "bounded")
SAC = CR.sac({"actions_per_context": 1, "accuracy_fha": 70.0,
              "accuracy_sac": 70.2, "peak_k": 8})
check("single-action parity holds", SAC["verdict"] == "single-action-parity")
check("single-action compaction keeps the accuracy", close(SAC["delta"], 0.2))
COL = CR.sac({"actions_per_context": 1, "accuracy_fha": 53.0,
              "accuracy_sac": 3.6, "peak_k": 12})
check("a verbose model can collapse", COL["verdict"] == "collapse")
check("a lossy recap without a store loses information",
      CR.history({"lossy": True})["verdict"] == "information-lost")
check("a stored history makes it recoverable",
      CR.history({"lossy": True, "full_history_stored": True,
                  "retrievable": True})["verdict"] == "recoverable-by-retrieval")
check("the context audit names its misreadings",
      set(kinds(CR.audit_record({"compaction_is_summarisation": True,
                                 "peak_read_as_total": True})))
      == {"compaction-is-summarisation", "peak-read-as-total"})
check("the context advice lists six habits", len(CR.advise({})["findings"]) == 6)

# ---- verdict ----------------------------------------------------------
TOTAL = len(RESULTS)
PASSED = sum(RESULTS)
print("\n%d/%d checks passed" % (PASSED, TOTAL))
sys.exit(0 if PASSED == TOTAL else 1)
