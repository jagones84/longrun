#!/usr/bin/env python3
"""H2-5 — fail-closed probe planning and injected offline execution.

This is the step that answers "did the edit fix a concrete failure" without an
answer key: candidate harnesses are executed on the same task and their
behaviour is compared with the reference run's
(`research/papers/harness2/harness2_2610.14224.txt:285-297`). The paper warns
about the price: every probe is a full execution plus editor sessions, and
parallelism reduces latency, not compute (`:1905-1911`).

Hard rules, because a probe WRITES:

1. **Whole-run isolation is mandatory and unavailable.** Production refuses
   before staging or host execution. Offline injected runners test planning and
   contrast only; a copy and redirected stores do not establish confinement.
2. **Off by default.** `harness.enabled` is false; `max_candidates` is 2; a
   caller-declared token budget below `MIN_TOKENS` refuses before any copy.
3. **A candidate it cannot apply is refused, not approximated.** The loop the
   probe drives is the operator's real chat loop (`agent.chat_once`, via
   `harness.runner`), which assembles its system prompt from constants + the
   prompt MAP, not from `prompt.d` addenda — so a system-prompt candidate is
   refused with that exact reason instead of being silently ignored. The same
   goes for `tool_guidance`, which would need a real `tools.yaml` merge.
4. **Nothing is adopted here.** Injected execution returns a record and contrast.
   The current single-rollout cycle cannot establish a durable lesson or approval.

Supported planning kinds: `skill` (skills/harness/<name>/SKILL.md), `guardrail`
(rules/Project_rules.md, prepared through the existing project rules owner).
"""
import os
import shutil
import uuid

from longrun.harness import contrast as contrast_mod
from longrun.harness import record as record_mod
from longrun.util.fswrite import write_json

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
KINDS = ("skill", "guardrail")


def isolation_status():
    """Whole-chat isolation readiness, not the shell tool's sandbox setting.

    A copied workspace and redirected stores do not confine fs tools, Python or
    network calls. No supported whole-run launcher exists yet, so production
    probes must refuse rather than use the legacy host subprocess.
    """
    return {"available": False, "backend": None,
            "reason": "whole-run isolation unavailable; host probe execution refused"}


