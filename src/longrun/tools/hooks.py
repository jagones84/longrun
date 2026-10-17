#!/usr/bin/env python3
"""Longrun hooks — deterministic lifecycle scripts (JAG-69).

Frontier harnesses (Claude Code, Codex CLI) wrap the agent loop with
*deterministic* shell hooks: the model is not consulted, the exit code decides.
This is the "contorno" that makes a harness reliable — formatting, logging,
linting, enforcement — instead of trusting the model to do it.

Events (config/hooks.yaml, one entry per hook):
  PreToolUse   before a tool executes. Exit 2 BLOCKS the call (reason = stdout,
               Claude Code contract). Other non-zero exits are advisory unless
               `block_on_fail: true`.
  PostToolUse  after a tool executes; the observation is in
               $LONGRUN_OBSERVATION.
  Stop         when a chat turn / agent run ends.

Each hook gets LONGRUN_HOOK_EVENT / _TOOL / _RUN / _ARGS / _OBSERVATION in its
environment and runs from the repo root with a hard timeout.
"""

import json
import os
import re
import subprocess
import time

from longrun.util import osutil

from longrun.util.paths import REPO_ROOT as REPO, DATA_DIR
CONFIG = os.environ.get("LONGRUN_HOOKS") or os.path.join(REPO, "config", "hooks.yaml")
# JAG-491: the WebUI hook table writes a gitignored overlay so the shipped file
# (with its documented examples) is never rewritten. Present = REPLACES the list.
# An explicit LONGRUN_HOOKS (tests) disables the overlay unless it is named too,
# so a test never picks up the live user overlay.
OVERLAY = os.environ.get("LONGRUN_HOOKS_OVERLAY") or (
    "" if os.environ.get("LONGRUN_HOOKS") else os.path.join(DATA_DIR, "hooks.overlay.yaml"))
DEFAULT_TIMEOUT = 60
EVENTS = ("PreToolUse", "PostToolUse", "Stop")

_cache = {"ts": None, "hooks": []}


def _read_hooks(path):
    """The normalised hook list stored in one file ([] when absent/broken)."""
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        out = []
        for h in (data.get("hooks") or []):
            if not isinstance(h, dict) or h.get("event") not in EVENTS or not h.get("command"):
                continue
            out.append({
                "event": str(h["event"]),
                "matcher": str(h.get("matcher") or ""),
                "command": str(h["command"]),
                "timeout_secs": int(h.get("timeout_secs") or DEFAULT_TIMEOUT),
                "block_on_fail": bool(h.get("block_on_fail", False)),
            })
        return out
    except Exception:  # noqa: BLE001 — hooks must never break a run
        return []


def load(reload=False):
    """Cached hook list: config/hooks.yaml, REPLACED by the WebUI overlay."""
    stamps = []
    for path in (CONFIG, OVERLAY):
        try:
            stamps.append(os.stat(path).st_mtime if path else None)
        except OSError:
            stamps.append(None)
    key = tuple(stamps)
    if not reload and _cache["ts"] == key:
        return _cache["hooks"]
    hooks = _read_hooks(OVERLAY) if OVERLAY and os.path.isfile(OVERLAY) else _read_hooks(CONFIG)
    _cache.update(ts=key, hooks=hooks)
    return hooks


def _fire(kind, **d):
    try:
        from longrun.core import server
        server.publish(kind, **d)
    except Exception:  # noqa: BLE001
        pass


def _match(hook, tool):
    m = hook.get("matcher") or ""
    if not m:
        return True
    try:
        return re.search(m, tool or "") is not None
    except re.error:
        return False


def run(event, tool=None, args=None, observation=None, run_id=None):
    """Run every matching hook for `event`.

    Returns {"blocked": bool, "reason": str, "results": [entry, ...]}. A
    PreToolUse hook exiting 2 blocks the tool; a non-zero exit is advisory
    unless the hook sets `block_on_fail: true`.
    """
    results, blocked, reason = [], False, ""
    for hook in load():
        if hook["event"] != event or not _match(hook, tool):
            continue
        env = dict(os.environ)
        env.update({
            "LONGRUN_HOOK_EVENT": event,
            "LONGRUN_TOOL": tool or "",
            "LONGRUN_RUN": run_id or "",
            "LONGRUN_ARGS": json.dumps(args or {}, ensure_ascii=False, default=str)[:4000],
            "LONGRUN_OBSERVATION": str(observation or "")[:4000],
        })
        t0 = time.time()
        try:
            p = subprocess.run(osutil.shell_argv(hook["command"]), capture_output=True,
                               text=True, timeout=hook["timeout_secs"], env=env, cwd=REPO)
            code, out, err = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            code, out, err = 124, "", "hook timeout after %ss" % hook["timeout_secs"]
        except Exception as e:  # noqa: BLE001
            code, out, err = 125, "", str(e)
        entry = {"event": event, "tool": tool, "command": hook["command"],
                 "exit_code": code, "stdout": (out or "")[:2000],
                 "stderr": (err or "")[:1000],
                 "duration_ms": int((time.time() - t0) * 1000)}
        results.append(entry)
        _fire("hook.run", run=run_id, **entry)
        if event == "PreToolUse":
            if code == 2:
                blocked = True
                reason = (out or err or "blocked by hook").strip()[:400]
            elif code not in (0,) and hook["block_on_fail"]:
                blocked = True
                reason = (err or out or "hook failed").strip()[:400]
    return {"blocked": blocked, "reason": reason, "results": results}

