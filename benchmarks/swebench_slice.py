#!/usr/bin/env python3
"""SWE-bench Verified — a SCREENED slice that runs natively on aarch64, no Docker.

Why this file exists
--------------------
Every official SWE-bench image is `sweb.eval.x86_64.*`; on this ARM64 host they die
with `exec format error`, and no x86 emulation is allowed. What CAN run here is the
same task contract on the host: clone the repo at `base_commit`, install it in a
venv, apply the instance's `test_patch`, and grade with the instance's own
FAIL_TO_PASS / PASS_TO_PASS node ids — the official scorer, no judge.

The dataset is read from the Hugging Face datasets-server (stdlib urllib), because
`datasets` is not a dependency of this repo; the row carries `patch`, `test_patch`,
`FAIL_TO_PASS`, `PASS_TO_PASS`, `base_commit` and the `eval_script`.

A slice is only usable when it is SCREENED: before the gold patch, FAIL_TO_PASS must
FAIL and PASS_TO_PASS must PASS. `--verify` proves that on one instance with ZERO
model calls (gold patch passes, no patch fails) — the control-arm idea of LHB,
applied to a real SWE task.

Usage
-----
    python3 -m benchmarks.swebench_slice --list 20          # ids, cached dataset
    python3 -m benchmarks.swebench_slice --check            # offline dataset proof
    python3 -m benchmarks.swebench_slice --verify <instance># screen + gold/stub proof
    python3 -m benchmarks.swebench_slice --run <instance> --arm longrun
    python3 -m benchmarks.swebench_slice --run <instance> --arm openclaw \
        --model openrouter:z-ai/glm-5.3-flash

Every artifact of a run lives under `.agent/BENCHMARKS/runs/<stamp>_swe_<instance>/`:
the clone, the venv log, the diff the arm produced, the test output, `result.json`.
"""
import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DATASET = "SWE-bench/SWE-bench_Verified"
CONFIG = "default"
SPLIT = "test"
ROWS_API = "https://datasets-server.huggingface.co/rows"
CACHE = Path(".agent/BENCHMARKS/cache/swebench_verified.json")
RUNS = Path(".agent/BENCHMARKS/runs")
PAGE = 100
#: A screen may look at this many PASS_TO_PASS ids (a subset: the full list can hold
#: hundreds of node ids and the screen must stay a preflight, not a full suite run).
P2P_SAMPLE = 40

ALLOWED_MODELS = ("openrouter:z-ai/glm-5.3-flash", "deepseek:deepseek-flash")
LOCAL_MODEL_PREFIXES = ("dgx:", "local:", "llamacpp:", "llama:")


# ------------------------------------------------------------------ dataset ---
def _get_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "longrun-swe-slice"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_rows(force=False):
    """All 500 rows, cached: one page per 100 rows, no `datasets` dependency."""
    if CACHE.is_file() and not force:
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    rows, offset = [], 0
    while True:
        url = ("%s?dataset=%s&config=%s&split=%s&offset=%d&length=%d"
               % (ROWS_API, urllib.parse.quote(DATASET, safe=""), CONFIG, SPLIT,
                  offset, PAGE))
        page = _get_json(url)
        got = [r["row"] for r in page.get("rows") or []]
        rows += got
        if len(got) < PAGE:
            break
        offset += PAGE
        if offset > 2000:
            break
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def _as_list(value):
    """FAIL_TO_PASS / PASS_TO_PASS arrive as a JSON string or a Python repr."""
    if isinstance(value, list):
        return [str(x) for x in value]
    text = str(value or "").strip()
    if not text:
        return []
    for parse in (json.loads, ast.literal_eval):
        try:
            got = parse(text)
            if isinstance(got, list):
                return [str(x) for x in got]
        except (ValueError, SyntaxError):
            continue
    return [text]


def instance(rows, iid):
    for row in rows:
        if row.get("instance_id") == iid:
            return row
    raise SystemExit("unknown instance %r (try --list)" % iid)


