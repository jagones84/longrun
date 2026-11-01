#!/usr/bin/env python3
"""Longrun as an ARM in Terminal-Bench (the official, end-state-graded suite).

Terminal-Bench runs the agent and the task in the SAME container: the score is the
task's own tests run against the machine's final state, so a harness whose tools
touch the host would change nothing and score 0 for a reason that has nothing to do
with the model. Longrun is an HTTP service, so the honest way to seat it inside the
task container is the one Claw-SWE-Bench uses for every claw: take the runtime with
you.

This agent (host side) therefore:

  1. copies `src/longrun` + `server.py` into the task container (tar over the docker
     API — no network, no image rebuild);
  2. starts `server.py` INSIDE the container, bound to 127.0.0.1, with the task
     directory as the session workspace;
  3. drives it over its own REST API through `docker exec` (the port is not
     published, so every call is a short python one-liner inside the container);
  4. puts the server in benchmark mode (approvals=full, no verifier, routing pinned
     to the arm's model — the same preparation `benchmarks/longrun_adapter.setup()`
     applies to the operator's live service);
  5. runs ONE headless turn with the task instruction, detached, and polls the
     reply file (a blocking exec has no timeout, and a task may legitimately take
     longer than any RPC should);
  6. returns the token totals from the harness's own cost ledger.

Usage (from the terminal-bench checkout):

    .venv/bin/tb run -p original-tasks -t hello-world \
        --agent-import-path benchmarks.terminal_bench_agent:LongrunAgent \
        --agent-kwarg model_name=openrouter:z-ai/glm-5.3-flash

The wrapper `scripts/bench-terminal-bench.sh` is the supported entry point.
"""
import io
import json
import os
import tarfile
import time
from pathlib import Path

try:  # the real run happens inside the terminal-bench venv
    from terminal_bench.agents.base_agent import AgentResult, BaseAgent
    from terminal_bench.agents.failure_mode import FailureMode
    HAS_TB = True
except ImportError:  # the acceptance battery's python has no `terminal_bench`
    HAS_TB = False

    class BaseAgent:  # structural stand-in: only the battery imports this module
        def __init__(self, **kwargs):
            self._version = kwargs.get("version")
            self._prompt_template = kwargs.get("prompt_template")

    class AgentResult:  # noqa: D101 — mirror of the tb model, same field names
        def __init__(self, total_input_tokens=0, total_output_tokens=0,
                     failure_mode=None, timestamped_markers=None):
            self.total_input_tokens = total_input_tokens
            self.total_output_tokens = total_output_tokens
            self.failure_mode = failure_mode
            self.timestamped_markers = timestamped_markers or []

    class FailureMode:  # noqa: D101 — only the two members this adapter sets
        NONE = "none"
        UNKNOWN = "unknown"

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src" / "longrun"
SHIM = REPO / "server.py"
PORT = 8791
#: Where the harness lands inside the task container.
DEST = "/opt/longrun-agent"
#: Built once, then reused by every trial of a run (see `payload_tar`).
PAYLOAD = Path("/tmp/longrun_tb_payload.tar")


