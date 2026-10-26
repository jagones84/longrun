#!/usr/bin/env python3
"""v459 — JAG-462 sweep: the bugs found by the bug-hunt run.

Covers, each with an independent failure mode:
  A) `config/compaction.yaml` was SILENTLY IGNORED (the loader unwrapped the policy
     twice, so `.get("compaction")` was always None and the hard-coded defaults won).
  B) `keepgoing.hitl_gate` fired on an ABORT (`user_stop`), popping a "⏸ Paused"
     card the moment the operator pressed Stop.
  C) an external MCP client whose config key differs in CASE from the policy key
     (live: `PMCP` vs `pmcp__gateway.*`) had EVERY tool silently DISABLED.
  D) hybrid knowledge search returned a list-of-lists query vector, so cosine was
     always 0.0 (semantic retrieval silently degraded to lexical).
  E) deleting a session did not purge its per-session COST ledger (orphan files).
  F) the skills cache fingerprint ignored the SKILL.md file, so an edited skill kept
     its stale description in the system prompt.
  G) `routing.pick(preferred)` matched the pin case-SENSITIVELY and could return a
     model the router marked FAILED.
  H) a helper's durable publish + the caller's `on_event` publish wrote every
     graph/tool event TWICE to events.db.
  I) WebUI: unescaped model-authored `deps` in the Plan list (stored XSS); the slash
     picker also fired on Ctrl/Cmd+Enter (double action); deleting a session leaked
     its browser-side caches.
  J) harness: an ABORTED run was "finalized" (open todos force-closed as `done` with
     fabricated evidence); the close-todos override ignored `plan_only`/`autonomous`.

Deterministic: no model, no network, no server.
"""
import json
import os
import sqlite3
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v459-")
for _k, _d in (("LONGRUN_CONFIG_DIR", "cfg"), ("LONGRUN_SESSIONS_DIR", "sessions"),
               ("LONGRUN_GRAPH_DIR", "graphs"), ("LONGRUN_THREADS_DIR", "threads"),
               ("LONGRUN_COSTS_DIR", "costs")):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
    os.environ[_k] = os.path.join(TMP, _d)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_KNOWLEDGE_DIR"] = os.path.join(TMP, "knowledge")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import events                      # noqa: E402