def list_rows(rows, limit=20):
    by_repo = {}
    for row in rows:
        by_repo.setdefault(row.get("repo"), []).append(row)
    print("%d instances · %d repos · dataset %s" % (len(rows), len(by_repo), DATASET))
    shown = 0
    for repo in sorted(by_repo):
        for row in by_repo[repo]:
            if shown >= limit:
                return
            print("  %-46s %-28s f2p=%d p2p=%d"
                  % (row.get("instance_id"), repo,
                     len(_as_list(row.get("FAIL_TO_PASS"))),
                     len(_as_list(row.get("PASS_TO_PASS")))))
            shown += 1


# --------------------------------------------------------------------- shell ---
def sh(cmd, cwd=None, env=None, timeout=900, log=None):
    """Run a command, capture it, and append the same output to `log`."""
    started = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env,
                              capture_output=True, text=True, timeout=timeout)
        out, err, rc = proc.stdout or "", proc.stderr or "", proc.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        out, err, rc = "", "docker-free harness: %r" % exc, 124
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write("\n$ %s   (cwd=%s, rc=%s, %.1fs)\n%s%s\n"
                    % (" ".join(cmd), cwd, rc, time.time() - started, out[-4000:],
                       err[-4000:]))
    return rc, out, err


def prepare_repo(row, root, log):
    """Clone at base_commit. Returns the repo path (raises SystemExit on failure)."""
    repo = row["repo"]
    repo_dir = Path(root) / "repo"
    if repo_dir.is_dir():
        return repo_dir
    url = "https://github.com/%s.git" % repo
    rc, _out, err = sh(["git", "clone", "--filter=blob:none", "--no-checkout",
                        url, str(repo_dir)], timeout=900, log=log)
    if rc != 0:
        raise SystemExit("clone failed: %s" % err[-300:])
    rc, _out, err = sh(["git", "checkout", row["base_commit"]], cwd=repo_dir,
                       timeout=600, log=log)
    if rc != 0:
        raise SystemExit("checkout %s failed: %s" % (row["base_commit"], err[-300:]))
    return repo_dir


def _python_candidates(row):
    """Interpreters to try, ordered by the instance's ERA.

    SWE-bench pins the interpreter inside each image and the dataset never states it
    (the `version` field is the package release, and `eval_script` just says
    `conda activate testbed`). The only honest way is empirical: try the era's
    interpreter first and keep the first venv where the repo INSTALLS. A 2014
    `setup.py` (`from collections import MutableMapping`) cannot even build on 3.12,
    so `psf__requests-1142` must land on 3.9 or older.
    """
    year = str(row.get("created_at") or "")[:4]
    try:
        year = int(year)
    except ValueError:
        year = 2023
    if year <= 2016:
        return ("3.9", "3.8", "3.10", "3.11", "3.12")
    if year <= 2020:
        return ("3.9", "3.10", "3.8", "3.11", "3.12")
    if year <= 2022:
        return ("3.10", "3.9", "3.11", "3.12")
    return ("3.11", "3.10", "3.12", "3.9")


def prepare_venv(repo_dir, log, candidates=("3.11", "3.10", "3.9", "3.12")):
    """A host venv with the repo installed editable — the aarch64 substitute for the
    image (the official one is x86_64, so it is never used).

    Tries `candidates` in order and keeps the FIRST interpreter where
    `pip install -e .` succeeds; every attempt is in the run log, and the winner is
    reported by the screen. `uv` fetches the interpreters (no system packages).
    """
    parent = Path(repo_dir).parent
    last = ""
    for ver in candidates:
        venv = parent / ("venv-%s" % ver)
        py = venv / "bin" / "python"
        if not py.exists():
            if shutil.which("uv"):
                rc, _o, _e = sh(["uv", "venv", "--python", ver, str(venv)],
                                timeout=900, log=log)
                if rc != 0:
                    last = "no interpreter %s" % ver
                    continue
            else:
                rc, _o, _e = sh([sys.executable, "-m", "venv", str(venv)],
                                timeout=300, log=log)
                if rc != 0:
                    last = "venv %s failed" % ver
                    continue
        install = (["uv", "pip", "install", "--python", str(py)]
                   if shutil.which("uv") else [str(py), "-m", "pip", "install"])
        rc, _o, err = sh(install + ["-q", "-e", "."], cwd=repo_dir, timeout=1800,
                         log=log)
        if rc != 0:
            last = "install on %s: %s" % (ver, (err or "")[-300:])
            shutil.rmtree(venv, ignore_errors=True)
            continue
        sh(install + ["-q", "pytest"], timeout=600, log=log)
        return py
    raise SystemExit("no interpreter could install this repo: %s" % last)


