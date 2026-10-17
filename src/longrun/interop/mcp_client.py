#!/usr/bin/env python3
"""Longrun MCP client — v0.3 / Sperimentale

Connects to external MCP servers (Filesystem, Playwright, GitHub, etc.) and
exposes their tools as native Longrun tools through the registry.

Two transports:
- **stdio**: spawn a subprocess, speak JSON-RPC over its stdin/stdout
- **HTTP** / **SSE**: POST /mcp (streamable-HTTP) or connect to an SSE endpoint

Configuration: `config/mcp_clients.yaml` (or JSON). Examples:

    clients:
      filesystem:
        command: "npx"
        args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/jagones"]
        enabled: true
      playwright:
        command: "npx"
        args: ["-y", "@playwright/mcp"]
        enabled: true
      github:
        url: "http://127.0.0.1:8791/mcp"
        enabled: true
      brave-search:
        command: "npx"
        args: ["-y", "@anthropic/mcp-brave-search"]
        enabled: false

Usage:
    from longrun.interop.mcp_client import MCPClientManager
    manager = MCPClientManager()
    manager.start_all()         # spawn configured clients
    tools = manager.list_tools()  # merge all client tools
    manager.call_tool("filesystem__read", {"path": "/etc/hostname"})
"""

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time

from longrun.util import osutil
from longrun.util.dataio import read_yaml
from longrun.tools import registry

REPO = registry.REPO
CONFIG_PATH = os.path.join(REPO, "config", "mcp_clients.yaml")
CONFIG_JSON_PATH = os.path.join(REPO, "config", "mcp_clients.json")
# JAG-108: user-added clients live in a LOCAL, gitignored file so tokens/paths
# never reach the tracked repo (workspace rule: no secrets in the repository).
CONFIG_LOCAL_PATH = os.path.join(REPO, "config", "mcp_clients.local.yaml")
CONFIG_LOCAL_JSON_PATH = os.path.join(REPO, "config", "mcp_clients.local.json")

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
# Keys a user may set from the API/UI (never arbitrary passthrough).
ALLOWED_CLIENT_KEYS = ("enabled", "command", "args", "url", "headers", "env", "cwd")

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

_log_lock = threading.Lock()


def log(fmt, *a):
    with _log_lock:
        try:
            msg = fmt % a if a else fmt
        except TypeError:
            msg = " ".join(str(x) for x in (fmt,) + a)
        print("[mcp-client]", msg, file=sys.stderr, flush=True)


def _mcp_session_expired(resp):
    """True when a streamable-HTTP MCP response reports a dead session (JAG-74)."""
    if not isinstance(resp, dict):
        return False
    err = resp.get("error")
    if not isinstance(err, dict):
        return False
    msg = str(err.get("message", "")).lower()
    return err.get("code") == -32001 or (
        "session" in msg and any(w in msg for w in ("not found", "expired", "invalid", "terminated")))


def _http_transport_error(resp) -> bool:
    """True for HTTP status and network errors, not MCP JSON-RPC errors."""
    if not isinstance(resp, dict):
        return False
    status = resp.get("_http_status")
    if isinstance(status, int) and 400 <= status < 600:
        return True
    error = resp.get("error")
    if not isinstance(error, dict):
        return False
    return error.get("code") == -1


# --------------------------------------------------------------- session ---

