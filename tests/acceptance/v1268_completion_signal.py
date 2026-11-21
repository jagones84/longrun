#!/usr/bin/env python3
"""v1268 — stop exploring once a recorded check establishes the work (round 167).

Sources (2026-11-18/19, read in full from the archive):
  S-2026-11-22-012  Duéñez-Guzmán et al., *The Price of an Explanation*,
                    arXiv:2611.25896 — a checkable artifact lets a run stop early
                    (38% of the sampling budget and 49% of the search budget
                    declined), while demanding one costs 93 → 68 of 120 tasks.
  S-2026-11-22-013  Huang et al., *EverydayBench*, arXiv:2611.25146 — completion
                    is judged by fixed criteria against the submission, not by
                    the agent's claim; 32.30% of 1,771 runs pass.
  S-2026-11-22-014  Chen, *Beyond Weight Updates*, arXiv:2611.25380 — harness
                    edits specialize behaviour with the policy frozen.

What this pins:

  A  only a verification command that passed AND said so in its own output is a
     signal; a bare exit 0, a read, or a failure is not
  B  the replacement nudge names the command and never claims the task is done
  C  it fires once, and only with no open plan step
  D  the live seam runs before the hazard note
  E  the forge group runs headless

Deterministic: no model, no network, no server.
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from longrun.harness import completion_signal as cs  # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


def card(command, output, ok=True, exit_code=0):
    return {"tool": "shell.exec", "args": {"command": command}, "ok": ok,
            "output": output, "exit_code": exit_code}


# ── A · what counts as verified ─────────────────────────────────────────────
r = cs.detect([card("pytest -q tests", "12 passed in 1.2s")])
check("A1 a passing check is verified", r["verified"] and r["step"] == 1, r)
check("A2 a bare exit 0 with no pass marker is not",
      cs.detect([card("make", "Nothing to be done.")])["verified"] is False)
check("A3 a failure is not a pass",
      cs.detect([card("pytest", "1 failed, 11 passed", ok=False, exit_code=1)])["verified"] is False)
check("A4 a mixed log is not a pass",
      cs.detect([card("pytest", "1 passed, 1 failed")])["verified"] is False)
check("A5 a read is not a check",
      cs.detect([{"tool": "fs.read", "args": {"path": "README.md"}, "ok": True,
                  "output": "ok"}])["verified"] is False)
r = cs.detect([card("pytest", "3 passed"), card("npm test", "All tests pass")])
check("A6 the LAST passing check wins", r["verified"] and r["step"] == 2, r["command"])

# ── B · the nudge ───────────────────────────────────────────────────────────
line = cs.text(r)
check("B1 the nudge names the recorded command",
      "npm test" in line and "answer now" in line, line[:140])
check("B2 it never claims the task is done",
      "done" not in line.lower() or "not " in line.lower(), line[:140])
check("B3 an unverified record has no nudge", cs.text({"verified": False}) == "")

# ── C · when it fires ───────────────────────────────────────────────────────
check("C1 it fires with no open step", cs.should(r, 0, False))
check("C2 an open step suppresses it", cs.should(r, 2, False) is False)
check("C3 it fires once", cs.should(r, 0, True) is False)
check("C4 no verification, no signal", cs.should({"verified": False}, 0, False) is False)
s = cs.summary([{"verified": True, "stopped_after": True},
                {"verified": True, "stopped_after": False},
                {"verified": False}])
check("C5 the summary reports the stop rate",
      s["verified"] == 2 and s["stopped_after"] == 1 and s["stop_rate"] == 0.5, s)
check("C6 an empty sample reports no-rows", cs.summary([])["verdict"] == "no-rows")

# ── D · the live seam ───────────────────────────────────────────────────────
source = open(os.path.join(SRC, "longrun", "agent", "agent.py"), encoding="utf-8").read()
hazard = source.find("Round 163 (arXiv:2611.26553")
check("D1 the signal is computed before the hazard note",
      "completion_signal as _cs" in source[:hazard][-2500:])
check("D2 it replaces the nudge once per turn",
      "_completion_signalled = True" in source and 'publish("completion.verified"' in source)
check("D3 the signal never ends the turn", "break" not in source[
    source.find("completion_signal as _cs"):source.find("completion_signal as _cs") + 1200])

# ── E · the forge group ────────────────────────────────────────────────────
doc = os.path.join(tempfile.mkdtemp(prefix="sf-v1268-"), "verified.json")
with open(doc, "w", encoding="utf-8") as fh:
    json.dump({"cards": [card("pytest -q", "12 passed")]}, fh)
env = dict(os.environ, PYTHONPATH=SRC)
out = subprocess.run([sys.executable, os.path.join(SRC, "longrun", "core", "forge.py"),
                      "verified", "detect", doc], capture_output=True, text=True,
                     env=env, timeout=60)
check("E1 verified detect runs headless",
      out.returncode == 0 and '"verified": true' in out.stdout, out.stdout[:160])

print("\n%d/%d checks passed" % (len(CHECKS) - len(FAILED), len(CHECKS)))
if FAILED:
    print("FAILED: " + ", ".join(FAILED))
    sys.exit(1)
