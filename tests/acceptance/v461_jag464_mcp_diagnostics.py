#!/usr/bin/env python3
"""v461 — JAG-464: MCP clients must say WHY they are down (and what is missing).

Live problem: the filesystem MCP process initialized but returned zero tools. Its
configuration also lacks an allowed directory, which Longrun's MCP client does not
provide through the Roots capability. The Settings ▸ MCP panel only showed a red dot.

Deterministic: no model, no network, no server.
"""
import io
import os
import sys
import urllib.error
import urllib.request
from email.message import Message

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.interop import mcp_client as mc  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


# ---- A) the host runtime probe -------------------------------------------------
_rt = mc.runtimes()
check("A1 runtimes() reports the stdio launchers as booleans",
      isinstance(_rt, dict) and {"npx", "node", "uvx", "python3"} <= set(_rt)
      and all(isinstance(v, bool) for v in _rt.values()), _rt)

# ---- B1) a client whose launcher is missing records a CLEAR error --------------
_orig_cfg = mc._load_config
mc._load_config = lambda *a, **k: {
    "ghost": {"command": "definitely-not-a-real-cmd-xyz", "args": ["-y", "x"],
              "enabled": True}}
mgr = mc.MCPClientManager()
_st = {}
try:
    mgr.start_all()
    # NOTE: status() reads the (monkeypatched) config, so capture it BEFORE restoring.
    _st = mgr.status()
finally:
    mc._load_config = _orig_cfg
    mgr.disconnect_all()
_c = (_st.get("clients") or {}).get("ghost") or {}
check("B1 the missing launcher is recorded as the client's error",
      "command not found" in str(_c.get("error")), _c.get("error"))
check("B2 the client reports launcher_ok=False",
      _c.get("launcher_ok") is False, _c.get("launcher_ok"))
check("B3 status() exposes the host runtime block", "runtime" in _st, list(_st)[:6])

# ---- B2) a connected server with no tools remains diagnosable -----------------
_orig_cfg = mc._load_config
_orig_session = mc.MCPSession


class _EmptySession:
    def __init__(self, name, config):
        self.name = name
        self.config = config
        self.tools = {}
        self.connected = False
        self._connect_time = None

    def _connect_stdio(self, command, args, env):
        return True

    def initialize(self):
        self.connected = True
        return True

    def fetch_tools(self):
        return []

    def close(self):
        self.connected = False


mc._load_config = lambda *a, **k: {
    "empty": {"command": "python3", "args": [], "enabled": True}}
mc.MCPSession = _EmptySession
_empty_mgr = mc.MCPClientManager()
try:
    _empty_mgr.start_all()
    _empty_status = _empty_mgr.status()
finally:
    _empty_mgr.disconnect_all()
    mc._load_config = _orig_cfg
    mc.MCPSession = _orig_session
_empty = (_empty_status.get("clients") or {}).get("empty") or {}
check("B4 connected server with no tools gets an explicit diagnostic",
      _empty.get("connected") and "zero tools" in str(_empty.get("error")), _empty)

# ---- B3) stdio notifications do not wait for a response -----------------------
class _NoReplyQueue:
    def get(self, timeout=None):
        raise AssertionError("a JSON-RPC notification must not wait for a reply")


class _MemoryStdin:
    def write(self, value):
        self.value = value

    def flush(self):
        pass


class _LiveProcess:
    def __init__(self):
        self.stdin = _MemoryStdin()

    def poll(self):
        return None


_notify_session = mc.MCPSession("notify", {})
_notify_session.proc = _LiveProcess()
_orig_queue = mc.queue.Queue
mc.queue.Queue = _NoReplyQueue
try:
    try:
        _notify_result = _notify_session._send_raw(
            {"method": "notifications/initialized"})
        _notify_ok = _notify_result is None and not _notify_session._pending
    except AssertionError:
        _notify_ok = False
finally:
    mc.queue.Queue = _orig_queue
check("B5 stdio notifications return without waiting for a response", _notify_ok)

# ---- B4) failed tools/list is not mislabeled as an empty tool list ------------
_orig_send_raw = mc.MCPSession._send_raw
mc.MCPSession._send_raw = lambda self, obj, **kwargs: None
_no_response_session = mc.MCPSession("no-response", {})
try:
    _no_response_tools = _no_response_session.fetch_tools()
    _no_response_error = getattr(_no_response_session, "tool_error", None)
