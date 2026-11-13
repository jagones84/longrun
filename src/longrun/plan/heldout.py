#!/usr/bin/env python3
"""Sealed held-out promotion gate (RDD point 2).

The self-improvement verifier must stay OUTSIDE the agent's workspace:
an external judge suite, anchored to a manifest of hashes, that `selfevolve.promote`
must pass (fail-closed) before archiving a proposal. This way the agent can
neither read nor tamper with the judge. Pure module (no dependency on the server).
"""
import hashlib
import json
import os
import shlex
import time

from longrun.util import paths
from longrun.model import context_limits as ctx_limits

# JAG-534: the sealed judge lives in the DATA HOME (outside any workspace and
# outside the checkout), so a home move carries it and nothing can resolve it
# from the agent's cwd.
DEFAULT_DIR = os.path.join(paths.DATA_DIR, "heldout")


def dir():
    """Directory of the held-out store (env LONGRUN_HELDOUT_DIR -> default)."""
    return os.path.abspath(os.path.expanduser(
        os.environ.get("LONGRUN_HELDOUT_DIR") or DEFAULT_DIR))


def require_enabled():
    """The gate is mandatory by default; `limits.require_heldout: false` turns it off."""
    return ctx_limits.limitb("require_heldout")


def manifest_path():
    return os.path.join(dir(), "manifest.json")


def load_manifest():
    """Reads the manifest or None if absent/unreadable/malformed."""
    try:
        with open(manifest_path(), "r", encoding="utf-8") as f:
            m = json.load(f)
        if not isinstance(m, dict) or not isinstance(m.get("files"), dict):
            return None
        return m
    except (OSError, ValueError):
        return None


def _sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def integrity(c=None):
    """Checks that every file in the manifest exists with the expected hash (fail-closed)."""
    m = load_manifest()
    if m is None:
        return {"ok": False, "reason": "no_manifest", "files": []}
    root = dir()
    files = []
    ok = True
    for rel, exp in sorted(m.get("files", {}).items()):
        actual = _sha256(os.path.join(root, rel))
        status = "ok" if (actual is not None and actual == exp) \
            else ("missing" if actual is None else "mismatch")
        if status != "ok":
            ok = False
        files.append({"path": rel, "expected": exp, "actual": actual, "status": status})
    return {"ok": ok, "reason": "ok" if ok else "integrity", "files": files}


def run(candidate=None, c=None, timeout=None, runner=None):
    """Runs the judge suite. Returns (green, output, duration_ms).

    `runner(suite_dir, command) -> (green, output)` is injectable in tests (pure);
    in production it runs in the sandbox. If the manifest command contains the
    placeholder `{candidate}`, it is replaced with the path of the proposal.
    """
    m = load_manifest()
    if m is None:
        return False, "no manifest", 0
    command = m.get("command") or "python3 check_all.py"
    if candidate and "{candidate}" in command:
        command = command.replace("{candidate}", shlex.quote(str(candidate)))
    suite = os.path.join(dir(), "suite")
    t0 = time.time()
    if runner is not None:
        try:
            green, out = runner(suite, command)
        except Exception as e:  # noqa: BLE001
            green, out = False, "runner error: %s" % e
    else:
        try:
            from longrun.tools import sandbox
            res = sandbox.run(command, timeout=int(timeout or 120), workspace=suite)
            out = (res.get("stdout") or "") + (res.get("stderr") or "")
            green = res.get("exit_code") == 0
        except Exception as e:  # noqa: BLE001
            green, out = False, "sandbox error: %s" % e
    return bool(green), str(out)[-1200:], int((time.time() - t0) * 1000)


def gate(candidate=None, c=None, runner=None):
    """Sealed verification: integrity AND run. Fail-closed on any doubt."""
    rep = integrity(c)
    if not rep.get("ok"):
        return {"green": False, "integrity": rep, "run": None,
                "reason": rep.get("reason", "integrity")}
    green, out, ms = run(candidate=candidate, c=c,
                         timeout=(c or {}).get("heldout_timeout"), runner=runner)
    return {"green": bool(green), "integrity": rep,
            "run": {"green": bool(green), "duration_ms": ms, "output": out},
            "reason": "ok" if green else "run_failed"}