class MCPSession:
    """A single MCP client session (stdio or HTTP)."""

    def __init__(self, name, config):
        self.name = name
        self.config = config
        self.proc = None          # subprocess for stdio
        self.tools = {}           # name -> {name, description, inputSchema}
        self._lock = threading.RLock()
        self._req_id = 0
        self._pending = {}        # id -> queue.Queue
        self._reader = None
        self._stop = False
        self._connected = False
        self._connect_time = None
        self.connection_error = None
        self.tool_error = None
        self._http_base = None    # HTTP transport base URL
        self._http_headers = {}   # extra HTTP headers (e.g. Authorization)
        self._http_session_id = None  # MCP streamable-HTTP session id

    @property
    def connected(self):
        return self._connected

    # ---- stdio transport ----

    def _connect_stdio(self, command, args, env):
        full_env = dict(os.environ)
        full_env.update(env or {})
        resolved_command = shutil.which(command, path=full_env.get("PATH")) or command
        self.proc = subprocess.Popen(
            [osutil.resolve_script(resolved_command)] + args, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=full_env,
            cwd=self.config.get("cwd", REPO), **osutil.popen_kwargs())
        log("%s: spawned pid=%d", self.name, self.proc.pid)

        self._reader = threading.Thread(target=self._read_stdio, daemon=True)
        self._reader.start()
        return True

    def _read_stdio(self) -> None:
        """Route stdio responses and release pending requests when the child exits."""
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    self.connection_error = "stdio server emitted invalid JSON"
                    break
                if not isinstance(msg, dict):
                    self.connection_error = "stdio server emitted non-object JSON-RPC data"
                    break
                mid = msg.get("id")
                if mid is not None:
                    with self._lock:
                        response_queue = self._pending.get(mid)
                    if response_queue is not None:
                        response_queue.put(msg)
                elif msg.get("method") and msg.get("params"):
                    pass  # server-initiated notification — ignore for now
        except Exception:
            pass
        finally:
            self._stdio_closed()

    def _stdio_closed(self) -> None:
        """Wake every stdio request when its child closes stdout."""
        with self._lock:
            was_connected = self._connected
            self._connected = False
            if (was_connected and not self._stop and not self.connection_error):
                self.connection_error = "stdio server closed stdout"
            pending = list(self._pending.values())
            self._pending.clear()
        for response_queue in pending:
            response_queue.put(None)

    def _send_raw(self, obj, timeout=20, _retry=True):
        mid = self._next_id()
        q = queue.Queue()
        is_notification = str(obj.get("method", "")).startswith("notifications/")
        with self._lock:
            if not is_notification:
                self._pending[mid] = q
            req = {"jsonrpc": "2.0", **obj}
            if not is_notification:
                req["id"] = mid
            if self.proc and self.proc.stdin:
                # JAG-bugfinder: a dead child keeps a non-None proc/stdin, but
                # writing raises BrokenPipeError. Check liveness and guard the
                # write so a crashed MCP server returns None instead of raising.
                if self.proc.poll() is not None:
                    self._pending.pop(mid, None)
                    self._connected = False
                    if not self._stop and not self.connection_error:
                        self.connection_error = "stdio server exited with code %s" \
                            % self.proc.returncode
                    return None
                try:
                    self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
                    self.proc.stdin.flush()
                except (BrokenPipeError, OSError, ValueError):
                    self._pending.pop(mid, None)
                    self._connected = False
                    if not self._stop and not self.connection_error:
                        self.connection_error = "stdio server closed stdin"
                    return None
                if is_notification:
                    return None
            elif self._http_base:
                resp = self._http_call(req, timeout)
                self._pending.pop(mid, None)
                # JAG-74: a streamable-HTTP MCP session can expire server-side
                # ("Session not found"), which made every pmcp tool fail until a
                # restart. Re-initialize once and replay the call.
                if _retry and _mcp_session_expired(resp):
                    log("%s: MCP session expired — re-initializing", self.name)
                    self._http_session_id = None
                    self._connected = False
                    try:
                        self.initialize()
                    except Exception:  # noqa: BLE001 — best effort
                        pass
                    return self._send_raw(obj, timeout, _retry=False)
                if _http_transport_error(resp):
                    error = (resp.get("error") or {})
                    self._connected = False
                    code = resp.get("_http_status") or error.get("code")
                    self.connection_error = ("HTTP transport failure (%s)" % code)
                return resp
            else:
                self._pending.pop(mid, None)
                return None
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            with self._lock:
                self._pending.pop(mid, None)
            return None

    def _next_id(self):
        with self._lock:
            self._req_id += 1
            return self._req_id

    # ---- HTTP transport ----

    def _connect_http(self, url, headers=None):
        if not url.startswith("http"):
            url = "http://" + url
        self._http_base = url.rstrip("/")
        self._http_headers = {
            "Accept": "application/json, text/event-stream",
        }
        for k, v in (headers or {}).items():
            self._http_headers[k] = os.path.expandvars(str(v))
        log("%s: HTTP base = %s", self.name, self._http_base)
        return True

    @staticmethod
    def _parse_http_body(body, content_type):
        """Parse a streamable-HTTP response body (JSON or SSE data: lines)."""
        text = (body or "").strip()
        if not text:
            return None
        if "text/event-stream" in (content_type or ""):
            last = None
            for line in text.splitlines():
                if line.startswith("data:"):
                    try:
                        last = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
            return last
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _http_call(self, obj, timeout=20):
        import urllib.request as ureq
        import urllib.error as uerr
        data = json.dumps(obj).encode("utf-8")
        headers = {"Content-Type": "application/json", **self._http_headers}
        if self._http_session_id:
            headers["Mcp-Session-Id"] = self._http_session_id
        req = ureq.Request(self._http_base, data=data, headers=headers)
        try:
            with ureq.urlopen(req, timeout=timeout) as r:
                self._http_session_id = self._http_session_id or \
                    r.headers.get("Mcp-Session-Id")
                return self._parse_http_body(r.read().decode("utf-8"),
                                             r.headers.get("Content-Type")) \
                    or {}
        except uerr.HTTPError as e:
            try:
                response = self._parse_http_body(
                    e.read().decode(), e.headers.get("Content-Type"))
            except Exception:
                response = None
            if not isinstance(response, dict):
                response = {"error": {
                    "code": e.code, "message": "HTTP status %d" % e.code}}
            response["_http_status"] = e.code
            return response
        except Exception as e:
            return {"error": {"code": -1,
                              "message": "HTTP transport failure (%s)"
                              % type(e).__name__}}

    def _send_http(self, obj, timeout=20):
        return self._http_call(obj, timeout)
    # ---- public session lifecycle ----

    def initialize(self):
        self.connection_error = None
        params = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "longrun", "version": "0.3.0"},
        }
        resp = self._send_raw({"method": "initialize", "params": params}, timeout=30,
                              _retry=False)
        if resp is None:
            self.connection_error = "initialize returned no response"
            return False
        error = resp.get("error")
        if isinstance(error, dict):
            reason = error.get("message") or error.get("code") or "unknown error"
            self.connection_error = "initialize failed: %s" % str(reason)[:180]
            return False
        result = resp.get("result")
        if not isinstance(result, dict):
            self.connection_error = "initialize returned an invalid response"
            return False
        server_ver = result.get("protocolVersion", "unknown")
        if server_ver not in SUPPORTED_PROTOCOLS and server_ver != "unknown":
            log("%s: protocol version %s may be incompatible", self.name, server_ver)
        # Send initialized notification
        self._send_raw({"method": "notifications/initialized"})
        self._connected = True
        self._connect_time = time.time()
        log("%s: initialized (protocol %s)", self.name, server_ver)
        return True

    def fetch_tools(self):
        self.tool_error = None
        resp = self._send_raw({"method": "tools/list"}, timeout=30)
        if resp is None:
            self.tool_error = "tools/list returned no response"
            return []
        error = resp.get("error")
        if isinstance(error, dict):
            reason = error.get("message") or error.get("code") or "unknown error"
            self.tool_error = "tools/list failed: %s" % str(reason)[:180]
            return []
        result = resp.get("result")
        if not isinstance(result, dict):
            self.tool_error = "tools/list returned an invalid response"
            return []
        tools = result.get("tools") or []
        if not isinstance(tools, list):
            self.tool_error = "tools/list returned an invalid tool list"
            return []
        if not tools:
            self.tool_error = "tools/list returned zero tools"
        with self._lock:
            for t in tools:
                tname = t.get("name", "unknown")
                # namespace by client name to avoid collisions
                self.tools[tname] = t
        log("%s: %d tools available", self.name, len(tools))
        return tools

    def call_tool(self, tool_name, args, timeout=120):
        """Call a tool on this client session."""
        # Normalise: if the caller uses the namespaced form "client__tool",
        # strip the prefix
        if "__" in tool_name:
            _, _, bare = tool_name.partition("__")
            tool_name = bare or tool_name
        resp = self._send_raw({
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args or {}},
        }, timeout=timeout)
        if resp is None:
            return {"isError": True, "content": [{"type": "text", "text": "mcp call timed out"}]}
        result = resp.get("result") or {}
        if "error" in resp:
            return {"isError": True, "content": [{"type": "text", "text": str(resp["error"])}]}
        return result

    def ping(self):
        resp = self._send_raw({"method": "ping"}, timeout=10)
        return resp is not None

    def close(self):
        self._stop = True
        if self.proc:
            osutil.kill_tree(self.proc)
        self._connected = False


