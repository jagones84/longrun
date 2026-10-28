#!/usr/bin/env python3
"""Longrun sandbox — real isolation for shell execution.

Backends (auto-detected, first working wins):
  * docker  — `docker run --rm --network none --read-only --tmpfs /tmp
                --cap-drop ALL --security-opt no-new-privileges --user 65534:65534
                -v <workspace>:/work` (a real container: the process does not see
                the host filesystem or the network)
  * bwrap   — bubblewrap: read-only binds of /usr /lib /bin …, tmpfs /tmp,
              a single writable scratch dir, `--unshare-all` (no net, no host)
  * nsjail  — used when installed (same contract as bwrap)
  * none    — host execution WITHOUT isolation; explicitly labelled `sandboxed: false`

The probe result is cached. `backend='auto'` never silently degrades to `none`:
it falls back only to another real sandbox, and reports `none` only when the
operator explicitly asked for it.

JAG-2.7: the SAME rule applies to a backend the harness cannot even name. An
unknown value is a typo, not a request for `auto`: `probe()` raises and
`sandbox.run(backend=...)` refuses instead of executing on the host. Before this,
`sandbox.backend: docker` misspelled as `dockerr` slipped into the auto branch
and ran unchecked on the host (live proof, 2026-10-22).
"""

import json
import os
import selectors
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import uuid

from longrun.util import osutil
from longrun.tools import registry

_probe_lock = threading.Lock()
_probe_cache = None

# JAG-68: live jobs, so a running tool can be STOPPED from the client.
#   job_id -> {"proc": Popen, "argv": [...], "started": ts, "cancelled": bool}
_RUNNING = {}
_RUN_LOCK = threading.Lock()
_WHOLE_RESERVATIONS = {}

# JAG-413: cap the bytes read back from a sandboxed command so a process that
# spews gigabytes cannot exhaust the server's memory (output goes to temp files,
# not pipes, and we only pull MAX_OUTPUT_BYTES per stream).
MAX_OUTPUT_BYTES = int(os.environ.get("LONGRUN_SANDBOX_MAX_OUTPUT",
                                      str(2 * 1024 * 1024)))

# JAG-2.7: the only backend values this module understands. Anything else is a
# typo (or a future backend the harness does not know yet) and must NEVER be
# treated as `auto` — that is how an "isolated" run silently became a host run.
BACKENDS = ("auto", "docker", "bwrap", "nsjail", "none")

# P3 trust profiles (Codex `sandbox_mode` direction): named bundles binding a
# session to an isolation level. `locked` = isolated execution or refusal
# (never the host); `standard` = today's global-config path; `open` = explicit
# host execution. Sessions carry the name; `run(trust=...)` enforces it.
TRUST_PROFILES = ("locked", "standard", "open")


def trust_profile(name):
    """Resolve a trust profile name (pure). Unknown names raise (JAG-2.7).

    Returns {"backend": ...}: "locked" means isolated-required (resolved at
    run time against the probe, never "none"); "none" means explicit host;
    None means defer to the global `sandbox.backend` config.
    """
    n = str(name or "").strip().lower()
    if n == "locked":
        return {"name": "locked", "backend": "locked", "isolated_required": True}
    if n == "standard":
        return {"name": "standard", "backend": None, "isolated_required": False}
    if n == "open":
        return {"name": "open", "backend": "none", "isolated_required": False}
    raise ValueError("sandbox: unknown trust profile %r (expected one of: %s); "
                     "refusing to guess." % (name, ", ".join(TRUST_PROFILES)))


def _read_capped(fh, cap=MAX_OUTPUT_BYTES):
    """Read at most `cap` bytes from a temp file (from offset 0) and decode it,
    appending a truncation marker when the stream was longer."""
    fh.seek(0)
    data = fh.read(cap + 1)
    if len(data) > cap:
        return (data[:cap].decode("utf-8", "replace")
                + "\n...[output truncated at %d bytes]" % cap)
    return data.decode("utf-8", "replace")


