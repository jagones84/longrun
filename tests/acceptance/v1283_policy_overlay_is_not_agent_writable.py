#!/usr/bin/env python3
"""v1283 — the policy overlay is the permission layer and is NOT agent-writable.

Bug hunt 2026-11-23 (F-002). `data/tools.overlay.yaml` is the programmatic
policy overlay: `load_config` merges it ON TOP of `config/tools.yaml` with a
per-tool SHALLOW update, so an overlay `tools: {<t>: {deny: []}}` ERASES the
shipped hard-deny list (the `.env`, `LONGRUN_TOKEN` and control-API rules). The
file sat DIRECTLY under the data dir — not a protected subdir — so it was not in
`matrix_guard._store_targets` and the agent's `python.run` door allowed writing
it, letting a tool call lift its own hard denies. Fix: the overlay is protected
like the harness record (python door via `_store_targets`, shell door via a
`config/tools.yaml` deny); the operator still writes it through `save_config`.

Contract:
  A the overlay is a PROTECTED store: the python door refuses a write, the shell
    door denies a redirect, and fs roots already exclude it
  B no over-block: an ordinary python write and an ordinary shell command are
    still allowed
  C the hard-deny survives: with the agent's write refused, `.env` stays denied

Deterministic: no model, no network, isolated temp dirs.
Run: python3 tests/acceptance/v1283_policy_overlay_is_not_agent_writable.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


tmp = tempfile.mkdtemp(prefix="sf-v1283-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "config")

from longrun.tools import matrix_guard          # noqa: E402
from longrun.tools import registry              # noqa: E402

registry._external_tools = lambda: {}
overlay = registry.OVERLAY_YAML

# ---- A: the overlay is a PROTECTED store, in every door --------------------
check("A1 the policy overlay is inside a PROTECTED store",
      matrix_guard._is_store(overlay) is True, overlay)
ok_py, why_py = matrix_guard.check_python_write(
    "open(%r,'w').write('tools: {fs: {read: {deny: []}}}')" % overlay)
check("A2 the python door refuses to write the overlay", ok_py is False, why_py)
dec, why = registry.classify("shell.exec", {"command": "printf x >> %s" % overlay})
check("A3 the shell door denies a redirect to the overlay",
      dec == "denied" and "hard-deny pattern" in str(why), (dec, why))

# ---- B: no over-block ------------------------------------------------------
ok_ok, _ = matrix_guard.check_python_write(
    "open(%r,'w').write('hi')" % os.path.join(tmp, "scratch.txt"))
check("B1 an ordinary python write is still allowed", ok_ok is True, _)
d_ok, _ = registry.classify("shell.exec", {"command": "echo hi"})
check("B2 an ordinary shell command is still allowed", d_ok != "denied", d_ok)

# ---- C: the hard deny survives (the write never happened) ------------------
d0, r0 = registry.classify("fs.read", {"path": ".env"})
check("C1 `.env` is denied before, and remains denied after, the refused write",
      d0 == "denied" and not os.path.exists(overlay), (d0, str(r0)[:40], os.path.exists(overlay)))

print("---")
ok_n = sum(RESULTS)
print("v1283: %d/%d PASS" % (ok_n, len(RESULTS)))
raise SystemExit(0 if ok_n == len(RESULTS) else 1)