# ------------------------------------------------------------- manager ----

def _load_env_files(paths):
    """Load KEY=VALUE lines from env files into os.environ (for ${VAR} refs)."""
    for path in paths or []:
        path = os.path.expanduser(str(path))
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val
            log("loaded env file %s", path)
        except Exception as e:
            log("env file %s: %s", path, e)


def _read_doc(path):
    """Read a YAML (or JSON) config document; {} on any failure (JAG-483).

    The parsing lives in ``dataio.read_yaml``; this keeps the local ``log()``
    for a file that IS present but cannot be parsed.
    """
    if not path or not os.path.isfile(path):
        return {}
    doc = read_yaml(path, default=None)
    if doc is None:
        log("error reading %s", path)
        return {}
    return doc


def _servers_to_clients(servers):
    """Trae-style `mcpServers` dict -> internal `clients` dict (JAG-158)."""
    out = {}
    for name, s in (servers or {}).items():
        if not isinstance(s, dict):
            continue
        c = {}
        if s.get("url") or s.get("serverUrl") or s.get("type") == "http":
            c["url"] = s.get("url") or s.get("serverUrl") or ""
            if isinstance(s.get("headers"), dict):
                c["headers"] = s["headers"]
        else:
            c["command"] = s.get("command") or ""
            args = s.get("args")
            c["args"] = args if isinstance(args, list) else ([args] if args else [])
            if isinstance(s.get("env"), dict):
                c["env"] = s["env"]
        if "enabled" in s:
            c["enabled"] = bool(s["enabled"])
        if s.get("cwd"):
            c["cwd"] = s["cwd"]
        out[name] = c
    return out


