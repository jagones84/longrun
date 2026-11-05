"""ONE live health report — components, host, model path and settings.

Before this module the answer to "is Longrun healthy?" was split in three places
that could not see each other: ``tools/diag.py`` (a host snapshot), ``core/
diagnostics.py`` (config/auth/model checks) and ``rllm.selfcheck_payload`` (the
LLM path). Each was correct and none said WHICH subsystem was failing NOW, because
the runtime swallowed its own errors (``routines._fire``, ``subagent.spawn``,
``jobs._run``).

This module is the single report and the single ledger:

  * **``HealthBoard``** — one entry per part, one writer per part. A part is
    ``unknown`` until it reports, ``ok`` when it last succeeded, ``warn`` after
    1–2 consecutive failures and ``error`` from the third (an isolated blip is not
    an outage). The counters are in memory: a restart honestly starts ``unknown``
    instead of replaying a stale green.
  * **``collect()``** — merges the board with LIVE probes (host, router, events
    store, memory, approvals, scheduler, sandbox, webhooks) and the existing
    settings report. Nothing is re-implemented: ``diag.health``, ``diagnostics.
    collect``, ``rllm.router_ping``/``selfcheck_payload`` and ``webhooks.stats``
    are imported, so a number has exactly one owner.

Consumers: ``GET /api/health``, the ``self`` tool (action ``diagnose``) and
Settings ▸ Diagnostics.
"""
from __future__ import annotations

import threading
import time

#: Consecutive failures before a part reports `error` (dsh's HealthBoard rule:
#: one failure is a blip, three in a row is a broken part).
FAILURES_BEFORE_ERROR = 3
_STATUS_RANK = {"error": 0, "warn": 1, "unknown": 2, "ok": 3}


