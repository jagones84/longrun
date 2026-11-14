"""Local harness optimizer — reads session traces and proposes registry changes (S1).

An Agentron-style local optimizer (HarnessNet, arXiv:2610.15221 §3.1): a coding agent
constrained to a single agent's org scope that reads execution traces after every session
and produces ONE structured proposal targeting a tool-registry row.

The optimizer is ADDITIVE — it reads existing ledgers (runmetrics, jobcost, policy_hits)
and submits its proposal through the EXISTING approvals pipeline (`util/improve.py`):
the delta lands in the operator's inbox and, on approve, `improve.decide` applies exactly
those bytes to the sparse registry overlay (`registry.apply_delta`). The optimizer never
modifies the harness itself; `config/tools.yaml` is never touched.

Triggered by a post-session hook in `agent/agent.py` and the v2 API worker
(`core/api_v02.py`). Every hook is fail-safe: a failure here logs and continues, never
breaking the session.
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


def _optimizer_model():
    """The model the optimizer runs on: the `agent` role, else the harness default."""
    try:
        from longrun.model import routing as _routing
        m = _routing.pick("agent")
        if m:
            return m
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.model.rllm import default_model
        return default_model()
    except Exception:  # noqa: BLE001
        return None


def _call_model(prompt, model=None):
    """One synchronous completion. Returns the raw reply text, or None on any failure.

    Resolves the endpoint through `providers.endpoint` so a cloud model carries its
    own auth header — `ROUTER_BASE` alone is not the whole address (it points at the
    local llama.cpp router, which is not where a routed `openrouter:` model lives).
    """
    try:
        import urllib.request as _req
        from longrun.model import providers as _prov
        model = model or _optimizer_model()
        if not model:
            return None
        url, headers, resolved = _prov.endpoint(model)
        body = json.dumps({
            "model": resolved,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
            "temperature": 0.3,
            "stream": False,
        }).encode("utf-8")
        req = _req.Request(url, data=body, headers=headers)
        resp = _req.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode("utf-8"))
        return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    except Exception:  # noqa: BLE001 — the model call is additive, never fails the session
        return None


def _extract_json(text):
    """Extract the first JSON object/array from a model reply. Returns (obj, ok)."""
    if not text:
        return None, False
    s = str(text).strip()
    if s.startswith("```"):
        s = s[3:]
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()
    try:
        return json.loads(s), True
    except ValueError:
        pass
    # Fall back to the outermost {...} or [...] block inside prose.
    for op, cl in (("{", "}"), ("[", "]")):
        i = s.find(op)
        j = s.rfind(cl)
        while i != -1 and j > i:
            try:
                return json.loads(s[i:j + 1]), True
            except ValueError:
                j = s.rfind(cl, 0, j)
    return None, False


def _build_analysis_prompt(trace, policy_hits, job_cost, feedback):
    """Build the optimizer's analysis prompt from session evidence.

    The prompt asks for ONE JSON object: either {"skip": true, ...} or a registry-row
    delta the existing approval pipeline can apply. It never asks for a code change.
    """
    parts = []

    tokens = trace.get("tokens", 0)
    steps = trace.get("steps", 0)
    outcome = trace.get("outcome", "unknown")
    model = trace.get("model", "unknown")
    parts.append(f"Session: {tokens} tokens, {steps} steps, outcome={outcome}, model={model}")

    code = trace.get("code")
    if code and code != 0:
        code_map = {1: "semantic error", 64: "usage error", 124: "timeout",
                    125: "sandbox", 126: "blocked", 127: "unknown tool", 130: "cancelled"}
        parts.append(f"Exit code: {code} ({code_map.get(code, 'unknown')})")

    if policy_hits:
        firings = policy_hits.get("firings", {})
        unknown = policy_hits.get("unknown_args", {})
        if firings:
            parts.append(f"Policy firings: {json.dumps(dict(list(firings.items())[:5]))}")
        if unknown:
            parts.append(f"Unknown args: {json.dumps(dict(list(unknown.items())[:5]))}")

    if job_cost:
        parts.append(f"Job cost: {job_cost.get('tokens', 0)} tokens, "
                     f"${job_cost.get('usd', 'unpriced')}, "
                     f"{job_cost.get('turns', 0)} turns")

    if feedback:
        fb_summary = feedback.get("summary", "")
        if fb_summary:
            parts.append(f"Downstream feedback: {fb_summary}")
        failed_agent = (feedback.get("details") or {}).get("failed_agent")
        if failed_agent:
            parts.append(f"A downstream agent that consumed this output failed: {failed_agent}")

    prompt = (
        "You are a harness optimizer. Analyze this session trace and identify ONE "
        "concrete deficiency in the TOOL REGISTRY — a tool that failed, a gate that "
        "blocked a legitimate call, or a policy that created friction.\n\n"
        "Evidence:\n" + "\n".join(f"- {p}" for p in parts) + "\n\n"
        "Reply with ONE JSON object and NOTHING else. Either:\n"
        '  {"skip": true, "reason": "..."}   — when no registry deficiency is evident\n'
        "or a delta naming one editable registry field:\n"
        '  {"target": "<tool row, e.g. shell.exec or the namespace shell>",\n'
        '   "field": "<one of: enabled, approval, auto_approve, roots, deny, '
        'allow_hosts, always_ask>",\n'
        '   "value": <bool for enabled; "auto"|"required"|"denied" for approval; '
        'a list of strings for the others>,\n'
        '   "reason": "...", "confidence": "low"|"medium"|"high"}\n\n'
        "Only propose changes to the tool registry. Never propose changes to the "
        "agent loop, session management, or job dispatch."
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


def _submit(delta, evidence, sid):
    """Register the delta as a `registry` proposal. Returns the proposal id or None.

    The proposal goes through the EXISTING approvals pipeline — no new gate: it
    appears in the operator's inbox and ledger, and `improve.decide(approve)`
    applies the delta via `registry.apply_delta` (overlay-only).
    """
    try:
        from longrun.util import improve as _improve
        content = "%s.%s = %s — %s" % (
            delta.get("target"), delta.get("field"),
            json.dumps(delta.get("value")), delta.get("reason") or "")
        rec = _improve.propose(
            "registry", content,
            reason=str(delta.get("reason") or "")[:500],
            origin="optimizer", delta=delta,
            experiment={"session": sid, "evidence": evidence})
        return rec.get("id")
    except Exception:  # noqa: BLE001 — submitting is additive, never fails the session
        return None


def run(sid, jid=None):
    """Run the local optimizer on a session trace.

    Reads existing ledgers, asks the model (the `agent` role) for ONE registry delta,
    and submits it through the existing approvals pipeline. The delta is NOT applied
    here — a human approves it. Returns the proposal dict, or {"skip": True, ...}.
    """
    sid = str(sid or "").strip()
    if not sid:
        return {"skip": True, "reason": "no session id"}

    trace = _read_trace(sid)
    if not trace:
        return {"skip": True, "reason": "no trace"}

    steps = trace.get("steps", 0)
    if steps < MIN_TOOL_CALLS:
        return {"skip": True, "reason": "below minimum tool calls (%s < %s)" % (steps, MIN_TOOL_CALLS)}

    policy_hits = _read_policy_hits()
    job_cost = _read_job_cost(jid) if jid else {}
    feedback = _read_feedback(sid)
    prompt = _build_analysis_prompt(trace, policy_hits, job_cost, feedback)

    evidence = {
        "tokens": trace.get("tokens", 0),
        "steps": steps,
        "outcome": trace.get("outcome", "unknown"),
        "exit_code": trace.get("code"),
        "policy_firings": len(policy_hits.get("firings", {})),
        "unknown_args": len(policy_hits.get("unknown_args", {})),
        "job_tokens": job_cost.get("tokens", 0),
        "has_feedback": bool(feedback),
    }

    reply = _call_model(prompt)
    delta, parsed = _extract_json(reply)
    if not parsed:
        result = {"skip": True, "reason": "unparseable model reply",
                  "session": sid, "prompt": prompt, "evidence": evidence}
        _log_run(sid, result)
        return result

    # The registry owner is the ONE validator: a delta it would refuse is not a
    # proposal — the optimizer skips instead of writing an unusable entry.
    try:
        from longrun.tools import registry as _reg
        err = _reg.delta_error(delta)
    except Exception:  # noqa: BLE001
        err = "registry validator unavailable"
    if err:
        result = {"skip": True, "reason": err, "session": sid,
                  "delta": delta, "prompt": prompt, "evidence": evidence}
        _log_run(sid, result)
        return result

    proposal_id = _submit(delta, evidence, sid)
    proposal = {"session": sid, "job": jid, "delta": delta,
                "proposal_id": proposal_id, "prompt": prompt, "evidence": evidence}
    _log_run(sid, proposal)
    return proposal