finally:
    mc.MCPSession._send_raw = _orig_send_raw
check("B6 tools/list with no response has a distinct diagnostic",
      not _no_response_tools and "no response" in str(_no_response_error),
      _no_response_error)

# ---- B5) stdio EOF releases every pending request -----------------------------
class _ClosedStdoutProcess:
    stdout = ()


_eof_session = mc.MCPSession("eof", {})
_eof_session.proc = _ClosedStdoutProcess()
_eof_session._connected = True
_eof_queue = mc.queue.Queue()
_eof_session._pending[77] = _eof_queue
try:
    _eof_session._read_stdio()
    _eof_value = _eof_queue.get_nowait()
    _eof_ok = _eof_value is None and not _eof_session._pending \
        and not _eof_session.connected \
        and "closed" in str(getattr(_eof_session, "connection_error", ""))
except (AttributeError, mc.queue.Empty):
    _eof_ok = False
check("B7 stdio EOF releases pending requests immediately", _eof_ok)

# ---- B8) non-object stdout payloads retain a protocol error --------------------
class _MalformedStdoutProcess:
    stdout = ("[]\n",)


_malformed_session = mc.MCPSession("malformed", {})
_malformed_session.proc = _MalformedStdoutProcess()
_malformed_session._connected = True
_malformed_session._read_stdio()
check("B8 non-object stdout JSON records a protocol error",
      "non-object" in str(getattr(_malformed_session, "connection_error", "")),
      getattr(_malformed_session, "connection_error", None))

# ---- B9) unexpected post-connect exit appears in client status -----------------
class _ExitedSession:
    connected = False
    tools = {"ping": {"name": "ping"}}
    _connect_time = 1
    connection_error = "stdio server closed stdout"


_orig_cfg = mc._load_config
mc._load_config = lambda *a, **k: {
    "crashed": {"command": "mcp-launcher", "args": [], "enabled": True}}
_exit_mgr = mc.MCPClientManager()
_exit_mgr.sessions["crashed"] = _ExitedSession()
try:
    _exit_status = _exit_mgr.status()
finally:
    mc._load_config = _orig_cfg
_exit_client = (_exit_status.get("clients") or {}).get("crashed") or {}
check("B9 unexpected stdio exit appears in client status",
      _exit_client.get("error") == "stdio server closed stdout", _exit_client)

# ---- B10) disconnected sessions cannot expose or execute stale tools -----------
_old_external_tools = dict(mc._EXTERNAL_TOOLS)
mc._EXTERNAL_TOOLS.clear()
try:
    _dead_tools = _exit_mgr.list_external_tools()
    mc._EXTERNAL_TOOLS["crashed__ping"] = {
        "client_name": "crashed", "original_name": "ping"}
    try:
        _dead_call = _exit_mgr.call_external("crashed__ping", {})
    except Exception as error:
        _dead_call = {"ok": True, "error": str(error)}
finally:
    mc._EXTERNAL_TOOLS.clear()
    mc._EXTERNAL_TOOLS.update(_old_external_tools)
check("B10 disconnected sessions do not register stale tools",
      not any(t.get("client_name") == "crashed" for t in _dead_tools), _dead_tools)
check("B11 calls to disconnected sessions fail before dispatch",
      not _dead_call.get("ok") and "not connected" in _dead_call.get("error", ""),
      _dead_call)

# ---- B12) disabled clients do not retain stale runtime errors -----------------
_orig_cfg = mc._load_config
mc._load_config = lambda *a, **k: {
    "disabled": {"command": "npx", "args": [], "enabled": False}}
_disabled_mgr = mc.MCPClientManager()
_disabled_mgr._errors["disabled"] = "stale startup failure"
try:
    _disabled_mgr.start_all()
    _disabled_status = _disabled_mgr.status()
finally:
    mc._load_config = _orig_cfg
    _disabled_mgr.disconnect_all()
_disabled = (_disabled_status.get("clients") or {}).get("disabled") or {}
check("B12 disabled clients do not show stale connection errors",
      not _disabled.get("enabled") and not _disabled.get("error"), _disabled)

# ---- B13) client-specific PATH is used for launcher lookup --------------------
class _OneToolSession(_EmptySession):
    def __init__(self, name, config):
        super().__init__(name, config)
        self.tools = {"ping": {"name": "ping", "description": "test", "inputSchema": {}}}

    def fetch_tools(self):
        return list(self.tools.values())


