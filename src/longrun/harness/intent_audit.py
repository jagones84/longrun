#!/usr/bin/env python3
"""Intent audit — least privilege for tool calls, with escalation only on flags.

Source: arXiv:2611.11305, "Least-Privilege Auditing of Agent Tool Calls with
Intent Graphs and Reasoning-Guided Escalation" (round 155). The user's objective
already determines most of what a legitimate run needs, so an intent DAG is
extracted once from the trusted objective and the static tool catalog, and every
call is checked against it with plain code (`intent_graph_audit_2611.11305.txt:60`,
`:156`).

  * **the graph is (V, E, Λ, Π, R)**: goals, precondition edges, authorized
    tools, scope predicates and the repeatable flag (`:158`).
  * **four checks decide a call**: frontier membership (UNKNOWN or OUT_OF_ORDER),
    scope predicates (SCOPE_VIOLATION), a simulated future violation, and taint
    (`:200`).
  * **local reads may bypass** because harm lies in the write or outward step;
    an external read such as a URL fetch must stay audited (`:227`, `:230`).
  * **the alignment score γ is not an identity signal**: adding it to a
    cross-session detector lowers splice detection by 4.7 points and drift by
    3.6, while the audit's own verdict detects hijack far better than behaviour
    (TPR 0.762 vs 0.072–0.121) (`:516`, `:537`).

  * `graph(record)` — validate the DAG and return its frontier.
  * `from_objective(objective, tools, effects)` — the trusted-objective producer:
    a catalog tool is authorized only when the objective names its namespace or
    a verb for its declared effect; reads and untyped tools stay authorized.
  * `scope(expr, params)` — the hardened expression language and its policy.
  * `policy(record)` — local read / external read / write / unclassified.
  * `audit(call, graph, state)` — Algorithm 1, with the read-only bypass.
  * `metrics(rows)` — ASR at the first and the harmful call, benign effects.
  * `coupling(record)` — why the score cannot strengthen identity detection.
  * `audit_record(record)` / `advise(profile)` — misreadings and mapping.

Pure: graphs, calls, states and outcome rows in; verdicts and rates out.
"""
from __future__ import annotations

import ast
import re

from longrun.harness import tool_policy

FORMAT = "longrun-intent-audit/1"

VERDICTS = ("ALLOW", "FLAG", "BLOCK")
FAILURE_TYPES = ("NONE", "UNKNOWN", "OUT_OF_ORDER", "SCOPE_VIOLATION",
                 "FUTURE_VIOLATION", "TAINT")
# ONE classifier: the shared module owns the verb lists and the argument roles.
# Kept as module aliases so existing callers keep resolving the names.
READ_VERBS = tool_policy.READ_VERBS
EFFECT_VERBS = tool_policy.EFFECT_VERBS
DESTINATION_HINTS = tool_policy.DESTINATION_HINTS
LOOKUP_FUNCS = {"all": all, "any": any, "len": len, "str": str,
                "isinstance": isinstance, "int": int, "float": float,
                "bool": bool, "lower": str.lower}
