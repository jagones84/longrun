#!/usr/bin/env python3
"""v718 — `self.info` states WHO is asking and WHICH namespaces are enabled.

Found by the A53 drill: a model asked "which agent am I, which namespaces do I
have?" and `self.info` answered with paths, config and service state only. The
dispatch contract is `fn(args, run_id)`, so nothing else reaches a handler; the
identity is decided at the GATE (`api_v02._session_scope`) and was never exposed.

  A  an unrestricted session reports its id, no role, trust and every namespace
  B  an ORG agent reports its id/role and the scope actually admits fewer tools
     than the namespace exposes
  C  a disabled namespace is named as disabled instead of looking identical
  D  identity never breaks the report (no session, no registry answers)

Deterministic: no live model, no network, no server.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v718-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402
from longrun.tools import diag  # noqa: E402
from longrun.tools import registry  # noqa: E402
from longrun.agent import agents  # noqa: E402
from longrun.agent import subagent  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


# ------------------------------------- A: plain session --------------------
r = T._self({"action": "info"}, "sess-plain")
ident = r.get("identity") or {}
check("A1 the report carries identity", ident.get("session_id") == "sess-plain", ident)
check("A2 a plain session has no role", ident.get("role") is None, ident)
check("A3 its scope is unrestricted", ident.get("scope") == "unrestricted", ident)
check("A4 the trust profile is reported", ident.get("trust") == "standard", ident)

ns = r.get("namespaces") or {}
check("A5 the report carries namespaces", bool(ns.get("ok")) and ns.get("count", 0) > 3, ns)
check("A6 an enabled namespace exists (fs)", "fs" in (ns.get("enabled") or []),
      ns.get("enabled"))
check("A7 unrestricted admits every enabled namespace",
      ns.get("admitted") == ns.get("enabled"), ns.get("admitted"))
check("A8 a namespace reports its tool count",
      (ns.get("namespaces") or {}).get("fs", {}).get("tools", 0) >= 2,
      (ns.get("namespaces") or {}).get("fs"))

# ------------------------------------- B: org agent with a scoped role ------
sid = "sess-agent-1"
with open(os.environ["LONGRUN_AGENTS_FILE"], "w", encoding="utf-8") as f:
    json.dump({"agents": {sid: {"id": "AX1", "name": "Tester", "role": "tester",
                                "n": 1}}, "seq": 1}, f)
subagent.load_cfg._cache = {"roles": {"tester": {"brief": "test it",
                                                 "tools": ["fs.read"]}}}
r2 = T._self({"action": "info"}, sid)
i2 = r2.get("identity") or {}
check("B1 an org agent reports its agent id", i2.get("agent_id") == "AX1", i2)
check("B2 it reports its role", i2.get("role") == "tester", i2)
check("B3 the role scope is listed verbatim", i2.get("scope") == ["fs.read"], i2)
n2 = r2.get("namespaces") or {}
fs2 = (n2.get("namespaces") or {}).get("fs") or {}
check("B4 the namespace exposes more tools than the scope admits",
      fs2.get("tools", 0) > fs2.get("admitted", 0) == 1, fs2)
check("B5 a fully denied namespace is not admitted",
      "shell" not in (n2.get("admitted") or []), n2.get("admitted"))
check("B6 admitted is a SUBSET of enabled",
      set(n2.get("admitted") or []) <= set(n2.get("enabled") or []), n2.get("admitted"))

# ------------------------------------- C: a disabled namespace -------------
cfg = registry.load_config()
cfg.setdefault("tools", {})["memory"] = {"enabled": False}
registry.save_config(cfg)
registry.load_config(reload=True)
n3 = diag.namespaces()
check("C1 a disabled namespace is named", "memory" in (n3.get("disabled") or []),
      n3.get("disabled"))
check("C2 it exposes zero enabled tools",
      (n3.get("namespaces") or {}).get("memory", {}).get("enabled") == 0,
      (n3.get("namespaces") or {}).get("memory"))

# ------------------------------------- D: never breaks ---------------------
r4 = T._self({"action": "info"}, None)
check("D1 no session still answers", bool(r4.get("ok")) and "identity" in r4, r4)
check("D2 the A53 fields are the documented ones",
      set(("identity", "namespaces")) <= set(T._self({}, "x").keys()))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
