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
import collections
import json
import os
import time

DEFAULTS = {
    "enabled": False,
    # "auto" = resolve the project's own test command from its markers (see
    # `resolve_command`). Any other non-empty string is used verbatim.
    "command": "",
    "timeout_secs": 120,
    "paths": [],
    # F1: verify ONCE at closeout (not per edit) when the step changed the
    # environment. THREE states (v861):
    #   false  — off.
    #   true   — STRICT: on with no resolvable command REFUSES the close.
    #   "auto" — DEFAULT: run it when a command resolves; when none does, the step
    #            closes UNVERIFIED and the plan says so. Closing is never blocked
    #            by a workspace that ships no test runner (that made `true` the
    #            default a trap: every step in a bare directory was unclosable).
    "closeout": "auto",
    # Resolve the project's OWN test command from its markers (pytest/npm/make)
    # only when `command: "auto"` asks for it: auto-detection on an empty command
    # would run a full suite once per closed step on every repository that has a
    # `tests/` directory.
    "closeout_autodetect": False,
}

TARGET_TOOLS = ("fs.write", "fs.edit")

# Markers, in precedence order. The FIRST hit decides, so a repo that has both
# pytest and npm is verified by pytest (the harness itself is Python-first).
PYTEST_MARKERS = ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", "tests")
PYTEST_COMMAND = "python3 -m pytest -q"

# Bounded closeout memo: per (workspace, node) we remember the last verdict and
# the mutation stamp it was taken on. A second `done` with NO new mutation must
# not re-run an expensive suite — the model is re-claiming, not repairing.
_CLOSEOUT_MEMO = collections.OrderedDict()
_CLOSEOUT_MEMO_MAX = 512


def reset_closeout_memo():
    """Drop the bounded closeout memory (tests, and a workspace reset)."""
    _CLOSEOUT_MEMO.clear()


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


SYNTAX_GATE_SUFFIXES = (".py",)


def syntax_gate(tool, path, snap, res):
    """Zero-config post-edit syntax gate (Aider post-edit-loop direction).

    Unlike `verify()` above — which needs an operator-configured command —
    this ALWAYS runs for `.py` targets of fs.write/fs.edit: the new content
    is `compile()`d, and on SyntaxError/ValueError the result becomes a
    failure carrying the error, so the model can fix it next turn
    (fix-and-retry, not silent acceptance). An EXISTING file is rolled back
    to the pre-image; a NEW file is KEPT — `restore()` would DELETE it, so
    one bad line used to destroy a whole freshly-written script. Anything
    else (green, out of scope, unreadable file) passes `res` through
    untouched. Never raises.
    """
    try:
        if tool not in TARGET_TOOLS:
            return res, {"ran": False}
        if not str(path or "").endswith(SYNTAX_GATE_SUFFIXES):
            return res, {"ran": False}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            return res, {"ran": False}
        try:
            compile(content, str(path), "exec")
        except (SyntaxError, ValueError) as e:
            # A NEW FILE IS NOT ROLLED BACK. `restore()` deletes a file that did not
            # exist before, so the gate used to answer a 240-line script with one
            # bad line by deleting the whole script — the model then had to write it
            # again from scratch (measured 2026-10-31, JobBench bookkeeping: two
            # attempts, `output/` empty, 0/88). There is nothing to protect on a
            # file that did not exist: the error keeps the file and names the line.
            new_file = not (isinstance(snap, dict) and snap.get("exists"))
            rolled = False if new_file else restore(path, snap)
            failed = dict(res)
            failed["ok"] = False
            failed["exit_code"] = 1
            failed["syntax_failed"] = True
            try:
                detail = "line %s: %s" % (e.lineno, e.msg)
            except AttributeError:
                detail = str(e)
            if new_file:
                advice = ("the file is KEPT — fix that line with fs.edit (path=%s) "
                          "instead of writing the whole file again." % path)
            else:
                advice = ("the change has been rolled back%s — fix the syntax and "
                          "retry." % ("" if rolled else " (ROLLBACK FAILED)"))
            failed["error"] = "syntax gate: %s does not parse (%s); %s" % (
                path, detail, advice)
            return failed, {"ran": True, "green": False, "new_file": new_file,
                            "rolled_back": rolled, "error": detail}
        return res, {"ran": True, "green": True}
    except Exception:  # noqa: BLE001 — the gate must never break a write
        return res, {"ran": False}


