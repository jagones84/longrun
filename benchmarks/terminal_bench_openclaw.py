#!/usr/bin/env python3
"""OpenClaw as an arm in Terminal-Bench — the second harness on the same tasks.

Why this file exists: `benchmarks/terminal_bench_agent.py` measures Longrun alone, so
the official suite could only compare a harness against the ORACLE. A ranking needs
two arms on the same end-state-graded tasks.

The design is the same one Claw-SWE-Bench uses, and the same one the Longrun arm
already proves: the runtime travels INTO the task container, because the score is the
machine's final state — a harness whose tools run on the host edits nothing the tests
can see.

OpenClaw is a Node application, so the payload is the host's own `node` binary plus
its installed package (measured 2026-11-01: `OpenClaw 2026.10.9`, node v24.22.1 — the
node the app itself demands; v26.8.1 is refused by its engine check). Both are copied
with one `put_archive`, and the run is `openclaw agent exec --isolated --auth-env-only`
so no ambient config or gateway is needed inside the container.

Run:
    scripts/bench-terminal-bench.sh <tag> --arm openclaw hello-world
"""
import base64
import io
import json
import os
import posixpath
import shlex
import tarfile
import time
from pathlib import Path
from typing import Any, Mapping

from benchmarks.terminal_bench_forensics import (
    MAX_TRACE_ITEMS,
    is_openclaw_trajectory_path,
    openclaw_trace,
    session_key_for_id,
    write_forensic,
)

try:  # inside the terminal-bench venv
    from terminal_bench.agents.base_agent import AgentResult, BaseAgent
    from terminal_bench.agents.failure_mode import FailureMode
    HAS_TB = True
except ImportError:  # the acceptance battery's python has no `terminal_bench`
    HAS_TB = False

    class BaseAgent:  # structural stand-in: only the battery imports this module
        def __init__(self, **kwargs):
            self._version = kwargs.get("version")
            self._prompt_template = kwargs.get("prompt_template")

    class AgentResult:  # mirror of the tb model, same field names
        def __init__(self, total_input_tokens=0, total_output_tokens=0,
                     failure_mode=None, timestamped_markers=None):
            self.total_input_tokens = total_input_tokens
            self.total_output_tokens = total_output_tokens
            self.failure_mode = failure_mode
            self.timestamped_markers = timestamped_markers or []

    class FailureMode:
        NONE = "none"
        UNKNOWN = "unknown"


# The node openclaw itself accepts (`openclaw --version` on 26.8.1 prints the
# "requires Node >=24.22.1 <25, or >=26.12.1" refusal, so the payload pins 24.x).
NODE_BIN = Path("/home/jagones/.nvm/versions/node/v24.22.1/bin/node")
OC_PKG = Path("/home/jagones/.local/node/lib/node_modules/openclaw")
PAYLOAD = Path("/tmp/openclaw_tb_payload.tar")  # built once, reused by every trial
DEST = "/opt/oc"


