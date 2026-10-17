#!/usr/bin/env python3
"""Verifier "apply-only-if-green" (JAG-131).

After every file write/edit (fs.write / fs.edit), when the verifier is
active, the harness runs a verification command (e.g. the project tests) in the
sandbox: if the command does NOT pass, the change is REVERTED (rollback to the
pre-image) and the model receives the error as an observation.

It is the "edit -> test -> rollback" pattern: correctness is demonstrated
on the environment before accepting the action, regardless of the model
(verifier / test-time verification). PURE module, disabled by default: it is
switched on from `config/tools.yaml`:

    verifier:
      enabled: true
      command: "python3 -m pytest -q"
      timeout_secs: 120
      paths: ["longrun/src"]      # optional: only paths containing these
"""
import os
import time

DEFAULTS = {
    "enabled": False,
    "command": "",
    "timeout_secs": 120,
    "paths": [],
}

TARGET_TOOLS = ("fs.write", "fs.edit")


def cfg(override=None):
    """Effective config: DEFAULTS <- config/tools.yaml (verifier) -> override."""
    from longrun.tools.registry import section_config
    return section_config("verifier", DEFAULTS, override)


def is_active(c=None):
    """True only if enabled AND with a configured command."""
    c = c or cfg()
    return bool(c.get("enabled")) and bool(str(c.get("command") or "").strip())


def in_scope(path, c=None):
    """True if the path is within scope (empty paths = everything)."""
    c = c or cfg()
    pats = [p for p in (c.get("paths") or []) if p]
    if not pats:
        return True
    p = str(path or "")
    return any(str(x) in p for x in pats)


def should_verify(tool, path, c=None):
    """True if this (tool, path) must be verified."""
    c = c or cfg()
    return tool in TARGET_TOOLS and is_active(c) and in_scope(path, c)


def restore(path, snap):
    """Restores the pre-image (or deletes the file if it did not exist before)."""
    if not snap:
        return False
    try:
        if snap.get("exists"):
            with open(path, "w", encoding="utf-8") as f:
                f.write(snap.get("content") or "")
        elif os.path.exists(path):
            os.remove(path)
        return True
    except OSError:
        return False


def run_check(workspace=None, c=None, run_id=None):
    """Runs the verification command in the sandbox. Returns (green, output)."""
    c = c or cfg()
    cmd = str(c.get("command") or "").strip()
    if not cmd:
        return True, ""
    try:
        from longrun.tools import sandbox
        res = sandbox.run(cmd, run_id=run_id, timeout=c.get("timeout_secs"),
                          workspace=workspace)
    except Exception as e:  # noqa: BLE001
        return False, "verifier error: %s" % e
    green = res.get("exit_code") == 0
    out = (res.get("stdout") or "") + (res.get("stderr") or "")
    return green, out


def verify(tool, path, snap, res, workspace=None, run_id=None, c=None):
    """Applies "apply-only-if-green" to a write result.

    Returns (res, report): if the check is green `res` is unchanged; if red the
    change is reverted and `res` becomes a failure with the check error.
    """
    c = c or cfg()
    if not should_verify(tool, path, c):
        return res, {"ran": False}
    t0 = time.time()
    green, out = run_check(workspace=workspace, c=c, run_id=run_id)
    report = {"ran": True, "green": bool(green), "command": c.get("command"),
              "duration_ms": int((time.time() - t0) * 1000)}
    if green:
        return res, report
    rolled = restore(path, snap)
    report["rolled_back"] = rolled
    failed = dict(res)
    failed["ok"] = False
    failed["exit_code"] = 1
    failed["verifier_failed"] = True
    failed["error"] = ("verifier: the verification command does NOT pass; the change to %s "
                       "has been rolled back%s.\n%s"
                       % (path, "" if rolled else " (ROLLBACK FAILED)",
                          str(out)[-1200:]))
    report["output"] = str(out)[-1200:]
    return failed, report