def running():
    """Jobs currently executing: [{job, pid, command, seconds}]."""
    now = time.time()
    with _RUN_LOCK:
        items = list(_RUNNING.items())
    return [{"job": k, "pid": v["proc"].pid, "command": " ".join(v["argv"])[:200],
             "seconds": round(now - v["started"], 2),
             "cancel": v.get("cancelled", False)} for k, v in items]


def _kill(entry):
    """SIGTERM then SIGKILL the whole process group of a job (wrapper + children).

    For a docker job the CLI may die while the container keeps running, so we
    also `docker kill <name>` the explicitly named container.
    """
    proc = entry["proc"]
    argv = entry.get("argv") or []
    if argv and os.path.basename(argv[0]) == "docker":
        try:
            name = argv[argv.index("--name") + 1]
            prefix = argv[:3] if argv[1:2] == ["--host"] else argv[:1]
            subprocess.run(prefix + ["kill", name], timeout=10, env=entry.get("env"),
                           capture_output=True, text=True)
        except Exception:  # noqa: BLE001
            pass
    osutil.kill_tree(proc)


def cancel(job_id):
    """Terminate the running job `job_id` (and its children). Idempotent."""
    with _RUN_LOCK:
        entry = _RUNNING.get(job_id)
    if not entry:
        return {"cancelled": False, "job": job_id, "reason": "not running"}
    entry["cancelled"] = True
    _kill(entry)
    return {"cancelled": True, "job": job_id, "pid": entry["proc"].pid}


def _wait_bounded(entry, sinks, timeout, limit):
    """Drain both POSIX pipes without growing either output file past `limit`.

    Popen.wait alone can deadlock on pipes; communicate buffers without a bound.
    See https://docs.python.org/3.12/library/subprocess.html#subprocess.Popen.wait.
    Detached descendants holding a pipe produce a failed, bounded drain, not
    proof of cleanup. The outer container owner must verify their removal.
    """
    proc = entry["proc"]
    deadline = None if timeout is None else time.monotonic() + timeout
    exited_at = None
    why = None
    sizes = {stream: 0 for stream in sinks}
    with selectors.DefaultSelector() as selector:
        try:
            for stream in sinks:
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map() or proc.poll() is None:
                now = time.monotonic()
                if entry["cancelled"]:
                    why = "cancelled"
                    break
                if deadline is not None and now >= deadline:
                    why = "timeout"
                    break
                if proc.poll() is not None:
                    exited_at = exited_at or now
                    if now - exited_at >= 1:
                        why = "output_incomplete"
                        break
                for key, _mask in selector.select(0.05):
                    stream = key.fileobj
                    data = os.read(stream.fileno(), 65536)
                    if not data:
                        selector.unregister(stream)
                        continue
                    remaining = limit - sizes[stream]
                    sinks[stream].write(data[:remaining])
                    sizes[stream] += min(remaining, len(data))
                    if len(data) > remaining:
                        why = "output_limit"
                        break
                if why:
                    break
        except (OSError, ValueError):
            why = "output_error"
        finally:
            if why:
                _kill(entry)
            for stream in sinks:
                stream.close()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        why = why or "output_incomplete"
        _kill(entry)
    return why