def cfg(override=None):
    """Effective config: DEFAULTS <- env (`LONGRUN_HARNESS_*`) -> override.

    Deliberately NOT a `config/tools.yaml` leaf: a new leaf would demand a Settings
    form (`v491`) for a value nobody tunes yet, and the block is a spend/risk switch
    rather than a preference. The enable flag never overrides isolation refusal.
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
    root_dst = os.path.realpath(dst)
    if root_dst == root_src or root_dst.startswith(root_src + os.sep):
        return {"ok": False, "files": 0, "bytes": 0, "skipped": [],
                "reason": "destination is inside source workspace"}
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


def _target(kind, name):
    """The runtime path a candidate kind occupies -> (target, refusal reason).

    Pure: the target is computed BEFORE anything is written, so a duplicate can be
    refused without its content ever touching the stage.
    """
    slug = _safe(name, "candidate")
    if kind == "skill":
        return os.path.join("skills", "harness", slug, "SKILL.md"), ""
    if kind == "guardrail":
        return os.path.join("rules", "Project_rules.md"), ""
    if kind == "script":
        return "", "script has no supported runtime consumer"
    if kind in ("prompt", "tool_guidance"):
        return "", ("%s candidates are not supported by the agent loop: its prompt is "
                    "assembled from constants + the prompt MAP, not from prompt.d "
                    "addenda (and tool guidance would need a tools.yaml merge)" % kind)
    return "", "unknown kind %r" % (kind,)


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
    target, why = _target(kind, name)
    if not target:
        return {"ok": False, "target": "", "path": "", "reason": why}
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


def _skills_root(staged, base_dir):
    """A skills root = the REAL tree + the staged candidate(s).

    A probe must differ from the base harness in the CANDIDATE only. Pointing
    `LONGRUN_SKILLS_DIR` at the stage alone would hide every real skill and the
    contrast would then measure that loss instead of the candidate's effect.
    """
    from longrun.memory import skills as skills_mod  # local: probe is also used headless
    real = getattr(skills_mod, "SKILLS_DIR", "")
    out = os.path.join(base_dir, "skills")
    if os.path.isdir(real) and not os.path.exists(out):
        try:
            shutil.copytree(real, out, symlinks=True)
        except (OSError, shutil.Error):
            os.makedirs(out, exist_ok=True)
    else:
        os.makedirs(out, exist_ok=True)
    for base, _dirs, names in os.walk(staged):
        for name in names:
            src = os.path.join(base, name)
            dst = os.path.join(out, os.path.relpath(src, staged))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.isdir(dst) and not os.path.islink(dst):
                shutil.rmtree(dst)
            shutil.copy2(src, dst)
    return out


def plan(base, candidates, c=None, probe_id=None):
    """Reserve unique scratch space and clean every preparation failure."""
    pid = _safe(probe_id or ("probe-" + uuid.uuid4().hex))
    directory = os.path.join(root(), pid)
    try:
        os.makedirs(directory, exist_ok=False)
    except OSError as exc:
        return {"ok": False, "reason": "cannot reserve probe scratch: %s" % exc,
                "refusals": []}
    try:
        return _prepare_plan(base, candidates, c, pid)
    except Exception as exc:
        cleanup(pid)
        return {"ok": False, "reason": "probe preparation failed: %s: %s" %
                (type(exc).__name__, exc), "refusals": []}


def _prepare_plan(base, candidates, c=None, probe_id=None):
    """The exact command + env a probe would use, or the reasons it cannot run.

    Returns {"ok", "reason", "env", "cmd", "cwd", "stage", "refusals", "workspace"}.
    No side effect beyond the stage directory inside `<harness>/probe`.
    """
    c = c or cfg()
    pid = _safe(probe_id or ("probe-" + uuid.uuid4().hex))
    base_dir = os.path.join(root(), pid)
    stage_dir = os.path.join(base_dir, "stage")
    scratch = os.path.join(base_dir, "workspace")
    refusals = []
    staged = {}
    by_target = {}
    for cand in (candidates or []):
        if not isinstance(cand, dict):
            refusals.append({"name": "?", "reason": "not an object"})
            continue
        kind = str(cand.get("kind") or "")
        label = str(cand.get("name") or "?")
        target, why = _target(kind, cand.get("name"))
        if not target:
            refusals.append({"name": label, "reason": why})
            continue
        first = by_target.get(target)
        if first:
            # Two candidates of the same kind write the SAME file, so the second
            # would silently overwrite the first while Compose claimed both were
            # adopted. One file per kind per probe; the refusal names the winner.
            # The check runs BEFORE the write, so the first text survives intact.
            refusals.append({"name": label,
                             "reason": "same file as %r (%s) — one per kind per probe"
                                       % (first, target)})
            continue
        got = stage(kind, cand.get("name"), cand.get("content"), stage_dir)
        if not got["ok"]:
            refusals.append({"name": label, "reason": got["reason"]})
            continue
        by_target[target] = label
        staged[label] = got["path"]
    if not _has_files(stage_dir):
        shutil.rmtree(base_dir, ignore_errors=True)
        return {"ok": False, "reason": "nothing stageable", "refusals": refusals,
                "stage": stage_dir, "workspace": scratch}
    copied = guarded_copy(str(base.get("workspace") or ""), scratch,
                          c.get("copy_max_mb", DEFAULTS["copy_max_mb"]))
    if not copied["ok"]:
        shutil.rmtree(base_dir, ignore_errors=True)
        return {"ok": False, "reason": copied["reason"], "refusals": refusals,
                "stage": stage_dir, "workspace": scratch, "copy": copied}
    from longrun.memory import rules
    collected = rules.collect(ws=base["workspace"])
    # The copied workspace already carries its AGENTS.md. Do not duplicate it
    # by also turning the collected addendum into a native project rule.
    snapshot = {}
    for scope in ("global", "project"):
        texts = []
        for path in collected[scope]["files"]:
            if scope == "project" and path == rules.project_agents_path(base["workspace"]):
                continue
            with open(path, encoding="utf-8") as f:
                texts.append(f.read())
        snapshot[scope] = "\n\n".join(texts)
    rules_file = os.path.join(base_dir, "rules.json")
    write_json(rules_file, snapshot)
    staged_guard = os.path.join(stage_dir, "rules", "Project_rules.md")
    env = dict(os.environ)
    staged_skills = os.path.join(stage_dir, "skills")
    if _has_files(staged_skills):
        env["LONGRUN_SKILLS_DIR"] = _skills_root(staged_skills, base_dir)
    env["LONGRUN_HARNESS_PROBE"] = pid
    # The probe runs the REAL chat loop in a child process: it must write its
    # session and events into the probe dir, never into the operator's stores.
    # DATA_DIR is boxed for the same reason — the chat loop's reflection/improvement
    # pass writes memory and proposals, and a probe must never land those in the
    # live inbox. Fidelity limit, stated instead of hidden: the candidate therefore
    # runs with a FRESH data dir (no accumulated operator memory), so a memory-driven
    # step can differ; the contrast reports that instead of a probe polluting state.
    env["LONGRUN_SESSIONS_DIR"] = os.path.join(base_dir, "sessions")
    env["LONGRUN_DB"] = os.path.join(base_dir, "events.db")
    env["LONGRUN_DATA_DIR"] = os.path.join(base_dir, "data")
    env["LONGRUN_DATA_HOME"] = os.path.join(base_dir, "home")
    env["LONGRUN_CONFIG_DIR"] = os.path.join(base_dir, "config")
    for key, leaf in (("PROJECTS_DIR", "projects"), ("HARNESS_DIR", "harness"),
                      ("RUNS_DIR", "runs"), ("THREADS_DIR", "threads"),
                      ("MESSAGES_DIR", "messages"), ("CODEBASE_DIR", "codebase"),
                      ("KNOWLEDGE_DIR", "knowledge"), ("EMBEDDING_DIR", "embedding"),
                      ("MATRIX_DOT", "matrix"), ("WORKSPACES_ROOT", "workspaces"),
                      ("SKILLS_LOCAL_DIR", "skills-local"),
                      ("SKILLS_DIGESTS", "skills-digests.json"), ("HOOKS", "hooks.yaml")):
        env["LONGRUN_" + key] = os.path.join(base_dir, leaf)
    # `agent.CHAT_TOOL_MAX_STEPS` is read at import time from this var — the step
    # ceiling is a budget, so the child gets it before the module is imported.
    env["LONGRUN_CHAT_TOOL_STEPS"] = str(int(c.get("max_steps") or DEFAULTS["max_steps"]))
    # The probe runs `-m longrun.harness.runner` in a child process: the package
    # must be importable there even when the service was started from `server.py`
    # (which puts `src` on sys.path only inside its own process).
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    env["PYTHONPATH"] = os.pathsep.join(
        [src] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    cmd = [os.environ.get("LONGRUN_PYTHON") or "python3", "-m", "longrun.harness.runner",
           "--goal", str(base.get("goal") or ""),
           "--model", str(base.get("model") or ""),
           "--rules", rules_file, "--out", os.path.join(base_dir, "result.json")]
    if os.path.isfile(staged_guard):
        cmd += ["--guardrail", staged_guard]
    return {"ok": True, "reason": "", "env": env, "cmd": cmd, "cwd": scratch,
            "stage": stage_dir, "refusals": refusals, "workspace": scratch,
            "probe_id": pid, "copy": copied, "staged": staged}


def _spawn(plan_obj, timeout):
    """No host fallback, including direct calls to this legacy entry point."""
    return None, isolation_status()["reason"]


def run(base, candidates, runner=None, c=None, budget=None):
    """Probe `candidates` on the same task and contrast with the reference run.

    Args:
        base: the reference execution record (`harness.record.build`).
        candidates: [{kind, name, content}] — at most `max_candidates`.
        runner: `runner(plan_obj, timeout) -> (result|None, error)`; injected in
            tests. The production default refuses: no whole-run launcher exists.
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
    if runner is None:
        isolation = isolation_status()
        if not isolation["available"]:
            return {"status": "refused", "reason": isolation["reason"],
                    "isolation": isolation}
    plan_obj = plan(base, candidates, c)
    if not plan_obj["ok"]:
        return {"status": "refused", "reason": plan_obj["reason"],
                "refusals": plan_obj.get("refusals") or []}
    call = runner or _spawn
    try:
        result, error = call(plan_obj, int(c.get("max_seconds") or DEFAULTS["max_seconds"]))
    except Exception as exc:
        result, error = None, "%s: %s" % (type(exc).__name__, exc)
    if result is None:
        cleanup(plan_obj["probe_id"])
        return {"status": "failed", "reason": error, "probe_id": plan_obj["probe_id"]}
    got = result.get("record") if isinstance(result, dict) else None
    if not isinstance(got, dict) or result.get("error"):
        # A runner that produced no record is a FAILURE, never an empty contrast:
        # an empty candidate record would read as "every base error is gone".
        cleanup(plan_obj["probe_id"])
        return {"status": "failed", "probe_id": plan_obj["probe_id"],
                "reason": str((result.get("error") if isinstance(result, dict) else "")
                              or "runner returned no record")[:400]}
    diff = contrast_mod.diff(base, got)
    if not c.get("keep"):
        # The workspace COPY goes now (it is the big part); the small `stage/` stays
        # so Compose can copy the adopted component into the library. `cleanup()`
        # removes the rest when the cycle is done with it.
        shutil.rmtree(os.path.join(root(), plan_obj["probe_id"], "workspace"), ignore_errors=True)
    return {"status": "ran", "probe_id": plan_obj["probe_id"], "record": got,
            "contrast": diff, "refusals": plan_obj.get("refusals") or [],
            "copy": plan_obj.get("copy"), "staged": plan_obj.get("staged") or {}}


def cleanup(probe_id):
    """Remove one probe's scratch directory (workspace copy + stage)."""
    shutil.rmtree(os.path.join(root(), _safe(probe_id)), ignore_errors=True)