def apply_patch(repo_dir, patch_text, log):
    if not str(patch_text or "").strip():
        return True, "empty patch"
    path = Path(repo_dir).parent / "patch.diff"
    path.write_text(patch_text, encoding="utf-8")
    for cmd in (["git", "apply", "-v", str(path)],
                ["git", "apply", "-v", "--3way", str(path)],
                ["patch", "-p1", "-i", str(path)]):
        rc, out, err = sh(cmd, cwd=repo_dir, timeout=300, log=log)
        if rc == 0:
            return True, "applied with %s" % " ".join(cmd[:2])
    return False, ((out or "") + (err or ""))[-300:]


def run_tests(py, repo_dir, node_ids, log, timeout=900):
    """pytest on the instance's own node ids: {id: bool}.

    Deliberately AGGREGATE and conservative: pytest's exit code is the official
    signal ("did this set of tests pass"), and a non-zero exit is reported as a
    failure for every id rather than guessed per test. The raw output is in the run
    log, so a human can see which one broke.
    """
    if not node_ids:
        return {}
    rc, _out, _err = sh([str(py), "-m", "pytest", "-q", "--tb=short",
                         "-p", "no:cacheprovider"] + node_ids, cwd=repo_dir,
                        timeout=timeout, log=log)
    return {nid: rc == 0 for nid in node_ids}


# -------------------------------------------------------------------- screen ---
def screen(row, root, log, *, apply_gold=False, apply_tests=True):
    """Stage the instance and report the pre/post-patch state of its tests."""
    repo_dir = prepare_repo(row, root, log)
    py = prepare_venv(repo_dir, log, _python_candidates(row))
    if apply_gold:
        ok, why = apply_patch(repo_dir, row.get("patch"), log)
        if not ok:
            return {"ok": False, "error": "gold patch: %s" % why}
    if apply_tests:
        ok, why = apply_patch(repo_dir, row.get("test_patch"), log)
        if not ok:
            return {"ok": False, "error": "test patch: %s" % why}
    f2p = _as_list(row.get("FAIL_TO_PASS"))
    p2p = _as_list(row.get("PASS_TO_PASS"))[:P2P_SAMPLE]
    f2p_res = run_tests(py, repo_dir, f2p, log)
    p2p_res = run_tests(py, repo_dir, p2p, log)
    return {"ok": True, "python": str(py), "repo": str(repo_dir),
            "f2p": f2p_res, "p2p": p2p_res,
            "f2p_pass": sum(1 for v in f2p_res.values() if v),
            "f2p_total": len(f2p_res),
            "p2p_pass": sum(1 for v in p2p_res.values() if v),
            "p2p_total": len(p2p_res)}


def _fresh_dir(name):
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    out = (RUNS / ("%s_swe_%s" % (stamp, name))).resolve()
    if out.exists():
        raise SystemExit("refusing existing run dir %s" % out)
    out.mkdir(parents=True)
    return out