ALLOWED_NODES = (ast.Expression, ast.BoolOp, ast.UnaryOp, ast.BinOp,
                 ast.Compare, ast.Subscript, ast.IfExp, ast.List, ast.Tuple,
                 ast.Set, ast.ListComp, ast.SetComp, ast.GeneratorExp,
                 ast.Constant, ast.Name, ast.Call, ast.Attribute, ast.Load,
                 ast.Store, ast.And, ast.Or, ast.Not, ast.USub, ast.Add,
                 ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Eq, ast.NotEq,
                 ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is,
                 ast.IsNot, ast.comprehension)


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def graph(record):
    """Validate an intent DAG: unique goals, known edges, no cycles."""
    r = record or {}
    nodes = {}
    order = []
    for node in r.get("nodes") or []:
        n = node or {}
        nid = str(n.get("id") or "")
        if not nid:
            return {"format": FORMAT, "verdict": "node-without-id"}
        if nid in nodes:
            return {"format": FORMAT, "verdict": "duplicate-node"}
        nodes[nid] = {"tools": list(n.get("tools") or []),
                      "scope": n.get("scope"),
                      "repeatable": n.get("repeatable", True)}
        order.append(nid)
    if not nodes:
        return {"format": FORMAT, "verdict": "empty-graph"}
    preds = {nid: [] for nid in order}
    for edge in r.get("edges") or []:
        if not isinstance(edge, (list, tuple)) or len(edge) != 2:
            return {"format": FORMAT, "verdict": "bad-edge"}
        u, v = str(edge[0]), str(edge[1])
        if u not in nodes or v not in nodes:
            return {"format": FORMAT, "verdict": "unknown-edge"}
        preds[v].append(u)
    colour = {}
    def visit(nid, stack):
        colour[nid] = 1
        for p in preds[nid]:
            if colour.get(p) == 1:
                return True
            if colour.get(p) is None and visit(p, stack + [p]):
                return True
        colour[nid] = 2
        return False
    for nid in order:
        if colour.get(nid) is None and visit(nid, [nid]):
            return {"format": FORMAT, "verdict": "cycle"}
    satisfied = {str(s) for s in (r.get("satisfied") or [])}
    frontier = [nid for nid in order
                if all(p in satisfied for p in preds[nid])
                and (nodes[nid]["repeatable"] or nid not in satisfied)]
    return {"format": FORMAT, "nodes": nodes, "frontier": frontier,
            "preds": preds, "verdict": "valid"}


# The verbs an objective has to use before a declared mutating tool is in scope.
# Only declared effects are listed: an untyped tool cannot be proven harmful, so
# it stays authorized rather than being restricted from prose alone.
_EFFECT_SCOPE_VERBS = {
    "write": ("write", "edit", "create", "save", "modify", "update", "rename"),
    "append": ("append", "add", "store", "save", "remember"),
    "delete": ("delete", "remove", "rm", "purge", "forget", "drop"),
    "external": ("send", "run", "exec", "execute", "shell", "command",
                 "post", "upload", "fetch", "request", "dispatch", "deploy"),
}
_MUTATING_EFFECTS = tuple(_EFFECT_SCOPE_VERBS)


def from_objective(objective, tools, effects=None):
    """Build the intent node the trusted objective authorizes.

    Deterministic approximation of the paper's extraction (`:60`, `:158`).
    Untyped, `none` and `read` tools stay authorized: the catalog cannot prove
    what an untyped tool does, and a read is not the harmful step. A DECLARED
    mutating tool is authorized only when the objective names its namespace
    (`fs`) or uses a verb for its effect (`write`/`edit`, `delete`/`remove`,
    `send`/`run`). An objective that names neither a namespace nor any such
    verb authorizes everything, so generic prose never invents a restriction.
    """
    names = sorted({str(t) for t in (tools or []) if t})
    effects = effects or {}
    words = set(re.findall(r"[a-z0-9]+", str(objective or "").lower()))
    namespaces = {n.split(".", 1)[0] for n in names}
    named = namespaces & words
    any_verb = any(v in words for vs in _EFFECT_SCOPE_VERBS.values() for v in vs)
    authorized = []
    for name in names:
        effect = (effects.get(name) or {}).get("effect")
        if effect not in _MUTATING_EFFECTS:
            authorized.append(name)
            continue
        if not named and not any_verb:
            authorized.append(name)
            continue
        if name.split(".", 1)[0] in named:
            authorized.append(name)
            continue
        if any(v in words for v in _EFFECT_SCOPE_VERBS.get(effect, ())):
            authorized.append(name)
    if not authorized:
        authorized = names
    return {"nodes": [{"id": "objective", "tools": authorized,
                       "scope": None, "repeatable": True}],
            "edges": [], "satisfied": []}