def _run_tracked(argv, timeout=None, cwd=None, env=None, job_id=None, output_limit=None):
    """Popen + process-group tracking so the job can be cancelled mid-flight.

    stdout/stderr are redirected to TEMP FILES, not pipes (JAG-413): a command
    that spews gigabytes cannot exhaust the server's memory or deadlock on a full
    pipe buffer — we read back at most MAX_OUTPUT_BYTES per stream.

    With `output_limit`, POSIX pipes are drained concurrently into files capped
    at that many bytes each. Overflow terminates the job; unavailable platforms
    refuse before launch. This opt-in contract is for whole-process experiments.
    """
    if output_limit is not None and (os.name != "posix"
            or type(output_limit) is not int or not 0 < output_limit <= MAX_OUTPUT_BYTES):
        return {"exit_code": 126, "stdout": "", "stderr": "invalid bounded output profile",
                "duration_ms": 0}
    t0 = time.time()
    out_f = tempfile.TemporaryFile()
    err_f = tempfile.TemporaryFile()
    try:
        proc = subprocess.Popen(argv, stdout=out_f if output_limit is None else subprocess.PIPE,
                                stderr=err_f if output_limit is None else subprocess.PIPE,
                                cwd=cwd, env=env, **osutil.popen_kwargs())
    except FileNotFoundError as e:
        out_f.close()
        err_f.close()
        return {"exit_code": 127, "stdout": "", "stderr": "not found: %s" % e,
                "duration_ms": 0}
    except Exception as e:  # noqa: BLE001
        out_f.close()
        err_f.close()
        return {"exit_code": 125, "stdout": "", "stderr": "exec error: %s" % e,
                "duration_ms": 0}
    entry = {"proc": proc, "argv": argv, "env": env, "started": t0, "cancelled": False}
    if job_id:
        with _RUN_LOCK:
            _RUNNING[job_id] = entry
    why = None
    try:
        if output_limit is None:
            proc.communicate(timeout=timeout)
        else:
            why = _wait_bounded(entry, {proc.stdout: out_f, proc.stderr: err_f},
                                timeout, output_limit)
    except subprocess.TimeoutExpired:
        why = "timeout"
        _kill(entry)
        proc.communicate()
    except (OSError, ValueError):
        if output_limit is None:
            raise
        why = "output_error"
        _kill(entry)
        proc.stdout.close()
        proc.stderr.close()
    finally:
        if job_id:
            with _RUN_LOCK:
                _RUNNING.pop(job_id, None)
    capture_failure = why if why in ("output_limit", "output_incomplete", "output_error") else None
    if entry["cancelled"]:
        why = "cancelled"
    out, err = "", ""
    try:
        out = _read_capped(out_f)
        err = _read_capped(err_f)
    except (OSError, ValueError):
        if output_limit is None:
            raise
        capture_failure = "output_error"
    finally:
        for stream in (out_f, err_f):
            try:
                stream.close()
            except (OSError, ValueError):
                if output_limit is None:
                    raise
                capture_failure = "output_error"
    res = {"exit_code": proc.returncode, "stdout": out or "", "stderr": err or "",
           "duration_ms": int((time.time() - t0) * 1000)}
    if why == "timeout":
        res.update({"exit_code": 124, "timeout": True,
                    "stderr": (res["stderr"] or "") + "\ntimeout after %ss" % timeout})
    elif why == "cancelled":
        res.update({"cancelled": True, "exit_code": 130,
                    "stderr": (res["stderr"] or "") + "\ncancelled by user"})
    elif why in ("output_limit", "output_incomplete", "output_error"):
        res.update({why: True, "exit_code": 125,
                    "stderr": (res["stderr"] or "") + "\n" + why.replace("_", " ")})
    if capture_failure:
        res[capture_failure] = True
        if why not in ("cancelled", "timeout"):
            res["exit_code"] = 125
        if capture_failure != why:
            res["stderr"] += "\n" + capture_failure.replace("_", " ")
    return res


