#!/usr/bin/env python3
"""v1071 — the trace-store deny covers the SHELL spelling too.

v1070 denied the run/transcript/event/held-out store through the `fs.*` verbs; a
shell-capable agent could still reach it with `rm`, a redirect, `tee` or a reader —
and "agents decompose operations across tool calls" to evade a monitor
(arXiv:2609.30217, stored S-2026-11-18-018), so the store must be denied in the
shell spelling as well (arXiv:2609.30266, S-2026-11-18-015). Hard deny:
`approvals.mode=full` never lifts it.

Contract:
  S1 `rm`/`mv`/`shred` of the store is DENIED
  S2 a redirect INTO the event log is DENIED
  S3 `tee` into the run store is DENIED
  S4 a reader of the sealed heldout store is DENIED
  S5 an ordinary command is NOT denied (including a harmless `ls` of the store)

Deterministic: pure `registry.classify`, no server, no model.
Run: python3 tests/acceptance/v1071_trace_store_shell_deny.py
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
    d, why = registry.classify("shell.exec", {"command": command})
    return d, why


for cmd in ("rm -rf data/runs/r1.json",
            "rm data/sessions/s.json",
            "mv data/events.db /tmp/x",
            "shred -u data/runs/r1.json"):
    _d, _why = decision(cmd)
    check("S1 denied: %s" % cmd, _d == "denied", (_d, _why))

_d, _why = decision("echo '{}' > data/events.db")
check("S2 denied: redirect into the event log", _d == "denied", (_d, _why))

_d, _why = decision("echo hi | tee data/runs/r1.json")
check("S3 denied: tee into the run store", _d == "denied", (_d, _why))

_d, _why = decision("cat data/heldout/manifest.json")
check("S4 denied: reader of the sealed heldout store", _d == "denied", (_d, _why))

for cmd in ("ls -la data/runs", "echo hi > /tmp/ok.txt", "python3 tests/x.py"):
    _d, _why = decision(cmd)
    check("S5 not denied: %s" % cmd, _d != "denied", (_d, _why))

print("\n---\nv1071: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