def scope(expr, params, policy="fail-closed"):
    """Evaluate a scope predicate; a broken expression follows the policy."""
    text = str(expr or "").strip()
    if not text:
        return {"format": FORMAT, "ok": True, "verdict": "unconstrained"}
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return {"format": FORMAT, "ok": False, "verdict": "scope-error",
                "decision": "allow" if policy == "fail-open" else "fail-closed"}
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            return {"format": FORMAT, "ok": False, "verdict": "scope-rejected",
                    "node": type(node).__name__}
        if isinstance(node, ast.Attribute) and str(node.attr).startswith("_"):
            return {"format": FORMAT, "ok": False, "verdict": "scope-rejected",
                    "node": "private-attribute"}
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in LOOKUP_FUNCS:
                return {"format": FORMAT, "ok": False, "verdict": "scope-rejected",
                        "node": "function"}
    env = {"__builtins__": {}}
    env.update(LOOKUP_FUNCS)
    env.update(params or {})
    try:
        value = eval(compile(tree, "<scope>", "eval"), env)  # noqa: S307
    except Exception:
        return {"format": FORMAT, "ok": False, "verdict": "scope-error",
                "decision": "allow" if policy == "fail-open" else "fail-closed"}
    return {"format": FORMAT, "ok": bool(value), "verdict": "scope-evaluated"}


def policy(record):
    """Classify a tool from its schema: local read, external read or write."""
    p = tool_policy.classify(record or {})
    return {"format": FORMAT, "kind": p["kind"], "roles": p["roles"],
            "bypass_allowed": p["kind"] == "local-read",
            "verdict": p["verdict"]}


def _tainted(call, state):
    s = state if isinstance(state, dict) else {}
    values = [str(v).lower() for v in s.get("tainted") or [] if v]
    if s.get("untrusted") is True:
        return True
    if not values:
        return False
    for value in (call or {}).get("params", {}).values():
        text = str(value).lower()
        if any(t in text for t in values):
            return True
    return False


def audit(call, intent, state=None, bypass=False, severity=None, threshold=0.99,
          scope_policy="fail-closed"):
    """Algorithm 1: frontier, scopes, future violation, taint, then dispatch."""
    c = call or {}
    g = intent or {}
    if g.get("verdict") != "valid":
        g = graph(g)
    if g.get("verdict") != "valid":
        return {"format": FORMAT, "verdict": "invalid-graph"}
    tool = str(c.get("tool") or "")
    nodes = g.get("nodes") or {}
    by_tool = {nid for nid, node in nodes.items() if tool in node["tools"]}
    if bypass and severity is None:
        kind = str(c.get("kind") or "")
        if not kind:
            p = policy({"name": tool, "description": c.get("description") or "",
                        "args": c.get("schema") or c.get("args") or []})
            kind = p["kind"]
        if kind == "local-read":
            return {"format": FORMAT, "verdict": "ALLOW", "type": "NONE",
                    "confidence": 1.0, "gamma": 1.0, "bypassed": True}
    frontier = set(g.get("frontier") or [])
    candidates = [nid for nid in (g.get("frontier") or []) if nid in by_tool]
    if not candidates:
        if not by_tool:
            return {"format": FORMAT, "verdict": "BLOCK", "type": "UNKNOWN",
                    "confidence": 0.95, "gamma": 0.0}
        return {"format": FORMAT, "verdict": "BLOCK", "type": "OUT_OF_ORDER",
                "confidence": 0.95, "gamma": 0.0}
    scoped = []
    failed = 0
    for nid in candidates:
        expr = nodes[nid].get("scope")
        if expr is None:
            scoped.append(nid)
            continue
        result = scope(expr, c.get("params") or {}, scope_policy)
        if result.get("ok") is True:
            scoped.append(nid)
        else:
            failed += 1
    if not scoped:
        return {"format": FORMAT, "verdict": "FLAG", "type": "SCOPE_VIOLATION",
                "confidence": 0.80, "gamma": 0.2}
    first = scoped[0]
    score = _num((severity or {}).get(first)) if severity else None
    if score is not None and score >= threshold:
        return {"format": FORMAT, "verdict": "BLOCK",
                "type": "FUTURE_VIOLATION", "confidence": 0.85, "gamma": 0.0}
    if _tainted(c, state):
        return {"format": FORMAT, "verdict": "FLAG", "type": "TAINT",
                "confidence": 0.75, "gamma": 0.2}
    gamma = 0.6 if failed else 1.0
    return {"format": FORMAT, "verdict": "ALLOW", "type": "NONE",
            "confidence": 1.0, "gamma": gamma, "node": first}