def _dotenv_key(name):
    """The provider key: the environment first, then the operator's `~/.hermes/.env`."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        for line in Path(os.path.expanduser("~/.hermes/.env")).read_text(
                encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _api_client_code(method, path, body=None, port=PORT, timeout=120):
    """The python program that performs ONE REST call INSIDE the task container.

    Pure and testable on purpose: the first version embedded the JSON body with
    `%s` instead of `%r`, so python received a dict literal and `json.loads(dict)`
    raised — the harness answered every call with an error traceback and the bench
    looked like a model failure (measured 2026-10-31, `lr-hello`).
    """
    payload = json.dumps(body) if body is not None else "null"
    return (
        "import json, urllib.request, urllib.error\n"
        "_b = %r\n_bd = %r\n_body = json.loads(_bd) if _bd != 'null' else None\n"
        "_d = json.dumps(_body).encode() if _body is not None else None\n"
        "_r = urllib.request.Request('http://127.0.0.1:%d' + _b, data=_d,\n"
        "    headers={'Content-Type': 'application/json'}, method=%r)\n"
        "try:\n"
        "    with urllib.request.urlopen(_r, timeout=%d) as _x:\n"
        "        print(_x.status); print(_x.read().decode('utf-8', 'replace'))\n"
        "except urllib.error.HTTPError as _e:\n"
        "    print(_e.code); print(_e.read().decode('utf-8', 'replace'))\n"
        % (path, payload, port, method, timeout))


def _payload_sources():
    """(path, arcname) pairs that travel into the task container."""
    items = [(SRC, "src/longrun"), (SHIM, "server.py")]
    for item in sorted((REPO / "config").iterdir()):
        # Never ship the operator's MCP clients: they point at the HOST
        # (`http://192.168.1.37:3344/mcp`), so the in-container server booted
        # with them and logged `PMCP: connected with 26 tools` (measured
        # 2026-10-31). The score is the task container's end state — an arm
        # that can act outside it is not being measured.
        if item.name.startswith("mcp_clients"):
            continue
        items.append((item, "config/" + item.name))
    return items


def payload_tar():
    """One tar with the runtime and the shipped config, cached across trials.

    Built ONCE per run on purpose. A per-trial tar is a non-atomic snapshot of the
    working tree, so editing the repo while a sweep runs ships a torn tree: measured
    2026-10-31 (`hard1`, fix-code-vulnerability), `httpapi.py` from one revision and
    `server.py` from another booted into `ImportError: cannot import name
    'heartbeat_frame' from partially initialized module` — a circular import that
    does not exist at the commit the run was supposed to measure. The cache is
    invalidated when any source file is newer than the tar.
    """
    sources = _payload_sources()
    newest = max(p.stat().st_mtime for src, _ in sources
                 for p in ([src] + sorted(src.rglob("*")) if src.is_dir() else [src]))
    if PAYLOAD.is_file() and PAYLOAD.stat().st_mtime >= newest:
        return PAYLOAD.read_bytes()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for src, arc in sources:
            tar.add(str(src), arcname=arc)
    data = buf.getvalue()
    PAYLOAD.write_bytes(data)
    return data


class _Container:
    """Thin wrapper over the tb container: every call is docker exec."""

    def __init__(self, container):
        self.c = container

    def sh(self, cmd, check=False, timeout_note=""):
        res = self.c.exec_run(["bash", "-lc", cmd], user="root")
        out = (res.output or b"").decode("utf-8", "replace") if isinstance(
            res.output, (bytes, bytearray)) else str(res.output or "")
        if check and res.exit_code != 0:
            raise RuntimeError("container command failed (%s)%s: %s%s"
                               % (res.exit_code, timeout_note, cmd, out[-600:]))
        return res.exit_code, out

    def python(self, code, check=True):
        """Run a python program inside the container (the REST client)."""
        return self.sh("python3 - <<'PYEOF'\n%s\nPYEOF" % code, check=check)

    def api(self, method, path, body=None, timeout=120):
        rc, out = self.python(_api_client_code(method, path, body, PORT, timeout),
                              check=False)
        if rc != 0:
            return 0, {"error": out[-400:]}
        line, _, rest = out.partition("\n")
        try:
            status = int(line.strip())
        except ValueError:
            return 0, {"error": out[-400:]}
        try:
            return status, json.loads(rest or "{}")
        except ValueError:
            return status, {"raw": rest[:600]}


class LongrunAgent(BaseAgent):
    """`tb run --agent-import-path benchmarks.terminal_bench_agent:LongrunAgent`."""

    def __init__(self, model_name="openrouter:z-ai/glm-5.3-flash", timeout=1800,
                 max_steps=60, **kwargs):
        super().__init__(**kwargs)
        self.model_name = model_name
        self.timeout = float(timeout)
        self.max_steps = int(max_steps)

    @staticmethod
    def name():
        return "longrun"

    # ------------------------------------------------------------------ setup
    def _upload(self, box):
        """Ship the runtime AND the shipped config: without `config/providers.yaml`
        the harness falls back to built-in defaults that point at the operator's
        local router (`http://127.0.0.1:8080`), which does not exist inside a task
        container — measured 2026-10-31: the first turn died with
        `provider unreachable: http://127.0.0.1:8080/v1/chat/completions`.

        The payload itself comes from `payload_tar()`, built once per run."""
        data = payload_tar()
        box.sh("mkdir -p %s" % DEST, check=True)
        # put_archive needs a file object; the container path is the tar root.
        box.c.put_archive(DEST, io.BytesIO(data))
        return len(data)

    def _ensure_python(self, box):
        rc, out = box.sh("python3 -c 'import sys; print(sys.version_info[:2])'")
        if rc != 0:
            box.sh("apt-get update -qq && apt-get install -y -qq python3", check=True)
            rc, out = box.sh("python3 -c 'import sys; print(sys.version_info[:2])'")
            if rc != 0:
                raise RuntimeError("no python3 in the task container")
        rc, _ = box.sh("python3 -c 'import yaml'")
        if rc != 0:
            box.sh("(python3 -m pip --version >/dev/null 2>&1 || "
                   "apt-get update -qq && apt-get install -y -qq python3-pip) >/dev/null 2>&1", check=False)
            box.sh("python3 -m pip install --quiet --break-system-packages pyyaml "
                   "|| apt-get install -y -qq python3-yaml", check=True)
            box.sh("python3 -c 'import yaml'", check=True)
        return out.strip()

    def _start_server(self, box, key):
        env = {
            "OPENROUTER_API_KEY": key,
            "LONGRUN_CONFIG_DIR": "/tmp/lr/config",
            "LONGRUN_SESSIONS_DIR": "/tmp/lr/sessions",
            "LONGRUN_DATA_DIR": "/tmp/lr/data",
            "LONGRUN_DB": "/tmp/lr/events.db",
            "LONGRUN_GRAPH_DIR": "/tmp/lr/graphs",
            "LONGRUN_EDITS_DIR": "/tmp/lr/edits",
            "LONGRUN_RUNS_DIR": "/tmp/lr/runs",
            "LONGRUN_COSTS_DIR": "/tmp/lr/costs",
            "LONGRUN_THREADS_DIR": "/tmp/lr/threads",
            "LONGRUN_TOKENS_OFF": "1",
        }
        for k in ("LONGRUN_DATA_DIR", "LONGRUN_CONFIG_DIR", "LONGRUN_SESSIONS_DIR"):
            box.sh("mkdir -p %s" % env[k])
        cmd = ("cd %s && PYTHONPATH=%s/src nohup python3 %s/server.py "
               "--host 127.0.0.1 --port %d > /tmp/lr/server.log 2>&1 & echo $! > /tmp/lr/pid"
               % (DEST, DEST, DEST, PORT))
        box.sh("mkdir -p /tmp/lr")
        envs = " ".join("%s=%s" % (k, json.dumps(v)) for k, v in env.items())
        box.sh("export %s; %s" % (envs, cmd), check=False)
        deadline = time.time() + 60
        while time.time() < deadline:
            code, _ = box.sh("python3 -c \"import urllib.request;"
                             "print(urllib.request.urlopen('http://127.0.0.1:%d/api/status',"
                             "timeout=3).status)\"" % PORT)
            if code == 0:
                return True
            time.sleep(1)
        _, log = box.sh("tail -30 /tmp/lr/server.log")
        raise RuntimeError("the harness never came up in the container:\n" + log[-1500:])

    def _bench_mode(self, box, workspace):
        """Same preparation as benchmarks/longrun_adapter.setup(): a headless bench."""
        box.api("POST", "/api/tools", {
            "approvals": {"mode": "full",
                          "kinds": {"memory": "auto", "proposals": "auto",
                                    "skills": "auto", "subagent": "auto"}},
            "verifier": {"enabled": False}})
        if self.model_name:
            box.api("POST", "/api/routing",
                    {"roles": {r: {"model": self.model_name}
                               for r in ("chat", "agent", "subagent", "summarizer")}})
        st, obj = box.api("POST", "/api/sessions", {"title": "tb"})
        sid = obj.get("id") or obj.get("session")
        if not sid:
            raise RuntimeError("no session from the harness: %s" % obj)
        if self.model_name:
            box.api("POST", "/api/sessions/%s/model" % sid, {"model": self.model_name})
        st, obj = box.api("POST", "/api/workspace", {"session": sid, "workspace": workspace})
        if st != 200 or obj.get("ok") is False:
            raise RuntimeError("workspace refused: %s" % obj)
        return sid

    def _chat(self, box, sid, instruction):
        """One headless turn, detached: a blocking exec would have no timeout."""
        req = ("import json, urllib.request, time\n"
               "body = json.dumps({'session': %r, 'message': %r, 'headless': True,"
               " 'model': %r, 'max_steps': %d}).encode()\n"
               "r = urllib.request.Request('http://127.0.0.1:%d/api/chat', data=body,\n"
               "    headers={'Content-Type': 'application/json'}, method='POST')\n"
               "t0 = time.time()\n"
               "try:\n"
               "    with urllib.request.urlopen(r, timeout=%d) as x:\n"
               "        out = {'status': x.status, 'body': x.read().decode('utf-8','replace')}\n"
               "except Exception as e:\n"
               "    out = {'status': 0, 'error': repr(e)[:400]}\n"
               "out['elapsed'] = round(time.time()-t0, 1)\n"
               "open('/tmp/lr/reply.json','w').write(json.dumps(out))\n"
               % (sid, instruction, self.model_name, self.max_steps, PORT,
                  int(self.timeout)))
        box.sh("rm -f /tmp/lr/reply.json")
        path = "/tmp/lr/chat.py"
        box.sh("cat > %s <<'PYEOF'\n%s\nPYEOF" % (path, req), check=True)
        box.sh("nohup python3 %s > /tmp/lr/chat.log 2>&1 &" % path, check=False)

    def _wait_reply(self, box):
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            rc, out = box.sh("test -s /tmp/lr/reply.json && echo YES || echo NO")
            if "YES" in out:
                rc2, raw = box.sh("cat /tmp/lr/reply.json")
                try:
                    return json.loads(raw)
                except ValueError:
                    return {"status": 0, "error": "unparsable reply: " + raw[-300:]}
            time.sleep(5)
        return {"status": 0, "error": "timeout after %ss" % int(self.timeout)}

    # ------------------------------------------------------------------- run
    def perform_task(self, instruction, session, logging_dir=None):
        box = _Container(session.container)
        key = _dotenv_key("OPENROUTER_API_KEY")
        t0 = time.time()
        sid = ""
        tokens_in = tokens_out = 0
        try:
            rc, ws = box.sh("pwd")
            workspace = (ws or "/app").strip().splitlines()[-1] or "/app"
            self._upload(box)
            self._ensure_python(box)
            self._start_server(box, key)
            sid = self._bench_mode(box, workspace)
            self._chat(box, sid, instruction)
            reply = self._wait_reply(box)
            st, costs = box.api("GET", "/api/costs?session=%s" % sid)
            usage = (costs or {}).get("total") or costs or {}
            tokens_in = int(usage.get("tokens_in") or usage.get("input") or 0)
            tokens_out = int(usage.get("tokens_out") or usage.get("output") or 0)
            if logging_dir:
                Path(logging_dir).mkdir(parents=True, exist_ok=True)
                (Path(logging_dir) / "longrun-turn.json").write_text(
                    json.dumps({"workspace": workspace, "session": sid,
                                "reply_status": reply.get("status"),
                                "elapsed_s": reply.get("elapsed"),
                                "error": reply.get("error") or "",
                                "costs": costs, "wall_s": round(time.time() - t0, 1)},
                               indent=1), encoding="utf-8")
            failed = reply.get("status") not in (200, None)
            return AgentResult(
                total_input_tokens=tokens_in,
                total_output_tokens=tokens_out,
                failure_mode=FailureMode.NONE if not failed else FailureMode.UNKNOWN,
            )
        except Exception as exc:  # noqa: BLE001 — a harness fault is an agent failure
            print("LongrunAgent failed: %r" % (exc,), flush=True)
            return AgentResult(failure_mode=FailureMode.UNKNOWN)
        finally:
            try:
                box.sh("kill $(cat /tmp/lr/pid) 2>/dev/null; true")
            except Exception:  # noqa: BLE001
                pass
