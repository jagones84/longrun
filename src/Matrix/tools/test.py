"""Matrix tool namespace: test — run the Longrun test gate with structured results.

Real implementation (replaces the earlier placeholder): executes
``tests/battery.sh`` — or a single test file — in a subprocess scoped to the
workspace, parses the aggregate line the gate prints, and returns a
machine-readable verdict so an agent can prove an edit is safe.

Read-only with respect to the repo: every run happens in throwaway
``LONGRUN_*`` dirs under the system temp dir, exactly like the gate itself.
Scope is fixed to ``<repo>/tests`` — no argument can point elsewhere.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

DEFAULT_BATTERY_TIMEOUT = 900
DEFAULT_ONE_TIMEOUT = 300

# The gate's own per-test env contract (mirrors tests/battery.sh:_run_one).
_DATA_DIRS = (
    ("LONGRUN_DATA_DIR", "data"),
    ("LONGRUN_CONFIG_DIR", "cfg"),
    ("LONGRUN_SESSIONS_DIR", "sessions"),
    ("LONGRUN_GRAPH_DIR", "graphs"),
    ("LONGRUN_EDITS_DIR", "edits"),
    ("LONGRUN_RUNS_DIR", "runs"),
    ("LONGRUN_ROLES_DIR", "roles"),
    ("LONGRUN_COSTS_DIR", "costs"),
    ("LONGRUN_THREADS_DIR", "threads"),
    ("LONGRUN_MATRIX_SRC", "matrix_src"),
    ("LONGRUN_MATRIX_DOT", "matrix_dot"),
)

_TEST_SUBDIRS = ("acceptance", "live", "properties", "legacy")

_AGG_RE = re.compile(r"===\s*battery:\s*(\d+)/(\d+)\s*(GREEN|\(FAILURES)", re.I)
_BLOCK_RE = re.compile(r"^=====\s*(\S+?)\s*=====\s*$")


# --------------------------------------------------------------- schemas ----

TOOL_SCHEMAS = {
    "test.battery": {
        "description": (
            "[MATRIX experimental] Run the repo test gate (`bash tests/battery.sh`) and "
            "return a structured verdict {ok, passed, failed, duration_s, failures, "
            "summary}. `only` runs just those test files directly in an isolated env; "
            "`full=true` also runs the heavy tests the fast gate skips; `timeout_s` caps "
            "the run. Read-only: every test gets throwaway LONGRUN_* dirs."
        ),
        "type": "object",
        "properties": {
            "full": {
                "type": "boolean",
                "description": "Run the heavy tests too (sets LONGRUN_BATTERY_FULL=1).",
                "default": False,
            },
            "only": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Run only these tests instead of the whole gate. Accepts a bare name "
                    "(v531_costs_cache_fields), a file name, or a path under tests/."
                ),
                "default": [],
            },
            "timeout_s": {
                "type": "integer",
                "description": "Hard timeout in seconds (default 900, clamped 5..3600).",
                "default": DEFAULT_BATTERY_TIMEOUT,
            },
        },
        "required": [],
        "approval": "auto",
    },
    "test.one": {
        "description": (
            "[MATRIX experimental] Run ONE test file from `tests/` in an isolated env and "
            "return {ok, passed, failed, duration_s, failures, summary}. The path is "
            "resolved under the repo's tests/ directory only."
        ),
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": (
                    "Test to run: bare name (v531_costs_cache_fields), file name, or a "
                    "path under tests/ (e.g. tests/live/v199_endpoint_sweep.py)."
                ),
            },
            "timeout_s": {
                "type": "integer",
                "description": "Hard timeout in seconds (default 300, clamped 5..3600).",
                "default": DEFAULT_ONE_TIMEOUT,
            },
        },
        "required": ["file"],
        "approval": "auto",
    },
}


# ------------------------------------------------------------- workspace ----

def _repo_root():
    """Locate the repo without walking the tree: known relative paths only."""
    try:  # inside the harness the canonical root is authoritative
        from longrun.util.paths import REPO_ROOT  # type: ignore

        p = Path(REPO_ROOT)
        if (p / "tests" / "battery.sh").exists():
            return p
    except Exception:
        pass
    for up in Path(__file__).resolve().parents:
        if (up / "tests" / "battery.sh").exists():
            return up
    # src/Matrix/tools/test.py -> repo root
    return Path(__file__).resolve().parents[3]


def _tests_dir(repo):
    return Path(repo) / "tests"


def _under(path, root):
    """True when `path` is inside `root` (resolved, string containment)."""
    try:
        p = os.path.abspath(str(path))
        r = os.path.abspath(str(root))
        return os.path.commonpath([p, r]) == r
    except (ValueError, OSError):
        return False


def _find_test(name, repo):
    """Resolve a user-supplied test selector to a path under <repo>/tests."""
    tests = _tests_dir(repo)
    raw = str(name or "").strip()
    if not raw:
        return None

    cand = Path(raw).expanduser()
    if cand.is_absolute():
        p = cand.resolve()
        if _under(p, tests) and p.suffix == ".py" and p.is_file():
            return p
        return None

    for base in (Path(repo), tests):
        p = (base / raw)
        if p.suffix == ".py" and p.is_file() and _under(p, tests):
            return p.resolve()

    stem = raw[:-3] if raw.endswith(".py") else raw
    for sub in _TEST_SUBDIRS:
        d = tests / sub
        if not d.is_dir():
            continue
        p = d / (stem + ".py")
        if p.is_file():
            return p.resolve()
    return None


# ---------------------------------------------------------------- helpers ----

def _timeout(args, default):
    try:
        value = int(args.get("timeout_s", default) or default)
    except (TypeError, ValueError):
        value = default
    return max(5, min(3600, value))


def _isolated_env(tmp):
    """The gate's throwaway env: no real state dir is ever touched."""
    tmp = Path(tmp)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(tmp / "pyc")
    for var, sub in _DATA_DIRS:
        env[var] = str(tmp / sub)
    env["LONGRUN_DB"] = str(tmp / "events.db")
    env["LONGRUN_PRICES_FILE"] = str(tmp / "prices.json")
    return env


