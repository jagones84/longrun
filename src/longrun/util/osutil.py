#!/usr/bin/env python3
"""Longrun OS abstraction — the single place for platform-specific bits.

The harness was written for POSIX (the DGX). Only a handful of operations are
actually platform-dependent; they live here so the rest of the code stays clean:

  * shell_argv     — ['/bin/sh','-c',cmd] on POSIX, ['cmd','/c',cmd] on Windows
  * popen_kwargs   — put the child in its own process group, so it can be killed
                     as a tree (start_new_session on POSIX, CREATE_NEW_PROCESS_GROUP
                     on Windows)
  * kill_tree      — SIGTERM->SIGKILL the group (POSIX) / taskkill /T /F (Windows)
  * resolve_script — npx/pip -> npx.cmd/pip.exe on Windows (PATHEXT resolution)
  * launcher_path  — the PATH a spawned launcher sees, with the per-user bin dirs
                     (`~/.local/bin`) added: a systemd user service does not carry them

Every function accepts ``on_windows=None`` (default = the real platform) so the
Windows branch is unit-testable from Linux.
"""

import os
import shutil
import signal
import subprocess

IS_WINDOWS = os.name == "nt"
IS_POSIX = os.name == "posix"

# subprocess.CREATE_NEW_PROCESS_GROUP only exists on Windows; keep a literal
# fallback so the Windows branch is importable (and testable) everywhere.
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)


def _win(on_windows=None):
    """True when targeting Windows (explicit flag wins over the real platform)."""
    return IS_WINDOWS if on_windows is None else bool(on_windows)


def shell_argv(command, on_windows=None):
    """An argv that runs ``command`` through the system shell."""
    if _win(on_windows):
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return [comspec, "/c", command]
    return ["/bin/sh", "-c", command]


def popen_kwargs(on_windows=None):
    """Popen kwargs that isolate the child so the whole tree can be killed."""
    if _win(on_windows):
        return {"creationflags": _CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_tree(proc, on_windows=None, grace=5):
    """Terminate ``proc`` AND its children. Best effort, never raises."""
    if proc is None:
        return
    if _win(on_windows):
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, text=True, timeout=10)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:  # noqa: BLE001
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
    try:
        proc.wait(timeout=grace)
    except Exception:  # noqa: BLE001
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass


def service_hint():
    """How to (re)start the harness on this platform — informational only."""
    if IS_WINDOWS:
        return "run.ps1 (or `python server.py`); install as a service with nssm"
    if IS_POSIX:
        return "systemctl --user restart longrun.service"
    return "restart the server process"


def resolve_script(name, on_windows=None):
    """Resolve a command name to something spawnable (npx -> npx.cmd on Windows)."""
    if not name or not _win(on_windows):
        return name
    if os.path.isabs(name) or ("/" in name) or ("\\" in name):
        return name
    found = shutil.which(name)
    if found:
        return found
    for ext in (".cmd", ".exe", ".bat"):
        found = shutil.which(name + ext)
        if found:
            return found
    return name


# Per-user tool directories, in preference order. `~/.local/bin` is where the
# official Node.js installer (and `pip install --user`, `cargo`, `uv`) put their
# launchers on a POSIX host.
_USER_BIN_DIRS = ("~/.local/bin", "~/.npm-global/bin", "~/.volta/bin", "~/bin")


def launcher_path(env=None, on_windows=None):
    """The PATH a spawned launcher (`npx`, `uvx`, …) must SEE, not the one we were given.

    A systemd USER service inherits a minimal PATH
    (`/usr/local/sbin:…:/snap/bin`) that does NOT contain `~/.local/bin`, while a
    per-user Node install lives exactly there. Probed live 2026-10-26 on the DGX:
    `/home/jagones/.local/bin/npx` -> npm existed and ran (node v22.11.0), yet
    `shutil.which("npx")` failed inside the service, so every `command: npx` MCP
    client was reported as "not installed on this host" and would have died with
    ENOENT on spawn.

    ONE owner: the availability probe and the spawn both call this, so the panel
    can never report a runtime the launch cannot use.

    POSIX only — Windows resolves through `resolve_script` (PATHEXT + the
    inherited PATH already carries the install dir). `on_windows` follows the
    module convention so that branch is testable from Linux.
    """
    base = ((env if env is not None else os.environ).get("PATH") or "")
    if _win(on_windows):
        return base
    parts = [p for p in base.split(os.pathsep) if p]
    prepend = []
    for d in _USER_BIN_DIRS:
        full = os.path.expanduser(d)
        if os.path.isdir(full) and full not in parts and full not in prepend:
            prepend.append(full)
    if not prepend:
        return base
    return os.pathsep.join(prepend + parts)

