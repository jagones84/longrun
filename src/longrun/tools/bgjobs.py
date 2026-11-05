#!/usr/bin/env python3
"""Background shell jobs — start a long command, get a handle, poll it (2026-11-05).

Operator: *"Yes shell may be backgrounded but i think its not blocking agent the
shell tool call or agent wait for it? But when command is unfinished agent shall
know look how works modern IDE for that"*.

The foreground `shell` tool WAITS for the command (default 120 s, up to 3600 s),
so a build / install / training run parks the whole turn. A modern IDE instead
hands the terminal back immediately, keeps the process running and lets you look
at its output later. That is exactly what this module adds, with the same shape:

  start(cmd, cwd)  -> {"ok": true, "background": true, "job": "bg-…", "pid": n}
  status(job)      -> {"running": bool, "exit_code": …|None, "tail": "…"}
  stop(job)        -> terminate the whole process group

The process is DETACHED into its own session (POSIX) / process group (Windows),
its stdout+stderr go to ONE log file under the app data dir, and the log is the
only thing kept — the harness never buffers the output in memory. Host execution
only: under an isolating sandbox (docker/bwrap/nsjail) a host process would escape
the isolation, so `_shell` refuses background mode there instead of lying.
"""
import os
import signal
import subprocess
import threading
import time

from longrun.util.paths import DATA_DIR

LOG_DIR = os.path.join(DATA_DIR, "bgjobs")
TAIL_CHARS = 4000        # what `status` returns to the model
MAX_JOBS = 20            # finished jobs kept in memory (the logs stay on disk)
WINDOWS = os.name == "nt"

_JOBS = {}
_LOCK = threading.Lock()
_seq = [0]


def _path(job):
    return os.path.join(LOG_DIR, job + ".log")


def _prune():
    """Drop the OLDEST finished jobs beyond MAX_JOBS (logs are left on disk)."""
    done = [(j["ended"], job) for job, j in _JOBS.items()
            if j["ended"] and j.get("announced")]
    for _ts, job in sorted(done)[:max(0, len(done) - MAX_JOBS)]:
        _JOBS.pop(job, None)


def start(command, cwd=None, label=None, session=None):
    """Run `command` detached and return its handle immediately."""
    cmd = str(command or "")
    if not cmd.strip():
        return {"ok": False, "error": "empty command"}
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except OSError as e:
        return {"ok": False, "error": "cannot create the log dir: %s" % e}
    with _LOCK:
        _seq[0] += 1
        job = "bg-%d-%s" % (int(time.time()), os.urandom(2).hex())
        log = _path(job)
        try:
            out = open(log, "wb")
        except OSError as e:
            return {"ok": False, "error": "cannot open the log: %s" % e}
        kwargs = {"cwd": cwd or None, "stdout": out, "stderr": subprocess.STDOUT,
                  "stdin": subprocess.DEVNULL, "shell": True}
        if WINDOWS:
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True   # kill the GROUP, never the harness
        try:
            proc = subprocess.Popen(cmd, **kwargs)  # noqa: S602 — the command is gated upstream
        except Exception as e:  # noqa: BLE001
            try:
                out.close()
            except OSError:
                pass
            return {"ok": False, "error": "cannot start the job: %s" % e}
        finally:
            try:
                out.close()
            except OSError:
                pass
        _JOBS[job] = {"job": job, "proc": proc, "cmd": cmd, "cwd": cwd or os.getcwd(),
                      "label": str(label or "")[:120], "log": log,
                      "session": str(session or ""), "announced": False,
                      "persisted": False,
                      "started": time.time(), "ended": None, "exit_code": None}
        _prune()
        try:
            threading.Thread(target=_watch, args=(job,), daemon=True,
                             name="bgjob-" + job).start()
        except Exception:  # noqa: BLE001 — the job still runs; only the notice is lost
            pass
    return {"ok": True, "background": True, "running": True, "job": job,
            "pid": proc.pid, "log": log, "cwd": cwd or os.getcwd(), "command": cmd,
            "hint": ("running in the background — the turn is NOT blocked. It will "
                     "announce itself when it finishes; you can also check it with "
                     "shell {action:'status', job:'%s'} and stop it with "
                     "{action:'stop'}." % job)}


def _exit_of(job, rec):
    proc = rec["proc"]
    code = proc.poll()
    if code is not None and rec["ended"] is None:
        rec["ended"] = time.time()
        rec["exit_code"] = int(code)
    return code


def _watch(job):
    """Wait for the detached process, then let the job announce itself.

    Operator (2026-11-05): *"Yes. [a finished job should announce itself]"*. A
    modern IDE tells you the build ended; asking the agent to poll is what made
    the turn look stuck. Nobody has to remember the handle: the watcher reports
    the exit code, and the chat loop hands the SAME notice to the model on its
    next round (see `announce`).
    """
    with _LOCK:
        rec = _JOBS.get(job)
    if not rec:
        return
    try:
        rec["proc"].wait()
    except Exception:  # noqa: BLE001 — a vanished child still counts as finished
        pass
    _finish(job, rec)


