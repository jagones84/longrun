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

# RRSI (arXiv:2609.24972, abstract): recursive harness editing must condition the
# proposer on the evolution history ("encourages unexplored trajectories") and a
# pruner drops changes that are "no longer useful". The inbox is that history: the
# same delta re-proposed after a decision is noise, not exploration.
HISTORY_LIMIT = 8


def _evolution_history(limit=HISTORY_LIMIT):
    """Recent registry proposals with their decision, newest first.

    Read-only and fail-open: no history is better than no proposal. Only rows
    that actually carry a `delta` are useful here (a prose proposal has nothing
    to compare against).
    """
    try:
        from longrun.util import improve as _improve
        rows = [p for p in _improve.list_proposals() if p.get("scope") == "registry"]
    except Exception:  # noqa: BLE001 — the prompt must never break a run
        return []
    out = []
    for p in rows:
        d = p.get("delta")
        if not isinstance(d, dict) or not d:
            continue
        out.append({"id": p.get("id"), "status": str(p.get("status") or "pending"),
                    "delta": d, "reason": str(p.get("reason") or "")[:160],
                    "stale": str(p.get("stale") or "")})
        if len(out) >= limit:
            break
    return out


def _delta_key(delta):
    """The IDENTITY of a delta: target/field/value/add/remove, no prose.

    `reason`/`confidence` are the model's explanation and may differ between two
    runs that propose the same change; including them would defeat the pruner.
    List order is not part of a list's identity (the validator treats a list as a
    set of entries).
    """
    d = delta if isinstance(delta, dict) else {}
    keep = {k: d.get(k) for k in ("target", "field", "value", "add", "remove")
            if k in d}
    for k in ("add", "remove"):
        if isinstance(keep.get(k), list):
            keep[k] = sorted(str(x) for x in keep[k])
    try:
        return json.dumps(keep, sort_keys=True)
    except (TypeError, ValueError):
        return ""


def _history_block(history):
    """The bounded 'already tried' section of the prompt ("" when empty)."""
    if not history:
        return ""
    lines = ["Already proposed for this registry (newest first) — do NOT propose "
             "an identical delta again (approved = already applied, denied = "
             "refused, 'cannot apply' = the registry no longer accepts it); choose "
             "a DIFFERENT row, or skip:"]
    for h in history:
        d = h.get("delta") or {}
        bits = ["%s.%s" % (d.get("target"), d.get("field"))]
        if "value" in d:
            bits.append("value=%s" % json.dumps(d.get("value")))
        for k in ("add", "remove"):
            if d.get(k):
                bits.append("%s=%s" % (k, json.dumps(d.get(k))))
        status = str(h.get("status"))
        if h.get("stale"):
            status += " · cannot apply"
        lines.append("- [%s] %s — %s" % (status, " ".join(bits),
                                         h.get("reason") or "(no reason)"))
    return "\n".join(lines)[:3000]


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


def _hit_rows(policy_hits):
    """Split the firing ledger into the rules that are LIVE and the ones RETIRED.

    The ledger is HISTORY: a rule deleted from the policy keeps its counters for
    ever, and the keys are `<tool>:<kind>:<pattern>`. 2026-11-18 (round 75) the
    prompt printed the first five ledger keys as "Policy firings" — three of them
    rules the policy no longer has (measured: `shell:deny:grep[^\\n]*\\.env`) — and
    the model proposed removing one. The registry already decides which configured
    rules fired and which ledger keys it no longer owns (`retired_rules`), so this
    function only SPLITS that classification; it never re-derives it.
    """
    hits = (policy_hits or {}).get("firings") or {}
    retired = {str(k) for k in ((policy_hits or {}).get("retired_rules") or [])}
    live, gone = [], []
    for key, rec in hits.items():
        parts = str(key).split(":", 2)
        if len(parts) != 3:
            continue
        row = {"tool": parts[0], "kind": parts[1], "pattern": parts[2],
               "n": int((rec or {}).get("n") or 0)}
        (gone if str(key) in retired else live).append(row)
    live.sort(key=lambda r: (-r["n"], r["tool"], r["pattern"]))
    gone.sort(key=lambda r: (-r["n"], r["tool"], r["pattern"]))
    return live, gone


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


def _policy_snapshot(policy_hits):
    """The LIVE values of the rows the evidence names, for the model to copy.

    2026-11-17: the prompt used to describe the delta shape without showing a
    single current value, so the model rewrote `shell.exec.deny` from memory and
    proposed a one-entry list — a click away from deleting seven hard-deny rules.
    A model may only `add`/`remove` entries it was shown (the validator refuses
    a `remove` that is not in the live list, and refuses a whole-list `value`).

    2026-11-18 (round 75): the fix above passed `firings` KEYS (`shell.exec:deny:
    …`) to `tool_spec`, which knows no such tool, so on real data the section read
    "(not available)" — measured on the live ledger. The tool name is the first
    segment of the key.
    """
    live, _gone = _hit_rows(policy_hits)
    names = []
    for row in live:
        if row["tool"] not in names:
            names.append(row["tool"])
    for key in (policy_hits or {}).get("never_fired") or []:
        tool = str(key).split(":", 1)[0]
        if tool and tool not in names:
            names.append(tool)
    if not names:
        names = ["shell.exec"]
    try:
        from longrun.tools import registry as _reg
    except Exception:  # noqa: BLE001 — no snapshot is better than no prompt
        return ""
    rows = []
    for name in names[:4]:
        try:
            spec = _reg.tool_spec(name) or {}
        except Exception:  # noqa: BLE001
            continue
        if not spec:
            continue
        rows.append("%s: approval=%s deny=%s always_ask=%s auto_approve=%s" % (
            name, spec.get("approval"),
            json.dumps(spec.get("deny") or []),
            json.dumps(spec.get("always_ask") or []),
            json.dumps(spec.get("auto_approve") or [])))
    return "\n".join(rows)[:5000]


