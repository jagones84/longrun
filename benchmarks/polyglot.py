#!/usr/bin/env python3
"""Aider-polyglot (Exercism) code-editing suite, scored by the exercise's OWN tests.

Why this suite replaces the LLM judge for harness comparison:

* **Deterministic.** The score is `pytest`'s exit code on the exercise's own test
  file, nothing else. Two runs on the same artefacts cannot disagree by ±12
  points (the JobBench judge does: measured 2026-10-31).
* **Harness-agnostic.** Every task is a directory the agent edits; the runner
  collects nothing from the agent's prose, only from the files it wrote.
* **Cheap.** No Docker image, no external corpus build: `python3 -m pytest`.
* **Provenance.** The exercises come from `Aider-AI/polyglot-benchmark`, the same
  corpus the Aider polyglot leaderboard uses (225 exercises, 6 languages).

Only the **Python track** is wired here: it needs `pytest` and nothing else. The
other tracks (JS/Go/Rust/Java/C++) need a per-language image with their test deps;
`load_tasks` refuses them by name instead of silently scoring 0.

The reference solution lives in `.meta/example.py` and is NEVER staged into the
workspace — staging it would hand the agent the answer.
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

DATASET_ENV = "POLYGLOT_DIR"
DEFAULT_DATASET = Path("/home/jagones/Repositories/polyglot-benchmark")

#: language -> the files that make a task, and the command that decides it.
#: `image` set = the command runs inside that container (the host has no such
#: toolchain); the workspace is bind-mounted at /e and the network is OFF.
WIRED = {
    "python": {"src_suffix": ".py", "test_suffix": "_test.py",
               "cmd": ["python3", "-m", "pytest", "-q"]},
    "go": {"src_suffix": ".go", "test_suffix": "_test.go",
           "cmd": ["go", "test", "./..."], "image": "golang:1.22-bookworm",
           "cache": ("~/.cache/polyglot-go-build", "/root/.cache/go-build")},
}

#: Tasks whose own tests pass on the UNTOUCHED stub — they measure nothing, so
#: the score would be free points for every arm. Found by `--check` (2026-10-31:
#: go/ledger `exemplar=passed stub=passed`).
KNOWN_BAD = {"go/ledger"}


def dataset_root():
    """The polyglot checkout (`POLYGLOT_DIR`, else the documented default)."""
    return Path(os.environ.get(DATASET_ENV) or DEFAULT_DATASET)


def dataset_commit():
    """Short git sha of the dataset checkout, so a run names the exact corpus."""
    try:
        return subprocess.run(["git", "-C", str(dataset_root()), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _exercise_dirs(language):
    root = dataset_root() / language / "exercises" / "practice"
    return sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


def _files_of(exercise, language):
    """(source, test) relative names of one exercise, or (None, None)."""
    spec = WIRED[language]
    tests = sorted(p.name for p in exercise.glob("*" + spec["test_suffix"]))
    if len(tests) != 1:
        return None, None
    sources = [p.name for p in exercise.glob("*" + spec["src_suffix"])
               if not p.name.endswith(spec["test_suffix"])]
    if len(sources) != 1:
        return None, None
    return sources[0], tests[0]


def load_tasks(language="python", limit=None, only=None):
    """Tasks = exercises that have instructions, one source, one test, an exemplar.

    A task without `.meta/example.py` cannot be checked end-to-end (the `--check`
    mode proves the verifier), so it is skipped rather than trusted.
    """
    if language not in WIRED:
        raise SystemExit(
            "%r track is not wired: it needs a container with its test deps "
            "(npm/go/cargo/mvn). Wired: %s" % (language, ", ".join(sorted(WIRED))))
    tasks = []
    for exercise in _exercise_dirs(language):
        src, test = _files_of(exercise, language)
        if not src or not (exercise / ".docs" / "instructions.md").is_file():
            continue
        if not (exercise / ".meta" / ("example" + WIRED[language]["src_suffix"])).is_file():
            continue
        tasks.append({
            "id": "%s/%s" % (language, exercise.name),
            "language": language,
            "exercise": exercise.name,
            "dir": str(exercise),
            "source": src,
            "test": test,
            "instructions": (exercise / ".docs" / "instructions.md").read_text(
                encoding="utf-8", errors="replace"),
        })
    if only:
        wanted = set(only)
        tasks = [t for t in tasks if t["id"] in wanted or t["exercise"] in wanted]
    tasks = [t for t in tasks if t["id"] not in KNOWN_BAD]
    return tasks[: (limit or len(tasks))]


def stage(task, ws):
    """Copy the exercise into `ws`, minus `.meta` (the reference solution)."""
    ws = Path(ws)
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    for p in Path(task["dir"]).iterdir():
        if p.name == ".meta" or p.name == "__pycache__":
            continue
        if p.is_dir():
            shutil.copytree(p, ws / p.name)
        else:
            shutil.copy2(p, ws / p.name)
    return ws


def test_guard(task, ws):
    """sha256 of every file the agent is forbidden to edit (the tests + data)."""
    guard = {}
    for p in Path(ws).rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ws).as_posix()
        if "__pycache__" in rel or rel.endswith(".pyc"):
            continue
        if rel == task["test"] or rel.startswith(".docs/"):
            guard[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return guard


def prompt_for(task, ws):
    """The prompt every arm receives: identical text, one job, one destination."""
    spec = WIRED[task["language"]]
    cmd = " ".join(spec["cmd"])
    if spec.get("image"):
        how = ("Scoring runs `%s` in a clean container against this directory "
               "(`%s` is not installed on the host)." % (cmd, task["language"]))
    else:
        how = "Run the tests yourself with `%s %s` from `%s` until they pass." % (
            cmd, task["test"], ws)
    return (
        "You are working in the directory `%s`.\n\n"
        "Fix the exercise so its test suite passes. Edit `%s` in that directory. "
        "Do NOT modify `%s` or any other test/data file: a changed test file makes "
        "the result invalid.\n\n"
        "%s\n\n"
        "--- exercise instructions ---\n%s\n"
        % (ws, task["source"], task["test"], how, task["instructions"].strip())
    )


def verify(task, ws, timeout=180.0):
    """Run the exercise's own tests in `ws`. Deterministic: exit code decides.

    Returns {resolved, status, detail}. `status` is `passed`, `failed`,
    `tests_modified` (the agent edited the grader), `no_tests`, or `error`.
    """
    ws = Path(ws)
    guard = test_guard(task, ws)
    for rel, digest in guard.items():
        p = ws / rel
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            return {"resolved": False, "status": "tests_modified",
                    "detail": "%s changed by the agent" % rel}
    cmd = _command_for(task, ws)
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run(cmd, cwd=str(ws), env=env, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"resolved": False, "status": "error", "detail": "test timeout"}
    except OSError as exc:
        return {"resolved": False, "status": "error", "detail": str(exc)}
    tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-800:]
    if "no tests ran" in tail.lower() or "no test files" in tail.lower() \
            or "[no test files]" in tail.lower():
        return {"resolved": False, "status": "no_tests", "detail": tail}
    if proc.returncode == 0:
        return {"resolved": True, "status": "passed", "detail": tail[-200:]}
    return {"resolved": False, "status": "failed", "detail": tail}


def _command_for(task, ws):
    """The verifier command: native for python, a container for a track the host
    has no toolchain for. The container gets the workspace at /e and no network."""
    spec = WIRED[task["language"]]
    if not spec.get("image"):
        return spec["cmd"] + [task["test"]]
    args = ["docker", "run", "--rm", "--network", "none",
            "-v", "%s:/e" % Path(ws).resolve(), "-w", "/e"]
    if spec.get("cache"):
        host_cache = Path(os.path.expanduser(spec["cache"][0]))
        host_cache.mkdir(parents=True, exist_ok=True)
        args += ["-v", "%s:%s" % (host_cache, spec["cache"][1])]
    return args + [spec["image"]] + spec["cmd"]


def reference_solution(task, ws):
    """Copy the exemplar over the stub — used by `--check` to prove the verifier."""
    src = Path(ws) / task["source"]
    exemplar = Path(task["dir"]) / ".meta" / ("example" + Path(task["source"]).suffix)
    if not exemplar.is_file():
        return False
    shutil.copy2(exemplar, src)
    return True


if __name__ == "__main__":
    # tiny CLI: list the tasks the suite would run
    lang = sys.argv[1] if len(sys.argv) > 1 else "python"
    tasks = load_tasks(lang)
    print("%d %s tasks from %s (commit %s)"
          % (len(tasks), lang, dataset_root(), dataset_commit() or "?"))
    for t in tasks:
        print("  %-28s src=%-28s test=%s" % (t["id"], t["source"], t["test"]))