def _finish(job, rec):
    """Close the record once, then announce it: live event + transcript copy."""
    _exit_of(job, rec)
    notice = _notice(job, rec)
    sid = str(rec.get("session") or "")
    if sid and not _turn_active(sid):
        # No turn is running, so nobody will pick the notice up in a round: write
        # it into the transcript itself. When a turn IS running the chat loop does
        # it through `_inject`, so this must stay inside the `not active` branch
        # (two copies of one event would be a second truth).
        rec["persisted"] = _persist(sid, describe([notice]))
    if not sid:
        # Nothing to announce to (a raw POST /api/tools/call): let `_prune` recycle it.
        rec["announced"] = True
    try:
        from longrun.core.events import publish
        publish("bgjob.finished", session=sid, job=job,
                exit_code=rec.get("exit_code"), command=rec["cmd"])
    except Exception:  # noqa: BLE001 — the feed is not worth a crash
        pass
    return notice


def _turn_active(sid):
    try:
        from longrun.core.events import turn_active
        return bool(turn_active(sid))
    except Exception:  # noqa: BLE001 — events.db trouble must not hide the notice
        return False


def _persist(sid, text):
    """Append the notice to the session transcript (idle sessions only)."""
    try:
        from longrun.memory import stores
        sess = stores.load_session(sid)
        if not sess:
            return False
        return bool(stores.persist_inject(sess, "observation", text))
    except Exception:  # noqa: BLE001 — a lost notice must never fail the job
        return False


def _notice(job, rec):
    """One plain record of what the job did — the single shape both callers use."""
    ended = rec.get("ended") or time.time()
    return {"job": job, "command": rec["cmd"], "cwd": rec["cwd"],
            "exit_code": rec.get("exit_code"),
            "elapsed_s": round(ended - rec["started"], 1),
            "log": rec["log"], "tail": _tail(rec["log"]),
            "persisted": bool(rec.get("persisted"))}


def describe(notices):
    """The notice text: what ran, how it ended, and the tail of its output."""
    out = []
    for n in notices:
        code = n.get("exit_code")
        state = ("still RUNNING (no exit code)" if code is None else "exit=%d" % int(code))
        out.append("[shell.exec] job %s FINISHED %s after %.1fs — %s\n%s"
                   % (n.get("job"), state, float(n.get("elapsed_s") or 0.0),
                      n.get("command"), (n.get("tail") or "").rstrip()))
    return "\n\n".join(out)


def announce(session):
    """Finished jobs this session has not been told about yet — consumed on read.

    The chat loop calls this once per round: a background job that ended while
    the turn was alive reaches the model as an observation instead of waiting for
    a `status` poll. `persisted` says the transcript already holds the copy (the
    watcher wrote it because no turn was running), so the loop must not write a
    second one.
    """
    sid = str(session or "")
    if not sid:
        return []
    out = []
    with _LOCK:
        for job, rec in _JOBS.items():
            if rec.get("session") != sid or not rec.get("ended") or rec.get("announced"):
                continue
            rec["announced"] = True
            out.append(_notice(job, rec))
    return out


def status(job):
    """Running? exit code? last output? — one poll, never blocks."""
    job = str(job or "").strip()
    if not job:
        return {"ok": False, "error": "job required (the id returned when it started)"}
    with _LOCK:
        rec = _JOBS.get(job)
    if not rec:
        return {"ok": False, "error": "unknown job %r — it was never started in this "
                                      "process (a restart forgets the handles)" % job}
    code = _exit_of(job, rec)
    return {"ok": True, "job": job, "running": code is None,
            "exit_code": (None if code is None else int(code)),
            "elapsed_s": round((rec["ended"] or time.time()) - rec["started"], 1),
            "command": rec["cmd"], "cwd": rec["cwd"], "log": rec["log"],
            "tail": _tail(rec["log"])}


def stop(job):
    """Terminate the job's whole process group (a build spawns children)."""
    job = str(job or "").strip()
    with _LOCK:
        rec = _JOBS.get(job)
    if not rec:
        return {"ok": False, "error": "unknown job %r" % job}
    proc = rec["proc"]
    if proc.poll() is not None:
        return {"ok": True, "job": job, "stopped": False, "exit_code": int(proc.returncode),
                "note": "it had already finished"}
    try:
        if WINDOWS:
            proc.terminate()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:  # noqa: BLE001 — a dead child is not an error
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
    try:
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001
        try:
            if not WINDOWS:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except Exception:  # noqa: BLE001
            pass
    _exit_of(job, rec)
    return {"ok": True, "job": job, "stopped": True,
            "exit_code": rec.get("exit_code"), "tail": _tail(rec["log"])}


def action(verb, job):
    """`status` / `stop`, one door for the shell tool."""
    v = str(verb or "").strip().lower()
    if v in ("status", "poll", "jobs"):
        return status(job)
    if v in ("stop", "kill", "terminate"):
        return stop(job)
    return {"ok": False, "error": "unknown background action %r" % verb}


def _tail(path, limit=TAIL_CHARS):
    """The LAST `limit` chars of the log (a huge build log must not flood the model)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > limit:
                f.seek(size - limit)
                head = f.read(limit)
                return "…[truncated %d chars]…\n" % (size - limit) + \
                    head.decode("utf-8", "replace")
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""
