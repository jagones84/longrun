#!/usr/bin/env python3
"""v579 — Matrix scaffold -> verify contract (F1) + dotted-name remove (F2 guard).

F1 (confirmed by repro): `scaffold tool testing.hello` writes
`tools/testing.py` with TOOL_SCHEMAS (plural), but
`verify_target tool testing.hello` resolves `tools/testing.hello.py`
("artifact not found") and the contract check accepts only TOOL_SCHEMA
(singular) — so no scaffolded tool can ever verify -> promote is blocked.

F2 (reported live, not reproduced in isolation): `remove` must delete the
namespace file for dotted and plain names alike. Locked here as a guard.

Deterministic, no model, no network, no server. repo_root=TMP isolates all.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v579-")
for name, tail in {
    "LONGRUN_DATA_DIR": "data",
    "LONGRUN_CONFIG_DIR": "cfg",
    "LONGRUN_DB": "events.db",
    "LONGRUN_SESSIONS_DIR": "sessions",
    "LONGRUN_GRAPH_DIR": "graphs",
    "LONGRUN_EDITS_DIR": "edits",
    "LONGRUN_RUNS_DIR": "runs",
    "LONGRUN_ROLES_DIR": "roles",
    "LONGRUN_COSTS_DIR": "costs",
    "LONGRUN_THREADS_DIR": "threads",
    "LONGRUN_MATRIX_SRC": "matrix_src",
    "LONGRUN_MATRIX_DOT": "matrix_dot",
    "LONGRUN_APPROVALS": "approvals.json",
}.items():
    os.environ[name] = os.path.join(TMP, tail)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import matrix  # noqa: E402
from longrun.tools import matrix_guard  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


matrix_guard.ensure_layout(TMP)

# ---- F1a: dotted tool name resolves to the namespace file ------------------
k, nm, fpath = matrix._resolve_target_path("tool", "testing.hello", TMP)
want = os.path.join(matrix._roots(TMP)[1], "tools", "testing.py")
check("F1a dotted tool name resolves to the namespace file",
      fpath == want, fpath)

# ---- F1b: a scaffolded tool verifies after a recorded test -----------------
made = matrix.scaffold("tool", "testing.hello", "F1 repro tool.", repo_root=TMP)
check("scaffold writes the namespace file",
      made.get("ok") is True and os.path.isfile(made.get("path") or ""),
      made.get("error") or made.get("path"))
if made.get("ok"):
    matrix._record_verified("tool", "testing.hello", "test_matrix.py", TMP)
    v = matrix.verify_target("tool", "testing.hello", repo_root=TMP)
    check("F1b scaffolded (plural TOOL_SCHEMAS) tool verifies",
          v.get("ok") is True, v.get("error"))
    matrix._record_verified("tool", "testing", "test_matrix.py", TMP)
    v2 = matrix.verify_target("tool", "testing", repo_root=TMP)
    check("F1c namespace name verifies too", v2.get("ok") is True, v2.get("error"))

# ---- F2 guard: remove deletes the namespace file for both name forms -------
made2 = matrix.scaffold("tool", "probe.check", "F2 guard tool.", repo_root=TMP)
if made2.get("ok"):
    r = matrix.remove("tool", "probe.check", repo_root=TMP)
    check("F2a remove by dotted name deletes the namespace file",
          r.get("ok") is True and r.get("removed")
          and not os.path.exists(made2.get("path") or ""), r)
made3 = matrix.scaffold("tool", "probe2", "F2 guard tool 2.", repo_root=TMP)
if made3.get("ok"):
    r2 = matrix.remove("tool", "probe2", repo_root=TMP)
    check("F2b remove by plain name deletes the namespace file",
          r2.get("ok") is True and r2.get("removed")
          and not os.path.exists(made3.get("path") or ""), r2)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
