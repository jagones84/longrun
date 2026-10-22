#!/usr/bin/env python3
"""Longrun real terminal — ONE persistent per-session shell (JAG-281).

The old Terminal panel was a one-shot wrapper around the gated `shell` tool: every
Enter spawned a fresh, stateless process, so `cd`/`export` never survived and the
output was buffered until the process exited. That is why it did not feel like a
terminal.

This module keeps ONE long-lived shell per WebUI session, so the panel behaves
like a real terminal: the working directory, environment and shell state persist
across commands, and output is delivered live by short polling.

JAG-2.9 — the SAME shell also backs the agent's `shell` tool whenever the command
would run on the host anyway (sandbox backend `none`). That is what makes the panel
and the agent agree: the agent's command appears in the terminal, the human's `cd`
is still in effect when the agent runs next, and the agent can read (and reset) the
session with `shell{action:"read"|"reset"}`. Under an ISOLATING backend (docker /
bwrap / nsjail) the agent keeps using the sandbox — a terminal on the host would
silently escape the isolation.

Platforms: POSIX uses `$SHELL`/bash/sh; Windows uses PowerShell in `-Command -`
mode (no prompt echo, real exit codes). `LONGRUN_TERM_SHELL` overrides the argv,
e.g. `cmd.exe /Q` or `/bin/zsh`. Works the same on x86-64 and ARM64 because it only
relies on the shell that ships with the system.

Security model (deliberate):
  * This is the HUMAN terminal — the operator typing. The agent's `shell` tool
    keeps its approval gate; this module is the shared execution engine, not a
    second door around approvals.
  * It is reachable only behind the harness token (the whole HTTP surface is
    auth-gated) and runs with the session workspace as cwd.
"""

import collections
import os
import shlex
import shutil
import subprocess
import threading
import time

MAX_SHELLS = 8          # oldest idle shell is reaped beyond this
IDLE_TIMEOUT = 3600.0   # a shell idle for 1h is reaped
BACKLOG = 2000          # events kept per shell (for cursor catch-up)
CAPTURE_MAX = 200_000   # chars of stdout returned to the agent
_MARK = "__SF_DONE__"
_PS_MARKER = ('$c = $(if ($LASTEXITCODE -ne $null) { $LASTEXITCODE } elseif ($?) { 0 } else { 1 }); '
              '$global:LASTEXITCODE = $null; Write-Output ("' + _MARK + '" + $c + [char]30)')

WINDOWS = os.name == "nt"


def _shell_argv():
    """The persistent shell for THIS host. `LONGRUN_TERM_SHELL` wins."""
    override = os.environ.get("LONGRUN_TERM_SHELL")
    if override:
        return shlex.split(override, posix=not WINDOWS)
    if WINDOWS:
        for exe in ("powershell.exe", "pwsh.exe"):
            if shutil.which(exe):
                return [exe, "-NoProfile", "-NoLogo", "-NonInteractive", "-Command", "-"]
        return [os.environ.get("COMSPEC") or "cmd.exe", "/Q"]
    for cand in (os.environ.get("SHELL"), "/bin/bash", "/bin/sh"):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return [cand]
    return ["/bin/sh"]


def _kind(argv):
    exe = os.path.basename(argv[0] or "").lower()
    if "powershell" in exe or exe.startswith("pwsh"):
        return "powershell"
    if exe.startswith("cmd"):
        return "cmd"
    return "posix"


def _quote_path(path, kind):
    """Quote a directory for a `cd` inside the persistent shell."""
    p = str(path or "")
    if kind == "powershell":
        return "'" + p.replace("'", "''") + "'"
    if kind == "cmd":
        return '"' + p.replace('"', '""') + '"'
    return shlex.quote(p)