_orig_cfg = mc._load_config
_orig_session = mc.MCPSession
_orig_which = mc.shutil.which
mc._load_config = lambda *a, **k: {
    "custom-path": {"command": "mcp-launcher", "args": [],
                    "env": {"PATH": "/custom/mcp-bin"}, "enabled": True}}
mc.MCPSession = _OneToolSession
mc.shutil.which = lambda command, path=None: (
    "/custom/mcp-bin/mcp-launcher" if path == "/custom/mcp-bin" else None)
_path_mgr = mc.MCPClientManager()
try:
    _path_mgr.start_all()
    _path_status = _path_mgr.status()
finally:
    _path_mgr.disconnect_all()
    mc._load_config = _orig_cfg
    mc.MCPSession = _orig_session
    mc.shutil.which = _orig_which
_path_client = (_path_status.get("clients") or {}).get("custom-path") or {}
check("B13 launcher lookup honors client env.PATH",
      _path_client.get("connected") and _path_client.get("launcher_ok") is True,
      _path_client)

# ---- B14) initialization failures preserve their cause -------------------------
_orig_send_raw = mc.MCPSession._send_raw


def _initialize_with(response):
    def _fake_send(self, obj, **kwargs):
        return response if obj.get("method") == "initialize" else None

    mc.MCPSession._send_raw = _fake_send
    session = mc.MCPSession("initialize-probe", {})
    try:
        return session.initialize(), getattr(session, "connection_error", None)
    finally:
        mc.MCPSession._send_raw = _orig_send_raw


_init_rpc_ok, _init_rpc_error = _initialize_with({
    "error": {"code": -32000, "message": "unsupported initialize"}
})
_init_empty_ok, _init_empty_error = _initialize_with(None)
check("B14 initialize JSON-RPC errors are not reported as connected",
      not _init_rpc_ok and "unsupported initialize" in str(_init_rpc_error),
      _init_rpc_error)
check("B15 initialize no-response has a distinct error",
      not _init_empty_ok and "no response" in str(_init_empty_error),
      _init_empty_error)

# ---- B16) registry refresh serializes with session teardown -------------------
class _BlockedSession:
    tools = {"ping": {"name": "ping", "inputSchema": {}}}

    def __init__(self):
        self.entered = mc.threading.Event()
        self.release = mc.threading.Event()

    @property
    def connected(self):
        self.entered.set()
        self.release.wait(10)
        return True

    def close(self):
        self.release.set()


_old_external_tools = dict(mc._EXTERNAL_TOOLS)
mc._EXTERNAL_TOOLS.clear()
_race_mgr = mc.MCPClientManager()
_blocked_session = _BlockedSession()
_race_mgr.sessions["race"] = _blocked_session
_refresh_thread = mc.threading.Thread(target=_race_mgr._register_as_tools, daemon=True)
_refresh_thread.start()
_reader_entered = _blocked_session.entered.wait(5)
_lock_available = _race_mgr._lock.acquire(blocking=False)
if _lock_available:
    _race_mgr._lock.release()
_blocked_session.release.set()
_refresh_thread.join(5)
_race_mgr.disconnect_all()
mc._EXTERNAL_TOOLS.clear()
mc._EXTERNAL_TOOLS.update(_old_external_tools)
check("B16 registry refresh holds the lifecycle lock through session inspection",
      _reader_entered and not _lock_available and not _refresh_thread.is_alive(),
      {"entered": _reader_entered, "lock_available": _lock_available})

# ---- B17) request after child exit keeps an explicit cause ---------------------
class _ExitedProcess:
    stdin = _MemoryStdin()
    returncode = 7

    def poll(self):
        return 7


_exited_process_session = mc.MCPSession("exited-process", {})
_exited_process_session.proc = _ExitedProcess()
_exited_process_session._connected = True
_exited_response = _exited_process_session._send_raw({"method": "tools/list"})
check("B17 request detects an already-exited stdio child",
      _exited_response is None and not _exited_process_session.connected
      and "exited" in str(getattr(_exited_process_session, "connection_error", "")),
      getattr(_exited_process_session, "connection_error", None))

# ---- B18) spawn resolves commands from client-specific PATH -------------------
_orig_which = mc.shutil.which
_orig_popen = mc.subprocess.Popen
_spawned_command = []


class _SpawnedProcess:
    pid = 12345
    stdout = ()
    stdin = _MemoryStdin()
    returncode = 0

    def poll(self):
        return 0