def _build_analysis_prompt(trace, policy_hits, job_cost, feedback, history=None):
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
        live, gone = _hit_rows(policy_hits)
        never = [str(k) for k in ((policy_hits or {}).get("never_fired") or [])]
        unknown = policy_hits.get("unknown_args", {})
        if live:
            parts.append(
                "Rules that FIRED and are STILL in the live policy (load-bearing — each "
                "one blocked a real call, so removing one needs evidence from the "
                "trace):\n" + "\n".join(
                    "  %s %s x%d: %s" % (r["tool"], r["kind"], r["n"], r["pattern"])
                    for r in live[:12]))
        if gone:
            parts.append(
                "Ledger history of rules the live policy NO LONGER has (they are absent "
                "from the live list below, so they cannot be removed — never propose "
                "one of these in `remove`):\n" + "\n".join(
                    "  %s %s x%d: %s" % (r["tool"], r["kind"], r["n"], r["pattern"])
                    for r in gone[:6]))
        if never:
            parts.append(
                "Configured rules that NEVER fired (context only — a guard that never "
                "fired may be doing its job; do not propose removing one without "
                "friction evidence):\n" + "\n".join("  " + k for k in never[:8]))
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

    snap = _policy_snapshot(policy_hits)
    _hist = _history_block(history)
    prompt = (
        "You are a harness optimizer. Analyze this session trace and identify ONE "
        "concrete deficiency in the TOOL REGISTRY — a tool that failed, a gate that "
        "blocked a legitimate call, or a policy that created friction.\n\n"
        "Evidence:\n" + "\n".join(f"- {p}" for p in parts) + "\n\n"
        "Current live policy of the row(s) the evidence names (the exact values; a "
        "list is changed ONLY through add/remove, never rewritten from memory):\n"
        + (snap or "(not available)") + "\n\n"
        + ((_hist + "\n\n") if _hist else "")
        + "Reply with ONE JSON object and NOTHING else. Either:\n"
        '  {"skip": true, "reason": "..."}   — when no registry deficiency is evident\n'
        "or a delta naming one editable registry field:\n"
        '  {"target": "<tool row, e.g. shell.exec or the namespace shell>",\n'
        '   "field": "<one of: enabled, approval, auto_approve, roots, deny, '
        'allow_hosts, always_ask>",\n'
        '   "value": <bool for enabled; "auto"|"required"|"denied" for approval>,\n'
        '   "add": ["<exact NEW list entries>"],\n'
        '   "remove": ["<exact EXISTING entries to delete, copied verbatim>"],\n'
        '   "reason": "...", "confidence": "low"|"medium"|"high"}\n'
        "For a list field use add/remove only; an entry you do not copy into `add` "
        "is kept, so adding a rule can never delete another one.\n\n"
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
    history = _evolution_history()
    prompt = _build_analysis_prompt(trace, policy_hits, job_cost, feedback,
                                    history=history)

    _live, _gone = _hit_rows(policy_hits)
    evidence = {
        "tokens": trace.get("tokens", 0),
        "steps": steps,
        "outcome": trace.get("outcome", "unknown"),
        "exit_code": trace.get("code"),
        "live_firings": len(_live),
        "retired_firings": len(_gone),
        "never_fired": len(policy_hits.get("never_fired") or []),
        "unknown_args": len(policy_hits.get("unknown_args", {})),
        "job_tokens": job_cost.get("tokens", 0),
        "has_feedback": bool(feedback),
    }

    reply = _call_model(prompt)
    delta, parsed = _extract_json(reply)
    if not parsed:
        # 2026-11-18 (round 75): 95 of 170 logged runs ended here and the log kept
        # no reply, so a dead model (no endpoint) and a malformed reply were the
        # same row — undiagnosable. The reply is kept (empty when the call failed).
        result = {"skip": True, "reason": "unparseable model reply",
                  "session": sid, "prompt": prompt, "evidence": evidence,
                  "reply": str(reply or "")[:1500]}
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
    # RRSI pruner ("no longer useful"): the same delta already decided or still
    # waiting adds a duplicate to the inbox and no information to the operator.
    _key = _delta_key(delta)
    _seen = next((h for h in history if _key and _delta_key(h["delta"]) == _key), None)
    if _seen:
        result = {"skip": True, "session": sid, "delta": delta,
                  "reason": "already proposed (%s): %s" % (
                      _seen["status"], _seen["reason"] or "no reason"),
                  "proposal_id": _seen.get("id"), "prompt": prompt,
                  "evidence": evidence}
        _log_run(sid, result)
        return result

    proposal_id = _submit(delta, evidence, sid)
    proposal = {"session": sid, "job": jid, "delta": delta,
                "proposal_id": proposal_id, "prompt": prompt, "evidence": evidence}
    _log_run(sid, proposal)
    return proposal