from longrun.model import compaction_config as cc    # noqa: E402
from longrun.model import costs, routing             # noqa: E402
from longrun.model import embed as embed_mod         # noqa: E402
from longrun.memory import knowledge as K            # noqa: E402
from longrun.memory import stores                    # noqa: E402
from longrun.plan import keepgoing                   # noqa: E402
from longrun.tools import registry as R              # noqa: E402

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """Record and print one deterministic acceptance check."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(rel: str) -> str:
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


# ---- A) the compaction policy file is honoured --------------------------------
_p = os.path.join(TMP, "compaction.yaml")
with open(_p, "w", encoding="utf-8") as f:
    f.write("compaction:\n  trigger_pct: 12\n  target_pct: 5\n  keep_recent: 2\n")
_orig_cc_path, _orig_cc_local = cc._PATH, cc._LOCAL_PATH
cc._PATH = _p
# The loader reads TWO files since JAG-487: the shipped policy AND the per-machine
# WebUI overlay (`compaction.local.yaml`). Isolate BOTH, or a machine with a saved
# overlay leaks its values into this assertion.
cc._LOCAL_PATH = os.path.join(TMP, "compaction.local.yaml")
cc.reset_cache()
try:
    _pol = cc.load(force=True)
finally:
    cc._PATH, cc._LOCAL_PATH = _orig_cc_path, _orig_cc_local
    cc.reset_cache()
check("A1 config/compaction.yaml is READ, not silently replaced by the defaults",
      _pol.get("trigger_pct") == 12 and _pol.get("keep_recent") == 2,
      "trigger=%s keep=%s" % (_pol.get("trigger_pct"), _pol.get("keep_recent")))

# ---- B) the HITL gate never fires on an abort ---------------------------------
check("B1 hitl_gate('user_stop') does NOT fire",
      keepgoing.hitl_gate("user_stop", [{"id": "n1"}]) is False)
check("B2 hitl_gate('budget') still fires (no regression)",
      keepgoing.hitl_gate("budget", [{"id": "n1"}]) is True)
check("B3 hitl_gate never fires on a user pivot",
      keepgoing.hitl_gate("user_pivot", [{"id": "n1"}]) is False)

# ---- C) a case-differing external client still resolves its policy ------------
_orig_lc = R.load_config
R.load_config = lambda *a, **k: {"tools": {"pmcp__gateway.health": {"enabled": True}}}
_orig_ext = R._external_tools
R._external_tools = lambda: {"PMCP__gateway.health": {
    "description": "x", "inputSchema": {"type": "object", "properties": {}}}}
try:
    _spec = R.tool_spec("PMCP__gateway.health")
finally:
    R.load_config = _orig_lc
    R._external_tools = _orig_ext
check("C1 a mixed-case external tool resolves its lowercase policy entry",
      bool(_spec) and _spec.get("enabled") is True, str(_spec)[:90])
_mc_src = _read("src/longrun/interop/mcp_client.py")
check("C2 external tool names lowercase the client key at registration",
      "str(cname).strip().lower()" in _mc_src)

# ---- D) the hybrid query vector is FLAT ---------------------------------------
_orig_et = embed_mod.embed_texts
embed_mod.embed_texts = lambda texts, model=None: ([[0.1, 0.2, 0.3]], {})
try:
    _qv = K._embed_texts_query("m", "hello")
finally:
    embed_mod.embed_texts = _orig_et
check("D1 the query embedding is a flat float vector (cosine can work)",
      isinstance(_qv, list) and len(_qv) == 3 and isinstance(_qv[0], float), str(_qv))

# ---- E) deleting a session purges its cost ledger -----------------------------
costs.record("vsweep", "m", {"prompt_tokens": 5, "completion_tokens": 5})
_cpath = costs._path("vsweep")
check("E0 the cost ledger exists before the purge", os.path.exists(_cpath), _cpath)
stores._purge_session_artifacts("vsweep")
check("E1 deleting a session purges its cost ledger", not os.path.exists(_cpath), _cpath)

# ---- F) the skills fingerprint includes the SKILL.md file ---------------------
check("F1 the skills signature fingerprints SKILL.md (not just the dir)",
      'os.path.join(sd, "SKILL.md")' in _read("src/longrun/memory/skills.py"))

# ---- G) routing.pick honours a pin case-insensitively and skips FAILED ---------
_orig_roster, _orig_lc2 = routing._roster, routing.load_config
routing.load_config = lambda *a, **k: {"roles": {"chat": {"pattern": "other",
                                                          "fallbacks": []}},
                                       "default_fallbacks": []}
try:
    routing._roster = lambda: [{"alias": "Qwen3", "loaded": True, "failed": False},
                               {"alias": "other-1", "loaded": True, "failed": False}]
    _got = routing.pick("chat", preferred="qwen3")
    routing._roster = lambda: [{"alias": "dead", "loaded": True, "failed": True}]
    _dead = routing.pick("chat", preferred="dead")
finally:
    routing._roster, routing.load_config = _orig_roster, _orig_lc2
check("G1 a case-differing pin resolves to the roster alias", _got == "Qwen3", str(_got))
check("G2 a FAILED pin is never returned", _dead is None, str(_dead))

# ---- H) a back-to-back duplicate event is collapsed ---------------------------
events.publish("graph.node.added", session="s", node={"id": "n1"})
events.publish("graph.node.added", session="s", node={"id": "n1"})
events.publish("graph.node.added", session="s", node={"id": "n2"})
_con = sqlite3.connect(os.environ["LONGRUN_DB"])
_n = _con.execute("SELECT COUNT(*) FROM events WHERE kind='graph.node.added'").fetchone()[0]
_con.close()
check("H1 a helper publish + the caller re-emit writes ONE row", _n == 2, "rows=%s" % _n)

# ---- I) WebUI wiring ----------------------------------------------------------
_html = _read("webui/index.html")
check("I1 the Plan list ESCAPES model-authored dep ids",
      "⤷ ${esc(n.deps.join" in _html)
# v680: the open `/` menu now OWNS Enter (with or without Ctrl): it picks the
# highlighted command, and the send handler returns early in that exact state so
# the keystroke can never both pick and send. Shift+Enter still inserts a newline.
check("I2 the slash picker owns Enter while it is open (Shift+Enter excepted)",
      'e.key === "Enter" && !e.shiftKey' in _html
      and "if (menu && !menu.hidden && _slashItems.length) return;" in _html)
check("I3 deleting a session drops its browser-side caches",
      "delete _sessModel[s.id]" in _html and "delete _sessJob[s.id]" in _html
      and "clearDone(s.id);" in _html)

# ---- J) harness: abort + plan-only -------------------------------------------
_ag = _read("src/longrun/agent/agent.py")
check("J1 an ABORTED run is never finalized into fake 'done'",
      "if not aborted:" in _ag
      and "finish_run_graph(trace.id, None, goal, on_event=on_event)" in _ag)
check("J2 the close-todos override is skipped for plan_only/autonomous turns",
      "not plan_only and not autonomous" in _ag)
check("J3 the `self` report exposes the EFFECTIVE MCP clients",
      'info["mcp"] = {' in _read("src/longrun/tools/tools.py"))

# ---- K) the external registry is derived from the LIVE sessions ---------------
from longrun.interop import mcp_client as mc   # noqa: E402


class _FakeSess:
    def __init__(self, tools):
        self.tools = tools
        self.connected = True


_mgr = mc.MCPClientManager()
mc._EXTERNAL_TOOLS.clear()
_mgr.sessions["PMCP"] = _FakeSess({"gateway.health": {
    "description": "h", "inputSchema": {"type": "object", "properties": {}}}})
_names = sorted(t["name"] for t in _mgr.list_external_tools())
check("K1 an EMPTY external registry self-heals from the live sessions",
      _names == ["pmcp__gateway.health"], str(_names))
check("K2 the registered name lowercases the client key",
      all(n.split("__", 1)[0] == "pmcp" for n in _names), str(_names))

print("---")
okc = sum(results)
print("\nv459: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)