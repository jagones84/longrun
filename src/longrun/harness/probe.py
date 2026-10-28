#!/usr/bin/env python3
"""H2-5 — probe: re-run the SAME task on a candidate harness, in isolation.

This is the step that answers "did the edit fix a concrete failure" without an
answer key: candidate harnesses are executed on the same task and their
behaviour is compared with the reference run's
(`research/papers/harness2/harness2_2610.14224.txt:285-297`). The paper warns
about the price: every probe is a full execution plus editor sessions, and
parallelism reduces latency, not compute (`:1905-1911`).

Hard rules, because a probe WRITES:

1. **Isolation is mandatory.** The operator's workspace is copied into
   `<data>/harness/probe/<id>/workspace` and the run happens there. The copy
   skips VCS/dependency trees, never follows a symlink that leaves the root, and
   refuses a tree above `copy_max_mb`.
2. **Off by default.** `harness.enabled` is false; `max_candidates` is 2; a
   caller-declared token budget below `MIN_TOKENS` refuses before any copy.
3. **A candidate it cannot apply is refused, not approximated.** The loop the
   probe drives (`agent.agent_run`) assembles its system prompt from constants +
   the prompt MAP, not from `prompt.d` addenda — so a system-prompt candidate is
   refused with that exact reason instead of being silently ignored. The same
   goes for `tool_guidance`, which would need a real `tools.yaml` merge.
4. **Nothing is adopted here.** `run()` returns a record and a contrast; Compose
   decides, and only a proposal leaves this module.

Supported candidate kinds: `skill` (skills/<name>/SKILL.md), `guardrail`
(<workspace>/Project_rules.md), `script` (scripts/<name>.py).
"""
import json
import os
import shutil
import subprocess
import time

from longrun.harness import contrast as contrast_mod
from longrun.harness import record as record_mod

DEFAULTS = {
    "enabled": False,
    "max_candidates": 2,
    "max_seconds": 900,
    "max_steps": 12,
    "copy_max_mb": 512,
    "keep": False,
}
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".gradle", "build",
             "dist", ".mypy_cache", ".pytest_cache", ".ruff_cache", "target"}
MIN_TOKENS = 1000
MAX_FILE_BYTES = 2 * 1024 * 1024
KINDS = ("skill", "guardrail", "script")


def cfg(override=None):
    """Effective config: DEFAULTS <- env (`LONGRUN_HARNESS_*`) -> override.

    Deliberately NOT a `config/tools.yaml` leaf: a new leaf would demand a Settings
    form (`v491`) for a value nobody tunes yet, and the block is a spend/risk switch
    rather than a preference. `LONGRUN_HARNESS_ENABLED=1` is the one switch an
    operator needs.
    """
    out = dict(DEFAULTS)
    env = {
        "enabled": ("LONGRUN_HARNESS_ENABLED", bool),
        "max_candidates": ("LONGRUN_HARNESS_MAX_CANDIDATES", int),
        "max_seconds": ("LONGRUN_HARNESS_MAX_SECONDS", int),
        "max_steps": ("LONGRUN_HARNESS_MAX_STEPS", int),
        "copy_max_mb": ("LONGRUN_HARNESS_COPY_MAX_MB", int),
        "keep": ("LONGRUN_HARNESS_KEEP", bool),
    }
    for key, (name, kind) in env.items():
        raw = os.environ.get(name)
        if raw is None or not str(raw).strip():
            continue
        try:
            out[key] = (str(raw).strip().lower() not in ("0", "false", "no", "off")
                        if kind is bool else int(raw))
        except ValueError:
            continue
    out.update(override or {})
    return out


def root():
    """`<harness>/probe` — scratch space for every probe."""
    return os.path.join(record_mod.dir_path(), "probe")


def _safe(value, fallback="probe"):
    """A filesystem-safe token for a probe/candidate name."""
    out = "".join(c for c in str(value or "") if c.isalnum() or c in "-_.").strip("-.")
    return (out or fallback)[:64]