class Shell:
    """One persistent shell process with a replayable event buffer."""

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
        self._done = threading.Event()
        self.argv = _shell_argv()
        self.kind = _kind(self.argv)
        self.proc = subprocess.Popen(
            self.argv,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=self.cwd, bufsize=0,
        )
        self._t = threading.Thread(target=self._reader, daemon=True)
        self._t.start()

    # ------------------------------------------------------------ events ----
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
                s = line.decode("utf-8", "replace").replace("\r\n", "\n")
                if _MARK in s:
                    # PowerShell/cmd may print a prompt or echo before the marker:
                    # everything before it is host noise, not program output.
                    tail = s[s.index(_MARK):]
                    digits = "".join(c for c in tail if c.isdigit())
                    with self._lock:
                        self.busy = False
                    self._emit("done", code=int(digits) if digits else 0)
                    self._done.set()
                else:
                    self._emit("out", text=s)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------- input ----
    def _payload(self, cmd):
        if self.kind == "powershell":
            return cmd + "\r\n" + _PS_MARKER + "\r\n"
        if self.kind == "cmd":
            return cmd + "\r\n@echo " + _MARK + "%ERRORLEVEL%\r\n"
        return cmd + "\nprintf '\\n" + _MARK + "%d\\036\\n' $?\n"

    def _write(self, cmd):
        self.proc.stdin.write(self._payload(cmd).encode("utf-8"))
        self.proc.stdin.flush()

    def with_cwd(self, cmd, cwd=None):
        """Prefix `cd` when a DIFFERENT directory was asked for explicitly.

        Deliberately changes the persistent shell's cwd too: the terminal and the
        agent are the same session, so after the agent runs in a folder the human
        prompt is there as well.
        """
        if not cwd:
            return cmd
        try:
            if os.path.realpath(cwd) == os.path.realpath(self.cwd):
                return cmd
        except OSError:
            return cmd
        q = _quote_path(cwd, self.kind)
        if self.kind == "powershell":
            prefix = "Set-Location -LiteralPath %s; " % q
        elif self.kind == "cmd":
            prefix = "cd /d %s && " % q
        else:
            prefix = "cd %s && " % q
        self.cwd = cwd
        return prefix + cmd

    def _claim(self):
        with self._lock:
            if self.proc.poll() is not None:
                return "shell exited"
            if self.busy:
                return "busy — wait for the current command"
            self.busy = True
        self._done.clear()
        return None

    def run(self, cmd, origin="user"):
        """Send one command line to the persistent shell (fire and forget)."""
        cmd = str(cmd or "")
        if "\x00" in cmd:
            return {"ok": False, "error": "invalid command"}
        err = self._claim()
        if err:
            return {"ok": False, "error": err}
        self._emit("cmd", text=cmd, origin=origin)
        try:
            self._write(cmd)
        except Exception as e:  # noqa: BLE001
            self.busy = False
            self._emit("done", code=1)
            return {"ok": False, "error": str(e)}
        self.last = time.time()
        return {"ok": True}

    def run_capture(self, cmd, timeout=None, origin="agent", cwd=None):
        """Run one command and WAIT for it, returning its output + exit code.

        Used by the agent's `shell` tool. The command and its output stay in the
        shared buffer, so the human sees exactly what the agent ran.
        """
        cmd = str(cmd or "")
        if "\x00" in cmd:
            return {"ok": False, "exit_code": 1, "stdout": "", "error": "invalid command"}
        cmd = self.with_cwd(cmd, cwd)
        err = self._claim()
        if err:
            return {"ok": False, "exit_code": 1, "stdout": "", "error": err}
        with self._lock:
            start = self.seq
        self._emit("cmd", text=cmd, origin=origin)
        try:
            self._write(cmd)
        except Exception as e:  # noqa: BLE001
            self.busy = False
            return {"ok": False, "exit_code": 1, "stdout": "", "error": str(e)}
        self.last = time.time()
        finished = self._done.wait(timeout if timeout else 120)
        with self._lock:
            evs = [e for e in self.events if e["seq"] > start]
        code = None
        parts = []
        for e in evs:
            if e["kind"] == "out":
                parts.append(e.get("text") or "")
            elif e["kind"] == "done":
                code = e.get("code")
        text = "".join(parts)
        if len(text) > CAPTURE_MAX:
            text = text[:CAPTURE_MAX] + "\n[output truncated]\n"
        if not finished:
            # The command is still running: reset the shell so the NEXT call is not
            # wedged behind a busy prompt. The panel shows the reset.
            reset(self.key)
            return {"ok": False, "exit_code": 124, "stdout": text, "timed_out": True,
                    "error": "timeout — the terminal was reset"}
        return {"ok": code == 0, "exit_code": code if code is not None else 1,
                "stdout": text}

    def poll(self, cursor):
        """Return events newer than `cursor` plus the new cursor."""
        with self._lock:
            evs = [e for e in self.events if e["seq"] > int(cursor or 0)]
            reset_needed = int(cursor or 0) < self.first_seq - 1 and bool(self.events)
            return {"events": evs, "cursor": self.seq, "busy": self.busy,
                    "reset": reset_needed, "cwd": self.cwd, "kind": self.kind}

    def tail(self, lines=80):
        """The last `lines` of the session (what the human typed included)."""
        with self._lock:
            rows = []
            for e in self.events:
                if e["kind"] == "out":
                    rows.extend((e.get("text") or "").splitlines())
                elif e["kind"] == "cmd":
                    who = "agent" if e.get("origin") == "agent" else "you"
                    rows.append("[%s] $ %s" % (who, e.get("text") or ""))
        n = int(lines or 80)
        return "\n".join(rows[-n:]) if n > 0 else "\n".join(rows)

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
        return [{"key": k, "cwd": s.cwd, "busy": s.busy, "kind": s.kind,
                 "idle_secs": int(time.time() - s.last)} for k, s in _SHELLS.items()]
