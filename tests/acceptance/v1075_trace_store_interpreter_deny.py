#!/usr/bin/env python3
"""v1075 — the trace-store deny covers the INTERPRETER spelling too.

Rounds 2–4 closed three spellings of one boundary: `fs.*` writes, shell
redirect/delete verbs, and `python.run` (through `matrix_guard.check_python_write`).
Proved live before this change: `shell.exec` auto-approved

    python3 -c "open('data/events.db','w').write('{}')"

under `approvals.mode=full`. The boundary must hold for every execution surface —
agents "decompose operations across tool calls" to evade a monitor
(arXiv:2609.30217, S-2026-11-18-018; trace tampering arXiv:2609.30266).

Contract:
  I1 an interpreter one-liner naming the store is DENIED (`python/node/perl/ruby`)
  I2 a heredoc body that names the store is DENIED
  I3 `cd <data home> && python3 -c "...events.db..."` is DENIED
  I4 a READ through an interpreter is denied too (the shell is not the read path)
  I5 an ordinary interpreter run is NOT denied
  I6 the ordinary shell store rules still behave (`ls` allowed)
  I7 the rule is shipped in `config/tools.yaml` (a hard deny survives mode=full)

Deterministic: pure `registry.classify`, no server, no model.
Run: python3 tests/acceptance/v1075_trace_store_interpreter_deny.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def decision(command):
    return registry.classify("shell.exec", {"command": command})


# ---- I1: one-liners naming the store ---------------------------------------
for cmd, label in (
        ("python3 -c \"open('data/events.db','w').write('{}')\"", "python write"),
        ("python3 -c \"import pathlib; pathlib.Path('data/runs/x.json').write_text('')\"",
         "pathlib write"),
        ("node -e \"require('fs').writeFileSync('data/sessions/x.json','')\"",
         "node write"),
        ("perl -e \"open(F,'>','data/threads/x.json')\"", "perl write")):
    _d, _why = decision(cmd)
    check("I1 denied: %s" % label, _d == "denied", (_d, _why))

# ---- I2: heredoc ------------------------------------------------------------
_d, _why = decision("python3 - <<'PY'\nopen('data/runs/x.json','w').write('{}')\nPY")
check("I2 denied: python heredoc naming the store", _d == "denied", (_d, _why))

# ---- I3: cwd into the data home, store named relatively --------------------
_d, _why = decision("cd ~/.longrun/data && python3 -c \"open('events.db','w').write('x')\"")
check("I3 denied: interpreter after cd into the data home", _d == "denied", (_d, _why))

# ---- I4: a read through the interpreter is not the read path ---------------
_d, _why = decision("python3 -c \"print(open('data/heldout/manifest.json').read())\"")
check("I4 denied: interpreter read of the held-out store", _d == "denied", (_d, _why))

# ---- I5/I6: ordinary commands stay allowed ---------------------------------
for cmd in ("python3 tests/acceptance/v1071_trace_store_shell_deny.py",
            "python3 -c \"print(2+2)\"",
            "python3 -m pytest tests/acceptance/v868_one_kind_per_gate.py -q",
            "bash tests/battery.sh",
            "ls -la data/runs"):
    _d, _why = decision(cmd)
    check("I5 not denied: %s" % cmd, _d != "denied", (_d, _why))

# ---- I7: the rule is in the shipped config (hard deny, not an approval) ----
_CFG = open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8").read()
check("I7 the interpreter rule is shipped in config/tools.yaml",
      "(?:python[0-9.]*|node|perl|ruby)" in _CFG
      and "data/(runs|sessions|threads|heldout|proposals|improvement)" in _CFG)

print("\n---\nv1075: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