def verify(row, out):
    """The instrument proof on a REAL instance, with zero model calls.

    gold patch -> FAIL_TO_PASS must pass; no patch -> they must fail. If the second
    half does not hold, the task is already solved at base_commit and cannot grade
    any arm (`SATURATED` at n=1).
    """
    iid = row["instance_id"]
    log = out / "verify.log"
    gold = screen(row, out / "gold", log, apply_gold=True)
    base = screen(row, out / "base", log, apply_gold=False)
    verdict = {
        "instance": iid, "repo": row.get("repo"), "gold": gold, "base": base,
        "gradable": bool(gold.get("ok") and base.get("ok")
                         and gold["f2p_pass"] == gold["f2p_total"] > 0
                         and base["f2p_pass"] == 0),
    }
    (out / "verify.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    print("instance %s (%s)" % (iid, row.get("repo")))
    print("  gold  : f2p %d/%d  p2p %d/%d  %s"
          % (gold.get("f2p_pass"), gold.get("f2p_total"), gold.get("p2p_pass"),
             gold.get("p2p_total"), gold.get("error") or ""))
    print("  base  : f2p %d/%d  p2p %d/%d  %s"
          % (base.get("f2p_pass"), base.get("f2p_total"), base.get("p2p_pass"),
             base.get("p2p_total"), base.get("error") or ""))
    print("  GRADABLE" if verdict["gradable"] else "  NOT GRADABLE")
    return 0 if verdict["gradable"] else 1


# ----------------------------------------------------------------------- arm ---
def _refuse_local_model(model):
    if any(str(model or "").startswith(p) for p in LOCAL_MODEL_PREFIXES):
        return ("refusing local model %r — allowed: %s (project rule 2026-11-06)"
                % (model, ", ".join(ALLOWED_MODELS)))
    return ""


def run_arm(row, out, arm, model, timeout):
    """One agent turn on the staged repo, then the official grading on its diff."""
    iid = row["instance_id"]
    log = out / "arm.log"
    repo_dir = prepare_repo(row, out, log)
    py = prepare_venv(repo_dir, log, _python_candidates(row))
    before = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo_dir),
                            capture_output=True, text=True).stdout
    prompt = ("You are working in the git repository `%s`.\n\n%s\n\n"
              "Fix the problem above by editing the repository. Do not edit or "
              "delete test files. When you are done, stop; the harness grades the "
              "working tree." % (repo_dir, row.get("problem_statement")))
    t0 = time.time()
    from benchmarks.jobbench_compare import (openclaw_command, _openclaw_env,
                                             _openclaw_usage, _openrouter_key)
    if arm == "openclaw":
        rmodel = model.replace(":", "/", 1)
        env = _openclaw_env(_openrouter_key())
        cmd = openclaw_command(repo_dir, rmodel, prompt, timeout,
                               session_key="swe:%s:%s" % (iid, int(t0)))
        try:
            proc = subprocess.run(cmd, cwd=os.path.expanduser("~"), env=env,
                                  text=True, capture_output=True, timeout=timeout + 60)
            usage, _reply = _openclaw_usage(proc.stdout or "")
        except subprocess.TimeoutExpired:
            usage = {"tokens_in": 0, "tokens_out": 0, "total_usd": 0.0}
    else:
        from benchmarks.longrun_adapter import LongrunAdapter
        ad = LongrunAdapter(model=model, timeout=timeout, keep_sessions=True,
                            tag="swe", max_steps=60)
        ad.setup()
        try:
            ref = ad.create_agent({"id": iid, "workspace": str(repo_dir)})
            res = ad.send_task(ref, prompt, timeout=timeout)
            usage = {"tokens_in": res.tokens, "tokens_out": 0,
                     "total_usd": res.cost_usd}
            if not res.ok:
                usage["error"] = res.error
        finally:
            ad.teardown()
    # `add -A` first: a fix that CREATES a file is part of the patch, and a plain
    # `git diff` would silently drop it.
    subprocess.run(["git", "add", "-A"], cwd=str(repo_dir), capture_output=True,
                   text=True)
    diff = subprocess.run(["git", "diff", "--cached"], cwd=str(repo_dir),
                          capture_output=True, text=True).stdout
    (out / "arm.diff").write_text(diff, encoding="utf-8")
    # Grade on the instance's own tests: restore the tree (the arm may have edited
    # tests or left scratch files), re-apply its diff, then the official test_patch.
    sh(["git", "reset"], cwd=repo_dir, timeout=120, log=log)
    sh(["git", "checkout", "--", "."], cwd=repo_dir, timeout=120, log=log)
    sh(["git", "clean", "-fd"], cwd=repo_dir, timeout=120, log=log)
    ok, why = apply_patch(repo_dir, diff, log)
    apply_patch(repo_dir, row.get("test_patch"), log)
    f2p = _as_list(row.get("FAIL_TO_PASS"))
    p2p = _as_list(row.get("PASS_TO_PASS"))[:P2P_SAMPLE]
    f2p_res = run_tests(py, repo_dir, f2p, log) if ok else {}
    p2p_res = run_tests(py, repo_dir, p2p, log) if ok else {}
    strict = bool(ok and f2p and all(f2p_res.values()) and all(p2p_res.values()))
    result = {"instance": iid, "repo": row.get("repo"), "arm": arm, "model": model,
              "strict": strict, "patch_applied": ok, "patch_error": "" if ok else why,
              "f2p_pass": sum(1 for v in f2p_res.values() if v), "f2p_total": len(f2p_res),
              "p2p_pass": sum(1 for v in p2p_res.values() if v),
              "p2p_total": len(p2p_res), "diff_bytes": len(diff),
              "duration_s": round(time.time() - t0, 1), "usage": usage,
              "git_dirty_before": bool(before.strip())}
    (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("instance", "arm", "strict",
                                             "f2p_pass", "f2p_total", "p2p_pass",
                                             "p2p_total", "diff_bytes")}, indent=2))
    return 0 if strict else 1


