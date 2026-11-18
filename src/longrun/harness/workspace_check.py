#!/usr/bin/env python3
"""The workspace's own check, executed for the read-back (R-1 / AdaPRA, round 84).

Why this module exists
----------------------
The read-back (agent._deliverable_review_text → plan.artifacts.review) describes the
files a turn wrote; it never RUNS anything. AdaPRA (arXiv 2610.33245, archive report
2026-11-07_next-five-compaction-stopping-reward-memory) audits a trajectory "by
executing checks", and the local gap was recorded as R-1: the closing gate could see
a file and not whether it works.

What it is
----------
Narrow on purpose: a workspace `check.py`, or a `tests/` directory holding at least
one `test_*.py`. That command goes through the SAME policy gate as any agent call
(`registry.classify`); it runs only when the decision is `auto`, so the read-back can
never bypass an approval, a hard deny or a disabled tool lane. If the policy asks for
a human, the check is SKIPPED and the text says so — the gate never blocks a turn.

Design rules
------------
* One command per workspace, bounded (`CHECK_TIMEOUT`), output clipped.
* Never raises: the read-back may be slower, never broken.
* Facts only — exit status and the tail of the output; no verdict about the code.
"""
import os
import time

CHECK_TIMEOUT = 60          # seconds; a check that hangs is killed by shell.exec
MAX_TAIL = 6                # non-empty lines kept from the end
MAX_LINE = 240
MAX_TEXT = 1600


def detect(workspace):
    """The workspace's own check command, or None. Narrow by design."""
    ws = str(workspace or "")
    if not ws or not os.path.isdir(ws):
        return None
    if os.path.isfile(os.path.join(ws, "check.py")):
        return "python3 check.py"
    tdir = os.path.join(ws, "tests")
    if os.path.isdir(tdir):
        try:
            names = sorted(os.listdir(tdir))
        except OSError:
            return None
        if any(n.startswith("test_") and n.endswith(".py") for n in names):
            return "python3 -m pytest -q tests"
    return None


def _tail(stdout, stderr):
    blob = "\n".join(x for x in (stdout or "", stderr or "") if x)
    lines = [ln.rstrip()[:MAX_LINE] for ln in blob.splitlines() if ln.strip()]
    return lines[-MAX_TAIL:]


def run(workspace, session=None, timeout=CHECK_TIMEOUT):
    """Run the workspace check under the tool gate. -> dict, or None (no check)."""
    cmd = detect(workspace)
    if not cmd:
        return None
    args = {"command": cmd, "cwd": str(workspace), "timeout_secs": int(timeout)}
    out = {"cmd": cmd, "decision": None, "ran": False, "ok": None,
           "exit_code": None, "tail": [], "duration_s": None, "why": ""}
    try:
        from longrun.tools import registry
        decision, why = registry.classify("shell.exec", args, session=session)
    except Exception as exc:  # noqa: BLE001 — no gate, no run
        out["decision"] = "unavailable"
        out["why"] = str(exc)[:200]
        return out
    out["decision"] = decision
    if decision != "auto":
        # A human gate is the operator's, and the read-back must never wait on one.
        out["why"] = str(why or "")[:200]
        return out
    try:
        from longrun.tools import tools
        t0 = time.time()
        res = tools.execute("shell.exec", args) or {}
        out["duration_s"] = round(time.time() - t0, 3)
        out["ran"] = True
        out["ok"] = bool(res.get("ok"))
        out["exit_code"] = res.get("exit_code")
        out["tail"] = _tail(res.get("stdout"), res.get("stderr") or res.get("error"))
    except Exception as exc:  # noqa: BLE001 — a broken runner is reported, not raised
        out["why"] = ("runner failed: " + str(exc))[:200]
    return out


def text(result):
    """The block injected into the read-back, or "" when there is nothing to say."""
    if not result:
        return ""
    cmd = result.get("cmd") or "check"
    if not result.get("ran"):
        dec = result.get("decision") or "not run"
        return ("WORKSPACE CHECK (`%s`): NOT RUN — policy answered %s%s. The check was "
                "not executed; do not claim it passed."
                % (cmd, dec, (": " + result["why"]) if result.get("why") else ""))
    ok = result.get("ok")
    code = result.get("exit_code")
    head = ("WORKSPACE CHECK (`%s`): exit %s — %s (%.1f s)"
            % (cmd, code, "passed" if ok else "FAILED", result.get("duration_s") or 0.0))
    lines = [head]
    if result.get("tail"):
        lines += ["  " + ln for ln in result["tail"]]
    if not ok:
        lines.append("  * the workspace's own check disagrees with the delivery: fix "
                     "the code/the artifact until this command exits 0, or state in "
                     "your answer exactly which check fails and why it is not yours.")
    return "\n".join(lines)[:MAX_TEXT]