def metrics(rows):
    """ASR at the first and the harmful call, plus the benign-side costs."""
    attacked = compromised = first_hit = harmful_hit = 0
    benign = benign_flagged = benign_blocked = 0
    calls = flagged_calls = 0
    for row in rows or []:
        r = row or {}
        if r.get("attacked") is True:
            attacked += 1
            if r.get("compromised") is True:
                compromised += 1
                if r.get("flagged_first") is not True:
                    first_hit += 1
                if r.get("harmful") is True and r.get("flagged_harmful") is not True:
                    harmful_hit += 1
        if r.get("benign") is True:
            benign += 1
            calls += int(_num(r.get("calls")) or 1)
            flagged_calls += int(_num(r.get("flagged_calls")) or 0)
            if r.get("flagged") is True:
                benign_flagged += 1
            if r.get("blocked") is True:
                benign_blocked += 1
    return {"format": FORMAT, "attacked": attacked, "compromised": compromised,
            "asr_first": (first_hit / compromised) if compromised else None,
            "asr_harmful": (harmful_hit / compromised) if compromised else None,
            "benign_tasks": benign,
            "benign_flagged_tasks": (benign_flagged / benign) if benign else None,
            "benign_blocked_tasks": (benign_blocked / benign) if benign else None,
            "benign_flagged_calls": (flagged_calls / calls) if calls else None,
            "verdict": "measured"}


def coupling(record):
    """Does γ strengthen an identity-drift detector? The paper says no."""
    r = record or {}
    splice = _num(r.get("splice_delta"))
    drift = _num(r.get("drift_delta"))
    hijack = _num(r.get("hijack_delta"))
    audit_tpr = _num(r.get("audit_tpr"))
    behavioural = _num(r.get("behavioural_tpr"))
    if splice is None or drift is None:
        return {"format": FORMAT, "verdict": "insufficient-input"}
    worsens = splice < 0 and drift < 0
    verdict = "coupling-fails" if worsens else "coupling-helps"
    if audit_tpr is not None and behavioural is not None and audit_tpr > behavioural:
        verdict = "verdict-dominates-behaviour"
    return {"format": FORMAT, "splice_delta": splice, "drift_delta": drift,
            "hijack_delta": hijack, "verdict": verdict}


def audit_record(record):
    """The misreadings the paper's evaluation protocol excludes."""
    r = record or {}
    findings = []
    if r.get("policy_calibrated_with_attack_labels") is True:
        findings.append({"kind": "label-informed-calibration",
                         "why": "the policy must be built without attack labels"})
    if r.get("session_tool_list_given_to_extractor") is True:
        findings.append({"kind": "session-derived-tool-list",
                         "why": "the extractor sees the objective and the catalog only"})
    if r.get("replay_read_as_live") is True:
        findings.append({"kind": "replay-read-as-live",
                         "why": "replay assumes no re-planning and overstates security"})
    if r.get("read_bypass_extended_to_external") is True:
        findings.append({"kind": "read-bypass-extended-to-external",
                         "why": "a URL fetch can exfiltrate; it stays audited"})
    if r.get("guardian_sees_tool_outputs") is True:
        findings.append({"kind": "guardian-sees-tool-outputs",
                         "why": "injected text would reach the reviewer"})
    if r.get("alignment_score_as_identity_signal") is True:
        findings.append({"kind": "alignment-score-as-identity-signal",
                         "why": "the score is about the call, not about who asks"})
    if not findings:
        findings.append({"kind": "audit-conditions-met"})
    return {"format": FORMAT, "findings": findings, "verdict": "audit-complete"}


def advise(profile):
    """Map a harness profile onto the least-privilege gaps the paper names."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("extracts_the_plan_before_reading", "plans_after_tool_outputs",
         "an injected instruction must not enlarge the plan"),
        ("checks_every_call_against_the_plan", "trusts_tool_descriptions",
         "descriptions say what a tool can do, not whether it is in scope"),
        ("keeps_external_reads_audited", "bypasses_all_reads",
         "a URL fetch can carry data out"),
        ("escalates_only_flagged_calls", "asks_a_model_about_every_call",
         "the deterministic path is microseconds; the model is seconds"),
        ("keeps_the_guardian_blind_to_outputs", "shows_outputs_to_the_reviewer",
         "the reviewer would read the attacker's text"),
        ("measures_benign_flagging_beside_asr", "reports_asr_only",
         "a block that costs the task is part of the trade-off"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