def pin(paths=None, command=None):
    """Admin: (re)writes the manifest with the current hashes. It is NOT an agent action.

    `command` defaults to the EXISTING manifest's command, so a re-pin after a
    suite edit keeps the way the judge is invoked. It used to always write
    `python3 check_all.py`, which silently dropped the `{candidate}` placeholder
    an installed suite relies on: the judge then received no directory, answered
    `no candidate directory`, and every promotion was refused with `run_failed`
    for a reason that had nothing to do with the candidate (measured 2026-11-14
    by v975 H3 → J1).
    """
    root = dir()
    files = {}
    if paths:
        for rel in paths:
            files[rel] = _sha256(os.path.join(root, rel))
    else:
        suite = os.path.join(root, "suite")
        for base, _dirs, names in os.walk(suite):
            for n in names:
                p = os.path.join(base, n)
                files[os.path.relpath(p, root)] = _sha256(p)
    prev = load_manifest() or {}
    m = {"version": 1,
         "command": (command or prev.get("command") or "python3 check_all.py"),
         "files": files}
    os.makedirs(root, exist_ok=True)
    with open(manifest_path(), "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2, sort_keys=True)
    return m


# ---------------------------------------------------------------- install ---
#
# The gate above is only half a gate until a suite EXISTS: `integrity()` answers
# `no_manifest` and `promote()` refuses every candidate, so on an install that
# never had a suite the skill half of self-evolution can never close (measured
# 2026-11-14: 123 drafts, 0 promoted). `install()` is the missing admin step, and
# like `pin()` it is NOT an agent action: the agent must not write the judge that
# certifies it.
#
# The suite is DELIBERATELY small and independent: it reads the candidate and its
# own frozen allow-list, nothing else — no repo import, no network, no model. It
# can refuse, and that is the point: a judge that cannot red is not a judge.

SEALED_SUITE_SRC = '''#!/usr/bin/env python3
"""Sealed held-out judge for a self-evolution candidate (installed by heldout.install).

Usage: python3 check_all.py <candidate-dir>

Independent on purpose: reads ONLY the candidate and ./allowed_tools.json.
No repo import, no network, no model. Exit 0 = the candidate may be promoted.

  A  the candidate directory exists and the proposal parses
  B  skill.json is a recipe: a non-empty list of steps, each naming a tool
  C  every step tool is in the sealed allow-list (frozen at install time)
  D  at least two DISTINCT tools: a repeated single call is not a procedure
  E  SKILL.md exists, is non-empty and within the prompt-cost ceiling
  F  SKILL.md carries no approval-bypass instruction
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_SKILL_MD = 12000
BYPASS = ("skip the approval", "bypass the approval", "auto-approve",
          "autoapprove", "ignore the gate", "disable the gate",
          "without approval", "approve it automatically")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except (OSError, ValueError) as e:
        return None, str(e)


def main(argv):
    fails = []
    notes = []
    cand = (argv[1] if len(argv) > 1 else "").strip()
    if not cand or not os.path.isdir(cand):
        print("A0 no candidate directory: %r" % cand)
        return 2
    prop, err = _read_json(os.path.join(cand, "proposal.json"))
    if err:
        fails.append("A1 proposal.json unreadable: %s" % err)
    elif not isinstance(prop, dict):
        fails.append("A1 proposal.json is not an object")
    else:
        notes.append("A ok (%s)" % (prop.get("name") or os.path.basename(cand)))
    recipe, err = _read_json(os.path.join(cand, "skill.json"))
    steps = (recipe or {}).get("steps") if isinstance(recipe, dict) else None
    if err or not isinstance(steps, list) or not steps:
        fails.append("B1 skill.json has no steps (%s)" % (err or "empty"))
        steps = []
    bad = [i for i, s in enumerate(steps)
           if not isinstance(s, dict) or not str(s.get("tool") or "").strip()]
    if bad:
        fails.append("B2 step(s) with no tool: %s" % bad)
    allowed, aerr = _read_json(os.path.join(HERE, "allowed_tools.json"))
    if aerr or not isinstance(allowed, list):
        fails.append("C0 sealed allow-list unreadable: %s" % aerr)
        allowed = []
    unknown = sorted({str(s.get("tool")) for s in steps
                      if isinstance(s, dict)} - set(allowed))
    if unknown:
        fails.append("C1 tool(s) the harness cannot dispatch: %s" % ", ".join(unknown))
    tools = [str(s.get("tool")) for s in steps if isinstance(s, dict)]
    if len(set(tools)) < 2:
        fails.append("D1 %d step(s) but %d distinct tool(s) - a repeated single "
                     "call is not a procedure" % (len(tools), len(set(tools))))
    md, merr = "", None
    try:
        with open(os.path.join(cand, "SKILL.md"), encoding="utf-8") as f:
            md = f.read()
    except OSError as e:
        merr = str(e)
    if merr or not md.strip():
        fails.append("E1 SKILL.md missing or empty (%s)" % (merr or "blank"))
    elif len(md) > MAX_SKILL_MD:
        fails.append("E2 SKILL.md is %d chars (ceiling %d)" % (len(md), MAX_SKILL_MD))
    low = md.lower()
    hit = [p for p in BYPASS if p in low]
    if hit:
        fails.append("F1 SKILL.md asks to bypass a gate: %s" % ", ".join(hit))
    for n in notes:
        print(n)
    if fails:
        for x in fails:
            print("FAIL " + x)
        print("verdict: REFUSED (%d problem(s))" % len(fails))
        return 1
    print("verdict: PASS (%d step(s), %d distinct tool(s), %d chars)"
          % (len(tools), len(set(tools)), len(md)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
'''


def install(tools=None, force=False):
    """Admin: write the sealed judge suite into the data home and pin it.

    NOT an agent action (same contract as `pin`): the agent must not author the
    judge that certifies it. `tools` is the frozen allow-list — the caller passes
    the dispatchable names (one registry read); `None` asks the registry lazily,
    so this module keeps its no-server-dependency shape.

    Refuses to replace an already pinned suite unless `force`, so a repeated call
    is a no-op rather than a silent judge swap.
    """
    root = dir()
    if load_manifest() is not None and not force:
        return {"ok": False, "reason": "already installed",
                "manifest": manifest_path(), "hint": "pass force=True to replace"}
    if tools is None:
        try:
            from longrun.util import selfevolve
            tools = sorted(set(selfevolve._known_tools()))
        except Exception:  # noqa: BLE001 — an install must explain itself
            return {"ok": False, "reason": "no tool list (pass tools=[...])"}
    tools = sorted({str(t) for t in (tools or []) if str(t).strip()})
    if not tools:
        return {"ok": False, "reason": "empty tool list - refusing to install a "
                                       "judge that would refuse every candidate"}
    suite = os.path.join(root, "suite")
    try:
        os.makedirs(suite, exist_ok=True)
        with open(os.path.join(suite, "check_all.py"), "w", encoding="utf-8") as f:
            f.write(SEALED_SUITE_SRC)
        with open(os.path.join(suite, "allowed_tools.json"), "w", encoding="utf-8") as f:
            json.dump(tools, f, indent=2)
    except OSError as e:
        return {"ok": False, "reason": "write failed: %s" % e}
    # The command must HAND the candidate over: the default carries no
    # placeholder, and a judge that never sees what it judges always passes.
    m = pin(command="python3 check_all.py {candidate}")
    return {"ok": True, "dir": root, "suite": suite, "tools": len(tools),
            "files": sorted(m.get("files") or {}), "command": m["command"],
            "integrity": integrity()}

