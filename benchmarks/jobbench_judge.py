#!/usr/bin/env python3
"""The OFFICIAL JobBench judge, wrapped — never re-implemented.

`eval/judge.py` in the pinned upstream checkout grades a run's `output/` against
that task's `RUBRICS.json`, using any OpenAI-compatible endpoint
(`--api-base` / `JUDGE_API_KEY`, see the upstream docstring). Both arms are
graded by THIS process with the SAME judge model, so a score difference is a
harness difference and not a scorer difference.

Failure is `None`, never `0`: a judge that could not run is not evidence that the
agent produced nothing (the same rule the official adapter enforces).
"""
import json
import os
import subprocess
from pathlib import Path

from . import jobbench


def judge_python():
    """The interpreter the upstream judge needs (pandas/openpyxl/docx/openai)."""
    root = Path(os.environ.get("JOB_BENCH_REPO") or jobbench.DEFAULT_REPO).expanduser()
    return Path(os.environ.get("JOB_BENCH_JUDGE_PYTHON") or (root / ".venv" / "bin" / "python"))


def parse_details(got):
    """The official details payload -> the comparable numbers.

    Mirrors the upstream adapter: weighted `total_score/max_score` when present,
    a labelled unweighted fallback otherwise. A judge that reported nothing is
    `None`.
    """
    if not isinstance(got, dict):
        return None
    try:
        results = [r.get("result") or {} for r in got.get("rubrics") or []]
        n_c = sum(int(r.get("criteria_count") or 0) for r in results)
        n_p = sum(int(r.get("criteria_passed") or 0) for r in results)
        total = float(got.get("total_score") or 0)
        mx = float(got.get("max_score") or 0)
    except (TypeError, ValueError):
        return None
    judge_model = str(got.get("judge_model") or "")
    if not mx:
        if n_c <= 0:
            return None
        return {"ok": True, "score": float(n_p), "max": float(n_c),
                "criteria_passed": n_p, "criteria_count": n_c,
                "all_pass": n_p == n_c, "metric": "unweighted-fallback",
                "judge_model": judge_model}
    return {"ok": True, "score": total, "max": mx,
            "criteria_passed": n_p, "criteria_count": n_c,
            "all_pass": bool(n_c > 0 and n_p == n_c), "metric": "weighted",
            "judge_model": judge_model}


def judge(output_dir, rubrics, details_path, judge_model, api_base, api_key="",
          evaluated_model="", timeout=3600):
    """Grade one delivered `output/` directory. Returns the parsed score or None."""
    root = jobbench.repo()
    judge_py = root / "eval" / "judge.py"
    if not judge_py.is_file():
        return {"ok": False, "error": "upstream judge missing at %s" % judge_py}
    if not Path(rubrics).is_file():
        return {"ok": False, "error": "task rubrics missing at %s" % rubrics}
    py = judge_python()
    if not py.is_file():
        return {"ok": False, "error": "judge interpreter missing at %s "
                                      "(run the upstream setup_benchmark.py jb)" % py}
    details = Path(details_path)
    details.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(py), str(judge_py),
           "--output-dir", str(output_dir),
           "--rubrics-file", str(rubrics),
           "--details-file", str(details),
           "--judge-model", str(judge_model),
           "--api-base", str(api_base),
           "--evaluated-model", str(evaluated_model),
           "--max-workers", "8", "--max-retries", "3",
           "--timeout-per-rubric", "240"]
    env = dict(os.environ)
    if api_key:
        env["JUDGE_API_KEY"] = api_key          # argv stays clean
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": "judge could not run: %s" % e}
    if r.returncode != 0:
        return {"ok": False, "error": "judge exited %d: %s"
                                      % (r.returncode, (r.stderr or r.stdout)[-400:])}
    try:
        got = json.loads(details.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"ok": False, "error": "judge wrote no readable details: %s" % e}
    parsed = parse_details(got)
    if parsed is None:
        return {"ok": False, "error": "judge details carried no scores"}
    return parsed


def score_run(task, workspace, details_path, judge_model, api_base, api_key="",
              evaluated_model="", timeout=3600):
    """Score one arm's workspace: real zero when empty, official judge otherwise."""
    files = jobbench.deliverables(workspace)
    if not files:
        got = jobbench.no_output_score(task)
        return got if got is not None else {"ok": False,
                                            "error": "no deliverables and no rubric weights"}
    got = judge(Path(workspace) / "output", task["rubrics"], details_path,
                judge_model, api_base, api_key, evaluated_model=evaluated_model,
                timeout=timeout)
    if got.get("ok"):
        got["deliverables"] = len(files)
    return got
