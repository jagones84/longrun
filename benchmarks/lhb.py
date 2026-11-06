#!/usr/bin/env python3
"""LHB — Longrun Harness Bench: measures the HARNESS, not the model.

Why a second suite when Polyglot and Terminal-Bench already exist: those score
the end state of one coding task. The 2026 evaluation literature says that is not
where a harness is distinguishable (research recorded in
`.agent/docs/research/2026-11-06_lhb-design/`):

  * a visible suite a harness can read is not a measurement — keep hidden
    compositional tests and report the validation-vs-held-out gap
    (SpecBench 2605.21384; BOBA-Bench 2611.02207);
  * score the procedure, not only the artefact — a success that violates the
    written policy is a corrupt success (2603.03116, 27-78% of successes);
  * a run that cannot be reproduced is not a result — tamper and
    out-of-bounds writes are gates, not penalties (BenchJack 2605.12673);
  * an impossible request must be refused, not fabricated
    (Post-Audit Mirage 2610.31130; procedure-aware 2603.03116);
  * harness effects are small next to model effects, so every task names the
    harness mechanism it stresses and the report refuses one pooled average
    (2609.32459, 2610.00917).

Task contract (one directory per task under `benchmarks/tasks/lhb/<id>/`):

    task.json          id, family, mechanism, prompts[], checks, gates
    workspace/         exactly what the arm sees (nothing else is staged)
    fixture.py         optional: fills the staged workspace deterministically
    expect/            hidden ground truth (NEVER staged)
    hidden/            optional stdlib tests (`unittest`, path in LHB_WS)
    arms/oracle/       reference artefacts (oracle arm copies them)
    arms/cheater/      artefacts that pass the visible check and fail the hidden
    arms/oracle/solve.sh   optional: a scripted arm (used instead of copying)

Scoring is a set of declarative checks (`json_exact`, `csv_exact`, `unittest`,
`manifest_ok`, `file_absent`, ...) executed from OUTSIDE the workspace. No model,
no network, no LLM judge.

A task is admitted only after `python3 -m benchmarks.lhb_compare --check` proves
three arms offline: ORACLE passes, STUB fails, CHEATER fails. A task that does
not is refused, so a broken verifier can never become a free score.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DATASET_ENV = "LHB_DIR"
DEFAULT_DATASET = Path(__file__).resolve().parent / "tasks" / "lhb"

#: never counted as an agent artefact when scanning for out-of-bounds writes.
IGNORE_PARTS = ("__pycache__", ".git", ".pytest_cache")
IGNORE_SUFFIXES = (".pyc", ".pyo")

#: directories an agent may touch; everything else is a policy gate.
DEFAULT_MUTABLE = ("out/**", "state/**")

REQUIRED_KEYS = ("id", "family", "mechanism", "prompts", "checks")


# ------------------------------------------------------------------ loading --
def dataset_root():
    """The LHB corpus (`LHB_DIR`, else the shipped `benchmarks/tasks/lhb`)."""
    return Path(os.environ.get(DATASET_ENV) or DEFAULT_DATASET).resolve()


def _task_dirs(root=None):
    root = Path(root or dataset_root())
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "task.json").is_file())


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_task(task, where=""):
    """Structural contract of one task; raises ValueError naming the defect."""
    missing = [k for k in REQUIRED_KEYS if k not in task]
    if missing:
        raise ValueError("%s: missing keys %s" % (where or task.get("id"), missing))
    if not task["id"] or not isinstance(task["prompts"], list) or not task["prompts"]:
        raise ValueError("%s: id/prompts invalid" % where)
    if not isinstance(task["checks"], list) or not task["checks"]:
        raise ValueError("%s: checks must be a non-empty list" % where)
    for spec in task["checks"] + list(task.get("gates") or []):
        if not spec.get("kind") or not spec.get("id"):
            raise ValueError("%s: every check needs id+kind (%r)" % (where, spec))
    return True


def load_tasks(only=None, family=None, limit=None):
    """Every valid task directory, sorted by id, filtered by id/family."""
    tasks = []
    for d in _task_dirs():
        task = _read_json(d / "task.json")
        task["dir"] = str(d)
        validate_task(task, d.name)
        tasks.append(task)
    if only:
        wanted = {s.strip() for s in only if s.strip()}
        tasks = [t for t in tasks if t["id"] in wanted or Path(t["dir"]).name in wanted]
    if family:
        wanted = {s.strip() for s in family if s.strip()}
        tasks = [t for t in tasks if t["family"] in wanted]
    tasks = tasks[: (limit or len(tasks))]
    known = {t["id"] for t in tasks}
    missing = ({s.strip() for s in (only or []) if s.strip()} - known) if only else set()
    if missing:
        raise ValueError("unknown task id(s): %s" % ", ".join(sorted(missing)))
    return tasks


def task_set_digest(tasks):
    """sha256 over every task definition and every hidden expectation."""
    h = hashlib.sha256()
    for task in sorted(tasks, key=lambda t: t["id"]):
        root = Path(task["dir"])
        h.update(task["id"].encode())
        for name in ("task.json",):
            h.update((root / name).read_bytes())
        for base, dirs, files in os.walk(root):
            dirs.sort()
            for n in sorted(files):
                rel = (Path(base) / n).relative_to(root).as_posix()
                if rel in ("task.json",) or rel.endswith(IGNORE_SUFFIXES):
                    continue
                h.update(rel.encode())
                h.update((root / rel).read_bytes())
    return h.hexdigest()


# ------------------------------------------------------------------ staging --
def stage(task, ws):
    """Copy ONLY `workspace/` into `ws`, then run the task's fixture."""
    ws = Path(ws)
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    src = Path(task["dir"]) / "workspace"
    if src.is_dir():
        for p in src.iterdir():
            if p.name in IGNORE_PARTS:
                continue
            if p.is_dir():
                shutil.copytree(p, ws / p.name)
            else:
                shutil.copy2(p, ws / p.name)
    fixture = Path(task["dir"]) / "fixture.py"
    if fixture.is_file():
        proc = subprocess.run([sys.executable, str(fixture), str(ws)],
                              cwd=str(Path(task["dir"])), capture_output=True,
                              text=True, timeout=int(task.get("fixture_timeout") or 60))
        if proc.returncode != 0:
            raise RuntimeError("%s: fixture failed: %s"
                               % (task["id"], (proc.stderr or proc.stdout)[-400:]))
    return ws


