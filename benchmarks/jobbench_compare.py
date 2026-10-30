#!/usr/bin/env python3
"""JobBench: measure Longrun and Harness² on the SAME official tasks and judge.

    python3 -m benchmarks.jobbench_compare \\
        --profession biostatisticians --tasks 2 \\
        --arms longrun,harness2 \\
        --model openrouter:z-ai/glm-5.3-flash \\
        --judge-model z-ai/glm-5.3-flash \\
        --judge-base https://openrouter.ai/api/v1 \\
        --out .agent/BENCHMARKS/runs/2026-10-30_jobbench_glm53flash

Parity is the point, so it is explicit in the report:

* the same task corpus (`benchmarks.jobbench`), the same instruction text, the same
  `output/` convention;
* the same solver weights — Longrun takes `provider:model`, Harness²/OpenCode takes
  `provider/model`, the judge takes the bare id: one model, three spellings;
* the same judge process (`benchmarks.jobbench_judge`, the upstream `eval/judge.py`)
  with the same judge model, whichever arm produced the files.

Two honest asymmetries, recorded in every report: Longrun is driven over HTTP
(`POST /api/chat`), Harness² has no task endpoint and is driven through its own CLI
sweep; and Harness² runs its substrate (OpenCode) as the agent loop, which is the
thing being measured, not a setup detail.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import jobbench
from . import jobbench_judge as JJ
from .bare_adapter import _env_file_key, _key

DEFAULT_HARNESS2 = Path(os.environ.get("HARNESS2_REPO",
                                       "/home/jagones/Repositories/Harness2")).expanduser()

SUITE = "jobbench"
#: Where runs live by default. The repo ships no results; `.agent/` is local only.
RUNS_ROOT = Path(os.environ.get("BENCH_RUNS_DIR")
                 or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 ".agent", "BENCHMARKS", "runs")).expanduser()


def _slug(task_id):
    return re.sub(r"[^A-Za-z0-9_.-]+", "__", task_id)


def _model_slug(model):
    return re.sub(r"[^A-Za-z0-9.]+", "-", str(model or "model")).strip("-")


def default_out(arms, model, n_tasks, scope=""):
    """The canonical folder for a run — one naming rule, collision-safe.

    `<date>_<suite>_<model-slug>_<arms>_<scope>_n<N>`, with `-2`, `-3` appended when
    the same combination is run twice, so a run folder is always self-describing
    (what, with what, on which tasks) and never silently overwrites another one.
    """
    slug = "%s_%s_%s_%s%s_n%d" % (time.strftime("%Y-%m-%d"), SUITE, _model_slug(model),
                                  "-".join(arms),
                                  ("_" + _model_slug(scope)) if scope else "",
                                  int(n_tasks))
    path, i = RUNS_ROOT / slug, 2
    while path.exists():
        path = RUNS_ROOT / ("%s-%d" % (slug, i))
        i += 1
    return path


def select_tasks(all_tasks, only=None, limit=None):
    """The tasks a run actually uses — a re-run is named, never positional.

    `only` is a list of task ids or their bare suffixes (`task2`); a re-run must
    target the task that failed, not "the first N" again. `limit` keeps its
    meaning only when nothing is named (`--tasks 3`).
    """
    tasks = list(all_tasks or [])
    only = [o for o in (only or []) if o]
    if only:
        return [t for t in tasks
                if t.get("id") in only
                or any(str(t.get("id", "")).endswith("/" + o) for o in only)]
    return tasks if limit is None else tasks[:max(0, int(limit))]


def write_manifest(out, **fields):
    """Merge `fields` into `<out>/run.json` (one manifest per run, never a guess)."""
    path = Path(out) / "run.json"
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    data.update(fields)
    _write(path, data)
    return data


def rebuild_index(root=None):
    """`runs/INDEX.md`, derived from every `run.json` (the manifest is the truth)."""
    root = Path(root or RUNS_ROOT)
    rows = []
    if root.is_dir():
        for d in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
            f = d / "run.json"
            if not f.is_file():
                continue
            try:
                rows.append(json.loads(f.read_text(encoding="utf-8")))
            except ValueError:
                continue
    # Newest first by the manifest's own `started`: the folder name is not
    # chronological (`_n3` sorts before `_n1-2` lexically), and an index whose
    # first row is not the latest run is a misleading index.
    rows.sort(key=lambda r: str(r.get("started") or ""), reverse=True)
    lines = ["# Benchmark runs", "",
             "Derived from each run's `run.json` — do not edit by hand.", "",
             "| run | started | suite | arms | solver | judge | n | status | mean ratio |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        means = r.get("arms_summary") or {}
        mr = ", ".join("%s %s" % (k, v.get("mean_ratio"))
                       for k, v in sorted(means.items())) or "-"
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                     % (r.get("run_id", "?"), str(r.get("started", ""))[:16],
                        r.get("suite", ""), ",".join(r.get("arms") or []),
                        r.get("model", ""), r.get("judge_model", ""),
                        r.get("n_tasks", ""), r.get("status", ""), mr))
    text = "\n".join(lines) + "\n"
    root.mkdir(parents=True, exist_ok=True)
    (root / "INDEX.md").write_text(text, encoding="utf-8")
    return text


def _write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _openrouter_key():
    """The judge/solver key: process env first, then the DGX dotenv files."""
    return (_key(["OPENROUTER_API_KEY"])
            or _env_file_key(["OPENROUTER_API_KEY"], "~/.hermes/.env")
            or _env_file_key(["OPENROUTER_API_KEY"], ".env"))


# --------------------------------------------------------------- longrun arm
def run_longrun(tasks, out, *, model, judge_model, judge_base, key, timeout,
                judge_timeout, keep_sessions=False, max_steps=None):
    """Drive the LIVE Longrun over REST, one session per task, then judge."""
    from .longrun_adapter import LongrunAdapter
    arm = Path(out) / "longrun"
    arm.mkdir(parents=True, exist_ok=True)
    ad = LongrunAdapter(model=model, timeout=timeout, keep_sessions=keep_sessions,
                        tag="jobbench", max_steps=max_steps)
    rows, prov = [], {}
    try:
        prov = ad.provenance()
        ad.setup()
        for task in tasks:
            slug = _slug(task["id"])
            ws = arm / slug / "workspace"
            jobbench.stage(task, ws)
            t0 = time.time()
            ref = ad.create_agent({"id": task["id"], "workspace": str(ws)})
            res = ad.send_task(ref, jobbench.prompt_for(task, ws), timeout=timeout)
            files = jobbench.deliverables(ws)
            sc = JJ.score_run(task, ws, arm / slug / "judge.json", judge_model,
                              judge_base, key, evaluated_model="longrun-%s" % slug,
                              timeout=judge_timeout)
            row = {"task": task["id"], "arm": "longrun", "ok": bool(res.ok),
                   "error": res.error or "", "delivered": len(files),
                   "files": files[:40], "duration_s": round(time.time() - t0, 1),
                   "model": model, "score": sc,
                   # The reply is the only evidence of WHY a turn delivered nothing:
                   # keep its head and length, and the ids needed to open the session.
                   "reply": (res.output or "")[:1200],
                   "reply_len": len(res.output or ""),
                   "run_id": res.run_id, "session": ref.session,
                   "max_steps": max_steps,
                   "workspace_error": (ref.meta or {}).get("error", "")}
            _write(arm / slug / "result.json", row)
            rows.append(row)
            ad.delete_agent(ref)
            print("  longrun %-42s delivered=%d score=%s"
                  % (task["id"], len(files),
                     "%s/%s" % (sc.get("score"), sc.get("max")) if sc.get("ok") else sc.get("error")),
                  flush=True)
    finally:
        try:
            ad.teardown()
        except Exception:  # noqa: BLE001 — never leave the server half-configured
            pass
    return rows, prov


# -------------------------------------------------------------- harness2 arm
def harness2_command(tasks, solver_model, extra=""):
    """The official sweep command for the same tasks (Harness² has no HTTP API)."""
    prof = tasks[0]["profession"] if tasks else ""
    py = DEFAULT_HARNESS2 / ".venv" / "bin" / "python"
    cmd = [str(py), "-m", "harness2.cli.run_sweep", "--bench", "jb", "--substrate", "oc",
           "--k", "1", "--split", "all", "--modes", "parallel",
           "--only-domains", prof, "--max-tasks", str(len(tasks))]
    return cmd + ([extra] if extra else [])


def run_harness2(tasks, out, *, solver_model, judge_model, judge_base, key,
                 timeout, judge_timeout, dry_run=False):
    """Run Harness²'s own sweep, then grade ITS `model_output/` with the same judge."""
    arm = Path(out) / "harness2"
    arm.mkdir(parents=True, exist_ok=True)
    cmd = harness2_command(tasks, solver_model)
    env = dict(os.environ)
    env.update({"HARNESS2_SOLVER_MODEL": solver_model,
                "HARNESS2_IMPROVER_MODEL": solver_model,
                "HARNESS2_JUDGE_MODEL": judge_model,
                "HARNESS2_JUDGE_BASE_URL": judge_base,
                "HARNESS2_JUDGE_API_KEY": key})
    meta = {"command": cmd, "env_model": solver_model, "cwd": str(DEFAULT_HARNESS2),
            "status": "dry-run" if dry_run else ""}
    if dry_run:
        _write(arm / "command.json", meta)
        print("  harness2 (dry-run): %s" % " ".join(cmd), flush=True)
        return [], meta
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=str(DEFAULT_HARNESS2), env=env, text=True,
                           capture_output=True, timeout=timeout)
        meta.update({"returncode": r.returncode, "stderr_tail": (r.stderr or "")[-1200:],
                     "stdout_tail": (r.stdout or "")[-1200:],
                     "duration_s": round(time.time() - t0, 1)})
    except (OSError, subprocess.SubprocessError) as e:
        meta.update({"error": str(e), "duration_s": round(time.time() - t0, 1)})
        _write(arm / "command.json", meta)
        print("  harness2 FAILED to start: %s" % e, flush=True)
        return [], meta
    meta["status"] = "ok" if r.returncode == 0 else "failed"
    _write(arm / "command.json", meta)
    # Grade whatever IT produced: `<runs>/jb/dataset/<prof>/<task>/model_output/<label>`.
    rows = []
    for task in tasks:
        prof, name = task["id"].split("/", 1)
        base = DEFAULT_HARNESS2 / "runs" / "jb" / "dataset" / prof / name / "model_output"
        labels = sorted((p for p in base.iterdir() if p.is_dir()),
                        key=lambda p: p.stat().st_mtime, reverse=True) if base.is_dir() else []
        if not labels:
            rows.append({"task": task["id"], "arm": "harness2", "ok": False,
                         "error": "no model_output under %s" % base, "score": None})
            continue
        run_dir = labels[0]
        slug = _slug(task["id"])
        sc = JJ.judge(run_dir, task["rubrics"], arm / slug / "judge.json", judge_model,
                      judge_base, key, evaluated_model="harness2-%s" % run_dir.name,
                      timeout=judge_timeout)
        files = jobbench.deliverables(run_dir)
        row = {"task": task["id"], "arm": "harness2", "ok": bool(sc.get("ok")),
               "error": sc.get("error") or "", "delivered": len(files),
               "label": run_dir.name, "model": solver_model, "score": sc}
        _write(arm / slug / "result.json", row)
        rows.append(row)
        print("  harness2 %-41s delivered=%d score=%s"
              % (task["id"], len(files),
                 "%s/%s" % (sc.get("score"), sc.get("max")) if sc.get("ok") else sc.get("error")),
              flush=True)
    return rows, meta


