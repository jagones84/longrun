#!/usr/bin/env python3
"""v414 — native self-diagnosis (JAG-426 · Domain 1).

The harness must be able to inspect ITSELF (health, its own event log, its
context occupancy, its tool policy) with NO dependency on an external process/
performance manager, and every probe must DEGRADE instead of raising when a
system tool is missing (no nvidia-smi, no /proc, no session).

Deterministic, no live server, no network. Run: python3 tests/v414_self_diag.py
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v414-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import diag           # noqa: E402
from longrun.tools import registry       # noqa: E402
from longrun.tools import tools as T     # noqa: E402

registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- 1. health() never raises and carries the expected shape ----------------
h = diag.health()
check("1a health() returns ok + the core keys",
      h.get("ok") is True and all(k in h for k in
      ("ts", "version", "python", "cpu", "memory_mb", "disk", "gpu", "service", "ports")),
      sorted(h.keys()))
check("1b cpu count + disk are probed on this host",
      isinstance(h["cpu"].get("count"), int) and (h["disk"] is None or "free_gb" in h["disk"]))
check("1c ports are probed natively (bools)",
      all(isinstance(v, bool) for v in h["ports"].values()), h["ports"])

# ---- 2. graceful degradation when nvidia-smi is absent ----------------------
_real_which = shutil.which
shutil.which = lambda name, *a, **k: None
try:
    h2 = diag.health()
finally:
    shutil.which = _real_which
check("2 no nvidia-smi -> gpu None, still ok (no raise)",
      h2.get("ok") is True and h2.get("gpu") is None)

# ---- 3. tools_report mirrors the registry -----------------------------------
tr = diag.tools_report()
check("3a tools_report lists native tools incl. shell/self/fs.read",
      tr.get("ok") is True and {"shell", "self", "fs.read"}.issubset(set(tr.get("native", []))),
      tr.get("count"))
check("3b external MCP tools are separated (names contain '__')",
      all("__" in n for n in tr.get("external", [])))
check("3c tools_report agrees with registry.catalog()",
      tr.get("count") == len([t for t in registry.catalog() if t.get("name") and "__" not in t["name"]]))

# ---- 4. log_tail is bounded + safe on an empty event log --------------------
lt = diag.log_tail(limit=5)
check("4 log_tail bounded + no raise", lt.get("ok") is True and len(lt.get("lines", [])) <= 5,
      lt.get("count"))

# ---- 5. the `self` tool routes on `action` (no new tool name) ---------------
info = T.execute("self", {"action": "info"})
check("5a action=info keeps the static self-knowledge (back-compat)",
      info.get("ok") is True and info.get("repo_path") == REPO)
diag_res = T.execute("self", {"action": "diagnose"})
check("5b action=diagnose attaches a health snapshot",
      diag_res.get("diagnose", {}).get("ok") is True
      and diag_res.get("repo_path") == REPO)
t_res = T.execute("self", {"action": "tools"})
check("5c action=tools attaches the tool policy",
      t_res.get("tools", {}).get("ok") is True)
bad = T.execute("self", {"action": "nope"})
check("5d an unknown action reports it but keeps the static info",
      "error" in bad and bad.get("repo_path") == REPO)

# ---- 6. context() introspection (dry run, no LLM) ---------------------------
try:
    from longrun.core import server as s
    s.get_or_create_session("v414s", title="v414 session")
    cx = diag.context("v414s")
    check("6 context() introspects a real session (dry run)",
          cx.get("ok") is True and isinstance(cx.get("context"), dict), str(cx)[:120])
except Exception as e:  # noqa: BLE001
    check("6 context() introspects a real session (dry run)", False, "raised: %s" % e)

print("---")
okc = sum(results)
print("\nv414: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