# ---------------------------------------------------------------- isolation ---
def guarded_copy(src, dst, max_mb=512):
    """Copy a workspace into a scratch dir with hard guards.

    Args:
        src: the workspace to copy (read only).
        dst: the destination (must not exist or be empty).
        max_mb: refuse when the copied bytes exceed this.
    Returns:
        {"ok": bool, "files": int, "bytes": int, "skipped": [paths], "reason": str}
    """
    limit = max(0, int(max_mb)) * 1024 * 1024
    total, files, skipped = 0, 0, []
    root_src = os.path.realpath(src)
    if not os.path.isdir(root_src):
        return {"ok": False, "files": 0, "bytes": 0, "skipped": [], "reason": "no workspace"}
    try:
        os.makedirs(dst, exist_ok=False)
    except FileExistsError:
        return {"ok": False, "files": 0, "bytes": 0, "skipped": [], "reason": "destination exists"}
    for base, dirs, names in os.walk(root_src, followlinks=False):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel_base = os.path.relpath(base, root_src)
        for name in names:
            full = os.path.join(base, name)
            rel = os.path.normpath(os.path.join(rel_base, name))
            if os.path.islink(full):
                target = os.path.realpath(full)
                if not (target == root_src or target.startswith(root_src + os.sep)):
                    skipped.append(rel)
                    continue
            try:
                size = os.path.getsize(full)
            except OSError:
                skipped.append(rel)
                continue
            total += size
            if total > limit:
                shutil.rmtree(dst, ignore_errors=True)
                return {"ok": False, "files": files, "bytes": total, "skipped": skipped,
                        "reason": "workspace is larger than %d MB" % int(max_mb)}
            out = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            try:
                shutil.copy2(full, out)
                files += 1
            except OSError:
                skipped.append(rel)
    return {"ok": True, "files": files, "bytes": total, "skipped": skipped, "reason": ""}


def stage(kind, name, content, stage_dir):
    """Write ONE candidate file into the probe's stage (never into the workspace).

    Returns {"ok", "target", "path", "reason"}; `target` is where the runtime must
    look for it, `path` is the staged file.
    """
    text = str(content or "")
    if not text.strip():
        return {"ok": False, "target": "", "path": "", "reason": "empty candidate"}
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        return {"ok": False, "target": "", "path": "",
                "reason": "candidate is larger than %d bytes" % MAX_FILE_BYTES}
    slug = _safe(name, "candidate")
    if kind == "skill":
        target = os.path.join("skills", "harness", slug, "SKILL.md")
    elif kind == "guardrail":
        target = os.path.join("workspace", "Project_rules.md")
    elif kind == "script":
        target = os.path.join("scripts", slug + ".py")
    elif kind in ("prompt", "tool_guidance"):
        return {"ok": False, "target": "", "path": "",
                "reason": "%s candidates are not supported by the agent loop: its prompt is "
                          "assembled from constants + the prompt MAP, not from prompt.d "
                          "addenda (and tool guidance would need a tools.yaml merge)" % kind}
    else:
        return {"ok": False, "target": "", "path": "", "reason": "unknown kind %r" % (kind,)}
    path = os.path.join(stage_dir, target)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as exc:
        return {"ok": False, "target": target, "path": "", "reason": str(exc)}
    return {"ok": True, "target": target, "path": path, "reason": ""}


def _has_files(path):
    """True when a staged directory actually contains a file."""
    for _base, _dirs, names in os.walk(path):
        if names:
            return True
    return False


