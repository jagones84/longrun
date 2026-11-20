#!/usr/bin/env python3
"""v1238 — `harness.status`: the ONE deterministic session report (tool + `/status`).

Operator, 2026-11-21:
  *"in the commands (slash /) list there shall be created a command status that reports
  everything information on the session, context saturation, max context, LLM used … that
  command can be deterministically run as tools also by any agent … a generic tool harness
  already present for restart, there shall be put the status command."*

Deterministic: temp stores, no server, no network, no model.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="lr-v1238-")
for key, path in (
        ("LONGRUN_CONFIG_DIR", os.path.join(TMP, "cfg")),
        ("LONGRUN_SESSIONS_DIR", os.path.join(TMP, "sessions")),
        ("LONGRUN_DATA_DIR", os.path.join(TMP, "data")),
        ("LONGRUN_DB", os.path.join(TMP, "events.db")),
        ("LONGRUN_PROJECTS_DIR", os.path.join(TMP, "projects")),
        ("LONGRUN_WORKSPACE", os.path.join(TMP, "ws"))):
    os.environ[key] = path
    if key.endswith(("_DIR", "_WORKSPACE")):
        os.makedirs(path, exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry          # noqa: E402
from longrun.tools import tools as T        # noqa: E402
from longrun.memory import stores           # noqa: E402
from longrun.core import slash              # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- A: the registry contract (schema + field map + guidance) --------------
SCHEMA = registry._LEGACY_SCHEMAS["harness"]
check("A1 status is a declared harness action",
      "status" in (SCHEMA["properties"]["action"].get("enum") or []),
      SCHEMA["properties"]["action"].get("enum"))
check("A2 the canonical subtool has an explicit field map",
      registry._SUBTOOL_FIELDS["harness"].get("status") == ["session"],
      registry._SUBTOOL_FIELDS["harness"].get("status"))
check("A3 it has one actionable guidance line",
      "harness.status" in registry._SUBTOOL_GUIDANCE,
      list(registry._SUBTOOL_GUIDANCE))
check("A4 canonicalisation keeps restart as the bare-name default",
      registry.canonical_name("harness", {}) == "harness.restart")
check("A5 status is not gated (read-only must never ask)",
      registry.subtool_gate("harness.status", {}) is None)

# ---- B: the handler on a real session record -------------------------------
sess = stores.get_or_create_session(None, title="v1238 probe",
                                    workspace=os.environ["LONGRUN_WORKSPACE"])
sid = sess["id"]
res = T._harness({"action": "status", "session": sid}, run_id=None)
check("B1 it answers ok with a session_status kind", res.get("ok") is True
      and res.get("kind") == "session_status", res)
check("B2 it reports identity, model and workspace",
      (res.get("identity") or {}).get("id") == sid
      and "model" in (res.get("identity") or {})
      and "workspace" in (res.get("identity") or {}), res.get("identity"))
check("B3 context saturation vs the MAX context is reported",
      (res.get("context") or {}).get("max_tokens") is not None
      and (res.get("context") or {}).get("tokens_used") is not None
      and "pct" in (res.get("context") or {}), res.get("context"))
check("B4 the live plan, approvals and running state are present",
      isinstance(res.get("plan"), dict) and "open" in res["plan"]
      and isinstance(res.get("approvals"), dict)
      and "running" in res, {k: res.get(k) for k in ("plan", "approvals", "running")})
check("B5 the org identity (agent id / teams / role) is present",
      isinstance(res.get("agent"), dict) and "id" in res["agent"]
      and "teams" in res["agent"], res.get("agent"))
check("B6 there is a one-line human summary", "status[" in (res.get("stdout") or ""),
      res.get("stdout"))
check("B7 an unknown session is a refusal, not a crash",
      T._harness({"action": "status", "session": "nope-nope"}, None).get("ok") is False)
check("B8 it is JSON-serialisable (the tool result is shipped as-is)",
      bool(json.dumps(res)))
# VISTA (arXiv:2606.30005 §3): state proprioception needs the remaining budget in
# absolute tokens, not only a percentage — plus the archive status of curated payloads.
check("B9 the context block carries the remaining-token headroom",
      "remaining_tokens" in res["context"] and "headroom_pct" in res["context"]
      and res["context"]["remaining_tokens"] == res["context"]["max_tokens"]
          - res["context"]["tokens_used"], res["context"])
check("B10 the curated-payload archive status is reported",
      isinstance(res.get("curation"), dict) and "curated" in res["curation"]
      and "tool_cards" in res["curation"], res.get("curation"))

# ---- C: the `/status` slash builtin ----------------------------------------
check("C1 /status is a built-in UI command",
      any(c.get("id") == "status" and c.get("kind") == "ui" for c in slash.BUILTINS),
      [c.get("id") for c in slash.BUILTINS])
check("C2 the built-in token is reserved (a user command cannot shadow it)",
      "status" in slash.RESERVED and "status" in slash.catalog(sid)["reserved"])

# ---- D: the WebUI wires the same tool --------------------------------------
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("D1 the composer runs /status through the tool, not a re-derivation",
      "status: () => openSessionStatus()," in UI
      and 'action: "status", session: sessionId' in UI
      and 'tool: "harness"' in UI)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
