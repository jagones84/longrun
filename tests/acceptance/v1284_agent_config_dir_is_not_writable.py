#!/usr/bin/env python3
"""v1284 — the app CONFIG dir is not agent-writable.

Bug hunt 2026-11-23 (F-003). `~/.longrun/config` holds the GLOBAL RULES
(`Global_rules.md`, injected into every prompt) plus the routing / providers /
decisions / subagents configs. The golden rule is "the RULES are written by the
human — the agent at most PROPOSES". The dir sat outside the Nucleous and outside
every `matrix_guard._store_targets` entry, so the agent's `python.run` door
allowed writing `Global_rules.md` — a tool call could rewrite its own persistent
instructions. Fix: the config dir is a protected store (python door via
`_store_targets`; shell door via a `config/tools.yaml` deny).

Contract:
  A the config dir is PROTECTED: the python door refuses a write to the global
    rules and to config.json, and the shell door denies a redirect into it
  B no over-block: an ordinary python write, an ordinary shell command, and a
    write inside the Matrix runtime dir (`~/.longrun/matrix`) all stay allowed
  C the global rules file is not created by the refused write

Deterministic: no model, no network, isolated temp dirs.
Run: python3 tests/acceptance/v1284_agent_config_dir_is_not_writable.py
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


tmp = tempfile.mkdtemp(prefix="sf-v1284-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "config")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")

from longrun.tools import matrix_guard          # noqa: E402
from longrun.tools import registry              # noqa: E402
from longrun.util import paths                  # noqa: E402
from longrun.memory import rules                # noqa: E402

registry._external_tools = lambda: {}
grules = rules.global_rules_path()
cfgjson = paths.config_file()

# ---- A: the config dir is protected, in the python and shell doors ---------
check("A1 the global-rules file is inside a PROTECTED store",
      matrix_guard._is_store(grules) is True, grules)
check("A2 config.json is inside a PROTECTED store",
      matrix_guard._is_store(cfgjson) is True, cfgjson)
ok_g, why_g = matrix_guard.check_python_write(
    "open(%r,'w').write('x')" % grules)
check("A3 the python door refuses to write the global rules", ok_g is False, why_g)
# the shell door keys on the DEFAULT app home (a text rule), so test that shape
_dshell, _w = registry.classify("shell.exec", {
    "command": "echo x >> /home/u/.longrun/config/Global_rules.md"})
check("A4 the shell door denies a redirect into the config dir",
      _dshell == "denied" and "hard-deny pattern" in str(_w), (_dshell, _w))

# ---- B: no over-block ------------------------------------------------------
ok_ok, _ = matrix_guard.check_python_write(
    "open(%r,'w').write('hi')" % os.path.join(tmp, "scratch.txt"))
check("B1 an ordinary python write is still allowed", ok_ok is True, _)
d_ok, _ = registry.classify("shell.exec", {"command": "echo hi"})
check("B2 an ordinary shell command is still allowed", d_ok != "denied", d_ok)
d_mx, _ = registry.classify("shell.exec", {
    "command": "echo x >> /home/u/.longrun/matrix/notes.txt"})
check("B3 a write inside the Matrix runtime dir is still allowed",
      d_mx != "denied", d_mx)

# ---- C: nothing was written -----------------------------------------------
check("C1 the refused write created no global-rules file", not os.path.exists(grules), grules)

print("---")
ok_n = sum(RESULTS)
print("v1284: %d/%d PASS" % (ok_n, len(RESULTS)))
raise SystemExit(0 if ok_n == len(RESULTS) else 1)
