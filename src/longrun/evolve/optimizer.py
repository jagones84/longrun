"""Local harness optimizer — reads session traces and proposes registry/gate changes (S1).

An Agentron-style local optimizer (HarnessNet, arXiv:2610.15221 §3.1): a coding agent
constrained to a single agent's org scope that reads execution traces after every session
and produces structured proposals targeting the tool registry or gate tables.

The optimizer is ADDITIVE — it reads existing ledgers (runmetrics, jobcost, policy_hits)
and writes proposals. It never modifies the harness directly. Proposals go through the
existing human review gate (approval pipeline).

Scope-gated by the existing `coordinator_scope()` — the optimizer can only propose changes
within its agent's org subtree.

Triggered by a post-session hook in `agent/agent.py` (MEMORY_POLICY area). The hook is
fail-safe: a failure here logs and continues, never breaking the session.
"""
import json
import os
import time

from longrun.util import paths

OPTIMIZER_LOG = os.environ.get("LONGRUN_OPTIMIZER_LOG") or os.path.join(
    paths.DATA_DIR, "optimizer_runs.jsonl")

# Minimum session activity to trigger the optimizer: at least one tool call.
MIN_TOOL_CALLS = 1


def _read_trace(sid):
    """Read the session trace from runmetrics. Returns {} on any failure."""
    try:
        from longrun.model import runmetrics as _rm
        return _rm.get(sid) or {}
    except Exception:  # noqa: BLE001 — read-only, must never fail the session
        return {}


def _read_policy_hits():
    """Read the policy hits ledger. Returns {} on any failure."""
    try:
        from longrun.tools import registry as _reg
        return _reg.policy_report() or {}
    except Exception:  # noqa: BLE001
        return {}


def _read_job_cost(jid):
    """Read per-job cost aggregate. Returns {} on any failure."""
    if not jid:
        return {}
    try:
        from longrun.orchestrate import jobcost as _jc
        return _jc.aggregate(jid) or {}
    except Exception:  # noqa: BLE001
        return {}


def _read_feedback(sid):
    """Read per-agent feedback record (from S2 backward propagation). Returns {} on any failure."""
    try:
        from longrun.orchestrate import jobcost as _jc
        return _jc.feedback_for(None, sid) or {}
    except Exception:  # noqa: BLE001 — feedback is additive, never a read failure
        return {}


def _build_analysis_prompt(trace, policy_hits, job_cost, feedback):
    """Build the optimizer's analysis prompt from session evidence.

    The prompt asks the optimizer to identify harness deficiencies and propose
    structured deltas targeting specific registry rows or gate rules. The output
    is a JSON proposal, not free text.
    """
    parts = []

    # Session trace summary
    tokens = trace.get("tokens", 0)
    steps = trace.get("steps", 0)
    outcome = trace.get("outcome", "unknown")
    model = trace.get("model", "unknown")
    parts.append(f"Session: {tokens} tokens, {steps} steps, outcome={outcome}, model={model}")

    # Tool failures from exit codes (stored as `code` in runmetrics)
    code = trace.get("code")
    if code and code != 0:
        code_map = {1: "semantic error", 64: "usage error", 124: "timeout",
                    125: "sandbox", 126: "blocked", 127: "unknown tool", 130: "cancelled"}
        parts.append(f"Exit code: {code} ({code_map.get(code, 'unknown')})")

    # Policy hits
    if policy_hits:
        firings = policy_hits.get("firings", {})
        unknown = policy_hits.get("unknown_args", {})
        if firings:
            parts.append(f"Policy firings: {json.dumps(dict(list(firings.items())[:5]))}")
        if unknown:
            parts.append(f"Unknown args: {json.dumps(dict(list(unknown.items())[:5]))}")

    # Job cost
    if job_cost:
        parts.append(f"Job cost: {job_cost.get('tokens', 0)} tokens, "
                     f"${job_cost.get('usd', 'unpriced')}, "
                     f"{job_cost.get('turns', 0)} turns")

    # Feedback from downstream (S2)
    if feedback:
        fb_summary = feedback.get("summary", "")
        if fb_summary:
            parts.append(f"Downstream feedback: {fb_summary}")

    prompt = (
        "You are a harness optimizer. Analyze this session trace and identify "
        "harness deficiencies: tools that failed, gates that blocked legitimate "
        "calls, approval decisions that created friction, or patterns that suggest "
        "a registry or gate rule should change.\n\n"
        "Evidence:\n" + "\n".join(f"- {p}" for p in parts) + "\n\n"
        "Produce a JSON proposal with these fields:\n"
        "- target: the registry row (e.g., 'memory.recent') or gate rule (e.g., "
        "'subtool_gate:matrix.test') that should change\n"
        "- change: what should change (e.g., 'add field X to schema', "
        "'lower gate threshold', 'add guidance row')\n"
        "- reason: why, based on the evidence above\n"
        "- confidence: low | medium | high\n\n"
        "If no harness deficiency is evident, return {\"skip\": true, \"reason\": \"...\"}.\n"
        "Only propose changes to the tool registry or gate tables. Never propose "
        "changes to the agent loop, session management, or job dispatch."
    )
    return prompt


def _log_run(sid, proposal):
    """Append one optimizer run to the log. Never fails."""
    try:
        os.makedirs(os.path.dirname(OPTIMIZER_LOG), exist_ok=True)
        row = {"ts": round(time.time(), 3), "session": str(sid or ""),
               "proposal": proposal}
        with open(OPTIMIZER_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        pass


def run(sid, jid=None):
    """Run the local optimizer on a session trace.

    Called from the post-session hook in agent.py. Reads existing ledgers,
    builds an analysis prompt, and produces a structured proposal. The proposal
    is logged but NOT applied — it goes through the existing human review gate.

    Returns the proposal dict, or {"skip": True} if no deficiency found.
    """
    sid = str(sid or "").strip()
    if not sid:
        return {"skip": True, "reason": "no session id"}

    trace = _read_trace(sid)
    if not trace:
        return {"skip": True, "reason": "no trace"}

    # Minimum activity gate: skip sessions with no tool calls
    steps = trace.get("steps", 0)
    if steps < MIN_TOOL_CALLS:
        return {"skip": True, "reason": f"below minimum tool calls ({steps} < {MIN_TOOL_CALLS})"}

    policy_hits = _read_policy_hits()
    job_cost = _read_job_cost(jid) if jid else {}
    feedback = _read_feedback(sid)

    prompt = _build_analysis_prompt(trace, policy_hits, job_cost, feedback)

    # The optimizer is a coding agent — it calls the LLM through the normal
    # tool path. For now, we return the prompt as the proposal artifact;
    # the actual LLM call happens when the operator reviews the proposal.
    # This keeps the optimizer additive and reviewable.
    proposal = {
        "session": sid,
        "job": jid,
        "prompt": prompt,
        "evidence": {
            "tokens": trace.get("tokens", 0),
            "steps": steps,
            "outcome": trace.get("outcome", "unknown"),
            "exit_code": trace.get("code"),
            "policy_firings": len(policy_hits.get("firings", {})),
            "unknown_args": len(policy_hits.get("unknown_args", {})),
            "job_tokens": job_cost.get("tokens", 0),
            "has_feedback": bool(feedback),
        },
    }

    _log_run(sid, proposal)
    return proposal