def _dotenv_key(name):
    """The provider key: the environment first, then the operator's `~/.hermes/.env`."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        for line in Path(os.path.expanduser("~/.hermes/.env")).read_text(
                encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def openclaw_model(model_name):
    """`openrouter:z-ai/x` (longrun's spelling) -> `openrouter/z-ai/x` (openclaw's)."""
    return str(model_name or "").replace(":", "/", 1) if ":" in str(model_name or "") \
        else str(model_name or "")


def payload_tar():
    """One tar with `node` + the openclaw package, cached across trials.

    Uncompressed on purpose: `put_archive` streams it locally, so gzip would only
    buy CPU time. The cache is invalidated when the package or the node binary is
    newer than the tar.
    """
    if not NODE_BIN.is_file() or not OC_PKG.is_dir():
        raise RuntimeError("openclaw payload missing: %s / %s" % (NODE_BIN, OC_PKG))
    newest = max(NODE_BIN.stat().st_mtime,
                 max(p.stat().st_mtime for p in OC_PKG.rglob("*") if p.is_file()))
    if PAYLOAD.is_file() and PAYLOAD.stat().st_mtime >= newest:
        return PAYLOAD.read_bytes()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(str(NODE_BIN), arcname="node")
        tar.add(str(OC_PKG), arcname="openclaw")
    data = buf.getvalue()
    PAYLOAD.write_bytes(data)
    return data


class _Container:
    """The two things this arm needs from a tb terminal (exec + a file drop)."""

    def __init__(self, container):
        self.c = container

    def sh(self, cmd, timeout=None):
        kwargs = {}
        if timeout:
            kwargs["timeout_sec"] = timeout
        r = self.c.exec_run(["bash", "-lc", cmd], **kwargs)
        out = r.output or b""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return r.exit_code, out


def _capture_openclaw_forensic(
    box: Any,
    envelope: Mapping[str, Any],
    raw: str,
    logging_dir: str | os.PathLike[str] | None,
    api_key: str,
) -> None:
    """Export OpenClaw's redacted trajectory before its task container is removed."""
    if not logging_dir:
        return
    trajectory_files = {}
    trajectory_files_truncated = False
    stderr = ""
    capture_error = ""
    phase = "stderr-read"
    try:
        _, stderr = box.sh("cat /tmp/oc/err.log")
        session_id = str(envelope.get("sessionId") or "")
        if not session_id:
            phase = "session-id"
            raise RuntimeError("OpenClaw did not return a sessionId")

        # OpenClaw stores trajectory events in per-agent SQLite. The supported
        # exporter materializes a redacted bundle; JSONL sidecars are not the store.
        # Source: https://docs.openclaw.ai/tools/trajectory#capture-storage
        # Session key/ID mapping: https://docs.openclaw.ai/reference/session-management-compaction/schema#session-keys-(sessionkey)
        cli = ("%s/node" % DEST, "%s/openclaw/openclaw.mjs" % DEST)
        cli_cmd = " ".join(shlex.quote(part) for part in cli)
        env_prefix = "HOME=/tmp/oc OPENCLAW_STATE_DIR=/tmp/oc/state"
        phase = "session-list"
        rc, session_raw = box.sh(
            "cd /tmp/oc && %s %s sessions --json" % (env_prefix, cli_cmd)
        )
        if rc != 0:
            raise RuntimeError("OpenClaw session listing failed")
        session_key = session_key_for_id(json.loads(session_raw), session_id)
        if not session_key:
            raise RuntimeError("OpenClaw sessionId has no unique sessionKey")

        export_name = "terminal-bench-session"
        phase = "trajectory-export"
        export_cmd = " ".join(shlex.quote(part) for part in (
            *cli,
            "sessions",
            "export-trajectory",
            "--session-key",
            session_key,
            "--workspace",
            "/tmp/oc",
            "--output",
            export_name,
            "--json",
        ))
        rc, export_result = box.sh(
            "cd /tmp/oc && %s %s" % (env_prefix, export_cmd)
        )
        if rc != 0:
            raise RuntimeError(
                "OpenClaw trajectory export failed (exit %s): %s"
                % (rc, (export_result or "").strip()[-300:])
            )

        export_root = posixpath.join(
            "/tmp/oc", ".openclaw", "trajectory-exports", export_name
        )
        phase = "bundle-list"
        rc, listing = box.sh("find %s -type f" % shlex.quote(export_root))
        if rc != 0:
            raise RuntimeError("OpenClaw trajectory bundle is unavailable")
        paths = [path for path in (listing or "").splitlines()
                 if is_openclaw_trajectory_path(path)]
        trajectory_files_truncated = len(paths) > MAX_TRACE_ITEMS
        phase = "bundle-read"
        for path in paths[:MAX_TRACE_ITEMS]:
            rc, content = box.sh("cat " + shlex.quote(path))
            if rc == 0:
                name = posixpath.relpath(path.replace("\\", "/"), export_root)
                trajectory_files[name] = content
    except Exception as exc:  # noqa: BLE001 — forensic capture never grades the task
        detail = str(exc).strip()
        capture_error = "%s: %s%s" % (
            phase,
            type(exc).__name__,
            (": " + detail[:300]) if detail else "",
        )
    trace = openclaw_trace(
        envelope or {"raw_output": raw or ""},
        stderr=stderr or "",
        trajectory_files=trajectory_files,
        secrets=(api_key,) if api_key else (),
        trajectory_files_truncated=trajectory_files_truncated,
        capture_error=capture_error,
    )
    try:
        write_forensic(
            logging_dir, "openclaw-forensic.json", trace,
            secrets=(api_key,) if api_key else (),
        )
    except Exception:  # noqa: BLE001 — evidence failure must not fail a solved task
        pass


