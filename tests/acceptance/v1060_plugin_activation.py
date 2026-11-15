#!/usr/bin/env python3
"""v1060 — a plugin install is an INSTALL: its servers are enabled, verified and reported.

The measured failure this pins (Architect session, 2026-11-15): `plugin/chrome-devtools`
was installed with its MCP member `enabled: false`; `/plugin:chrome-devtools` arrived
with no state and a config path where a member should be, so the model installed the
server itself (`mcp.upsert` + `mcp.reload` + `npx`) — a second owner and a machine
specific config nobody recorded.

  A  a connector member whose ${KEY} is unset stays OFF, is `needs-key`, and names the key
  B  a plain mcp member is ENABLED and verified: client on, tools enabled, member `ready`
  C  `/plugin:<name>` carries the live state, the provenance and the "not yours" rule
  D  a server that cannot start is a RECORDED state with its reason, never a rollback
  E  an external MCP tool receives no `workspace` key (the strict server rejected it)
  F  the child's stderr reaches `connection_error` (the reason was DEVNULL)
  G  uninstall restores a pre-existing client the plugin had enabled
  H  an unknown `/plugin:<name>` is an explicit refusal, never prose

Deterministic: no network, and no real MCP server is spawned (one `python3` child for F).
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-v1060-")
FIX = os.path.join(_TMP, "fixtures")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_TMP, "data", "sessions")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_TMP, "skills")
os.environ["LONGRUN_SKILLS_LOCAL_DIR"] = os.path.join(_TMP, "skills", "local")
os.environ["LONGRUN_PLUGIN_ROOTS"] = FIX
os.environ.pop("V1060_ABSENT_KEY", None)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02, market, market_plugins as mp, slash  # noqa: E402
from longrun.interop import mcp_client  # noqa: E402
from longrun.tools import registry  # noqa: E402

mcp_client.CONFIG_LOCAL_JSON_PATH = os.path.join(os.environ["LONGRUN_CONFIG_DIR"],
                                                 "mcp_clients.local.json")
mcp_client.CONFIG_LOCAL_PATH = os.path.join(os.environ["LONGRUN_CONFIG_DIR"],
                                            "mcp_clients.local.yaml")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def pkg(name, files):
    root = os.path.join(FIX, name)
    for rel, text in files.items():
        write(os.path.join(root, rel), text)
    return root


SKILL = "---\nname: %s\ndescription: Does %s things\n---\n# %s\n"


# ── the deterministic stand-in for a stdio MCP server ─────────────────────
class FakeSession:
    """Answers initialize/tools/list without a process (mirrors v461's stub)."""

    mode = "ok"          # "ok" | "fail"

    def __init__(self, name, config):
        self.name = name
        self.config = config
        self.tools = {"hello": {"name": "hello", "description": "a test tool",
                                "inputSchema": {"type": "object", "properties": {}}}}
        self._connected = False
        self._connect_time = None
        self.connection_error = None
        self.tool_error = None

    @property
    def connected(self):
        return self._connected

    def _connect_stdio(self, command, args, env):
        if FakeSession.mode == "fail":
            self.connection_error = "ERROR: this server needs node 24"
            return False
        return True

    def initialize(self):
        self._connected = True
        self._connect_time = time.time()
        return True

    def fetch_tools(self):
        return list(self.tools.values())

    def call_tool(self, tool_name, args, timeout=120):
        return {"content": [{"type": "text", "text": "ok"}]}

    def close(self):
        self._connected = False


_RealSession = mcp_client.MCPSession
mcp_client.MCPSession = FakeSession


def reset():
    """No sessions, no live tools, no stale verdict between sections."""
    mcp_client.get_manager().disconnect_all()
    FakeSession.mode = "ok"


def members_of(plugin_id):
    rec = [r for r in market.installed()["installed"] if r["id"] == plugin_id]
    return (rec[0] if rec else {}), (rec[0].get("members") if rec else [])


def member(rows, name):
    return next((m for m in rows if m.get("name") == name), {})


# ── A: a connector waits for its key ──────────────────────────────────────
conn = pkg("conn-plugin", {
    ".trae-plugin/plugin.json": json.dumps({
        "name": "conn-plugin", "version": "1.0.0", "description": "Needs a key.",
        "skills": "./skills/", "mcp": ".mcp.json"}),
    "skills/conn-skill/SKILL.md": SKILL % ("Conn", "conn", "Conn"),
    ".mcp.json": json.dumps({"mcpServers": {
        "keyed": {"command": "python3", "args": ["-c", "pass"],
                  "env": {"TOKEN": "${V1060_ABSENT_KEY}"}}}}),
})
res = mp.install(conn)
rec, rows = members_of("plugin/conn-plugin")
keyed = member(rows, "keyed")
check("A1 the package installs even though one member cannot start",
      res.get("ok") is True and len(rows) == 2, res)
check("A2 the connector is installed OFF with the state that says why",
      keyed.get("enabled") is False and keyed.get("state") == "needs-key",
      keyed)
check("A3 the record names the missing key",
      "V1060_ABSENT_KEY" in str(keyed.get("error")), keyed.get("error"))
check("A4 the record keeps what the package SAID (title + description)",
      rec.get("title") == "conn-plugin" and rec.get("description") == "Needs a key.", rec)
check("A5 the owner does not pretend it is running",
      (mcp_client.load_doc().get("clients") or {}).get("keyed", {}).get("enabled") is False)
block = slash.plugin_block("conn-plugin")
check("A6 the activation says the key is what is missing",
      "NOT READY" in block and "V1060_ABSENT_KEY" in block and "Settings" in block, block)

# ── B: a plain server is enabled and verified during the install ──────────
reset()
fake = pkg("fake-plugin", {
    ".trae-plugin/plugin.json": json.dumps({
        "name": "fake-plugin", "version": "2.0.0",
        "description": "A fake plugin for the activation test.",
        "skills": "./skills/", "mcp": ".mcp.json"}),
    "skills/fake-skill/SKILL.md": SKILL % ("Fake", "fake", "Fake"),
    ".mcp.json": json.dumps({"mcpServers": {
        "fake": {"command": "python3", "args": ["-c", "pass"]}}}),
})
res = mp.install(fake)
rec, rows = members_of("plugin/fake-plugin")
fake_member = member(rows, "fake")
check("B1 the install reports every member it produced",
      res.get("ok") is True and [m.get("name") for m in rows] == ["fake-skill", "fake"], res)
check("B2 the MCP member is ENABLED, CONNECTED and counted",
      fake_member.get("enabled") is True and fake_member.get("state") == "ready"
      and fake_member.get("tools") == 1, fake_member)
check("B3 the owner config really carries the server switched on",
      (mcp_client.load_doc().get("clients") or {}).get("fake", {}).get("enabled") is True)
check("B4 the server's tools are reachable by the model, still approval-gated",
      (registry.load_config().get("tools") or {}).get("fake__hello", {}).get("enabled") is True
      and (registry.load_config().get("tools") or {}).get("fake__hello",
                                                         {}).get("approval") == "required")
state = market.plugin_states().get("plugin/fake-plugin") or {}
check("B5 the plugin reports itself READY, member by member",
      state.get("ready") is True and state.get("live") == 2 and state.get("total") == 2, state)

# ── C: the activation block tells the truth and forbids improvising ───────
block = slash.plugin_block("fake-plugin")
check("C1 the block opens with the live status and the tool count",
      "Status: READY \u2014 2/2 members live (1 tool)" in block, block[:400])
check("C2 it says where the plugin came from",
      "Source: Trae" in block, block[:400])
check("C3 it names the server's live state, not just its path",
      "- mcp fake \u2014 connected, 1 tool" in block, block)
check("C4 it forbids installing/repairing a member itself",
      "NEVER install" in block and "mcp.upsert" in block and "npx" in block, block)
check("C5 it stays bounded", len(block.encode("utf-8")) <= slash.MAX_BLOCK, len(block))
# A package may name a skill and a server the SAME thing (`chrome-devtools` does):
# joining the live state by name alone gave the skill the server's tool count.
reset()
same = pkg("same-name", {
    ".trae-plugin/plugin.json": json.dumps({
        "name": "same-name", "description": "A skill and a server called twin.",
        "skills": "./skills/", "mcp": ".mcp.json"}),
    "skills/twin/SKILL.md": SKILL % ("Twin", "twin", "Twin"),
    ".mcp.json": json.dumps({"mcpServers": {
        "twin": {"command": "python3", "args": ["-c", "pass"]}}}),
})
check("C6 the package installs", mp.install(same).get("ok") is True)
row = next(p for p in slash.plugins() if p["name"] == "same-name")
twin_skill = next(m for m in row["members"] if m["kind"] == "skill")
twin_mcp = next(m for m in row["members"] if m["kind"] == "mcp")
check("C7 a skill and a server with the same name keep their own state",
      twin_skill.get("state") == "ready" and twin_skill.get("tools") == 0
      and twin_mcp.get("state") == "ready" and twin_mcp.get("tools") == 1,
      row["members"])

# ── E: an external MCP tool is not given a `workspace` key ────────────────
# The session from section B is still live: no reinstall, so the record keeps
# the target the first install wrote.
check("E1 the external tool is registered by its owner as an MCP tool",
      (registry.tool_spec("fake__hello") or {}).get("origin") == "mcp",
      registry.tool_spec("fake__hello"))
check("E2 the gate does NOT inject `workspace` into it",
      api_v02._workspace_is_object_field("fake__hello") is True)
check("E3 a native tool is unaffected",
      api_v02._workspace_is_object_field("fs.read") is False)
# The manager starts clients lazily (first tool listing). A service that has not got
# there yet must not be called broken — the member is `starting`, and the plugin is
# still READY with a sentence that says when the servers come up.
reset()
starting = market.plugin_states().get("plugin/fake-plugin") or {}
check("E4 a not-yet-started service is not reported as a broken plugin",
      starting.get("ready") is True
      and [m["state"] for m in starting.get("members") or [] if m["kind"] == "mcp"] == ["starting"],
      starting)
check("E5 the activation says when the servers start",
      "the servers start on first use" in slash.plugin_block("fake-plugin"),
      slash.plugin_block("fake-plugin")[:200])

# ── D: a server that cannot start is a state, not a rollback ──────────────
reset()
broken = pkg("broken-plugin", {
    ".trae-plugin/plugin.json": json.dumps({
        "name": "broken-plugin", "description": "Starts nowhere.",
        "skills": "./skills/", "mcp": ".mcp.json"}),
    "skills/broken-skill/SKILL.md": SKILL % ("Broken", "broken", "Broken"),
    ".mcp.json": json.dumps({"mcpServers": {
        "broken": {"command": "python3", "args": ["-c", "pass"]}}}),
})
FakeSession.mode = "fail"
res = mp.install(broken)
rec, rows = members_of("plugin/broken-plugin")
broken_member = member(rows, "broken")
check("D1 the install succeeds: the files are installed",
      res.get("ok") is True, res)
check("D2 the member is recorded as ERROR with the server's own reason",
      broken_member.get("state") == "error" and "node 24" in str(broken_member.get("error")),
      broken_member)
check("D3 the skill it carries is still on disk",
      os.path.isdir(os.path.join(os.environ["LONGRUN_SKILLS_DIR"], "local", "broken-skill")))
block = slash.plugin_block("broken-plugin")
check("D4 the activation says NOT READY and quotes the reason",
      "NOT READY" in block and "node 24" in block, block)
FakeSession.mode = "ok"

# ── F: the child's stderr is the error ────────────────────────────────────
child = ("import sys;sys.stderr.write('ENGINE: node too old for this\\n');sys.exit(3)")
sess = _RealSession("stderr-child", {"command": sys.executable, "args": ["-c", child]})
started = sess._connect_stdio(sys.executable, ["-c", child], {})
ok = sess.initialize() if started else False
sess.close()
check("F1 a child that exits is not initialized",
      started is True and ok is False, (started, ok))
check("F2 its own sentence is in connection_error",
      "node too old" in str(sess.connection_error), sess.connection_error)

# ── G: uninstall restores a pre-existing client ───────────────────────────
reset()
_doc = mcp_client._load_local_doc()
_doc["clients"]["pre"] = {"command": "python3", "args": ["-c", "pass"], "enabled": False}
mcp_client._save_local_doc(_doc)
pre = pkg("pre-plugin", {
    ".trae-plugin/plugin.json": json.dumps({
        "name": "pre-plugin", "description": "Reuses a server.",
        "skills": "./skills/", "mcp": ".mcp.json"}),
    "skills/pre-skill/SKILL.md": SKILL % ("Pre", "pre", "Pre"),
    ".mcp.json": json.dumps({"mcpServers": {
        "pre": {"command": "python3", "args": ["-c", "pass"]}}}),
})
res = mp.install(pre)
rec, rows = members_of("plugin/pre-plugin")
pre_member = member(rows, "pre")
check("G1 an existing client is reused, not re-written, and it IS activated",
      res.get("ok") is True and pre_member.get("created") is False
      and pre_member.get("prev_enabled") is False and pre_member.get("enabled") is True,
      pre_member)
check("G2 the plugin did not create it",
      mcp_client.load_doc()["clients"].get("pre", {}).get("enabled") is True)
res = market.forget("plugin/pre-plugin", remove_target=True)
clients = mcp_client.load_doc().get("clients") or {}
check("G3 uninstall puts the pre-existing client back the way it found it",
      res.get("ok") is True and "pre" in clients and clients["pre"].get("enabled") is False,
      clients.get("pre"))
check("G4 and removes what it did create",
      not os.path.isdir(os.path.join(os.environ["LONGRUN_SKILLS_DIR"], "local", "pre-skill")))

# ── H: an unknown plugin is a refusal, and the surfaces are wired ─────────
unknown = slash.plugin_block("no-such-plugin")
check("H1 an unknown plugin is an explicit refusal, never silence",
      "no installed plugin named" in unknown and "never by the model" in unknown, unknown)
check("H2 the refusal lists what IS installed",
      "fake-plugin" in unknown, unknown[:400])
check("H3 the Manage row carries readiness from the server",
      "pluginStates" in open(os.path.join(REPO, "webui", "assets", "market.js"),
                             encoding="utf-8").read()
      and "not ready" in open(os.path.join(REPO, "webui", "assets", "market.js"),
                              encoding="utf-8").read())
check("H4 the CLI documents that plugin-add activates",
      "ACTIVATES the servers" in open(os.path.join(REPO, "docs", "CLI.md"),
                                      encoding="utf-8").read())

print("\n---\nv1060: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