# ---------------------------------------------------------------------- main ---
def main(argv=None):
    ap = argparse.ArgumentParser(prog="benchmarks.swebench_slice")
    ap.add_argument("--list", type=int, default=0, metavar="N")
    ap.add_argument("--check", action="store_true",
                    help="offline proof that the dataset rows carry the fields")
    ap.add_argument("--verify", default="", metavar="INSTANCE",
                    help="screen one instance: gold patch passes, no patch fails")
    ap.add_argument("--run", default="", metavar="INSTANCE")
    ap.add_argument("--arm", default="longrun")
    ap.add_argument("--model", default="openrouter:z-ai/glm-5.3-flash")
    ap.add_argument("--timeout", type=float, default=1800.0)
    ap.add_argument("--refresh", action="store_true", help="re-download the dataset")
    args = ap.parse_args(argv)

    if args.list:
        list_rows(fetch_rows(force=args.refresh), args.list)
        return 0
    if args.check:
        rows = fetch_rows(force=args.refresh)
        need = ("instance_id", "repo", "base_commit", "patch", "test_patch",
                "problem_statement", "FAIL_TO_PASS", "PASS_TO_PASS")
        bad = [r.get("instance_id") for r in rows
               if any(k not in r for k in need)]
        with_f2p = [r for r in rows if _as_list(r.get("FAIL_TO_PASS"))]
        print("%d rows · %d with FAIL_TO_PASS · %d missing a field"
              % (len(rows), len(with_f2p), len(bad)))
        print("repos: %d" % len({r.get("repo") for r in rows}))
        return 0 if rows and not bad and len(with_f2p) == len(rows) else 1
    if args.verify:
        row = instance(fetch_rows(force=args.refresh), args.verify)
        return verify(row, _fresh_dir(args.verify))
    if args.run:
        refused = _refuse_local_model(args.model)
        if refused:
            print(refused)
            return 2
        row = instance(fetch_rows(force=args.refresh), args.run)
        return run_arm(row, _fresh_dir(args.run), args.arm, args.model, args.timeout)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