def _clients_to_servers(clients):
    """Internal `clients` dict -> Trae-style `mcpServers` (for hand editing)."""
    out = {}
    for name, c in (clients or {}).items():
        if not isinstance(c, dict):
            continue
        if c.get("url"):
            s = {"url": c.get("url") or ""}
            if isinstance(c.get("headers"), dict) and c["headers"]:
                s["headers"] = c["headers"]
        else:
            s = {"command": c.get("command") or "", "args": list(c.get("args") or [])}
            if isinstance(c.get("env"), dict) and c["env"]:
                s["env"] = c["env"]
        if c.get("cwd"):
            s["cwd"] = c["cwd"]
        s["enabled"] = bool(c.get("enabled", True))
        out[name] = s
    return out


def load_doc():
    """Merged config: tracked base file + local (gitignored) user overrides.

    The local file is `config/mcp_clients.local.json` in Trae-style
    `{"mcpServers": {...}}` format; a legacy local YAML (clients schema) is
    still read for migration. Local entries override base ones by name.
    """
    base = _read_doc(CONFIG_PATH)
    if not base and os.path.exists(CONFIG_JSON_PATH):
        base = _read_doc(CONFIG_JSON_PATH)
    local = _load_local_doc()
    env_files = list(base.get("env_files") or [])
    for p in (local.get("env_files") or []):
        if p not in env_files:
            env_files.append(p)
    clients = dict(base.get("clients") or {})
    clients.update(local.get("clients") or {})
    return {"env_files": env_files, "clients": clients}