def _fake_which(command, path=None):
    return "/custom/mcp-bin/mcp-launcher" if path == "/custom/mcp-bin" else None


def _fake_popen(argv, **kwargs):
    _spawned_command.append(argv[0])
    return _SpawnedProcess()


mc.shutil.which = _fake_which
mc.subprocess.Popen = _fake_popen
_spawn_session = mc.MCPSession("spawn-path", {"env": {"PATH": "/custom/mcp-bin"}})
try:
    _spawn_session._connect_stdio("mcp-launcher", [], {"PATH": "/custom/mcp-bin"})
    _spawn_session._reader.join(1)
finally:
    mc.shutil.which = _orig_which
    mc.subprocess.Popen = _orig_popen
check("B18 stdio spawn resolves the launcher from client env.PATH",
      _spawned_command == ["/custom/mcp-bin/mcp-launcher"], _spawned_command)

# ---- B19) HTTP transport errors disconnect the MCP client ---------------------
_http_session = mc.MCPSession("http-failure", {})
_http_session._http_base = "https://unused.invalid/mcp"
_http_session._connected = True
_http_session._http_call = lambda obj, timeout: {
    "error": {"code": 503, "message": "service unavailable"}, "_http_status": 503}
_http_response = _http_session._send_raw({"method": "tools/list"})
check("B19 HTTP transport failure marks the client disconnected",
      _http_response.get("error", {}).get("code") == 503
      and not _http_session.connected
      and "503" in str(_http_session.connection_error),
      _http_session.connection_error)

# ---- B20) JSON-RPC errors do not disconnect a healthy HTTP transport -----------
_http_rpc_session = mc.MCPSession("http-rpc-error", {})
_http_rpc_session._http_base = "https://unused.invalid/mcp"
_http_rpc_session._connected = True
_http_rpc_session._http_call = lambda obj, timeout: {
    "error": {"code": 503, "message": "application-level failure"}}
_http_rpc_response = _http_rpc_session._send_raw({"method": "tools/list"})
check("B20 JSON-RPC errors preserve transport connection",
      _http_rpc_response.get("error", {}).get("code") == 503
      and _http_rpc_session.connected
      and not _http_rpc_session.connection_error,
      _http_rpc_session.connection_error)

# ---- B21) HTTP errors preserve MCP session-expired responses ------------------
_http_error_session = mc.MCPSession("http-expired", {})
_http_error_session._http_base = "https://unused.invalid/mcp"
_http_request = urllib.request.Request(
    "https://unused.invalid/mcp", data=b"{}")
_http_headers = Message()
_http_headers["Content-Type"] = "application/json"
_http_exception = urllib.error.HTTPError(
    _http_request.full_url, 404, "Not Found", _http_headers,
    io.BytesIO(b'{"jsonrpc":"2.0","id":1,"error":{"code":-32001,"message":"Session not found"}}'))
_orig_urlopen = urllib.request.urlopen


def _raise_http_error(*args, **kwargs):
    raise _http_exception


urllib.request.urlopen = _raise_http_error
try:
    _expired_response = _http_error_session._http_call(
        {"method": "tools/list", "id": 1})
finally:
    urllib.request.urlopen = _orig_urlopen
check("B21 HTTP errors retain MCP session-expired response bodies",
      _expired_response.get("error", {}).get("code") == -32001
      and _expired_response.get("_http_status") == 404,
      _expired_response)

# ---- B22) external registry snapshots use the shared registry lock -------------
class _InspectingExternalTools(dict):
    snapshot_locked = False

    def values(self):
        acquired = []
        completed = mc.threading.Event()

        def _probe_lock():
            ok = mc._EXTERNAL_TOOLS_LOCK.acquire(blocking=False)
            acquired.append(ok)
            if ok:
                mc._EXTERNAL_TOOLS_LOCK.release()
            completed.set()

        _probe = mc.threading.Thread(target=_probe_lock)
        _probe.start()
        self.snapshot_locked = completed.wait(5) and acquired == [False]
        return super().values()


_old_external_tools = mc._EXTERNAL_TOOLS
mc._EXTERNAL_TOOLS = _InspectingExternalTools()
_snapshot_mgr = mc.MCPClientManager()
_snapshot_session = _OneToolSession("snapshot", {})
_snapshot_session.connected = True
_snapshot_mgr.sessions["snapshot"] = _snapshot_session
try:
    _snapshot_tools = _snapshot_mgr.list_external_tools()
    _snapshot_locked = mc._EXTERNAL_TOOLS.snapshot_locked
