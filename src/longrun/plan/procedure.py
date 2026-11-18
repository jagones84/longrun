#!/usr/bin/env python3
"""Executable procedure — the workflow state lives OUTSIDE the model's context.

Source: arXiv:2611.10884, "Keeping LLM Agents on Procedure: Executable
Finite-State Control for Long-Horizon Instruction Fidelity" (round 111). Its
finding is that a long unattended run drifts from a procedure stated once at the
start, and that restating the instructions or resuming a stopped agent only moves
the drift to another shortcut. What held was a finite-state machine enforced by
the runtime at three points:

  1. every tool call is admitted only if the CURRENT state permits it;
  2. a transition commits only through a guard over the observable tool history,
     and the commit is atomic (state + history);
  3. the turn cannot end while a workflow is active and the state is not a
     declared pause point.

The frame (state, history) is persisted to disk by the caller, so compaction and
a service restart cannot erase it — a fresh context reads it back.

Pure and deterministic: no model, no tool execution; the caller feeds events.
"""
from __future__ import annotations

import json
import os
import tempfile
from fnmatch import fnmatch

FORMAT = "longrun-procedure/1"


class Procedure:
    """A flat statechart: states, admitted tool patterns, guarded transitions."""

    def __init__(self, spec):
        spec = spec or {}
        self.start = str(spec.get("start") or "start")
        self.exit = str(spec.get("exit") or "exit")
        self.paused = {str(s) for s in (spec.get("pause") or [])}
        self.states = {}
        for name, row in (spec.get("states") or {}).items():
            row = row or {}
            self.states[str(name)] = [str(p) for p in (row.get("allows") or [])]
        self.transitions = []
        for t in spec.get("transitions") or []:
            t = t or {}
            self.transitions.append({
                "from": str(t.get("from")),
                "to": str(t.get("to")),
                "requires": [str(p) for p in (t.get("requires") or [])],
            })
        self.state = self.start
        self.history = []

    # -- the three enforcement points -------------------------------------
    def admit_tool(self, tool):
        """Eq. 1: a call is admitted only when the current state permits it."""
        if self.state is None:
            return {"allow": True, "state": None, "reason": "no-active-procedure"}
        if self.state not in self.states:
            return {"allow": False, "state": self.state, "reason": "unknown-state"}
        allowed = any(fnmatch(str(tool), p) for p in self.states[self.state])
        return {"allow": allowed, "state": self.state,
                "reason": "permitted-by-state" if allowed else "not-permitted-by-state"}

    def record(self, tool, ok=True):
        """Append to the observable history the guards read."""
        self.history.append({"tool": str(tool), "ok": bool(ok)})
        return self.history[-1]

    def transition(self, target):
        """Eq. 2: commit only through a guarded transition; else stay put."""
        target = str(target)
        cand = next((t for t in self.transitions
                     if t["from"] == self.state and t["to"] == target), None)
        if cand is None:
            return {"ok": False, "state": self.state, "reason": "no-such-transition"}
        missing = [p for p in cand["requires"] if not self._seen(p)]
        if missing:
            return {"ok": False, "state": self.state, "reason": "guard-failed",
                    "missing": missing}
        self.state = target
        return {"ok": True, "state": self.state, "reason": "committed"}

    def end_turn(self):
        """Eq. 3: a turn cannot end mid-procedure outside a pause point."""
        if self.state is None or self.state in self.paused or self.state == self.exit:
            return {"allow": True, "state": self.state, "reason": "no-active-work"}
        return {"allow": False, "state": self.state, "reason": "mid-procedure"}

    # -- persistence (the durable half) -----------------------------------
    def frame(self):
        return {"format": FORMAT, "state": self.state, "history": list(self.history)}

    def save(self, path):
        """Atomic write: a crash leaves the previous frame, never half a frame."""
        self._atomic(path, json.dumps(self.frame(), ensure_ascii=False, sort_keys=True))
        return path

    @classmethod
    def resume(cls, spec, path):
        """Read the persisted frame back; an unreadable file restarts at `start`."""
        proc = cls(spec)
        try:
            with open(path, encoding="utf-8") as fh:
                frame = json.load(fh)
        except (OSError, ValueError):
            return proc
        if isinstance(frame, dict) and frame.get("format") == FORMAT:
            state = frame.get("state")
            if state in proc.states or state is None:
                proc.state = state
            proc.history = [h for h in (frame.get("history") or [])
                            if isinstance(h, dict)]
        return proc

    @staticmethod
    def _atomic(path, text):
        d = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".proc-", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _seen(self, pattern):
        return any(h.get("ok") and fnmatch(str(h.get("tool")), pattern)
                   for h in self.history)


def replay(spec, events):
    """Drive a procedure from a plain event list; returns every decision.

    events: `{"op": "call", "tool": ...}` (admitted?), `{"op": "done", "tool": ...,
    "ok": true}` (recorded), `{"op": "transition", "to": ...}`, `{"op": "end"}`.
    """
    proc = Procedure(spec)
    out = []
    for ev in events or ():
        ev = ev or {}
        op = str(ev.get("op") or "")
        if op == "call":
            out.append({"op": op, **proc.admit_tool(ev.get("tool"))})
        elif op == "done":
            proc.record(ev.get("tool"), ev.get("ok", True))
            out.append({"op": op, "tool": str(ev.get("tool")), "ok": bool(ev.get("ok", True))})
        elif op == "transition":
            out.append({"op": op, **proc.transition(ev.get("to"))})
        elif op == "end":
            out.append({"op": op, **proc.end_turn()})
    return {"format": FORMAT, "state": proc.state, "decisions": out}
