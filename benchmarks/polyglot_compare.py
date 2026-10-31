#!/usr/bin/env python3
"""Head-to-head harness comparison on the polyglot (Exercism) coding suite.

One command, one model, several harnesses, and a score that cannot drift: each
task is decided by `pytest` on the exercise's own test file (benchmarks/polyglot.py).
No LLM judge, no rubric, no ±12-point noise.

    python3 -m benchmarks.polyglot_compare \
        --arms longrun,openclaw,opencode --model openrouter:z-ai/glm-5.3-flash \
        --limit 10 --out .agent/BENCHMARKS/runs/2026-11-01_polyglot_py10

Before spending anything, prove the suite itself is sound (no model involved):

    python3 -m benchmarks.polyglot_compare --check

`--check` stages every task twice: once with the exercise's own exemplar (must
PASS) and once with the untouched stub (must FAIL). A task that does either the
other way round is a broken task, and the runner refuses it.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks import polyglot                                   # noqa: E402
from benchmarks.jobbench_compare import (                         # noqa: E402
    DEFAULT_HARNESS2, _h2_env, _kill_tree, _oc_usage, _openclaw_env,
    _openclaw_usage, _openrouter_key, _slug, _write, bare_model_id,
    openclaw_command, opencode_command,
)


# --------------------------------------------------------------- one task run
def _run_longrun(tasks, out, args):
    from benchmarks.longrun_adapter import LongrunAdapter
    ad = LongrunAdapter(model=args.model, timeout=args.timeout,
                        keep_sessions=args.keep_sessions,
                        tag=args.tag or "polyglot", max_steps=args.max_steps)
    rows = []
    ad.setup()
    try:
        for task in tasks:
            ws = Path(out) / "longrun" / _slug(task["id"]) / "workspace"
            polyglot.stage(task, ws)
            t0 = time.time()
            ref = ad.create_agent({"id": task["id"], "workspace": str(ws)})
            res = ad.send_task(ref, polyglot.prompt_for(task, ws), timeout=args.timeout)
            ver = polyglot.verify(task, ws)
            row = {"task": task["id"], "arm": "longrun", "ok": bool(res.ok),
                   "resolved": ver["resolved"], "status": ver["status"],
                   "detail": ver["detail"], "duration_s": round(time.time() - t0, 1),
                   "tokens": res.tokens, "session": getattr(ref, "session", ""),
                   "error": res.error}
            _write(Path(out) / "longrun" / _slug(task["id"]) / "result.json", row)
            rows.append(row)
            print("  longrun    %-30s %s (%ss)" % (task["id"], ver["status"],
                                                   row["duration_s"]), flush=True)
            ad.delete_agent(ref)
    finally:
        ad.teardown()
    return rows, ad.provenance()


def _run_cli(arm, tasks, out, args, cmd_fn, env_fn, usage_fn):
    rows = []
    for task in tasks:
        slug = _slug(task["id"])
        ws = Path(out) / arm / slug / "workspace"
        polyglot.stage(task, ws)
        prompt = polyglot.prompt_for(task, ws)
        cmd = cmd_fn(ws, args.model, prompt)
        t0 = time.time()
        timed_out = False
        try:
            proc = subprocess.Popen(cmd, cwd=str(DEFAULT_HARNESS2), env=env_fn(args.key),
                                    text=True, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    start_new_session=True)
            out_s, err_s = proc.communicate(timeout=args.timeout)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            timed_out, out_s, err_s, rc = True, "", "", -1
        except (OSError, subprocess.SubprocessError) as exc:
            _write(Path(out) / arm / slug / "command.json", {"command": ["<prompt>"],
                                                             "error": str(exc)})
            rows.append({"task": task["id"], "arm": arm, "ok": False, "resolved": False,
                         "status": "error", "detail": str(exc), "duration_s": 0.0})
            print("  %-10s %-30s START FAILED: %s" % (arm, task["id"], exc), flush=True)
            continue
        usage, _reply = usage_fn(out_s)
        ver = polyglot.verify(task, ws)
        row = {"task": task["id"], "arm": arm, "ok": rc == 0, "resolved": ver["resolved"],
               "status": ver["status"], "detail": ver["detail"],
               "duration_s": round(time.time() - t0, 1), "timed_out": timed_out,
               "usage": usage, "stderr_tail": (err_s or "")[-600:]}
        _write(Path(out) / arm / slug / "command.json",
               {"command": ["<prompt>" if i == 7 else c for i, c in enumerate(cmd)],
                "returncode": rc, "model": args.model})
        _write(Path(out) / arm / slug / "result.json", row)
        rows.append(row)
        print("  %-10s %-30s %s (%ss)" % (arm, task["id"], ver["status"],
                                          row["duration_s"]), flush=True)
    return rows, {"model": args.model, "transport": arm, "cwd": str(DEFAULT_HARNESS2)}


def _run_raw(tasks, out, args):
    """The no-harness floor: one chat call, no tools. It cannot edit files, so a
    `resolved` here would mean the verifier is broken — it stays 0 by design."""
    from benchmarks.bare_adapter import BareAdapter
    ad = BareAdapter(base=args.judge_base, api_key=args.key,
                     model=bare_model_id(args.model), timeout=args.timeout)
    rows = []
    for task in tasks:
        ws = Path(out) / "raw" / _slug(task["id"]) / "workspace"
        polyglot.stage(task, ws)
        res = ad.send_task(None, polyglot.prompt_for(task, ws), timeout=args.timeout)
        ver = polyglot.verify(task, ws)
        row = {"task": task["id"], "arm": "raw", "ok": bool(res.ok),
               "resolved": ver["resolved"], "status": ver["status"],
               "detail": ver["detail"], "duration_s": res.duration_s}
        _write(Path(out) / "raw" / _slug(task["id"]) / "result.json", row)
        rows.append(row)
        print("  raw        %-30s %s" % (task["id"], ver["status"]), flush=True)
    return rows, ad.provenance()


# ------------------------------------------------------------------- reports
def _report(out, rows, parity):
    by_arm = {}
    for r in rows:
        rec = by_arm.setdefault(r["arm"], {"n": 0, "resolved": 0, "invalid": 0,
                                           "duration_s": 0.0, "tokens": 0})
        rec["n"] += 1
        rec["resolved"] += 1 if r.get("resolved") else 0
        rec["invalid"] += 1 if r.get("status") == "tests_modified" else 0
        rec["duration_s"] = round(rec["duration_s"] + float(r.get("duration_s") or 0), 1)
        usage = r.get("usage") or {}
        rec["tokens"] += (int(usage.get("tokens_in") or 0)
                          + int(usage.get("tokens_out") or 0)
                          if usage else int(r.get("tokens") or 0))
    lines = ["| arm | resolved | n | pass@1 | tests_modified | time | tokens |",
             "|---|---|---|---|---|---|---|"]
    for arm, rec in sorted(by_arm.items()):
        lines.append("| %s | %d | %d | %.3f | %d | %ss | %d |"
                     % (arm, rec["resolved"], rec["n"],
                        (rec["resolved"] / rec["n"]) if rec["n"] else 0.0,
                        rec["invalid"], rec["duration_s"], rec["tokens"]))
    md = ("# Polyglot (Exercism, Python track) — harnesses on the same tasks\n\n"
          "Scored by each exercise's own `pytest` suite: deterministic, no judge.\n\n"
          "model `%s` · dataset `%s` @ `%s` · tasks %d · arms %s\n\n%s\n"
          % (parity.get("model"), parity.get("dataset"), parity.get("dataset_commit"),
             parity.get("n_tasks"), ", ".join(sorted(by_arm)), "\n".join(lines)))
    (Path(out) / "compare.md").write_text(md, encoding="utf-8")
    _write(Path(out) / "run.json", {"parity": parity, "arms": by_arm,
                                    "generated": round(time.time(), 3)})
    print(md)


# ---------------------------------------------------------------------- check
def _check(tasks, timeout=180.0):
    """No model: exemplar must PASS, the stub must FAIL. Refuses a broken task."""
    bad = []
    tmp = Path(tempfile.mkdtemp(prefix="polyglot-check-"))
    try:
        for task in tasks:
            ws = tmp / _slug(task["id"])
            polyglot.stage(task, ws)
            if not polyglot.reference_solution(task, ws):
                bad.append((task["id"], "no exemplar"))
                continue
            ref = polyglot.verify(task, ws, timeout=timeout)
            polyglot.stage(task, ws)
            stub = polyglot.verify(task, ws, timeout=timeout)
            ok = ref["resolved"] and not stub["resolved"] and stub["status"] != "tests_modified"
            print("  %-30s exemplar=%-6s stub=%-6s %s"
                  % (task["id"], ref["status"], stub["status"], "OK" if ok else "BROKEN"),
                  flush=True)
            if not ok:
                bad.append((task["id"], "exemplar=%s stub=%s"
                            % (ref["status"], stub["status"])))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d/%d tasks verified (exemplar passes, stub fails)" % (len(tasks) - len(bad), len(tasks)))
    for tid, why in bad:
        print("  BROKEN %s :: %s" % (tid, why))
    return 0 if not bad else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="benchmarks.polyglot_compare")
    ap.add_argument("--language", default="python", help="track to run (python is wired)")
    ap.add_argument("--limit", type=int, default=10, help="tasks from the track")
    ap.add_argument("--only", default="", help="comma list of exercise names/ids")
    ap.add_argument("--arms", default="longrun,openclaw,opencode")
    ap.add_argument("--model", default="openrouter:z-ai/glm-5.3-flash")
    ap.add_argument("--judge-base", default="https://openrouter.ai/api/v1",
                    help="only the raw arm uses it: the model endpoint")
    ap.add_argument("--timeout", type=float, default=600.0, help="seconds per task")
    ap.add_argument("--max-steps", type=int, default=40)
    ap.add_argument("--out", default=None)
    ap.add_argument("--keep-sessions", action="store_true")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--check", action="store_true",
                    help="verify the suite offline (exemplar passes, stub fails); no model calls")
    args = ap.parse_args(argv)

    only = [s.strip() for s in args.only.split(",") if s.strip()]
    tasks = polyglot.load_tasks(args.language, limit=None if args.check else args.limit,
                                only=only)
    if not tasks:
        print("no tasks: check %s (POLYGLOT_DIR)" % polyglot.dataset_root())
        return 2
    if args.check:
        return _check(tasks)

    args.key = _openrouter_key()
    out = Path(args.out or (".agent/BENCHMARKS/runs/2026-11-01_polyglot_%s_%d"
                            % (args.language, len(tasks))))
    out.mkdir(parents=True, exist_ok=True)
    parity = {"model": args.model, "dataset": str(polyglot.dataset_root()),
              "dataset_commit": polyglot.dataset_commit(),
              "language": args.language, "n_tasks": len(tasks),
              "tasks": [t["id"] for t in tasks],
              "scoring": "each exercise's own pytest suite; exit code only",
              "python": sys.version.split()[0],
              "git": subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                    capture_output=True, text=True).stdout.strip()}

    rows = []
    for arm in [a.strip() for a in args.arms.split(",") if a.strip()]:
        if arm == "longrun":
            got, _prov = _run_longrun(tasks, out, args)
        elif arm == "opencode":
            got, _prov = _run_cli("opencode", tasks, out, args, opencode_command,
                                  _h2_env, _oc_usage)
        elif arm == "openclaw":
            got, _prov = _run_cli(
                "openclaw", tasks, out, args,
                lambda ws, m, p: openclaw_command(ws, m, p, args.timeout),
                _openclaw_env, _openclaw_usage)
        elif arm == "raw":
            got, _prov = _run_raw(tasks, out, args)
        else:
            raise SystemExit("unknown arm %r (longrun|openclaw|opencode|raw)" % arm)
        rows += got
    _report(out, rows, parity)
    print("wrote %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