def _run(cmd, cwd, env, timeout_s):
    started = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout_s,
        )
        out, rc = proc.stdout or "", proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        raw = exc.stdout or ""
        out = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        rc = -1
    except OSError as exc:
        out, rc = "cannot start %r: %s" % (cmd[:1], exc), -1
    return rc, out, round(time.monotonic() - started, 2), timed_out


def _tail(text, limit=2000):
    text = (text or "").strip()
    return text[-limit:]


def _reason_from_output(out):
    """Pick the most informative last lines of a failing single test."""
    keep = []
    for line in (out or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(("FAIL", "AssertionError", "Traceback", "Error", "ERROR")) or "Error" in s:
            keep.append(s[:300])
    if keep:
        return " | ".join(keep[:3])
    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    return " | ".join(lines[-3:])[:400] if lines else "no output"


def _parse_gate(out):
    """Parse battery.sh output -> (passed, total, failures[])."""
    passed = total = None
    matches = list(_AGG_RE.finditer(out or ""))
    if matches:
        last = matches[-1]
        passed, total = int(last.group(1)), int(last.group(2))

    failures = []
    current = None
    for line in (out or "").splitlines():
        block = _BLOCK_RE.match(line.rstrip())
        if block:
            current = {"test": block.group(1), "lines": []}
            failures.append(current)
            continue
        if current is None:
            continue
        s = line.strip()
        if not s:
            continue
        if s.startswith("FAIL") or s.startswith(("AssertionError", "Traceback")) or "Error:" in s:
            current["lines"].append(s[:300])
    shaped = [
        {"test": f["test"], "reason": " | ".join(f["lines"][:3]) or "see output"}
        for f in failures
    ]
    return passed, total, shaped


# ---------------------------------------------------------------- actions ----

def run_battery(args, repo):
    repo = Path(repo)
    gate = _tests_dir(repo) / "battery.sh"
    timeout_s = _timeout(args, DEFAULT_BATTERY_TIMEOUT)

    if not gate.is_file():
        return {
            "ok": False,
            "passed": 0,
            "failed": 0,
            "duration_s": 0.0,
            "failures": [],
            "summary": "gate not found: %s" % gate,
            "error": "missing_battery_script",
        }

    only = args.get("only") or []
    if isinstance(only, str):
        only = [only]
    only = [str(x) for x in only if str(x).strip()]

    if only:
        return _run_selected(only, repo, timeout_s)

    tmp = tempfile.mkdtemp(prefix="mtx-battery-")
    try:
        env = _isolated_env(tmp)
        env["LONGRUN_BATTERY_FULL"] = "1" if args.get("full") else "0"
        rc, out, duration_s, timed_out = _run(["bash", str(gate)], repo, env, timeout_s)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    passed, total, failures = _parse_gate(out)

    if timed_out:
        return {
            "ok": False,
            "passed": passed or 0,
            "failed": 0,
            "duration_s": duration_s,
            "failures": failures,
            "summary": "battery TIMED OUT after %ss" % timeout_s,
            "timed_out": True,
            "returncode": rc,
            "output_tail": _tail(out),
        }

    if total is None:
        return {
            "ok": False,
            "passed": 0,
            "failed": 0,
            "duration_s": duration_s,
            "failures": failures,
            "summary": "battery produced no parseable summary (rc=%s)" % rc,
            "returncode": rc,
            "output_tail": _tail(out),
        }

    failed = max(0, total - passed)
    ok = rc == 0 and failed == 0
    skipped = re.search(r"\((\d+)\s+heavy skipped", out or "")
    summary = "battery: %d/%d %s in %.1fs" % (
        passed, total, "passed" if ok else "passed (%d failed)" % failed, duration_s
    )
    if skipped:
        summary += " (%s heavy skipped)" % skipped.group(1)

    return {
        "ok": ok,
        "passed": passed,
        "failed": failed,
        "duration_s": duration_s,
        "failures": failures,
        "summary": summary,
        "total": total,
        "returncode": rc,
        "full": bool(args.get("full")),
    }


def _run_selected(names, repo, timeout_s):
    """Run named tests directly, each in the gate's isolated env."""
    results = []
    passed = failed = 0
    total_duration = 0.0
    failures = []
    missing = []

    for name in names:
        path = _find_test(name, repo)
        if path is None:
            missing.append(name)
            failed += 1
            failures.append({"test": name, "reason": "test not found under tests/"})
            continue
        tmp = tempfile.mkdtemp(prefix="mtx-one-")
        try:
            env = _isolated_env(tmp)
            rc, out, duration_s, timed_out = _run(["python3", str(path)], repo, env, timeout_s)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        total_duration += duration_s
        entry = {"test": path.stem, "duration_s": duration_s, "returncode": rc}
        if timed_out:
            failed += 1
            entry["reason"] = "TIMEOUT after %ss" % timeout_s
            failures.append(entry)
        elif rc == 0:
            passed += 1
        else:
            failed += 1
            entry["reason"] = _reason_from_output(out)
            failures.append(entry)
        results.append(entry)

    total = passed + failed
    ok = failed == 0 and total > 0
    summary = "selected: %d/%d passed in %.1fs" % (passed, total, total_duration)
    if missing:
        summary += " (not found: %s)" % ", ".join(missing[:5])
    return {
        "ok": ok,
        "passed": passed,
        "failed": failed,
        "duration_s": round(total_duration, 2),
        "failures": failures,
        "summary": summary,
        "total": total,
        "results": results,
    }


def run_one(args, repo):
    name = args.get("file") or args.get("test") or args.get("name")
    if not name:
        return {
            "ok": False,
            "passed": 0,
            "failed": 1,
            "duration_s": 0.0,
            "failures": [{"test": "", "reason": "missing required argument: file"}],
            "summary": "test.one needs a `file` argument",
            "error": "missing_file",
        }

    path = _find_test(name, repo)
    if path is None:
        return {
            "ok": False,
            "passed": 0,
            "failed": 1,
            "duration_s": 0.0,
            "failures": [{"test": str(name), "reason": "not found under tests/"}],
            "summary": "test not found under tests/: %s" % name,
            "error": "not_found",
        }

    timeout_s = _timeout(args, DEFAULT_ONE_TIMEOUT)
    tmp = tempfile.mkdtemp(prefix="mtx-one-")
    try:
        env = _isolated_env(tmp)
        rc, out, duration_s, timed_out = _run(["python3", str(path)], repo, env, timeout_s)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if timed_out:
        return {
            "ok": False,
            "passed": 0,
            "failed": 1,
            "duration_s": duration_s,
            "failures": [{"test": path.stem, "reason": "TIMEOUT after %ss" % timeout_s}],
            "summary": "%s TIMED OUT after %ss" % (path.stem, timeout_s),
            "timed_out": True,
            "file": str(path.relative_to(repo)),
            "output_tail": _tail(out),
        }

    ok = rc == 0
    failures = [] if ok else [{"test": path.stem, "reason": _reason_from_output(out)}]
    return {
        "ok": ok,
        "passed": 1 if ok else 0,
        "failed": 0 if ok else 1,
        "duration_s": duration_s,
        "failures": failures,
        "summary": "%s: %s in %.2fs" % (path.stem, "passed" if ok else "FAILED (rc=%s)" % rc, duration_s),
        "file": str(path.relative_to(repo)),
        "returncode": rc,
        "output_tail": _tail(out) if not ok else "",
    }


# --------------------------------------------------------------- dispatch ----

def execute(args, run_id=None, subtool=None):
    args = args or {}
    repo = _repo_root()
    which = str(subtool or "battery").split(".")[-1].strip().lower()
    try:
        if which in ("one", "test_one"):
            return run_one(args, repo)
        return run_battery(args, repo)
    except Exception as exc:  # fail closed with a structured verdict
        return {
            "ok": False,
            "passed": 0,
            "failed": 0,
            "duration_s": 0.0,
            "failures": [{"test": which, "reason": "%s: %s" % (type(exc).__name__, exc)}],
            "summary": "test tool error: %s" % exc,
            "error": "exception",
        }