def resolve_command(workspace=None, c=None, auto_when_empty=False):
    """The verification command for THIS workspace, or "" when none applies.

    A literal `verifier.command` always wins. The value `"auto"` asks the
    project itself, first hit wins: pytest markers -> a `package.json` `test`
    script -> a Makefile `test:` target. Stat-only, per call, so a new marker is
    picked up without a restart and no resolved command is cached into a config
    file (one truth: the project tree).

    `auto_when_empty` is the CLOSEOUT path: an operator who enabled closeout
    without naming a command still gets the project's own suite, once per step.
    Per-edit verification never auto-resolves — running a full suite after every
    write is the expensive behaviour this harness must not inflict by surprise.
    """
    c = c or cfg()
    cmd = str(c.get("command") or "").strip()
    if cmd and cmd != "auto":
        return cmd
    if not cmd and not auto_when_empty:
        return ""
    if not workspace:
        return ""
    ws = str(workspace)
    for marker in PYTEST_MARKERS:
        if os.path.exists(os.path.join(ws, marker)):
            return PYTEST_COMMAND
    pkg = os.path.join(ws, "package.json")
    if os.path.isfile(pkg):
        try:
            with open(pkg, encoding="utf-8") as f:
                scripts = (json.load(f) or {}).get("scripts") or {}
        except (OSError, ValueError):
            scripts = {}
        if str(scripts.get("test") or "").strip():
            return "npm test"
    makefile = os.path.join(ws, "Makefile")
    if os.path.isfile(makefile):
        try:
            with open(makefile, encoding="utf-8", errors="replace") as f:
                if any(line.startswith("test:") for line in f):
                    return "make test"
        except OSError:
            pass
    return ""


def run_check(workspace=None, c=None, run_id=None):
    """Runs the verification command in the sandbox. Returns (green, output).

    An UNRESOLVABLE command is a skip, not a failure: `apply-only-if-green` must
    never roll an edit back because the project ships no test suite.
    """
    c = c or cfg()
    cmd = resolve_command(workspace, c)
    if not cmd:
        raw = str(c.get("command") or "").strip()
        return True, ("skipped: no test command detected for %s" % workspace) if raw else ""
    try:
        from longrun.tools import sandbox
        res = sandbox.run(cmd, run_id=run_id, timeout=c.get("timeout_secs"),
                          workspace=workspace)
    except Exception as e:  # noqa: BLE001
        return False, "verifier error: %s" % e
    green = res.get("exit_code") == 0
    out = (res.get("stdout") or "") + (res.get("stderr") or "")
    return green, out


#: Files that ARE the test setup. A step that touched one of these cannot be
#: verified by that same suite: a green run the agent could have written is not
#: independent evidence (SpecBench: agents saturate the VISIBLE suite while the
#: held-out gap grows with the size of the change).
_TEST_SETUP_NAMES = {"pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini",
                     "conftest.py", "Makefile", "package.json"}
_TEST_DIRS = ("/tests/", "/test/", "/spec/", "/__tests__/")


def touches_tests(node):
    """Paths this step changed that belong to the TEST setup ([] when none)."""
    out = []
    for p in (node or {}).get("paths") or []:
        s = str(p or "").replace("\\", "/")
        if not s:
            continue
        base = s.rsplit("/", 1)[-1]
        if (base in _TEST_SETUP_NAMES
                or base.startswith("test_") or base.endswith("_test.py")
                or base.endswith(".test.js") or base.endswith(".spec.ts")
                or any(d in ("/" + s) for d in _TEST_DIRS)):
            out.append(s)
    return out[:8]