def _run(argv, timeout=None, cwd=None, env=None):
    """Blocking run for probes; output is written to temp files and read back
    capped so a chatty command cannot exhaust memory (JAG-413)."""
    t0 = time.time()
    out_f = tempfile.TemporaryFile()
    err_f = tempfile.TemporaryFile()
    try:
        p = subprocess.Popen(argv, stdout=out_f, stderr=err_f, cwd=cwd, env=env)
    except FileNotFoundError as e:
        out_f.close()
        err_f.close()
        return {"exit_code": 127, "stdout": "", "stderr": "not found: %s" % e,
                "duration_ms": int((time.time() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001
        out_f.close()
        err_f.close()
        return {"exit_code": 125, "stdout": "", "stderr": "exec error: %s" % e,
                "duration_ms": int((time.time() - t0) * 1000)}
    timed_out = False
    try:
        p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        p.kill()
        p.communicate()
    out = _read_capped(out_f)
    err = _read_capped(err_f)
    out_f.close()
    err_f.close()
    res = {"exit_code": p.returncode, "stdout": out, "stderr": err,
           "duration_ms": int((time.time() - t0) * 1000)}
    if timed_out:
        res.update({"exit_code": 124, "timeout": True,
                    "stderr": err + "\ntimeout after %ss" % timeout})
    return res


# ----------------------------------------------------------------- probing ---

def _probe_docker(image):
    if not shutil.which("docker"):
        return False, "docker binary not found"
    info = _run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=10)
    if info["exit_code"] != 0:
        return False, "docker daemon unreachable: %s" % (info["stderr"] or "").strip()[:120]
    t = _run(["docker", "run", "--rm", "--network", "none", "--read-only",
              "--tmpfs", "/tmp", "--cap-drop", "ALL",
              "--security-opt", "no-new-privileges", image,
              "sh", "-c", "echo sfprobe"], timeout=60)
    if t["exit_code"] == 0 and "sfprobe" in t["stdout"]:
        return True, "docker %s / image %s" % (info["stdout"].strip(), image)
    return False, "docker run failed: %s" % (t["stderr"] or t["stdout"]).strip()[:160]


def _probe_bwrap():
    if not shutil.which("bwrap"):
        return False, "bwrap binary not found"
    argv = [ "bwrap", "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib",
             "--ro-bind", "/lib64", "/lib64", "--ro-bind", "/bin", "/bin",
             "--ro-bind", "/sbin", "/sbin", "--proc", "/proc", "--dev", "/dev",
             "--tmpfs", "/tmp", "--unshare-all", "--die-with-parent",
             "/bin/echo", "sfprobe"]
    t = _run(argv, timeout=20)
    if t["exit_code"] == 0 and "sfprobe" in t["stdout"]:
        return True, "bubblewrap (unprivileged userns ok)"
    return False, "bwrap: %s" % (t["stderr"] or "").strip()[:160]


def _probe_nsjail():
    if not shutil.which("nsjail"):
        return False, "nsjail binary not found"
    t = _run(["nsjail", "-Mo", "-Q", "--", "/bin/echo", "sfprobe"], timeout=20)
    if t["exit_code"] == 0 and "sfprobe" in t["stdout"]:
        return True, "nsjail"
    return False, "nsjail: %s" % (t["stderr"] or "").strip()[:160]


def probe(force=False):
    """{'backend': str, 'requested': str, 'available': {name: {'ok','detail'}}, 'isolated': bool}

    Raises when the configured `sandbox.backend` is explicit and unusable — either
    unavailable after probing (JAG-431r4b) or not a name this module knows (JAG-2.7).
    """
    global _probe_cache
    with _probe_lock:
        if _probe_cache is not None and not force:
            return _probe_cache
        cfg = registry.load_config()
        image = cfg["sandbox"]["image"]
        requested = cfg["sandbox"]["backend"]
        checks = {}
        for name, fn in (("docker", lambda: _probe_docker(image)),
                         ("bwrap", _probe_bwrap), ("nsjail", _probe_nsjail)):
            ok, detail = fn()
            checks[name] = {"ok": ok, "detail": detail}
        if requested in checks:
            # JAG-431r4b: an EXPLICIT requested backend that fails probe used
            # to silently fall back to `none` (host execution) — an isolation
            # regression invisible to the operator. Only auto-pick a fallback;
            # for an explicit ask, raise so the operator sees the failure.
            if checks[requested]["ok"]:
                chosen = requested
            else:
                raise RuntimeError(
                    "sandbox: explicit backend %r is not available (%s); "
                    "refusing to fall back to host execution. "
                    "Set sandbox.backend=auto to allow auto-pick."
                    % (requested, checks[requested]["detail"]))
        elif requested == "none":
            chosen = "none"
        elif requested == "auto":
            chosen = next((n for n in ("docker", "bwrap", "nsjail") if checks[n]["ok"]), "none")
        else:
            # JAG-2.7: the misspelling branch. `auto` was the implicit `else`, so
            # ANY unrecognized value ("dockerr", "podman", "") silently became an
            # auto-pick — and auto-picking with nothing available is host
            # execution. Name the value and refuse; the operator fixes the typo.
            raise RuntimeError(
                "sandbox: unknown backend %r (expected one of: %s); refusing to "
                "guess — a typo must not silently choose another backend."
                % (requested, ", ".join(BACKENDS)))
        _probe_cache = {"requested": requested, "backend": chosen,
                        "isolated": chosen != "none", "available": checks}
        return _probe_cache


def invalidate_probe():
    """JAG-431r4b: the probe result was cached FOREVER; there was no way to
    force a re-check after, e.g., installing docker. Expose the cache clear."""
    global _probe_cache
    with _probe_lock:
        _probe_cache = None


# -------------------------------------------------------------- workspaces ---

def workspace_for(run_id):
    """Per-run scratch dir, bind-mounted as /work and world-writable for the
    sandbox user (uid 65534 in the container).

    JAG-431r4b: a hostile or accidentally-pathological `run_id` ("../etc",
    "/abs/path", trailing slashes) used to escape the workspace root via
    os.path.join. Sanitize to a single basename + length cap before joining.
    """
    # JAG-533: the scratch root is USER DATA — registry.workspace_dir() resolves
    # it against the data home, never the checkout.
    root = os.path.realpath(registry.workspace_dir())
    raw = (run_id or "adhoc").strip()
    # JAG-431r4b: allow only the safe ASCII set, then take the last path
    # component so a malformed id never escapes the workspace.
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in raw)[:64].strip("_")
    if not safe:
        safe = "adhoc"
    ws = os.path.realpath(os.path.join(root, safe))
    # JAG-431r4b: defence in depth — refuse anything that resolves outside `root`.
    if not (ws == root or ws.startswith(root + os.sep)):
        ws = os.path.join(root, "adhoc")
    os.makedirs(ws, exist_ok=True)
    try:
        os.chmod(ws, 0o755)
    except OSError:
        pass
    return ws


# --------------------------------------------------------------- execution ---

def _whole_run_argv(snapshot, image, arguments, name, uid, gid,
                    gateway_socket=None, extra_env=None):
    """Trusted, fixed Python profile; only frozen input and one socket are mounted.

    Writable files are bounded tmpfs, not host bind mounts. The image must be
    pinned and verified by the runtime/snapshot owner before production use.
    Source: https://docs.docker.com/reference/cli/docker/container/run/.
    """
    argv = ["docker", "--host", "unix:///var/run/docker.sock", "run",
            "--pull", "never", "--rm", "--name", name,
            "--label", "longrun.whole_run=" + name,
            "--init", "--runtime", "runc", "--network", "none",
            "--read-only", "--log-driver", "none", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", "%d:%d" % (uid, gid),
            "--memory", "1024m", "--memory-swap", "1024m",
            "--pids-limit", "64", "--cpus", "2",
            "--mount", "type=bind,src=%s,dst=/input,readonly" % snapshot]
    if gateway_socket:
        argv += ["--mount", "type=bind,src=%s,dst=/state/gateway.sock,readonly"
                 % gateway_socket]
    argv += ["--workdir", "/work", "--entrypoint", "python3"]
    for target, size in (("/work", 128), ("/state", 128), ("/tmp", 64)):
        argv += ["--tmpfs", "%s:rw,noexec,nosuid,nodev,size=%dm,uid=%d,gid=%d,mode=0700" %
                 (target, size, uid, gid)]
    env = {"HOME": "/state/home", "PYTHONPATH": "/input/src",
           "PYTHONDONTWRITEBYTECODE": "1",
           "LONGRUN_DATA_HOME": "/state/home",
           "LONGRUN_DATA_DIR": "/state/data",
           "LONGRUN_CONFIG_DIR": "/state/config",
           "LONGRUN_SESSIONS_DIR": "/state/sessions",
           "LONGRUN_DB": "/state/events.db"}
    env.update(extra_env or {})
    for key in sorted(env):
        argv += ["--env", key + "=" + env[key]]
    return argv + [image] + list(arguments)


def reserve_whole_run():
    """Reserve private input storage under the existing sandbox workspace owner."""
    base = os.path.realpath(registry.workspace_dir())
    os.makedirs(base, exist_ok=True)
    root = os.path.join(base, "h2-" + uuid.uuid4().hex)
    os.mkdir(root, 0o700)
    snapshot = os.path.join(root, "inputs")
    os.mkdir(snapshot, 0o700)
    identity = tuple((os.stat(p).st_dev, os.stat(p).st_ino) for p in (root, snapshot))
    with _RUN_LOCK:
        _WHOLE_RESERVATIONS[snapshot] = identity
    return snapshot


def _image_volumes(image):
    """Anonymous volume paths declared by a cached image, or None if unreadable.

    `--read-only` constrains the root filesystem, not image-declared volumes: an
    image with `VOLUME /data` would get a writable, disk-backed mount outside the
    bounded tmpfs set. Refuse before launch instead of trusting the tag.
    """
    prefix = ["docker", "--host", "unix:///var/run/docker.sock"]
    try:
        result = _run_tracked(
            prefix + ["image", "inspect", "--format", "{{json .Config.Volumes}}", image],
            timeout=10, env={"PATH": os.defpath},
            output_limit=min(4096, MAX_OUTPUT_BYTES))
    except Exception:  # noqa: BLE001
        return None
    if result["exit_code"] != 0:
        return None
    text = (result.get("stdout") or "").strip()
    if text in ("", "null"):
        return {}
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def run_whole(snapshot, image, arguments, timeout=60, job_id=None,
              gateway_socket=None, extra_env=None):
    """Execute a pinned Python image with bounded, disposable writable storage.

    Internal launcher only: the caller must freeze and validate input/runtime
    fidelity. `gateway_socket` (optional) is the single mounted inference channel;
    `extra_env` is trusted container configuration, never candidate input.
    Cleanup verification means absence at the daemon check, not proof against
    a lost launcher or in-flight daemon creation. Production readiness needs
    the snapshot/gateway and crash-recovery owners as well.
    """
    refused = {"ok": False, "exit_code": 126, "stdout": "",
               "stderr": "invalid whole-run profile", "duration_ms": 0,
               "backend": "whole-run(refused)", "cleanup_verified": False}
    try:
        if os.name != "posix" or os.getuid() == 0 or os.getgid() == 0:
            return refused
        uid, gid = os.getuid(), os.getgid()
        base = os.path.realpath(registry.workspace_dir())
        path = os.path.abspath(snapshot)
        root = os.path.dirname(path)
        token = os.path.basename(root)
        if (path != os.path.realpath(path) or os.path.basename(path) != "inputs"
                or os.path.dirname(root) != base or len(token) != 35
                or not token.startswith("h2-")
                or any(c not in "0123456789abcdef" for c in token[3:])):
            return refused
        for directory in (root, path):
            snap_info = os.stat(directory)
            if (not os.path.isdir(directory) or snap_info.st_uid != uid
                    or snap_info.st_mode & 0o077):
                return refused
        identity = tuple((os.stat(p).st_dev, os.stat(p).st_ino) for p in (root, path))
        with _RUN_LOCK:
            if _WHOLE_RESERVATIONS.get(path) != identity:
                return refused
        if (not isinstance(image, str) or len(image) != 71
                or not image.startswith("sha256:")
                or any(c not in "0123456789abcdef" for c in image[7:])):
            return refused
        if (type(timeout) not in (int, float) or not 0 < timeout <= 900
                or not isinstance(arguments, (list, tuple)) or not 0 < len(arguments) <= 128
                or any(not isinstance(a, str) or "\0" in a or len(a) > 8192 for a in arguments)
                or any(c in path for c in ",\n\r")):
            return refused
        volumes = _image_volumes(image)
        if volumes is None or volumes:
            return refused
        if gateway_socket:
            socket_path = os.path.abspath(str(gateway_socket))
            info = os.stat(socket_path)
            if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != uid
                    or info.st_mode & 0o077 or any(c in socket_path for c in ",\n\r")):
                return refused
        for key, value in (extra_env or {}).items():
            if (not isinstance(key, str) or not key.isupper()
                    or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for c in key)
                    or not isinstance(value, str) or "\0" in value or "\n" in value
                    or len(value) > 4096):
                return refused
    except (OSError, TypeError, ValueError):
        return refused
    name = "h2-" + uuid.uuid4().hex
    argv = _whole_run_argv(path, image, arguments, name, uid, gid,
                           gateway_socket=gateway_socket, extra_env=extra_env)
    env = {"PATH": os.defpath}
    prefix = argv[:3]
    clean = False
    try:
        result = _run_tracked(argv, timeout=timeout, env=env, job_id=job_id or name,
                              output_limit=MAX_OUTPUT_BYTES)
    except Exception:
        result = {"exit_code": 125, "stdout": "", "stderr": "whole-run launcher failed",
                  "duration_ms": 0}
    finally:
        try:
            _run_tracked(prefix + ["container", "rm", "--force", name],
                         timeout=10, env=env, output_limit=min(4096, MAX_OUTPUT_BYTES))
            check = _run_tracked(
                prefix + ["container", "ls", "--all", "--filter",
                          "label=longrun.whole_run=" + name, "--format", "{{.ID}}"],
                timeout=10, env=env, output_limit=min(4096, MAX_OUTPUT_BYTES))
            clean = check["exit_code"] == 0 and not check["stdout"].strip()
        except Exception:
            clean = False
    result.update(backend="docker-whole(%s)" % image, container=name,
                  cleanup_verified=clean, ok=result["exit_code"] == 0 and clean)
    if not clean:
        result.update(ok=False, exit_code=125,
                      stderr=result["stderr"] + "\ncontainer cleanup unverified")
    return result