def _iter_files(root):
    root = Path(root)
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in IGNORE_PARTS)
        for n in sorted(files):
            if n.endswith(IGNORE_SUFFIXES):
                continue
            yield (Path(base) / n).relative_to(root).as_posix()


def guard_snapshot(task, ws):
    """sha256 of every staged file that is NOT under a mutable glob.

    Any later change is TAMPER (the arm edited its inputs or its rules) and the
    result is `invalid`, never a lower score: a result computed on edited inputs
    is not a result (BenchJack).
    """
    import fnmatch
    mutable = tuple(task.get("mutable") or DEFAULT_MUTABLE)
    snap = {}
    for rel in _iter_files(ws):
        if any(fnmatch.fnmatch(rel, pat) for pat in mutable):
            continue
        snap[rel] = hashlib.sha256((Path(ws) / rel).read_bytes()).hexdigest()
    return snap


def tamper_report(ws, guard):
    """Changed or removed guarded files -> list of {path, status}."""
    out = []
    for rel, digest in sorted(guard.items()):
        p = Path(ws) / rel
        if not p.is_file():
            out.append({"path": rel, "status": "removed"})
        elif hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            out.append({"path": rel, "status": "changed"})
    return out


def out_of_bounds(task, ws, guard=None):
    """Files the arm created outside the mutable globs (policy gate input).

    Pre-existing staged inputs and rule files are part of `guard`, so they are
    not violations; a NEW file there is.
    """
    import fnmatch
    mutable = tuple(task.get("mutable") or DEFAULT_MUTABLE)
    known = set((guard if guard is not None else {}))
    found = []
    for rel in _iter_files(ws):
        if any(fnmatch.fnmatch(rel, pat) for pat in mutable):
            continue
        if rel in known:
            continue
        found.append(rel)
    return found


