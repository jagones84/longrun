#!/usr/bin/env python3
"""v1273 — the report-only zone really is report-only (ADR-0003).

`docs/adr/0003` and `harness/checks/__init__.py` state the rule: a module under
`harness/checks/` is pure (data in, verdict out, no app imports) and is reachable
**only** from the CLI, whose single adapter is `core/forge.py`. `AGENTS.md` adds that
it is "proven by the import audit" — no such audit existed as code; this pin is it.

HISTORY: written 2026-11-22 it found the rule CROSSED twice — the running app reached
into the report-only zone from `memory/skills.py` (skill_os_contract) and
`tools/tools.py` (recall_log), contradicting `harness/__init__.py`'s own "Nothing in
`agent/`, `core/` or `tools/` imports them". The conflict was RESOLVED the same day the
way that docstring prescribes ("put the live seam in `longrun.harness`"): both modules
moved up to the `harness/` root, and the adapter + tests + docs moved with them. So the
frozen allow-list is now EMPTY and the rule is a plain invariant: a NEW crossing fails.

Anti-vacuity: self-tests prove the detector still finds an absolute and a relative
import, and does not flag an allowed `harness` root import.

Deterministic: no server, no model, no network (source is parsed only).
Run: python3 tests/acceptance/v1273_checks_reachability.py
"""
import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORE = os.path.join(REPO, "src", "longrun")
ADAPTER = os.path.join("src", "longrun", "core", "forge.py")

# The two live seams that were moved out of the report-only zone on 2026-11-22.
MOVED = ("recall_log", "skill_os_contract")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def reaches_checks(source):
    """Line numbers where this source imports from `...harness.checks`."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "longrun.harness.checks" or mod.endswith("harness.checks"):
                hits.append(node.lineno)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("longrun.harness.checks"):
                    hits.append(node.lineno)
    return hits


# ---- 0. anti-vacuity: the detector still detects ---------------------------
check("self-test: an absolute import from harness.checks is detected",
      reaches_checks("from longrun.harness.checks import fast_path\n") == [1])
check("self-test: a relative import from ...harness.checks is detected",
      reaches_checks("from ..harness.checks import x\n") == [1])
check("self-test: an allowed harness-root import is NOT flagged",
      reaches_checks("from longrun.harness import recall_log\n") == [])

# ---- 1. scan the core ------------------------------------------------------
crossers, files, adapter_sites = [], 0, 0
for dp, _, fs in os.walk(CORE):
    if "__pycache__" in dp:
        continue
    for f in fs:
        if not f.endswith(".py"):
            continue
        files += 1
        path = os.path.join(dp, f)
        rel = os.path.relpath(path, REPO).replace(os.sep, "/")
        with open(path, encoding="utf-8") as fh:
            n = len(reaches_checks(fh.read()))
        if not n:
            continue
        if rel == ADAPTER:
            adapter_sites += n
        else:
            crossers.append((rel, n))

check("the scan really read the core", files >= 200, "files=%d" % files)
check("forge.py is the CLI adapter for the checks (it imports them)",
      adapter_sites >= 20, "adapter_sites=%d" % adapter_sites)

# ---- 2. the invariant -------------------------------------------------------
check("no module outside the forge adapter reaches into the report-only zone",
      not crossers, "crossers=%s" % (crossers or "none"))

# ---- 3. the resolution is in place (the fix cannot silently revert) --------
for name in MOVED:
    at_root = os.path.isfile(os.path.join(CORE, "harness", name + ".py"))
    in_zone = os.path.isfile(os.path.join(CORE, "harness", "checks", name + ".py"))
    check("%s lives at the harness root, not in checks/" % name,
          at_root and not in_zone, "root=%s checks=%s" % (at_root, in_zone))

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