def _docker_argv(cfg, ws, command, image):
    return ["docker", "run", "--rm", "--name", "sf-" + os.urandom(4).hex(),
            "--network", "host" if cfg["sandbox"].get("network") else "none",
            "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "65534:65534", "--memory", "%dm" % cfg["sandbox"]["memory_mb"],
            "--pids-limit", str(cfg["sandbox"]["pids_limit"]),
            "--cpus", str(cfg["sandbox"]["cpus"]),
            "-v", ws + ":/work:rw", "-w", "/work",
            image, "sh", "-c", command]


def _bwrap_argv(ws, command):
    argv = ["bwrap",
            "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64", "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/sbin", "/sbin", "--ro-bind", "/etc", "/etc",
            "--proc", "/proc", "--dev", "/dev",
            "--tmpfs", "/tmp", "--bind", ws, "/work", "--chdir", "/work",
            "--unshare-all", "--die-with-parent", "/bin/sh", "-c", command]
    return argv


def run(command, run_id=None, timeout=None, workspace=None, backend=None, job_id=None,
        trust=None):
    """Execute `command` in the configured sandbox. Returns a result dict with
    exit_code / stdout / stderr / duration_ms / backend / sandboxed / workspace.

    JAG-68: the job is tracked under `job_id` (defaults to `run_id`) so a client
    can STOP it while it is still running via `sandbox.cancel(job_id)`.

    `trust` (P3, Codex direction) is a session trust profile: `locked` forces
    an isolated backend from the probe and REFUSES (exit 126, never the host)
    when only host execution is available; `open` is explicit host execution;
    `standard`/None keeps the path below. An explicit `backend=` still wins
    when it names an isolated backend under `locked`.
    """
    cfg = registry.load_config()
    sb = cfg["sandbox"]
    # JAG-2.7: an explicit `backend=` argument is checked BEFORE the probe, so an
    # unknown name is refused on its own terms (and even a broken config cannot
    # turn it into host execution). Only the four real backends + `none` pass.
    if backend is not None and backend not in BACKENDS:
        return {"ok": False, "exit_code": 126, "sandboxed": False,
                "backend": "refused(%s)" % backend, "command": command,
                "workspace": workspace,
                "error": "sandbox: unknown backend %r (expected one of: %s); "
                         "refusing to run on the host." % (backend, ", ".join(BACKENDS))}
    _locked = False
    _open = False
    if trust is not None:
        _tp = trust_profile(trust)  # raises on unknown names — fail closed
        _locked = bool(_tp.get("isolated_required"))
        _open = _tp.get("backend") == "none"
    p = probe()
    if _open:
        chosen = "none"
        _explicit_open = True
    else:
        chosen = backend or p["backend"]
        _explicit_open = False
    if chosen == "auto":
        chosen = p["backend"]
    if _locked and (chosen in ("none", "auto")
                    or backend not in ("docker", "bwrap", "nsjail")):
        if backend in ("docker", "bwrap", "nsjail"):
            chosen = backend
        else:
            avail = [n for n in ("docker", "bwrap", "nsjail")
                     if (p.get("available") or {}).get(n, {}).get("ok")]
            if not avail:
                return {"ok": False, "exit_code": 126, "sandboxed": False,
                        "backend": "refused(locked)", "command": command,
                        "workspace": workspace,
                        "error": "sandbox: trust=locked requires an isolated "
                                 "backend but only host execution is available; "
                                 "refusing to run."}
            chosen = avail[0]
    timeout = int(timeout or sb["timeout_secs"])
    ws = workspace or workspace_for(run_id)
    job_id = job_id or run_id

    if chosen == "docker":
        argv = _docker_argv(cfg, ws, command, sb["image"])
        res = _run_tracked(argv, timeout=timeout, job_id=job_id)
        res["backend"] = "docker(%s)" % sb["image"]
        res["sandboxed"] = True
    elif chosen == "bwrap":
        res = _run_tracked(_bwrap_argv(ws, command), timeout=timeout, job_id=job_id)
        res["backend"] = "bwrap"
        res["sandboxed"] = True
    elif chosen == "nsjail":
        argv = ["nsjail", "-Mo", "-Q", "--time_limit", str(timeout),
                "--bindmount_ro", "/usr", "--bindmount_ro", "/bin",
                "--bindmount_ro", "/lib", "--bindmount_ro", "/lib64",
                "--bindmount", ws, "/work", "--cwd", "/work",
                "--", "/bin/sh", "-c", command]
        res = _run_tracked(argv, timeout=timeout, job_id=job_id)
        res["backend"] = "nsjail"
        res["sandboxed"] = True
    else:
        # host execution: either the operator explicitly opted out
        # (config sandbox.backend: none) or no real backend is available.
        res = _run_tracked(osutil.shell_argv(command), timeout=timeout, cwd=ws,
                           job_id=job_id)
        res["backend"] = "none(host)"
        res["sandboxed"] = False
        res["warning"] = ("explicit trust=open — runs on the host"
                          if _explicit_open
                          else ("host execution: sandbox.backend is 'none' — runs on the host"
                                if p.get("requested") == "none"
                                else "no sandbox backend available — ran on the host"))
    res["command"] = command
    res["workspace"] = ws
    return res