# ------------------------------------------------------------------- report
def report(out, rows, parity):
    """`compare.json` + `compare.md`: per-task numbers and the parity block."""
    def _ratio(r):
        sc = r.get("score") or {}
        try:
            return float(sc["score"]) / float(sc["max"]) if sc.get("max") else None
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return None

    arms = {}
    for r in rows:
        a = arms.setdefault(r["arm"], {"tasks": 0, "delivered": 0, "scored": 0,
                                       "ratio_sum": 0.0, "ratio_n": 0})
        a["tasks"] += 1
        a["delivered"] += 1 if r.get("delivered") else 0
        rt = _ratio(r)
        if rt is not None:
            a["scored"] += 1
            a["ratio_sum"] += rt
            a["ratio_n"] += 1
    summary = {}
    for name, a in arms.items():
        summary[name] = {"tasks": a["tasks"], "delivered": a["delivered"],
                         "scored": a["scored"],
                         "mean_ratio": round(a["ratio_sum"] / a["ratio_n"], 4)
                         if a["ratio_n"] else None}
    payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "parity": parity,
               "arms": summary, "rows": rows}
    _write(Path(out) / "compare.json", payload)

    lines = ["# JobBench — Longrun vs Harness²", "",
             "| parity | value |", "|---|---|"]
    for k, v in sorted(parity.items()):
        lines.append("| %s | `%s` |" % (k, v))
    lines += ["", "| task | arm | delivered | score | max | ratio | note |",
              "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (x["task"], x["arm"])):
        sc = r.get("score") or {}
        rt = _ratio(r)
        note = sc.get("error") or r.get("error") or ""
        lines.append("| %s | %s | %s | %s | %s | %s | %s |"
                     % (r["task"], r["arm"], r.get("delivered", 0),
                        sc.get("score", "-"), sc.get("max", "-"),
                        ("%.3f" % rt) if rt is not None else "-",
                        str(note)[:60].replace("|", "/")))
    lines += ["", "| arm | tasks | delivered | scored | mean ratio |", "|---|---|---|---|---|"]
    for name, s in sorted(summary.items()):
        lines.append("| %s | %s | %s | %s | %s |"
                     % (name, s["tasks"], s["delivered"], s["scored"], s["mean_ratio"]))
    text = "\n".join(lines) + "\n"
    (Path(out) / "compare.md").write_text(text, encoding="utf-8")
    return payload, text


def main(argv=None):
    ap = argparse.ArgumentParser(prog="benchmarks.jobbench_compare")
    ap.add_argument("--profession", default="", help="JobBench profession folder")
    ap.add_argument("--tasks", type=int, default=1, help="task cap")
    ap.add_argument("--arms", default="longrun", help="comma list: longrun,harness2")
    ap.add_argument("--model", default="openrouter:z-ai/glm-5.3-flash",
                    help="solver model, Longrun spelling (provider:model)")
    ap.add_argument("--harness2-model", default="",
                    help="solver model, OpenCode spelling (provider/model); "
                         "derived from --model when empty")
    ap.add_argument("--judge-model", default="z-ai/glm-5.3-flash")
    ap.add_argument("--judge-base", default="https://openrouter.ai/api/v1")
    ap.add_argument("--judge-key-env", default="OPENROUTER_API_KEY")
    ap.add_argument("--out", default=None,
                    help="run folder; default: <runs>/<date>_jobbench_<model>_<arms>_n<N>")
    ap.add_argument("--rebuild-index", action="store_true",
                    help="only rebuild <runs>/INDEX.md from the existing run.json files")
    ap.add_argument("--timeout", type=float, default=2400.0, help="per-task solver timeout")
    ap.add_argument("--judge-timeout", type=float, default=3600.0)
    ap.add_argument("--keep-sessions", action="store_true")
    ap.add_argument("--max-steps", type=int, default=40,
                    help="real-tool steps per turn for the Longrun arm (server clamps "
                         "it to its iteration cap); the chat default is 8")
    ap.add_argument("--only-task", default="",
                    help="comma list of task ids or suffixes to re-run (e.g. task2); "
                         "the Longrun arm only — Harness² sweeps by domain")
    ap.add_argument("--harness2-dry-run", action="store_true",
                    help="print Harness²'s command without spending anything")
    args = ap.parse_args(argv)

    if args.rebuild_index:
        print(rebuild_index())
        return 0

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    only = [t.strip() for t in args.only_task.split(",") if t.strip()]
    if only and "harness2" in arms:
        print("--only-task is the Longrun arm only: Harness² sweeps a whole domain")
        return 2
    tasks = jobbench.tasks(args.profession, None if only else args.tasks)
    tasks = select_tasks(tasks, only, None if only else args.tasks)
    if not tasks:
        print("no JobBench task matched profession=%r" % args.profession)
        return 2
    out = Path(args.out) if args.out else default_out(arms, args.model, len(tasks),
                                                      scope=args.profession or "all")
    os.makedirs(out, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    write_manifest(out, run_id=out.name, suite=SUITE, started=started,
                   status="running", arms=arms, model=args.model,
                   judge_model=args.judge_model, judge_base=args.judge_base,
                   n_tasks=len(tasks), tasks=[t["id"] for t in tasks],
                   corpus=str(jobbench.repo()), argv=sys.argv[1:])
    print("run: %s" % out, flush=True)
    key = (_key([args.judge_key_env]) or _env_file_key([args.judge_key_env], "~/.hermes/.env")
           or _env_file_key([args.judge_key_env], ".env"))
    if not key:
        write_manifest(out, status="failed", error="no %s" % args.judge_key_env,
                       finished=time.strftime("%Y-%m-%dT%H:%M:%S"))
        print("no %s found (env, ~/.hermes/.env, ./.env)" % args.judge_key_env)
        return 2
    h2_model = args.harness2_model or args.model.replace(":", "/", 1)
    parity = {"corpus": str(jobbench.repo()), "tasks": ",".join(t["id"] for t in tasks),
              "solver_longrun": args.model, "solver_harness2": h2_model,
              "judge_model": args.judge_model, "judge_base": args.judge_base,
              "prompt": "upstream Harness2 PROMPT (verbatim)",
              "longrun_transport": "HTTP POST /api/chat",
              "longrun_max_steps": args.max_steps,
              "harness2_transport": "CLI sweep (harness2 run_sweep --bench jb)"}

    rows = []
    for arm in arms:
        if arm == "longrun":
            got, prov = run_longrun(tasks, out, model=args.model,
                                    judge_model=args.judge_model, judge_base=args.judge_base,
                                    key=key, timeout=args.timeout,
                                    judge_timeout=args.judge_timeout,
                                    keep_sessions=args.keep_sessions,
                                    max_steps=args.max_steps)
            parity.update({"longrun_git": prov.get("git_sha", ""),
                           "longrun_version": prov.get("version", ""),
                           "longrun_token_source": prov.get("token_source", "")})
            rows += got
        elif arm == "harness2":
            got, meta = run_harness2(tasks, out, solver_model=h2_model,
                                     judge_model=args.judge_model,
                                     judge_base=args.judge_base, key=key,
                                     timeout=max(args.timeout * len(tasks), 3600),
                                     judge_timeout=args.judge_timeout,
                                     dry_run=args.harness2_dry_run)
            parity.update({"harness2_status": meta.get("status", ""),
                           "harness2_cmd": " ".join(meta.get("command") or [])})
            rows += got
        else:
            write_manifest(out, status="failed", error="unknown arm %r" % arm,
                           finished=time.strftime("%Y-%m-%dT%H:%M:%S"))
            print("unknown arm %r" % arm)
            return 2

    payload, text = report(out, rows, parity)
    ok = all((r.get("score") or {}).get("ok") for r in rows) and bool(rows)
    write_manifest(out, status=("ok" if ok else "incomplete"),
                   finished=time.strftime("%Y-%m-%dT%H:%M:%S"),
                   arms_summary=payload.get("arms") or {},
                   results=[{"task": r["task"], "arm": r["arm"],
                             "score": (r.get("score") or {}).get("score"),
                             "max": (r.get("score") or {}).get("max"),
                             "delivered": r.get("delivered", 0),
                             "note": (r.get("score") or {}).get("error") or r.get("error") or ""}
                            for r in rows],
                   compare_md="compare.md")
    rebuild_index()
    print("\n" + text)
    print("-> %s/compare.md" % out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
