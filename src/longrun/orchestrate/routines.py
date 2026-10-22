"""Routines — agents that wake on a schedule (Paperclip-style heartbeats).

A routine binds an AGENT (AX) to a goal and a cadence: every N seconds the harness
wakes the agent by running the goal as a normal turn on its session. This is what
lets a team keep producing while no human is watching a terminal.

A single daemon scheduler thread (started by the server) checks for due routines and
dispatches each one in its own thread, so a slow turn never stalls the timer. Every
fired routine respects the agent's daily budget (`agents.AgentRegistry.charge`).

Storage: ``LONGRUN_ROUTINES_FILE`` (default ``data/routines.json``).
"""
import os
import threading
import time

from longrun.util.fswrite import read_registry, write_json
from longrun.util import paths
from longrun.util.paths import REPO_ROOT as REPO

_LOCK = threading.RLock()
ROUTINES_FILE = (os.environ.get("LONGRUN_ROUTINES_FILE")
                 or os.path.join(paths.DATA_DIR, "routines.json"))
MIN_EVERY = 30
DEFAULT_TICK = 20


def _load():
    return read_registry(ROUTINES_FILE, routines={}, seq=0)


def _save(d):
    write_json(ROUTINES_FILE, d)
    # JAG-532: the only writer of the routines file also announces the change, so
    # Orbit and any other view follow the EVENT instead of polling a stale list.
    try:
        from longrun.core.events import publish
        publish("routines.updated", routines=len(d.get("routines") or {}))
    except Exception:  # noqa: BLE001 — an event must never block a write
        pass


def _run_agent(session_id, goal, model=None):
    """Run the goal as one real turn on the agent's session (jobs shares this path)."""
    from longrun.orchestrate import jobs as jobs_mod
    return jobs_mod.JOBS._run_agent(session_id, goal, model=model)


class RoutineRegistry:
    """Create, list, enable/disable and fire routines."""

    def list(self):
        with _LOCK:
            d = _load()
        rows = sorted(d["routines"].values(), key=lambda r: r.get("n", 0))
        return {"routines": rows, "seq": d["seq"], "count": len(rows)}

    def get(self, rid):
        with _LOCK:
            return _load()["routines"].get(str(rid))

    def create(self, agent, goal, every_seconds, enabled=True, model=None):
        agent = str(agent or "").strip()
        goal = (goal or "").strip()
        if not agent:
            return {"ok": False, "error": "agent required"}
        if not goal:
            return {"ok": False, "error": "goal required"}
        try:
            every = int(every_seconds)
        except (TypeError, ValueError):
            every = 0
        if every < MIN_EVERY:
            return {"ok": False, "error": "every_seconds must be >= %d" % MIN_EVERY}
        try:
            from longrun.agent import agents as agents_mod
            if not agents_mod.REGISTRY.resolve(agent):
                return {"ok": False, "error": "unknown agent (designate it first)"}
        except Exception:  # noqa: BLE001
            pass
        with _LOCK:
            d = _load()
            d["seq"] += 1
            now = time.time()
            rec = {"id": "R%d" % d["seq"], "n": d["seq"], "agent": agent, "goal": goal,
                   "model": model, "every_seconds": every, "enabled": bool(enabled),
                   "created": round(now, 3), "last_run": None,
                   "next_run": round(now + every, 3), "runs": 0}
            d["routines"][rec["id"]] = rec
            _save(d)
        return {"ok": True, "routine": rec}

    def delete_for_agent(self, agent):
        """JAG-314: drop every routine bound to a released/deleted agent."""
        agent = str(agent or "")
        with _LOCK:
            d = _load()
            victims = [rid for rid, rec in d["routines"].items() if rec.get("agent") == agent]
            for rid in victims:
                d["routines"].pop(rid, None)
            if victims:
                _save(d)
            return victims

    def delete(self, rid):
        with _LOCK:
            d = _load()
            rec = d["routines"].pop(str(rid), None)
            if rec:
                _save(d)
        return {"ok": True, "deleted": rec["id"] if rec else None}

    def set_enabled(self, rid, enabled):
        with _LOCK:
            d = _load()
            r = d["routines"].get(str(rid))
            if not r:
                return {"ok": False, "error": "routine not found"}
            r["enabled"] = bool(enabled)
            if r["enabled"]:
                r["next_run"] = round(time.time() + int(r.get("every_seconds") or MIN_EVERY), 3)
            _save(d)
            return {"ok": True, "routine": r}

    def due(self, now=None):
        now = time.time() if now is None else now
        with _LOCK:
            d = _load()
        return [r for r in d["routines"].values()
                if r.get("enabled") and (r.get("next_run") or 0) <= now]

    def _mark(self, rid, ts):
        with _LOCK:
            d = _load()
            r = d["routines"].get(str(rid))
            if not r:
                return
            r["last_run"] = round(ts, 3)
            r["runs"] = r.get("runs", 0) + 1
            r["next_run"] = round(ts + int(r.get("every_seconds") or MIN_EVERY), 3)
            _save(d)

    def tick(self, now=None):
        """Fire every due routine (each in its own thread). Returns a dispatch log."""
        out = []
        for r in self.due(now):
            try:
                from longrun.agent import agents as agents_mod
                if not agents_mod.REGISTRY.charge(r["agent"]):
                    self._mark(r["id"], time.time())
                    out.append({"routine": r["id"], "agent": r["agent"], "state": "budget-skip"})
                    continue
            except Exception:  # noqa: BLE001
                pass
            self._mark(r["id"], time.time())
            threading.Thread(target=self._fire, args=(r,), daemon=True,
                             name="routine-" + r["id"]).start()
            out.append({"routine": r["id"], "agent": r["agent"], "state": "dispatched"})
        return out

    def _fire(self, r):
        try:
            from longrun.agent import agents as agents_mod
            a = agents_mod.REGISTRY.resolve(r["agent"]) or {}
            sid = a.get("session")
            if sid:
                _run_agent(sid, r["goal"], model=r.get("model"))
        except Exception:  # noqa: BLE001
            pass


REGISTRY = RoutineRegistry()
_SCHED = {"thread": None}


def start_scheduler(interval=DEFAULT_TICK):
    """Start the single heartbeat thread (idempotent). Called by the server on boot."""
    if _SCHED["thread"] and _SCHED["thread"].is_alive():
        return _SCHED["thread"]

    def loop():
        while True:
            try:
                REGISTRY.tick()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(max(5, int(interval)))

    t = threading.Thread(target=loop, daemon=True, name="routines")
    _SCHED["thread"] = t
    t.start()
    return t