class HealthBoard:
    """In-memory ledger: one entry per subsystem, one writer per entry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._parts: dict[str, dict] = {}
        self.started = time.time()

    def claim(self, part: str, title: str = "") -> dict:
        """Register a part (idempotent) and return its entry description."""
        name = str(part or "").strip()
        with self._lock:
            entry = self._parts.get(name)
            if entry is None:
                entry = {"part": name, "title": title or name, "reports": 0,
                         "failures": 0, "last_ok": None, "last_error": "",
                         "last_error_at": None, "status": "unknown"}
                self._parts[name] = entry
            elif title:
                entry["title"] = title
            return dict(entry)

    def report(self, part: str, ok: bool, error: str = "",
               detail: str = "") -> dict:
        """Record one outcome for a part and return its new entry.

        ``ok=False`` bumps the consecutive-failure counter (``error`` from the
        third); any success resets it. Never raises: a health write must not be
        able to break the thing it observes.
        """
        name = str(part or "").strip()
        if not name:
            return {}
        now = round(time.time(), 3)
        with self._lock:
            entry = self._parts.setdefault(name, {
                "part": name, "title": name, "reports": 0, "failures": 0,
                "last_ok": None, "last_error": "", "last_error_at": None,
                "status": "unknown"})
            entry["reports"] = int(entry.get("reports") or 0) + 1
            if ok:
                entry["failures"] = 0
                entry["last_ok"] = now
                entry["status"] = "ok"
                entry["last_error"] = ""
            else:
                entry["failures"] = int(entry.get("failures") or 0) + 1
                entry["last_error"] = str(error or "failed")[:300]
                entry["last_error_at"] = now
                entry["status"] = ("error" if entry["failures"] >= FAILURES_BEFORE_ERROR
                                   else "warn")
            if detail:
                entry["detail"] = str(detail)[:300]
            return dict(entry)

    def snapshot(self) -> list[dict]:
        """Every part, worst first (error → warn → unknown → ok)."""
        with self._lock:
            rows = [dict(entry) for entry in self._parts.values()]
        rows.sort(key=lambda r: (_STATUS_RANK.get(r.get("status"), 9),
                                 str(r.get("part") or "")))
        return rows

    def reset(self) -> None:
        """Drop every entry (tests; a restart has the same effect honestly)."""
        with self._lock:
            self._parts.clear()


#: The process-wide board. Modules report through it; nothing else owns state.
BOARD = HealthBoard()


# ----------------------------------------------------------------- probes ----

def _probe(name: str, fn, severity: str = "warn") -> dict:
    """Run one live probe and normalise its answer (never raises)."""
    started = time.time()
    try:
        ok, detail, extra = fn()
    except Exception as exc:  # noqa: BLE001 — a probe must degrade, never break
        ok, detail, extra = False, str(exc)[:300], {}
    out = {"name": name, "ok": bool(ok), "detail": detail,
           "severity": "error" if (not ok and severity == "error") else "warn",
           "ms": round((time.time() - started) * 1000, 1)}
    out.update(extra or {})
    return out


def _scheduler_probe():
    from longrun.orchestrate import routines
    thread = (routines._SCHED or {}).get("thread")
    if thread is None:
        return False, "not started", {}
    alive = bool(thread.is_alive())
    return alive, "alive" if alive else "thread died", {"thread": thread.name}


def _events_probe():
    from longrun.core import events
    # The READ is the health check: an empty log (fresh install, high-water 0) is
    # healthy — treating 0 as a failure made a brand-new instance read degraded.
    high = events.feed_seq()
    return True, ("empty" if not high else "high-water mark %s" % high), {
        "events": int(high or 0)}


def _memory_probe():
    from longrun.memory import memory
    data = memory.stats() or {}
    total = int(data.get("total") or 0)
    return True, "%d record(s)" % total, {"records": total,
                                          "vector_index": data.get("vector_index")}


def _approvals_probe():
    from longrun.tools import approvals
    data = approvals.stats() or {}
    return True, "%s pending" % data.get("pending", 0), {"pending": data.get("pending", 0)}


def _router_probe():
    from longrun.model import rllm
    ping = rllm.router_ping() or {}
    reachable = bool(ping.get("reachable"))
    return (reachable,
            "reachable" if reachable else "unreachable",
            {"latency_ms": ping.get("latency_ms"), "status": ping.get("status")})


def _sandbox_probe():
    from longrun.tools import sandbox
    data = sandbox.probe() or {}
    backend = str(data.get("backend") or "unknown")
    return bool(data.get("available", True)), backend, {"backend": backend}


def _webhooks_probe():
    from longrun.core import webhooks
    data = webhooks.stats()
    broken = bool(data.get("errors")) and data.get("errors", 0) >= max(
        1, int(data.get("accepted") or 0))
    return (not broken,
            "%d hook(s), %d accepted, %d error(s)"
            % (data.get("hooks", 0), data.get("accepted", 0), data.get("errors", 0)),
            {"hooks": data})


# ------------------------------------------------------------------ report ---

def collect(probe: bool = True, host: str = "127.0.0.1", port: int = 8790,
            session: str | None = None, model: str | None = None,
            llm_probe: bool = True) -> dict:
    """The one health report: live components first, then host, model and settings.

    ``probe=False`` skips the network probes (router, LLM latency); everything
    that reads local state still runs, so a caller can ask for a cheap snapshot.
    """
    started = time.time()
    parts = BOARD.snapshot()

    probes = [
        _probe("scheduler", _scheduler_probe, "error"),
        _probe("events", _events_probe, "error"),
        _probe("memory", _memory_probe),
        _probe("approvals", _approvals_probe),
        _probe("webhooks", _webhooks_probe),
        _probe("sandbox", _sandbox_probe),
    ]
    if probe:
        probes.insert(0, _probe("router", _router_probe, "error"))

    host_report = {}
    try:
        from longrun.tools import diag
        host_report = diag.health(host=host, port=port)
    except Exception as exc:  # noqa: BLE001
        host_report = {"ok": False, "error": str(exc)[:300]}

    llm = {}
    if probe:
        try:
            from longrun.model import rllm
            llm = rllm.selfcheck_payload(host=host, port=port, llm_probe=llm_probe)
        except Exception as exc:  # noqa: BLE001
            llm = {"status": "degraded", "error": str(exc)[:300]}

    settings = {"summary": {}, "issues": []}
    try:
        from longrun.core import diagnostics
        report = diagnostics.collect(session_id=session, model=model, host=host)
        settings = {"summary": report.get("summary") or {},
                    "issues": (report.get("issues") or [])[:20]}
    except Exception as exc:  # noqa: BLE001
        settings = {"summary": {"errors": 1, "warnings": 0, "info": 0,
                                "actionable": 1},
                    "issues": [{"code": "health.settings_unavailable",
                                "severity": "error", "scope": "global",
                                "title": "Settings checks could not run",
                                "message": str(exc)[:300], "source": "diagnostics"}]}

    errors = [p["part"] for p in parts if p.get("status") == "error"]
    warns = [p["part"] for p in parts if p.get("status") == "warn"]
    failed = [p["name"] for p in probes if not p.get("ok")]
    hard_failed = [p["name"] for p in probes
                   if not p.get("ok") and p.get("severity") == "error"]
    settings_errors = int((settings.get("summary") or {}).get("errors") or 0)

    if errors or hard_failed or settings_errors:
        overall = "error"
    elif warns or failed or (settings.get("summary") or {}).get("warnings"):
        overall = "degraded"
    elif all(p.get("status") == "unknown" for p in parts):
        # Nothing has reported yet and every probe is green: honest `ok` would
        # claim knowledge the board does not have. `degraded` is too alarming;
        # `unknown` says exactly what is true.
        overall = "unknown"
    else:
        overall = "ok"

    return {
        "ok": overall != "error",
        "status": overall,
        "generated_at": round(time.time(), 3),
        "uptime_secs": round(time.time() - BOARD.started, 1),
        "summary": {
            "parts": len(parts),
            "ok": sum(1 for p in parts if p.get("status") == "ok"),
            "warn": len(warns),
            "error": len(errors),
            "unknown": sum(1 for p in parts if p.get("status") == "unknown"),
            "errors": errors,
            "probes_failed": failed,
        },
        "parts": parts,
        "probes": probes,
        "host": host_report,
        "llm": llm,
        "settings": settings,
        "check_seconds": round(time.time() - started, 2),
    }
