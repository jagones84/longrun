#!/usr/bin/env python3
"""Admission scheduling — the API is a shared resource, so schedule it.

Source: arXiv:2604.17111, "HiveMind" (round 143). Eleven concurrent agents
sharing one rate-limited key lost three of them to connection resets and HTTP 502
— a 27% failure rate although the endpoint had enough aggregate capacity to serve
all eleven sequentially (`hivemind_scheduling_2604.17111.txt:22`, `:29`, `:62`).
The fix is not capacity but coordination: five OS-inspired primitives in front of
the API (`:34`, `:63`).

  * **admission control** gates concurrency on a condition variable, so Cmax can
    be resized safely while requests are in flight (`:163`, `:180`).
  * **rate-limit tracking** is both reactive (provider headers) and proactive
    (sliding-window RPM/TPM counters) (`:229`, `:251`).
  * **AIMD backpressure with a circuit breaker**: additive increase on latency
    under target, multiplicative decrease above it, and a half-open probe after a
    cooldown (`:217`, `:222`, `:290`).
  * **token budgets** warn at 85% and checkpoint at 100%, the OOM-killer analogue
    (`:275`, `:277`).
  * **priority queuing with a dependency DAG**: service class, then estimated
    token cost, then arrival; a task is ineligible until its predecessors finish
    (`:284`, `:290`).
  * **transparent retry is the load-bearing primitive**: removing it produces
    63.6% failures, while admission-only still fails at 81.8% (`:489`, `:502`).
  * **under contention** uncoordinated agents fail at 72–100%; the managed proxy
    brings that to 0–18% (`:45`, `:452`).

  * `provider(profile)` — the limits a scheduling decision needs.
  * `slot(active, cmax)` — one admission decision.
  * `aimd(state)` — the concurrency controller.
  * `circuit(state)` — closed / open / half-open and its fast-fail.
  * `backoff(attempt, ...)` — deterministic retry delay with an explicit jitter.
  * `budget(ceiling, used)` — ok / warn / checkpoint.
  * `order(tasks)` — priority, shortest job, arrival, and the dependency gate.
  * `ablate(rows)` — which primitive is load-bearing.
  * `pressure(rows)` — direct against managed under the same load.
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: counters and queues in; decisions out.
"""
from __future__ import annotations

FORMAT = "longrun-admission-schedule/1"

LEVELS = ("critical", "high", "normal", "low")
CIRCUIT = ("closed", "open", "half-open")


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def provider(profile):
    """The limits a decision needs; a missing one is named, not guessed."""
    p = profile or {}
    findings = []
    limits = {
        "rpm": _num(p.get("rpm")),
        "tpm": _num(p.get("tpm")),
        "cmax": _num(p.get("cmax")),
        "target_ms": _num(p.get("target_ms")),
    }
    for key, value in limits.items():
        if value is None or value <= 0:
            findings.append({"kind": "limit-missing", "field": key})
    if not p.get("retryable"):
        findings.append({"kind": "retryable-set-empty",
                         "why": "429/502/reset must be retryable centrally"})
    if not findings:
        findings.append({"kind": "profile-complete"})
    return {"format": FORMAT, "limits": limits, "findings": findings}


def slot(active, cmax, waiting=0):
    """One admission decision: admit while a slot exists, else wait."""
    a = _num(active, 0.0)
    c = _num(cmax, 0.0)
    if c <= 0:
        return {"format": FORMAT, "admitted": False, "reason": "no-capacity",
                "active": a, "cmax": c, "waiting": waiting}
    admitted = a < c
    return {"format": FORMAT, "admitted": admitted, "active": a, "cmax": c,
            "waiting": waiting,
            "reason": "slot-free" if admitted else "at-capacity",
            "notify": "one waiter" if admitted is False else "slot-taken"}


