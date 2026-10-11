#!/usr/bin/env python3
"""Longrun real terminal — a PERSISTENT per-session shell (JAG-281).

The old Terminal panel was a one-shot wrapper around the gated `shell` tool: every
Enter spawned a fresh, stateless process, so `cd`/`export` never survived and the
output was buffered until the process exited. That is why it did not feel like a
terminal.

This module keeps ONE long-lived `bash` per WebUI session, so the panel behaves
like a real terminal: the working directory, environment and shell state persist
across commands, and output is delivered live by short polling.

Security model (deliberate):
  * This is the HUMAN terminal — the operator typing. The agent's own `shell`
    tool keeps its approval gate; this endpoint is a separate, direct shell.
  * It is reachable only behind the harness token (the whole HTTP surface is
    auth-gated) and runs with the workspace as cwd, exactly like the agent shell.
"""

import collections
import os
import subprocess
import threading
import time

MAX_SHELLS = 8          # oldest idle shell is reaped beyond this
IDLE_TIMEOUT = 3600.0   # a shell idle for 1h is reaped
BACKLOG = 2000          # events kept per shell (for cursor catch-up)
_MARK = "\x1e__SF_DONE__"


class Shell:
    """One persistent bash process with a replayable event buffer."""

    def __init__(self, key, cwd=None):
        self.key = key
        self.cwd = cwd or os.path.expanduser("~")
        self.created = time.time()
        self.last = time.time()
        self.busy = False
        self.seq = 0
        self.events = collections.deque(maxlen=BACKLOG)
        self.first_seq = 0
        self._lock = threading.Lock()
        self.proc = subprocess.Popen(
            ["/bin/bash"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=self.cwd, bufsize=0,
        )
        self._t = threading.Thread(target=self._reader, daemon=True)
        self._t.start()

    def _emit(self, kind, **extra):
        with self._lock:
            self.seq += 1
            ev = {"seq": self.seq, "kind": kind}
            ev.update(extra)
            self.events.append(ev)
            self.first_seq = self.events[0]["seq"] if self.events else self.seq
        self.last = time.time()

    def _reader(self):
        out = self.proc.stdout
        try:
            while True:
                line = out.readline()
                if not line:
                    self._emit("exit", text="\n[shell exited]\n")
                    break
                s = line.decode("utf-8", "replace")
                if s.startswith(_MARK):
                    digits = "".join(c for c in s if c.isdigit())
                    self.busy = False
                    self._emit("done", code=int(digits) if digits else 0)
                else:
                    self._emit("out", text=s)
        except Exception:  # noqa: BLE001
            pass

    def run(self, cmd):
        """Send one command line to the persistent shell. Returns {ok} or an error."""
        cmd = str(cmd or "")
        if "\x00" in cmd:
            return {"ok": False, "error": "invalid command"}
        with self._lock:
            alive = self.proc.poll() is None
            if not alive:
                return {"ok": False, "error": "shell exited"}
            if self.busy:
                return {"ok": False, "error": "busy — wait for the current command"}
            self.busy = True
        self._emit("cmd", text=cmd)
        try:
            payload = cmd + "\nprintf '\\n" + _MARK + "%d\\036\\n' $?\n"
            self.proc.stdin.write(payload.encode("utf-8"))
            self.proc.stdin.flush()
        except Exception as e:  # noqa: BLE001
            self.busy = False
            self._emit("done", code=1)
            return {"ok": False, "error": str(e)}
        self.last = time.time()
        return {"ok": True}

    def poll(self, cursor):
        """Return events newer than `cursor` plus the new cursor."""
        with self._lock:
            evs = [e for e in self.events if e["seq"] > int(cursor or 0)]
            reset = int(cursor or 0) < self.first_seq - 1 and bool(self.events)
            return {"events": evs, "cursor": self.seq, "busy": self.busy, "reset": reset,
                    "cwd": self.cwd}

    def kill(self):
        try:
            self.proc.terminate()
        except Exception:  # noqa: BLE001
            pass


_SHELLS = {}
_LOCK = threading.Lock()


def _reap_locked():
    now = time.time()
    dead = [k for k, s in _SHELLS.items() if s.proc.poll() is not None]
    for k in dead:
        _SHELLS.pop(k, None)
    idle = sorted(_SHELLS.items(), key=lambda kv: kv[1].last)
    for k, s in idle:
        over_idle = (now - s.last) > IDLE_TIMEOUT
        over_cap = len(_SHELLS) > MAX_SHELLS and not s.busy
        if over_idle or over_cap:
            s.kill()
            _SHELLS.pop(k, None)


def get(key, cwd=None):
    """Get (or create) the persistent shell for `key`. `cwd` is only used on create."""
    key = str(key or "default")[:64] or "default"
    with _LOCK:
        _reap_locked()
        sh = _SHELLS.get(key)
        if sh and sh.proc.poll() is None:
            return sh
        if sh:
            _SHELLS.pop(key, None)
        sh = Shell(key, cwd)
        _SHELLS[key] = sh
        return sh


def peek(key):
    with _LOCK:
        return _SHELLS.get(str(key or "default")[:64])


def reset(key):
    with _LOCK:
        sh = _SHELLS.pop(str(key or "default")[:64], None)
    if sh:
        sh.kill()
        return True
    return False


def status():
    with _LOCK:
        _reap_locked()
        return [{"key": k, "cwd": s.cwd, "busy": s.busy,
                 "idle_secs": int(time.time() - s.last)} for k, s in _SHELLS.items()]