def plan(base, candidates, c=None, probe_id=None):
    """The exact command + env a probe would use, or the reasons it cannot run.

    Returns {"ok", "reason", "env", "cmd", "cwd", "stage", "refusals", "workspace"}.
    No side effect beyond the stage directory inside `<harness>/probe`.
    """
    c = c or cfg()
    pid = _safe(probe_id or ("probe-%d" % int(time.time() * 1000)))
    base_dir = os.path.join(root(), pid)
    stage_dir = os.path.join(base_dir, "stage")
    scratch = os.path.join(base_dir, "workspace")
    refusals = []
    for cand in (candidates or []):
        if not isinstance(cand, dict):
            refusals.append({"name": "?", "reason": "not an object"})
            continue
        got = stage(str(cand.get("kind") or ""), cand.get("name"), cand.get("content"), stage_dir)
        if not got["ok"]:
            refusals.append({"name": str(cand.get("name") or "?"), "reason": got["reason"]})
    if not _has_files(stage_dir):
        return {"ok": False, "reason": "nothing stageable", "refusals": refusals,
                "stage": stage_dir, "workspace": scratch}
    copied = guarded_copy(str(base.get("workspace") or ""), scratch,
                          c.get("copy_max_mb", DEFAULTS["copy_max_mb"]))
    if not copied["ok"]:
        shutil.rmtree(base_dir, ignore_errors=True)
        return {"ok": False, "reason": copied["reason"], "refusals": refusals,
                "stage": stage_dir, "workspace": scratch, "copy": copied}
    guard = os.path.join(scratch, "Project_rules.md")
    staged_guard = os.path.join(stage_dir, "workspace", "Project_rules.md")
    if os.path.isfile(staged_guard):
        try:
            with open(staged_guard, "r", encoding="utf-8") as f:
                body = f.read()
            with open(guard, "a", encoding="utf-8") as f:
                f.write("\n\n" + body)
        except OSError as exc:
            refusals.append({"name": "guardrail", "reason": "could not apply: %s" % exc})
    env = dict(os.environ)
    env["LONGRUN_SKILLS_DIR"] = os.path.join(stage_dir, "skills")
    env["LONGRUN_HARNESS_PROBE"] = pid
    # The probe runs `-m longrun.harness.runner` in a child process: the package
    # must be importable there even when the service was started from `server.py`
    # (which puts `src` on sys.path only inside its own process).
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    env["PYTHONPATH"] = os.pathsep.join(
        [src] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    cmd = [os.environ.get("LONGRUN_PYTHON") or "python3", "-m", "longrun.harness.runner",
           "--goal", str(base.get("goal") or ""),
           "--max-steps", str(int(c.get("max_steps") or DEFAULTS["max_steps"])),
           "--out", os.path.join(base_dir, "result.json")]
    return {"ok": True, "reason": "", "env": env, "cmd": cmd, "cwd": scratch,
            "stage": stage_dir, "refusals": refusals, "workspace": scratch,
            "probe_id": pid, "copy": copied}


def _spawn(plan_obj, timeout):
    """Run the probe command; returns (result_dict|None, error)."""
    try:
        proc = subprocess.run(plan_obj["cmd"], cwd=plan_obj["cwd"], env=plan_obj["env"],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    out = plan_obj["cmd"][plan_obj["cmd"].index("--out") + 1]
    try:
        with open(out, "r", encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return None, (proc.stderr or "no result file")[-400:]
    return (got if isinstance(got, dict) else None), ""


def run(base, candidates, runner=None, c=None, budget=None):
    """Probe `candidates` on the same task and contrast with the reference run.

    Args:
        base: the reference execution record (`harness.record.build`).
        candidates: [{kind, name, content}] — at most `max_candidates`.
        runner: `runner(plan_obj, timeout) -> (result|None, error)`; injected in
            tests. Default spawns `longrun.harness.runner` in the scratch copy.
        c: config override (tests).
        budget: {"tokens_left": int} declared by the caller, if any.
    Returns:
        {"status": "skipped|refused|ran|failed", ...}
    """
    c = c or cfg()
    if not c.get("enabled"):
        return {"status": "skipped", "reason": "disabled"}
    if not candidates:
        return {"status": "skipped", "reason": "no candidates"}
    if len(candidates) > int(c.get("max_candidates") or 1):
        return {"status": "refused",
                "reason": "more than %d candidates" % int(c.get("max_candidates") or 1)}
    if budget is not None and int(budget.get("tokens_left") or 0) < MIN_TOKENS:
        return {"status": "refused", "reason": "token budget below %d" % MIN_TOKENS}
    plan_obj = plan(base, candidates, c)
    if not plan_obj["ok"]:
        return {"status": "refused", "reason": plan_obj["reason"],
                "refusals": plan_obj.get("refusals") or []}
    call = runner or _spawn
    result, error = call(plan_obj, int(c.get("max_seconds") or DEFAULTS["max_seconds"]))
    if result is None:
        return {"status": "failed", "reason": error, "probe_id": plan_obj["probe_id"]}
    got = record_mod.from_actions(
        str(result.get("goal") or base.get("goal") or ""),
        result.get("actions") or [],
        workspace=plan_obj["workspace"],
        model=result.get("model") or base.get("model"),
        run_id="probe-" + plan_obj["probe_id"],
        created=result.get("created"))
    got["goal"] = str(base.get("goal") or "")  # comparison must be same-goal
    diff = contrast_mod.diff(base, got)
    if not c.get("keep"):
        shutil.rmtree(os.path.join(root(), plan_obj["probe_id"]), ignore_errors=True)
    return {"status": "ran", "probe_id": plan_obj["probe_id"], "record": got,
            "contrast": diff, "refusals": plan_obj.get("refusals") or [],
            "copy": plan_obj.get("copy")}