def _load_local_doc():
    """The user document (internal form). Canonical file = local JSON with
    `mcpServers`; entries from a legacy local YAML are merged underneath so an
    existing config is never lost, and the JSON wins on name clashes."""
    out = {"clients": {}}
    legacy = _read_doc(CONFIG_LOCAL_PATH)
    if isinstance(legacy, dict):
        if isinstance(legacy.get("clients"), dict):
            out["clients"].update(legacy["clients"])
        if legacy.get("env_files"):
            out["env_files"] = list(legacy["env_files"])
    doc = _read_doc(CONFIG_LOCAL_JSON_PATH)
    if isinstance(doc, dict):
        if isinstance(doc.get("mcpServers"), dict):
            out["clients"].update(_servers_to_clients(doc["mcpServers"]))
        elif isinstance(doc.get("clients"), dict):
            out["clients"].update(doc["clients"])
        if doc.get("env_files"):
            out["env_files"] = list(doc["env_files"])
    return out


def _save_local_doc(doc):
    """Persist the user document to the gitignored local JSON, mcpServers form."""
    payload = {"mcpServers": _clients_to_servers(doc.get("clients") or {})}
    if doc.get("env_files"):
        payload["env_files"] = doc["env_files"]
    os.makedirs(os.path.dirname(CONFIG_LOCAL_JSON_PATH), exist_ok=True)
    with open(CONFIG_LOCAL_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return CONFIG_LOCAL_JSON_PATH


def ensure_local_file():
    """Create the local mcp.json (gitignored) if missing; return its path (JAG-158)."""
    if not os.path.isfile(CONFIG_LOCAL_JSON_PATH):
        _save_local_doc({"clients": {}})
    return CONFIG_LOCAL_JSON_PATH


def _load_config():
    """Effective clients for the manager, from the merged document."""
    doc = load_doc()
    _load_env_files(doc.get("env_files"))
    return doc.get("clients") or {}


def runtimes():
    """Return availability of common MCP launchers on the Longrun host."""
    return {c: bool(shutil.which(c)) for c in ("npx", "node", "uvx", "python3", "docker")}


def _command_available(command: str, env: dict | None = None) -> bool:
    """Check a launcher using the environment that its client will inherit."""
    launch_env = dict(os.environ)
    if isinstance(env, dict):
        launch_env.update(env)
    return bool(shutil.which(command, path=launch_env.get("PATH")))


class MCPClientManager:
    """Manages all external MCP client sessions."""

    def __init__(self):
        self.sessions = {}        # name -> MCPSession
        self._lock = threading.RLock()
        self._tool_prefix = {}    # tool_name -> client_name
        self._started = False
        # JAG-464: last CONNECT error per client, so the panel can say WHY a server is
        # down instead of showing a bare "0 tool" next to a red dot.
        self._errors = {}

    def _ensure_config(self):
        """Create default config if neither file exists."""
        if not os.path.exists(CONFIG_PATH) and not os.path.exists(CONFIG_JSON_PATH):
            default = {
                "clients": {
                    "example-filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem",
                                 os.path.expanduser("~")],
                        "enabled": False,
                    },
                }
            }
            try:
                import yaml
                os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    yaml.safe_dump(default, f, sort_keys=False, allow_unicode=True,
                                   default_flow_style=False)
                log("created default config: %s", CONFIG_PATH)
            except ImportError:
                with open(CONFIG_JSON_PATH, "w", encoding="utf-8") as f:
                    json.dump(default, f, indent=2, ensure_ascii=False)
                log("created default config: %s", CONFIG_JSON_PATH)

    def start_all(self):
        """Start all enabled MCP client sessions."""
        with self._lock:
            if self._started:
                return
            self._ensure_config()
            configs = _load_config()
            self._errors.clear()
            for name, cfg in configs.items():
                if not cfg.get("enabled", True):
                    log("%s: disabled, skipping", name)
                    continue
                session = MCPSession(name, cfg)
                try:
                    ok = False
                    if cfg.get("command") and cfg.get("args") is not None:
                        # Resolve with this client's environment, not an SSH shell.
                        if not _command_available(str(cfg.get("command")), cfg.get("env")):
                            self._errors[name] = ("command not found on PATH: %s"
                                                  % cfg.get("command"))
                            log("%s: %s", name, self._errors[name])
                            continue
                        ok = session._connect_stdio(
                            cfg["command"], list(cfg.get("args", [])),
                            cfg.get("env", {}))
                    elif cfg.get("url"):
                        ok = session._connect_http(cfg["url"], cfg.get("headers"))
                    if ok:
                        init_ok = session.initialize()
                        if init_ok:
                            tools = session.fetch_tools()
                            self.sessions[name] = session
                            if tools:
                                self._errors.pop(name, None)
                            else:
                                detail = (getattr(session, "tool_error", None)
                                          or "tools/list returned zero tools")
                                connection_error = getattr(session, "connection_error", None)
                                self._errors[name] = (
                                    "%s (%s)" % (detail, connection_error)
                                    if connection_error else detail)
                            # Register tools
                            for tname in list(session.tools):
                                self._tool_prefix[tname] = name
                            if session.connected:
                                log("%s: connected with %d tools", name, len(tools))
                            else:
                                log("%s: disconnected during startup (%s)", name,
                                    self._errors[name])
                        else:
                            self._errors[name] = (getattr(session, "connection_error", None)
                                                  or "initialize failed")
                            log("%s: initialize failed, closing", name)
                            session.close()
                    else:
                        self._errors[name] = "transport connect failed"
                        log("%s: transport connect failed", name)
                except Exception as e:
                    self._errors[name] = str(e)[:200]
                    log("%s: connection error: %s", name, e)
                    try:
                        session.close()
                    except Exception:
                        pass
            self._started = True
            self._register_as_tools()

    def _register_as_tools(self):
        """Register each external MCP tool as a harness tool in the registry.

        Each external tool gets a synthetic entry named `client__toolname` so
        there are no name collisions. The approval policy is 'required' by
        default (configurable in tools.yaml).
        """
        # JAG-462: derive the registry from the LIVE sessions (the source of truth)
        # instead of the `_tool_prefix` index. That index is written ONCE at connect
        # time from `session.tools`; when the gateway's first `tools/list` came back
        # empty, the index stayed empty FOREVER and the ENTIRE MCP surface silently
        # vanished from the agent's tool list (`registry._external_tools()` only calls
        # `start_all` when `sessions` is EMPTY, so nothing ever repaired it). Live
        # evidence: the agent answered "no external MCP servers are active" while the
        # gateway was connected with 26 tools.
        with self._lock:
            live_tools = {}
            for cname, session in list(self.sessions.items()):
                if not getattr(session, "connected", True):
                    continue
                for tname, tspec in list(
                        (getattr(session, "tools", None) or {}).items()):
                    if not tspec:
                        continue
                    # Keep original client key for dispatch; normalize only namespace.
                    full_name = "%s__%s" % (str(cname).strip().lower(), tname)
                    live_tools[full_name] = {
                        "name": full_name,
                        "enabled": True,
                        "approval": "required",
                        "allowed": True,
                        "description": (tspec.get("description", "") +
                                        " [external MCP: %s/%s]" % (cname, tname)),
                        "inputSchema": tspec.get("inputSchema") or {},
                        "client_name": cname,
                        "original_name": tname,
                    }
            with _EXTERNAL_TOOLS_LOCK:
                _EXTERNAL_TOOLS.clear()
                _EXTERNAL_TOOLS.update(live_tools)

    def list_external_tools(self):
        """Return all external tools as registry-compatible entries."""
        # Rebuild from active sessions so tools from an exited child disappear.
        try:
            self._register_as_tools()
        except Exception:  # noqa: BLE001 — never break a tool listing
            pass
        with _EXTERNAL_TOOLS_LOCK:
            return list(_EXTERNAL_TOOLS.values())

    def call_external(self, full_name, args, run_id=None):
        """Call an external MCP tool by its full namespaced name."""
        with self._lock:
            with _EXTERNAL_TOOLS_LOCK:
                info = _EXTERNAL_TOOLS.get(full_name)
            session = self.sessions.get(info["client_name"]) if info else None
            if not info:
                return {"ok": False, "error": "unknown external tool: %s" % full_name}
            if not session or not getattr(session, "connected", True):
                return {"ok": False,
                        "error": "MCP client %r not connected" % info["client_name"]}
        if not session:
            return {"ok": False, "error": "MCP client %r not connected" % info["client_name"]}
        result = session.call_tool(info["original_name"], args)
        content = result.get("content") or []
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        is_err = result.get("isError", False)
        return {
            "ok": not is_err,
            "tool": full_name,
            "stdout": "\n".join(texts),
            "stderr": "",
            "exit_code": 1 if is_err else 0,
            "backend": "mcp(%s)" % info["client_name"],
            "sandboxed": False,
            "external": True,
        }

    def disconnect_all(self):
        # JAG-237: `start_all` (another request thread) inserts into
        # `self.sessions` under `self._lock`; iterating it here WITHOUT the lock
        # raised "dictionary changed size during iteration" (live repro:
        # POST /api/mcp/reload racing a start). Snapshot + clear atomically, then
        # close the sessions outside the lock so a slow kill_tree never blocks.
        with self._lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()
            with _EXTERNAL_TOOLS_LOCK:
                _EXTERNAL_TOOLS.clear()
            self._started = False
        for session in sessions:
            session.close()

    def status(self):
        """Effective client view: configured entries (connected or not) merged
        with live session state — single source for the API/UI (JAG-108)."""
        # Report the external tool count from active sessions, not stale registrations.
        try:
            self._register_as_tools()
        except Exception:  # noqa: BLE001
            pass
        configs = _load_config() or {}
        with self._lock:
            sessions = self.sessions.copy()
            errors = self._errors.copy()
        clients = {}
        for name, cfg in configs.items():
            s = sessions.get(name)
            clients[name] = {
                "connected": bool(s and s.connected),
                "tools": len(s.tools) if s else 0,
                "uptime": round(time.time() - s._connect_time, 1)
                if (s and s._connect_time) else 0,
                "enabled": bool(cfg.get("enabled", True)),
                "transport": "stdio" if cfg.get("command")
                else ("http" if cfg.get("url") else "?"),
                "command": cfg.get("command"),
                "args": cfg.get("args"),
                "url": cfg.get("url"),
                # JAG-464: WHY it is down + whether the launcher even exists here.
                "error": (errors.get(name)
                          or (getattr(s, "connection_error", None) if s else None)),
                "launcher": (cfg.get("command") or None) if cfg.get("command") else None,
                "launcher_ok": (_command_available(str(cfg.get("command")), cfg.get("env"))
                                if cfg.get("command") else None),
            }
        for name, s in sessions.items():
            clients.setdefault(name, {
                "connected": s.connected, "tools": len(s.tools),
                "uptime": round(time.time() - s._connect_time, 1)
                if s._connect_time else 0,
                "enabled": True, "transport": "?",
                "error": (errors.get(name)
                          or getattr(s, "connection_error", None))})
        with _EXTERNAL_TOOLS_LOCK:
            external_tool_count = len(_EXTERNAL_TOOLS)
        return {"clients": clients, "external_tools": external_tool_count,
                "runtime": runtimes(),
                "config": CONFIG_PATH, "local_config": CONFIG_LOCAL_JSON_PATH}