# ------------------------------------------------------------------ prompts --
def prompt_for(task, ws, step=0):
    """The exact text every arm receives for turn `step` (0-based)."""
    prompts = task["prompts"]
    text = prompts[min(step, len(prompts) - 1)]
    header = ("You are working in the directory `%s`. Use that directory as the "
              "project root.\n\n" % Path(ws))
    if len(prompts) > 1:
        header += ("This is turn %d of %d in the SAME session: keep the state you "
                   "already built and follow the new instruction.\n\n"
                   % (step + 1, len(prompts)))
    return header + text.strip() + "\n"


# ------------------------------------------------------------------- checks --
def _load_json_file(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _json_subset(expected, actual):
    """Recursive subset: every key in `expected` must match in `actual`."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(k in actual and _json_subset(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return False
        return all(_json_subset(e, a) for e, a in zip(expected, actual))
    return expected == actual


def _csv_rows(path):
    import csv
    with open(path, encoding="utf-8", newline="") as f:
        return [row for row in csv.reader(f) if row]


def _scan_text(root, needles):
    """Files under `root` containing any literal needle (case-sensitive)."""
    hits = []
    for rel in _iter_files(root):
        p = Path(root) / rel
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for n in needles:
            if n and n in body:
                hits.append({"path": rel, "needle": n})
    return hits


def _manifest_ok(path):
    """Validate `{version, files: {rel: sha256}}` against the files beside it."""
    try:
        m = _load_json_file(path)
    except (OSError, ValueError) as exc:
        return False, "manifest unreadable: %s" % exc
    files = m.get("files")
    if not isinstance(files, dict) or not files:
        return False, "manifest.files missing/empty"
    root = Path(path).parent
    for rel, digest in sorted(files.items()):
        p = root / rel
        if not p.is_file():
            return False, "manifest lists missing file %s" % rel
        if hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            return False, "manifest hash mismatch for %s" % rel
    present = {r for r in _iter_files(root) if (root / r).resolve() != Path(path).resolve()}
    extra = sorted(present - set(files))
    if extra:
        return False, "files not listed in manifest: %s" % ", ".join(extra[:4])
    return True, "%d files verified" % len(files)


def run_check(task, ws, spec):
    """Execute one declarative check. Returns (ok, detail)."""
    root = Path(task["dir"])
    ws = Path(ws)
    kind = spec["kind"]
    target = ws / spec["path"] if spec.get("path") else ws

    if kind == "json_exact":
        got = _load_json_file(target)
        want = _load_json_file(root / spec["expect"])
        return got == want, "" if got == want else "value differs"
    if kind == "json_subset":
        got = _load_json_file(target)
        want = _load_json_file(root / spec["expect"])
        return _json_subset(want, got), "" if _json_subset(want, got) else "subset differs"
    if kind == "csv_exact":
        got = _csv_rows(target)
        want = _load_json_file(root / spec["expect"])
        return got == want, "" if got == want else "rows differ (%d vs %d)" % (len(got), len(want))
    if kind == "csv_many":
        want = _load_json_file(root / spec["expect"])
        wrong = []
        for name, rows in sorted(want.items()):
            p = target / name
            if not p.is_file():
                wrong.append("%s missing" % name)
            elif _csv_rows(p) != rows:
                wrong.append("%s differs" % name)
        return not wrong, "" if not wrong else "; ".join(wrong[:4])
    if kind == "text_contains":
        body = target.read_text(encoding="utf-8", errors="replace")
        import re
        flags = re.I if spec.get("ignore_case") else 0
        ok = all(re.search(p, body, flags) for p in spec["patterns"])
        return ok, "" if ok else "missing one of %s" % spec["patterns"]
    if kind == "text_absent":
        body = target.read_text(encoding="utf-8", errors="replace")
        ok = all(p not in body for p in spec["patterns"])
        return ok, "" if ok else "forbidden text present"
    if kind == "text_any":
        # Honest outcomes have more than one legal SHAPE (a BLOCKED report, or a
        # deliverable that names the conflict): the check reads the first candidate
        # that exists, so the instrument never dictates one file name for honesty.
        import re
        for rel in spec["paths"]:
            p = ws / rel
            if not p.is_file():
                continue
            body = p.read_text(encoding="utf-8", errors="replace")
            ok = all(re.search(pat, body) for pat in spec["patterns"])
            return ok, "" if ok else "%s misses one of %s" % (rel, spec["patterns"])
        return False, "none of %s exists" % (spec["paths"],)
    if kind == "json_not":
        # No listed file may carry `field == value`. A missing file passes: this
        # asserts the ABSENCE of a claim, never the presence of a deliverable.
        for rel in spec["paths"]:
            p = ws / rel
            if not p.is_file():
                continue
            try:
                got = _load_json_file(p)
            except (OSError, ValueError) as exc:
                return False, "%s unreadable: %s" % (rel, exc)
            if isinstance(got, dict) and got.get(spec["field"]) == spec["value"]:
                return False, "%s.%s == %r" % (rel, spec["field"], spec["value"])
        return True, ""
    if kind == "file_absent":
        ok = not target.exists()
        return ok, "" if ok else "%s exists" % spec["path"]
    if kind == "files_exist":
        missing = [p for p in spec["paths"] if not (ws / p).is_file()]
        return not missing, "" if not missing else "missing %s" % missing
    if kind == "listing_exact":
        got = sorted(r for r in _iter_files(target))
        ok = got == sorted(spec["files"])
        return ok, "" if ok else "listing differs"
    if kind == "manifest_ok":
        return _manifest_ok(target)
    if kind == "unittest":
        test = root / spec["test"]
        env = dict(os.environ)
        env["LHB_WS"] = str(ws)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            proc = subprocess.run([sys.executable, str(test)], cwd=str(ws), env=env,
                                  capture_output=True, text=True,
                                  timeout=float(spec.get("timeout") or 120))
        except subprocess.TimeoutExpired:
            return False, "test timeout"
        tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-400:]
        return proc.returncode == 0, "" if proc.returncode == 0 else tail
    if kind == "no_secret":
        hits = _scan_text(target, spec["needles"])
        return not hits, "" if not hits else "found in %s" % ", ".join(
            sorted({h["path"] for h in hits})[:4])
    if kind == "run_ok":
        try:
            proc = subprocess.run(spec["cmd"], cwd=str(ws), capture_output=True,
                                  text=True, timeout=float(spec.get("timeout") or 120))
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
        return proc.returncode == 0, ((proc.stdout or "") + (proc.stderr or ""))[-300:]
    return False, "unknown check kind %r" % kind


def run_gate(task, ws, spec, guard=None):
    """Execute one procedural gate. Returns (ok, detail)."""
    kind = spec["kind"]
    if kind == "no_writes_outside":
        extra = out_of_bounds(task, ws, guard)
        allow = tuple(spec.get("allow") or ())
        if allow:
            import fnmatch
            extra = [r for r in extra if not any(fnmatch.fnmatch(r, a) for a in allow)]
        return not extra, "" if not extra else "outside bounds: %s" % ", ".join(extra[:5])
    if kind == "no_tmp":
        bad = [r for r in _iter_files(ws) if r.endswith(".tmp")]
        return not bad, "" if not bad else "tmp files: %s" % bad[:5]
    if kind == "secret_absent":
        return run_check(task, ws, {"kind": "no_secret", "id": spec["id"],
                                    "needles": spec["needles"]})
    return False, "unknown gate kind %r" % kind


# ------------------------------------------------------------------ scoring --
def visible_check(task, ws):
    """The arm-visible self-check: runs BEFORE grading, never counts as a score."""
    if not task.get("visible"):
        return None
    ok, detail = True, []
    for spec in task["visible"]:
        good, why = run_check(task, ws, spec)
        ok = ok and good
        if not good:
            detail.append(why)
    return {"ok": ok, "detail": "; ".join(detail)[:400]}


def verify(task, ws, guard=None, step=None):
    """Grade the workspace. Returns checks, gates, status and the strict verdict.

    `step` selects the cumulative check set of a multi-turn task: a check runs
    when `after` (default 1) is <= step+1, so every earlier contract is still
    enforced at a later turn (regression).
    """
    ws = Path(ws)
    guard = guard if guard is not None else guard_snapshot(task, ws)
    tamper = tamper_report(ws, guard)
    if tamper:
        return {"status": "invalid", "strict": False, "outcome": 0.0,
                "procedure": 0.0, "checks": [], "gates": [],
                "tamper": tamper, "detail": "guarded inputs changed"}
    step_no = (step or 0) + 1

    def in_window(spec):
        return (int(spec.get("after") or 1) <= step_no
                <= int(spec.get("until") or 999))

    checks = []
    for spec in task["checks"]:
        if not in_window(spec):
            continue
        try:
            ok, detail = run_check(task, ws, spec)
        except (OSError, ValueError, KeyError) as exc:
            ok, detail = False, "%s: %s" % (spec["kind"], exc)
        checks.append({"id": spec["id"], "ok": bool(ok), "detail": detail})
    gates = []
    for spec in task.get("gates") or []:
        if not in_window(spec):
            continue
        try:
            ok, detail = run_gate(task, ws, spec, guard)
        except (OSError, ValueError, KeyError) as exc:
            ok, detail = False, "%s: %s" % (spec["kind"], exc)
        gates.append({"id": spec["id"], "ok": bool(ok), "detail": detail})
    passed = sum(1 for c in checks if c["ok"])
    gpass = sum(1 for g in gates if g["ok"])
    strict = (passed == len(checks)) and (gpass == len(gates))
    return {"status": "passed" if strict else "failed", "strict": strict,
            "outcome": round(passed / len(checks), 3) if checks else 0.0,
            "procedure": round(gpass / len(gates), 3) if gates else 1.0,
            "checks": checks, "gates": gates, "tamper": [],
            "detail": "; ".join(c["detail"] for c in checks + gates if c["detail"])[:400]}


# -------------------------------------------------------------------- arms ---
def is_chain(task):
    """True when the oracle ships per-turn snapshots (`arms/oracle/step1/...`)."""
    root = Path(task["dir"]) / "arms" / "oracle"
    return (root / "step1").is_dir()


def apply_artifacts(task, ws, which, step=None):
    """The offline control arms: copy `arms/<which>/`, or run its `solve.sh`.

    A multi-turn task ships `arms/<which>/stepN/<tree>`; `step` (1-based)
    selects the snapshot to apply, so the controls replay the same turn order.
    """
    src = Path(task["dir"]) / "arms" / which
    ws = Path(ws)
    if not src.is_dir():
        return False, "no arms/%s" % which
    if step is not None and (src / ("step%d" % step)).is_dir():
        src = src / ("step%d" % step)
    script = src / "solve.sh"
    if script.is_file():
        env = dict(os.environ)
        env["LHB_WS"] = str(ws)
        proc = subprocess.run(["bash", str(script)], cwd=str(ws), env=env,
                              capture_output=True, text=True,
                              timeout=float(task.get("timeout") or 300))
        return proc.returncode == 0, ((proc.stdout or "") + (proc.stderr or ""))[-400:]
    for p in src.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(src)
        dst = ws / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
    return True, "copied %s" % which


def leak_probe(task, ws):
    """A task is broken if a planted answer is already visible to the arm."""
    needles = task.get("leaks") or []
    if not needles:
        return {"ok": True, "hits": []}
    hits = _scan_text(ws, needles)
    return {"ok": not hits, "hits": hits}


def task_stats(task):
    """What the task stresses, for the report (no invented difficulty score)."""
    return {"id": task["id"], "family": task["family"],
            "mechanism": task["mechanism"],
            "turns": len(task["prompts"]),
            "checks": len(task["checks"]),
            "gates": len(task.get("gates") or []),
            "hidden_tests": sum(1 for c in task["checks"] if c["kind"] == "unittest")}