def aimd(state):
    """Additive increase under the latency target, multiplicative decrease above it."""
    s = state or {}
    c = _num(s.get("c"))
    target = _num(s.get("target_ms"))
    latency = _num(s.get("mean_latency"))
    cmin = _num(s.get("cmin"), 1.0)
    cmax = _num(s.get("cmax"), 10.0)
    alpha = _num(s.get("alpha"), 0.5)
    beta = _num(s.get("beta"), 0.5)
    if c is None or target is None:
        return {"format": FORMAT, "verdict": "state-incomplete"}
    if s.get("error") is True:
        nxt = max(cmin, c * beta)
        return {"format": FORMAT, "c": nxt, "action": "decrease",
                "reason": "error", "changed": nxt != c}
    if latency is None:
        return {"format": FORMAT, "c": c, "action": "hold",
                "reason": "no-sample", "changed": False}
    if latency <= target:
        nxt = min(cmax, c + alpha)
        return {"format": FORMAT, "c": nxt, "action": "increase",
                "reason": "under-target", "changed": nxt != c}
    nxt = max(cmin, c * beta)
    return {"format": FORMAT, "c": nxt, "action": "decrease",
            "reason": "over-target", "changed": nxt != c}


def circuit(state):
    """Errors open the circuit, a cooldown admits one probe, success closes it."""
    s = state or {}
    now_state = str(s.get("state") or "closed")
    if now_state not in CIRCUIT:
        return {"format": FORMAT, "verdict": "unknown-state"}
    errors = _num(s.get("errors"), 0.0)
    total = _num(s.get("total"), 0.0)
    threshold = _num(s.get("threshold"), 0.5)
    window = _num(s.get("window"), 20.0)
    cooled = s.get("cooled") is True
    probe_ok = s.get("probe_ok")
    if now_state == "closed":
        if total >= window and total > 0 and errors / total >= threshold:
            nxt, fast = "open", True
        else:
            nxt, fast = "closed", False
    elif now_state == "open":
        if cooled:
            nxt, fast = "half-open", False
        else:
            nxt, fast = "open", True
    else:
        if probe_ok is True:
            nxt, fast = "closed", False
        elif probe_ok is False:
            nxt, fast = "open", True
        else:
            nxt, fast = "half-open", False
    return {"format": FORMAT, "state": nxt, "fast_fail": fast,
            "error_rate": (errors / total if total else 0.0),
            "status": 503 if fast else 200}


def backoff(attempt, retry_after=None, base=1.0, cap=30.0, jitter=0.0):
    """Exponential backoff; a Retry-After header overrides the computed delay."""
    k = int(_num(attempt, 0.0))
    if retry_after is not None:
        value = _num(retry_after, 0.0)
        return {"format": FORMAT, "delay": value, "source": "retry-after"}
    delay = min(cap, base * (2 ** k) + max(0.0, jitter))
    return {"format": FORMAT, "delay": delay, "source": "exponential",
            "jitter": jitter}


def budget(ceiling, used, warn_at=0.85):
    """85% warns, 100% checkpoints the agent and stops it."""
    c = _num(ceiling)
    u = _num(used, 0.0)
    if c is None or c <= 0:
        return {"format": FORMAT, "verdict": "no-ceiling"}
    share = u / c
    if share >= 1.0:
        verdict, action = "checkpoint", "stop-and-save"
    elif share >= warn_at:
        verdict, action = "warn", "warn-agent"
    else:
        verdict, action = "ok", "continue"
    return {"format": FORMAT, "share": share, "verdict": verdict,
            "action": action}


