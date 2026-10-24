#!/usr/bin/env python3
"""Deterministic acceptance predicates, evaluated in code (M8b1).

DeerFlow does not trust free text: `tests_passed:<cmd>` holds only when a
recorded execution of that command exited 0 (`task_tool.py:1210-1221`). This
module is Longrun's narrow slice: a pure predicate evaluator over a run's
trace (tool/args + `tool_result{exit_code, ok}`, see `api_v02.tool_action`)
plus absolute-path filesystem checks. No LLM, no network, no run needed.

Predicates (strings, callers cap count/length):
  file_exists:<abs path>    — the absolute path exists.
  file_nonempty:<abs path>   — exists and size > 0.
  file_written:<path>        — the trace holds an ok fs.write/fs.edit on it
                               (basename match when the predicate is relative).
  tests_passed:<cmd>         — the trace holds an ok shell-class call with
                               exit_code 0 whose command contains <cmd>.

Unknown predicate kinds and relative paths for the fs predicates are
VIOLATED (fail-closed, never silent). A run never fails for acceptance:
callers attach the verdict the way M1 attaches `schema_valid`.
"""

import os

MAX_PREDICATES = 20
MAX_PREDICATE_LEN = 200

_WRITE_TOOLS = frozenset({"fs.write", "fs.edit"})


def normalize(criteria):
    """Cap + truncate a raw criteria list into clean predicate strings."""
    out = []
    for c in (criteria or [])[:MAX_PREDICATES]:
        c = str(c or "").strip()
        if c:
            out.append(c[:MAX_PREDICATE_LEN])
    return out


def _shell_calls(trace):
    """(command, ok, exit_code) for every command-carrying call in the trace.

    Any tool whose args carry `command` counts (shell today, others tomorrow).
    Batch entries pair their input `calls` with the matching `results` so a
    batched shell run anchors exactly like a single one. A claim is anchored
    to a RECORDED run, never to prose — DeerFlow's `tests_passed` rule.
    """
    pairs = []
    for e in (trace or []):
        if not isinstance(e, dict):
            continue
        args = e.get("args") or {}
        if isinstance(args, dict) and args.get("command") is not None:
            res = e.get("tool_result") or {}
            pairs.append((args, res.get("ok", e.get("ok")), res.get("exit_code")))
        calls = e.get("calls") or []
        results = e.get("results") or []
        for i, c in enumerate(calls):
            if not isinstance(c, dict):
                continue
            cargs = c.get("args") or {}
            if not isinstance(cargs, dict) or cargs.get("command") is None:
                continue
            r = results[i] if i < len(results) and isinstance(results[i], dict) else {}
            pairs.append((cargs, r.get("ok"), r.get("exit_code")))
    out = []
    for args, ok, code in pairs:
        out.append({"command": str(args.get("command")), "ok": ok, "exit_code": code})
    return out


def _write_calls(trace):
    """(path, ok) for every file-write call in the trace.

    Batch entries pair input `calls` with matching `results`, same as shell.
    """
    pairs = []
    for e in (trace or []):
        if not isinstance(e, dict):
            continue
        args = e.get("args") or {}
        if isinstance(args, dict) and e.get("tool") in _WRITE_TOOLS \
                and args.get("path") is not None:
            res = e.get("tool_result") or {}
            pairs.append((str(args["path"]), res.get("ok", e.get("ok")),
                          res.get("exit_code")))
        calls = e.get("calls") or []
        results = e.get("results") or []
        for i, c in enumerate(calls):
            if not isinstance(c, dict) or c.get("tool") not in _WRITE_TOOLS:
                continue
            cargs = c.get("args") or {}
            if not isinstance(cargs, dict) or cargs.get("path") is None:
                continue
            r = results[i] if i < len(results) and isinstance(results[i], dict) else {}
            pairs.append((str(cargs["path"]), r.get("ok"),
                          r.get("exit_code")))
    return [{"path": p, "ok": ok, "exit_code": code} for p, ok, code in pairs]


def check_predicates(predicates, trace):
    """Evaluate predicates -> {predicate: {"holds": bool, "evidence": str}}."""
    out = {}
    for pred in normalize(predicates):
        if ":" not in pred:
            out[pred] = {"holds": False,
                         "evidence": "malformed predicate (need kind:value)"}
            continue
        kind, value = pred.split(":", 1)
        kind, value = kind.strip(), value.strip()
        if kind == "file_exists":
            if not os.path.isabs(value):
                out[pred] = {"holds": False,
                             "evidence": "relative path — pass an absolute path"}
            elif os.path.exists(value):
                out[pred] = {"holds": True, "evidence": "exists: " + value}
            else:
                out[pred] = {"holds": False, "evidence": "missing: " + value}
        elif kind == "file_nonempty":
            if not os.path.isabs(value):
                out[pred] = {"holds": False,
                             "evidence": "relative path — pass an absolute path"}
            elif os.path.isfile(value) and os.path.getsize(value) > 0:
                out[pred] = {"holds": True,
                             "evidence": "non-empty (%d bytes): %s"
                             % (os.path.getsize(value), value)}
            else:
                out[pred] = {"holds": False,
                             "evidence": "missing or empty: " + value}
        elif kind == "file_written":
            hit = None
            for w in _write_calls(trace):
                if not w.get("ok"):
                    continue
                if w["path"] == value or os.path.basename(w["path"]) == os.path.basename(value):
                    hit = w["path"]
                    break
            if hit:
                out[pred] = {"holds": True,
                             "evidence": "recorded ok write: " + hit}
            else:
                out[pred] = {"holds": False,
                             "evidence": "no recorded ok write of " + value}
        elif kind == "tests_passed":
            hit = None
            for s in _shell_calls(trace):
                if s.get("ok") and s.get("exit_code") == 0 \
                        and value and value in (s.get("command") or ""):
                    hit = s["command"]
                    break
            if hit:
                out[pred] = {"holds": True,
                             "evidence": "recorded exit-0 run: " + hit[:200]}
            else:
                out[pred] = {"holds": False,
                             "evidence": "no recorded exit-0 run of " + value}
        else:
            out[pred] = {"holds": False,
                         "evidence": "unknown predicate kind %r" % kind}
    return out


def all_hold(verdict):
    """True when every evaluated predicate holds (vacuously True when empty)."""
    return all(v.get("holds") for v in (verdict or {}).values())