# Module-level registry of external tools (populated by the manager)
_EXTERNAL_TOOLS = {}
_EXTERNAL_TOOLS_LOCK = threading.RLock()

# Singleton
_manager = None


def get_manager():
    global _manager
    if _manager is None:
        _manager = MCPClientManager()
    return _manager


def list_tools():
    """Convenience: get all external tools from the singleton manager."""
    return get_manager().list_external_tools()


def call_tool(full_name, args, run_id=None):
    return get_manager().call_external(full_name, args, run_id)


def status():
    return get_manager().status()


def start():
    return get_manager().start_all()


def reload():
    """Tear down every session and re-read the config, so user edits apply
    without a server restart (JAG-108)."""
    m = get_manager()
    m.disconnect_all()
    m.start_all()
    return m.status()


def test_client(spec):
    """Connect a candidate client WITHOUT persisting it; report the tools.

    Lets the UI validate a stdio command / HTTP url before saving it.
    """
    cfg = dict(spec or {})
    session = MCPSession("__test__", cfg)
    try:
        if cfg.get("command"):
            ok = session._connect_stdio(cfg["command"], list(cfg.get("args") or []),
                                        cfg.get("env") or {})
        elif cfg.get("url"):
            ok = session._connect_http(cfg["url"], cfg.get("headers") or {})
        else:
            return {"ok": False, "error": "command (stdio) or url (http) required"}
        if not ok:
            return {"ok": False, "error": "transport connect failed"}
        if not session.initialize():
            return {"ok": False, "error": (session.connection_error
                                             or "initialize failed")}
        tools = session.fetch_tools()
        names = [t.get("name") for t in tools]
        return {"ok": True, "count": len(names), "tools": names}
    except Exception as e:  # noqa: BLE001 — a bad spec must never crash the API
        return {"ok": False, "error": str(e)}
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass


def _filesystem_directory_error(spec: dict) -> str | None:
    """Reject filesystem MCP specs that omit or retain the preset path placeholder."""
    args = spec.get("args") or []
    package_name = "@modelcontextprotocol/server-filesystem"
    package_index = next((
        index for index, arg in enumerate(args)
        if isinstance(arg, str)
        and (arg == package_name or arg.startswith(package_name + "@"))
    ), None)
    if package_index is None:
        return None
    directories = args[package_index + 1:]
    if not directories or any(
            not isinstance(directory, str) or not directory.strip()
            or re.fullmatch(r"<[^<>]+>", directory.strip())
            for directory in directories):
        return "filesystem MCP requires an explicit allowed directory"
    return None


def upsert_client(name, spec):
    """Add or update a client in the LOCAL config and reload (JAG-108).

    Only whitelisted keys are accepted; the name must be a safe identifier.
    Persisting to the local file keeps secrets out of the tracked repo.
    """
    name = str(name or "").strip()
    if not _NAME_RE.match(name):
        return {"error": "invalid name: use letters/digits/._- (start alnum)"}
    if not isinstance(spec, dict):
        return {"error": "spec must be an object"}
    if not spec.get("command") and not spec.get("url"):
        return {"error": "either command+args (stdio) or url (http) is required"}
    if spec.get("args") is not None and not isinstance(spec.get("args"), list):
        return {"error": "args must be a list"}
    directory_error = _filesystem_directory_error(spec)
    if directory_error:
        return {"error": directory_error}
    doc = _load_local_doc()
    entry = doc["clients"].get(name) or {}
    for k in ALLOWED_CLIENT_KEYS:
        if k in spec and spec[k] is not None:
            entry[k] = spec[k]
    entry.setdefault("enabled", True)
    doc["clients"][name] = entry
    path = _save_local_doc(doc)
    st = reload()
    return {"ok": True, "name": name, "path": path, "client": entry, **st}


def remove_client(name):
    """Remove a user client (or disable a base one) and reload (JAG-108)."""
    name = str(name or "").strip()
    if not name:
        return {"error": "name required"}
    doc = _load_local_doc()
    removed = False
    if name in doc["clients"]:
        doc["clients"].pop(name, None)
        removed = True
    else:
        base = _read_doc(CONFIG_PATH) or {}
        if name in (base.get("clients") or {}):
            doc["clients"][name] = {"enabled": False}
            removed = True
    _save_local_doc(doc)
    st = reload()
    return {"ok": removed, "name": name, **st}