class OpenClawAgent(BaseAgent):
    def __init__(self, model_name="openrouter:z-ai/glm-5.3-flash", timeout=1800, **kwargs):
        super().__init__(**kwargs)
        self.model_name = model_name
        self.timeout = float(timeout or 1800)

    @staticmethod
    def name():
        return "openclaw"

    # ------------------------------------------------------------------ setup
    def _upload(self, box):
        data = payload_tar()
        box.sh("mkdir -p %s" % DEST, )
        box.c.put_archive(DEST, io.BytesIO(data))
        return len(data)

    def _check(self, box):
        code, out = box.sh("%s/node %s/openclaw/openclaw.mjs --version" % (DEST, DEST))
        if code != 0:
            raise RuntimeError("openclaw does not start in the container:\n" + out[-1500:])
        return out.strip()

    def _run(self, box, workspace, instruction, key):
        """One headless embedded turn, detached: a blocking exec has no cancellation."""
        box.sh("mkdir -p /tmp/oc/state")
        # base64 → the prompt cannot collide with a heredoc sentinel or carry a quote.
        b64 = base64.b64encode(instruction.encode("utf-8")).decode("ascii")
        box.sh("echo %s | base64 -d > /tmp/oc/task.txt" % b64)
        cmd = ["%s/node" % DEST, "%s/openclaw/openclaw.mjs" % DEST, "agent", "exec",
               "--isolated", "--state-dir", "/tmp/oc/state", "--auth-env-only",
               "--model", openclaw_model(self.model_name),
               "--cwd", workspace, "--timeout", str(int(self.timeout)), "--json",
               "--message-file", "/tmp/oc/task.txt"]
        line = ("cd %s && OPENROUTER_API_KEY=%s HOME=/tmp/oc nohup %s "
                "> /tmp/oc/out.json 2> /tmp/oc/err.log; echo $? > /tmp/oc/rc"
                % (workspace, json.dumps(key), " ".join(cmd)))
        box.sh("rm -f /tmp/oc/out.json /tmp/oc/rc")
        box.sh("nohup bash -c %s > /dev/null 2>&1 &" % json.dumps(line))

    def _wait(self, box):
        deadline = time.time() + self.timeout + 120
        while time.time() < deadline:
            code, out = box.sh("test -s /tmp/oc/rc && echo YES || echo NO")
            if "YES" in out:
                _, raw = box.sh("cat /tmp/oc/out.json")
                _, rc = box.sh("cat /tmp/oc/rc")
                return {"rc": (rc or "").strip(), "raw": raw}
            time.sleep(5)
        return {"rc": "timeout", "raw": ""}

    # -------------------------------------------------------------------- run
    def perform_task(self, instruction, session, logging_dir=None):
        box = _Container(session.container)
        key = _dotenv_key("OPENROUTER_API_KEY")
        t0 = time.time()
        tokens_in = tokens_out = 0
        raw = ""
        env = {}
        try:
            _, ws = box.sh("pwd")
            workspace = (ws or "/app").strip().splitlines()[-1] or "/app"
            self._upload(box)
            self._check(box)
            self._run(box, workspace, instruction, key)
            res = self._wait(box)
            raw = res.get("raw") or ""
            env = {}
            try:
                env = json.loads(raw or "{}")
            except ValueError:
                env = {"parse_error": "invalid JSON", "raw_output": raw}
            usage = env.get("usage") or {}
            tokens_in = int(usage.get("input") or 0)
            tokens_out = int(usage.get("output") or 0)
            if logging_dir:
                Path(logging_dir).mkdir(parents=True, exist_ok=True)
                (Path(logging_dir) / "openclaw-turn.json").write_text(
                    json.dumps({"workspace": workspace, "rc": res.get("rc"),
                                "ok": env.get("ok"), "status": env.get("status"),
                                "final": (env.get("final") or "")[:2000],
                                "usage": usage, "wall_s": round(time.time() - t0, 1)},
                               indent=1), encoding="utf-8")
            # A turn that did not answer is a HARNESS failure, never a solved task.
            failed = (res.get("rc") != "0") or (env.get("ok") is not True)
            return AgentResult(
                total_input_tokens=tokens_in,
                total_output_tokens=tokens_out,
                failure_mode=FailureMode.NONE if not failed else FailureMode.UNKNOWN,
            )
        except Exception as exc:  # noqa: BLE001 — a harness fault is an agent failure
            print("OpenClawAgent failed: %r" % (exc,), flush=True)
            return AgentResult(failure_mode=FailureMode.UNKNOWN)
        finally:
            _capture_openclaw_forensic(
                box, env, raw, logging_dir, key,
            )