finally:
    _snapshot_mgr.disconnect_all()
    mc._EXTERNAL_TOOLS = _old_external_tools
check("B22 external registry snapshots hold the shared lock",
      _snapshot_locked and len(_snapshot_tools) == 1,
      {"locked": _snapshot_locked, "tools": _snapshot_tools})

# ---- B23) client status snapshots sessions under lifecycle lock ----------------
class _LockCheckingSessions(dict):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.copy_locked = False

    def copy(self):
        acquired = []

        def _probe_status_lock():
            ok = self.manager._lock.acquire(blocking=False)
            acquired.append(ok)
            if ok:
                self.manager._lock.release()

        _probe = mc.threading.Thread(target=_probe_status_lock)
        _probe.start()
        _probe.join(5)
        self.copy_locked = acquired == [False]
        return super().copy()


_orig_cfg = mc._load_config
mc._load_config = lambda *a, **k: {}
_status_mgr = mc.MCPClientManager()
_status_sessions = _LockCheckingSessions(_status_mgr)
_status_mgr.sessions = _status_sessions
try:
    _locked_status = _status_mgr.status()
finally:
    mc._load_config = _orig_cfg
check("B23 client status snapshots sessions under lifecycle lock",
      _status_sessions.copy_locked and "clients" in _locked_status)

# ---- C) the WebUI surfaces it --------------------------------------------------
_html = _read("webui/index.html")
check("C1 the panel renders the client error next to the tool count",
      'const _errorHint = c.error' in _html
      and 'const _hint = c.error ? (" · ⚠ " + _errorHint)' in _html
      and '+ _hint;' in _html)
check("C2 the summary warns how many clients are NOT working",
      '(" · ⚠ " + broken.length + " not working")' in _html
      and "c.connected && !(c.tools > 0)" in _html)
check("C2b a connected-but-EMPTY server is explained, not just red",
      "connected but exposes 0 tools" in _html
      and 'n.toLowerCase() === "filesystem" && _empty' in _html
      and "check its allowed-directory argument and server logs" in _html)
check("C2c filesystem path advice only follows a tools/list failure",
      'String(c.error || "").startsWith("tools/list")' in _html)
check("C2d disabled clients do not inflate the broken count",
      "return c.enabled && (c.error || c.launcher_ok === false" in _html)
check("C3 the catalog disables 'add' when the launcher is missing",
      'b.disabled = _noLaunch;' in _html and "_mcpRuntime" in _html)

# ---- D) the filesystem preset ships a USABLE path -----------------------------
check("D1 the filesystem preset requires an explicit allowed directory",
      '@modelcontextprotocol/server-filesystem", "<absolute-allowed-directory>"]' in _html
      and "replace the directory placeholder" in _html)

def _upsert_without_write(name, args):
    called = []

    def _unexpected_persist(*persist_args, **persist_kwargs):
        called.append(True)
        raise AssertionError("invalid filesystem config reached persistence")

    original = mc._load_local_doc
    mc._load_local_doc = _unexpected_persist
    try:
        try:
            result = mc.upsert_client(name, {"command": "npx", "args": args})
        except AssertionError as error:
            result = {"error": str(error)}
    finally:
        mc._load_local_doc = original
    return result, called


_placeholder_result, _placeholder_persist = _upsert_without_write(
    "fs-placeholder", ["-y", "@modelcontextprotocol/server-filesystem",
                       "<absolute-allowed-directory>"])
_missing_path_result, _missing_path_persist = _upsert_without_write(
    "fs-missing-path", ["-y", "@modelcontextprotocol/server-filesystem"])
check("D2 filesystem placeholder is rejected before persistence",
      "allowed directory" in str(_placeholder_result.get("error", "")).lower()
      and not _placeholder_persist, _placeholder_result)
check("D3 filesystem with no directory is rejected before persistence",
      "allowed directory" in str(_missing_path_result.get("error", "")).lower()
      and not _missing_path_persist, _missing_path_result)
_versioned_result, _versioned_persist = _upsert_without_write(
    "fs-versioned", ["-y", "@modelcontextprotocol/server-filesystem@latest"])
check("D4 versioned filesystem package still requires a directory",
      "allowed directory" in str(_versioned_result.get("error", "")).lower()
      and not _versioned_persist, _versioned_result)

print("---")
okc = sum(results)
print("\nv461: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