def order(tasks, completed=()):
    """Priority, then shortest estimated job, then arrival; dependencies gate it."""
    rows = [t for t in (tasks or []) if isinstance(t, dict)]
    ids = {str(t.get("id")) for t in rows}
    done_ids = {str(t) for t in (completed or [])}
    rank = {level: i for i, level in enumerate(LEVELS)}
    for task in rows:
        level = str(task.get("priority") or "normal")
        if level not in rank:
            return {"format": FORMAT, "verdict": "unknown-priority",
                    "detail": level}
        for dep in task.get("depends_on") or []:
            if str(dep) not in ids and str(dep) not in done_ids:
                return {"format": FORMAT, "verdict": "dangling-dependency",
                        "detail": str(dep)}
    # cycle detection
    graph = {str(t.get("id")): [str(d) for d in (t.get("depends_on") or [])]
             for t in rows}
    visiting, done = set(), set()

    def visit(node):
        if node in done:
            return True
        if node in visiting:
            return False
        visiting.add(node)
        for dep in graph.get(node, []):
            if not visit(dep):
                return False
        visiting.discard(node)
        done.add(node)
        return True

    for node in graph:
        if not visit(node):
            return {"format": FORMAT, "verdict": "dependency-cycle",
                    "detail": node}
    ready, blocked = [], []
    for task in rows:
        deps = [str(d) for d in (task.get("depends_on") or [])]
        entry = {"id": str(task.get("id")),
                 "priority": task.get("priority") or "normal",
                 "tokens": _num(task.get("tokens"), 0.0),
                 "created": _num(task.get("created"), 0.0)}
        (ready if all(dep in done_ids for dep in deps) else blocked).append(entry)
    ready.sort(key=lambda t: (rank[t["priority"]], t["tokens"], t["created"]))
    return {"format": FORMAT, "verdict": "ordered", "ready": ready,
            "blocked": blocked}


def ablate(rows):
    """Which primitive carries the result: the paper's own ablation."""
    clean = []
    for row in rows or []:
        name = str((row or {}).get("config") or "")
        failures = _num((row or {}).get("failures"))
        if not name or failures is None:
            continue
        clean.append({"config": name, "failures": failures})
    if not clean:
        return {"format": FORMAT, "verdict": "no-rows"}
    worst = max(clean, key=lambda r: r["failures"])
    admission = next((r for r in clean
                       if "admission" in r["config"].lower()
                       and "only" in r["config"].lower()), None)
    findings = []
    retry_row = next((r for r in clean
                      if "retry" in r["config"].lower()
                      and "no" in r["config"].lower()), None)
    if retry_row and retry_row["failures"] >= 0.5:
        findings.append({"kind": "retry-is-load-bearing",
                         "failures": retry_row["failures"]})
    if admission and admission["failures"] > 0.5:
        findings.append({"kind": "admission-only-insufficient",
                         "failures": admission["failures"]})
    if not findings:
        findings.append({"kind": "no-load-bearing-primitive"})
    return {"format": FORMAT, "rows": clean, "worst": worst, "findings": findings}


def pressure(rows):
    """Direct against managed, on the same load."""
    direct, managed = [], []
    for row in rows or []:
        fail = _num((row or {}).get("failures"))
        if fail is None:
            continue
        (direct if str((row or {}).get("arm")) == "direct" else managed).append(fail)
    if not direct or not managed:
        return {"format": FORMAT, "verdict": "two-arms-required"}
    d = sum(direct) / len(direct)
    m = sum(managed) / len(managed)
    return {"format": FORMAT, "direct": d, "managed": m,
            "reduction": d - m,
            "verdict": ("stampede-without-scheduling" if d >= 0.72
                        else "contention-mild") if m < 0.2 else "managed-fails"}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    checks = (
        ("gates_concurrency", "uncoordinated-parallelism",
         "eleven agents, one key, 27% dead"),
        ("tracks_rate_limits", "provider-errors-only",
         "a sliding window throttles before the first 429"),
        ("adjusts_concurrency", "fixed-concurrency",
         "AIMD changes the slot count from observed latency"),
        ("retries_centrally", "per-agent-retry",
         "independent retries rebuild the thundering herd"),
        ("budgets_each_agent", "runaway-agent",
         "a token ceiling checkpoints instead of wasting the run"),
        ("orders_by_priority_and_deps", "fifo-by-arrival",
         "low-value work otherwise blocks high-value work"),
    )
    findings = []
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
