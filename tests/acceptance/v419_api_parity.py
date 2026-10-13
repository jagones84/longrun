#!/usr/bin/env python3
"""v419 — benchmark adapter + API parity (JAG-426 · Domain 3).

A harness that cannot be measured cannot be improved. This pins:
  * the harness-agnostic adapter contract (create_agent / send_task /
    backup_session / restore / delete_agent / docker_args / provenance);
  * that the adapter drives the PUBLIC REST API only (no internal imports), so
    what a benchmark measures is what an external user gets;
  * that the UI, the REST API and the ACP surface all funnel through the SAME
    agent loop with the SAME approval guard (parity).

Deterministic, no live server. Run: python3 tests/v419_api_parity.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, REPO)

from benchmarks.longrun_adapter import LongrunAdapter     # noqa: E402
from benchmarks.protocol import AgentRef, HarnessAdapter  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# ---- 1. the adapter implements the protocol ---------------------------------
ad = LongrunAdapter(base="http://127.0.0.1:9999", token="t", repo=REPO)
check("1a the adapter satisfies the HarnessAdapter protocol", isinstance(ad, HarnessAdapter))
check("1b it exposes name + provenance + docker_args",
      ad.name == "longrun" and callable(ad.provenance) and ad.docker_args() == [])

# ---- 2. it drives the REST API only (no internal imports) -------------------
src = _read("benchmarks", "longrun_adapter.py")
check("2a the adapter imports no longrun internals",
      "import longrun" not in src and "from longrun" not in src)
check("2b it speaks HTTP to the public endpoints",
      "/api/sessions" in src and "/api/chat" in src and "/api/checkpoints" in src)

# ---- 3. the contract maps correctly (fake transport) ------------------------
seen = []


def _fake(method, path, body=None, timeout=None):
    seen.append((method, path))
    if path == "/api/sessions":
        return 200, {"id": "sess1"}
    if path == "/api/chat":
        return 200, {"session": "sess1", "reply": "42", "run_id": "r1"}
    if path == "/api/checkpoints":
        return 200, {"id": "cp1"}
    if path == "/api/checkpoints/restore":
        return 200, {"ok": True}
    if path == "/api/status":
        return 200, {"version": "1.2.3"}
    if path == "/api/self":
        return 200, {"version": "1.2.3", "router": "http://127.0.0.1:8080"}
    return 200, {}


ad._req = _fake
ref = ad.create_agent({"id": "inst-1"})
check("3a create_agent opens a session", isinstance(ref, AgentRef) and ref.session == "sess1")
res = ad.send_task(ref, "solve it")
check("3b send_task returns the reply + run id + provenance",
      res.ok is True and res.output == "42" and res.run_id == "r1"
      and res.provenance.get("version") == "1.2.3")
check("3c backup_session returns a checkpoint id", ad.backup_session(ref) == "cp1")
check("3d restore maps to the restore endpoint", ad.restore(ref, "cp1") is True)
check("3e delete_agent maps to the session route", ad.delete_agent(ref) is True)

# ---- 4. UI / REST / ACP share ONE loop + ONE guard (parity) -----------------
http = _read("src", "longrun", "core", "httpapi.py")
api02 = _read("src", "longrun", "core", "api_v02.py")
acp = _read("src", "longrun", "interop", "acp.py")
check("4a the SSE chat path runs the agent loop",
      "def chat_stream_gen(" in http and "chat_once(" in http)
check("4b the sync POST /api/chat path runs the same loop",
      'if path == "/api/chat":' in http and "chat_once(" in http)
check("4c GET and POST /api/agent/run are both routed (in api_v02, the first dispatcher)",
      api02.count('"/api/agent/run"') >= 2)
check("4d ACP exposes the same agent-level operations",
      "agent/run" in acp and "plan/set" in acp and "tools/call" in acp)
check("4e ACP tools/call goes through the SAME approval gate",
      "gated_call" in acp or "approvals" in acp)

# ---- 5. both chat paths anchor a rewind point -------------------------------
check("5a the stream path anchors the turn",
      "_rewind.mark(" in http)
check("5b every turn anchor is idempotent per (session, message)",
      'idempotency_key="turn:%s:%s"' in _read("src", "longrun", "memory", "checkpoints.py"))

print("---")
okc = sum(results)
print("\nv419: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