def closeout_gate(node, workspace=None, run_id=None, c=None, check=None):
    """F1: verify a step ONCE, when it is closed, if it changed the environment.

    A node may be closed on a text claim only when it performed no mutating
    action (`taskgraph.note_mutation` marks it). When it did and closeout is on,
    the configured command runs here: green adds an OBSERVED evidence entry, red
    keeps the step open. Returns `(ok, report, observed)`.

    Three states of `verifier.closeout` (v861):
      * `false` — off, today's behaviour.
      * `true`  — STRICT, fail-closed: on with no `command` REFUSES the close
                  instead of pretending it observed anything.
      * `"auto"` (default) — run the check when a command resolves; when none
                  does, the step closes with `unavailable` in the report and the
                  caller records that it closed UNVERIFIED. Making `true` the
                  default would leave every workspace without a test runner
                  unable to close a single step.

    A step that edited the TEST SETUP itself is `tainted`: its own suite cannot
    prove it, so it closes unverified (like `unavailable`) and never green.
    """
    c = c or cfg()
    node = node or {}
    mode = c.get("closeout")
    observed_already = bool([e for e in (node.get("evidence") or [])
                             if e.get("observed")])
    if not mode or not node.get("mutated") or observed_already:
        return True, {"ran": False}, False
    auto = str(mode).strip().lower() == "auto"
    cmd = resolve_command(
        workspace, c,
        auto_when_empty=bool(c.get("closeout_autodetect"))
        or (auto and str(c.get("command") or "").strip().lower() == "auto"))
    if not cmd:
        if auto:
            return True, {"ran": False, "unavailable": True,
                          "error": "closeout: no test command could be resolved for "
                                   "this workspace, so the step closes UNVERIFIED "
                                   "(set verifier.command to change that)"}, False
        return False, {"ran": False, "green": False,
                       "error": "closeout verification is on but no test command "
                                "could be resolved (verifier.command=%r)"
                                % (c.get("command") or "")}, False
    tainted = touches_tests(node)
    if tainted:
        return True, {"ran": False, "tainted": True, "paths": tainted,
                      "error": "closeout: this step changed the TEST setup (%s), so a "
                               "green run would not be independent evidence — the step "
                               "closes UNVERIFIED" % ", ".join(tainted[:4])}, False
    if auto:
        # THE MODEL ACTS, THE HARNESS SUGGESTS (operator rule, 2026-11-07: "solo il
        # modello può eseguire azioni, l'harness può dare suggerimenti"). `auto`
        # therefore NEVER runs the suite by itself: it hands the model the exact
        # command and records the step as UNVERIFIED until the model runs it and
        # reports the output. Only the opt-in `closeout: true` executes.
        return True, {"ran": False, "unavailable": True, "suggest": cmd,
                      "error": "closeout: nothing was verified — run `%s` and report "
                               "the result; the step is closed UNVERIFIED until you "
                               "do" % cmd}, False
    # BOUNDED REPAIR: one external pass/fail plus ONE repair round. The first
    # red is handed to the model with the output; a second `done` that changed
    # nothing since that failure is a re-claim, not a repair — refuse it WITHOUT
    # paying for the suite again.
    memo_key = (str(workspace or ""), str(node.get("id") or ""))
    prev = _CLOSEOUT_MEMO.get(memo_key) or {}
    stamp = node.get("mutated")
    if prev.get("green") is False and prev.get("mutated") == stamp:
        return False, {"ran": False, "green": False, "command": cmd,
                       "skipped": "unchanged_since_failure",
                       "attempts": prev.get("attempts", 1),
                       "error": "no change since the last failed check — fix "
                                "something before claiming the step is done"}, False
    t0 = time.time()
    # Hand the RESOLVED command down: closeout may auto-detect it, while
    # `run_check` itself never auto-resolves (per-edit stays opt-in).
    c2 = dict(c)
    c2["command"] = cmd
    green, out = (check or run_check)(workspace=workspace, c=c2, run_id=run_id)
    report = {"ran": True, "green": bool(green), "command": cmd,
              "attempts": int(prev.get("attempts", 0)) + 1,
              "duration_ms": int((time.time() - t0) * 1000),
              "output": str(out or "")[-1200:]}
    if not green and auto:
        # A suite that hits its own budget proves nothing: in `auto` that is
        # "unavailable", never a red that keeps a step open forever. Strict mode
        # (`true`) keeps the red, because there the operator asked for a verdict.
        try:
            budget = int(float(c.get("timeout_secs") or 120) * 1000 * 0.95)
        except (TypeError, ValueError):
            budget = 114000
        if report["duration_ms"] >= budget:
            report["unavailable"] = True
            report["error"] = ("closeout: the check used its whole %ss budget without "
                               "a verdict — the step closes UNVERIFIED"
                               % c.get("timeout_secs"))
            return True, report, False
    _CLOSEOUT_MEMO[memo_key] = {"green": bool(green), "mutated": stamp,
                                "attempts": report["attempts"],
                                "ts": round(time.time(), 3)}
    while len(_CLOSEOUT_MEMO) > _CLOSEOUT_MEMO_MAX:
        _CLOSEOUT_MEMO.popitem(last=False)
    return bool(green), report, bool(green)


def verify(tool, path, snap, res, workspace=None, run_id=None, c=None):
    """Applies "apply-only-if-green" to a write result.

    Returns (res, report): if the check is green `res` is unchanged; if red the
    change is reverted and `res` becomes a failure with the check error.
    """
    c = c or cfg()
    if not should_verify(tool, path, c):
        return res, {"ran": False}
    cmd = resolve_command(workspace, c)
    if not cmd:
        return res, {"ran": False, "skipped": "no-command"}
    t0 = time.time()
    green, out = run_check(workspace=workspace, c=c, run_id=run_id)
    report = {"ran": True, "green": bool(green), "command": cmd,
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

