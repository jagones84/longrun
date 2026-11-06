#!/usr/bin/env python3
"""Run LHB — Longrun Harness Bench — across harness arms.

    # 0. prove the suite offline (no model, no network, no container)
    python3 -m benchmarks.lhb_compare --check

    # 1. one model, the floor and this harness
    python3 -m benchmarks.lhb_compare --arms raw,longrun \
        --model openrouter:z-ai/glm-5.3-flash --repeat 3

    # 2. a peer harness as a second arm
    python3 -m benchmarks.lhb_compare --arms raw,longrun,openclaw \
        --model openrouter:z-ai/glm-5.3-flash

Offline control arms (also used by `--check`): `oracle` (reference artefacts),
`stub` (does nothing), `cheater` (passes the visible self-check, fails hidden).
They cost nothing and prove the verifier can both pass and fail.

Reporting rules taken from the eval literature (sources in
`.agent/docs/research/2026-11-06_lhb-design/`):

  * no pooled average across families — instruments differ (WorkBuddy 2607.20911);
  * `strict` (every hidden check AND every gate) is the headline, `outcome` is a
    partial-credit column, `validation_gap` is reported separately (SpecBench);
  * n=1 ranks nothing: `--repeat k` prints pass@1 and pass^k, and a run where
    every arm passes every task is reported as SATURATED, never as a tie;
  * a task that never ran is a failure in the denominator, never dropped;
  * cost and duration are columns, read from the arm's own ledger.
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

from benchmarks import lhb                                             # noqa: E402
from benchmarks.jobbench_compare import (                              # noqa: E402
    DEFAULT_HARNESS2, _h2_env, _kill_tree, _oc_usage, _openclaw_env,
    _openclaw_usage, _openrouter_key, _slug, _write, bare_model_id,
    openclaw_command, opencode_command,
)

OFFLINE_ARMS = ("oracle", "stub", "cheater")
DEFAULT_ARMS = "raw,longrun"
#: A benchmark result must be reproducible on a model other people can call. The
#: local DGX router is a development convenience, not a benchmark backend: a 25B
#: local loop measures itself, not the harness (project rule, 2026-11-06).
LOCAL_MODEL_PREFIXES = ("dgx:", "local:", "llamacpp:", "llama:")
ALLOWED_MODELS = ("openrouter:z-ai/glm-5.3-flash", "deepseek:deepseek-flash")


def _refuse_local_model(model):
    """A one-line refusal for a local model ref, else ''."""
    text = str(model or "")
    if any(text.startswith(p) for p in LOCAL_MODEL_PREFIXES):
        return ("refusing local model %r — allowed: %s (project rule 2026-11-06)"
                % (text, ", ".join(ALLOWED_MODELS)))
    return ""


def _timeout(task, args):
    return float(task.get("timeout") or args.timeout)


def _task_result(task, arm, ws, guard, args, t0=0.0, res=None, step_scores=None,
                 step=None, session=""):
    """Grade one finished arm turn (or chain) and build its row.

    `step` is the LAST turn index: a chain is judged on its final state, where
    every earlier contract is still enforced (the `until` window retires the
    intermediate version checks only).
    """
    ver = lhb.verify(task, ws, guard, step=step)
    vis = lhb.visible_check(task, ws)
    row = {"task": task["id"], "family": task["family"], "arm": arm,
           "status": ver["status"], "strict": bool(ver["strict"]),
           "outcome": ver["outcome"], "procedure": ver["procedure"],
           "visible": (None if vis is None else bool(vis["ok"])),
           "validation_gap": bool(vis and vis["ok"] and not ver["strict"]),
           "checks": ver["checks"], "gates": ver["gates"], "tamper": ver["tamper"],
           "detail": ver["detail"],
           "duration_s": round(time.time() - t0, 1) if t0 else 0.0,
           "steps": step_scores or []}
    if res is not None:
        row.update({"ok": bool(res.ok), "tokens": int(getattr(res, "tokens", 0) or 0),
                    "cost_usd": float(getattr(res, "cost_usd", 0.0) or 0.0),
                    "session": session or getattr(res, "session", "") or "",
                    "error": getattr(res, "error", "") or ""})
    row["turn_timeout"] = bool(
        "timed out" in str(row.get("error") or "").lower()
        or any(s.get("status") == "timeout" for s in row["steps"]))
    return row


# ------------------------------------------------------------ offline arms ---
def _run_offline(arm, tasks, out, args):
    rows = []
    for task in tasks:
        ws = Path(out) / arm / _slug(task["id"]) / "r1" / "workspace"
        lhb.stage(task, ws)
        guard = lhb.guard_snapshot(task, ws)
        steps = []
        if arm != "stub":
            if lhb.is_chain(task):
                for i in range(len(task["prompts"])):
                    ok, detail = lhb.apply_artifacts(task, ws, arm, step=i + 1)
                    if not ok:
                        break
                    partial = lhb.verify(task, ws, guard, step=i)
                    steps.append({"step": i + 1, "strict": bool(partial["strict"]),
                                  "outcome": partial["outcome"],
                                  "status": partial["status"]})
            else:
                ok, detail = lhb.apply_artifacts(task, ws, arm)
                if not ok:
                    rows.append({"task": task["id"], "family": task["family"], "arm": arm,
                                 "status": "error", "strict": False, "outcome": 0.0,
                                 "procedure": 0.0, "detail": detail})
                    continue
        row = _task_result(task, arm, ws, guard, args, step_scores=steps,
                           step=(len(task["prompts"]) - 1) if steps else None)
        _write(Path(out) / arm / _slug(task["id"]) / "result.json", row)
        rows.append(row)
        print("  %-9s %-24s %-7s outcome=%.2f" % (arm, task["id"], row["status"],
                                                 row["outcome"]), flush=True)
    return rows, {"model": None, "transport": "scripted (no model)"}


# ---------------------------------------------------------------- real arms ---
def _run_longrun(tasks, out, args):
    from benchmarks.longrun_adapter import LongrunAdapter
    ad = LongrunAdapter(model=args.model, timeout=args.timeout,
                        keep_sessions=args.keep_sessions,
                        tag=args.tag or "lhb", max_steps=args.max_steps)
    rows = []
    ad.setup()
    try:
        for task in tasks:
            for rep in range(1, args.repeat + 1):
                ws = Path(out) / "longrun" / _slug(task["id"]) / ("r%d" % rep) / "workspace"
                lhb.stage(task, ws)
                guard = lhb.guard_snapshot(task, ws)
                ref = ad.create_agent({"id": task["id"], "workspace": str(ws)})
                t0 = time.time()
                steps, res, last = [], None, None
                for i in range(len(task["prompts"])):
                    try:
                        last = ad.send_task(ref, lhb.prompt_for(task, ws, i),
                                            timeout=_timeout(task, args))
                    except Exception as exc:  # noqa: BLE001 — a timeout is a result
                        from benchmarks.protocol import HarnessResult
                        last = HarnessResult(ok=False,
                                             error="transport: %s" % str(exc)[:300],
                                             duration_s=round(time.time() - t0, 1))
                        steps.append({"step": i + 1, "strict": False, "outcome": 0.0,
                                      "status": "timeout"})
                        break
                    partial = lhb.verify(task, ws, guard, step=i)
                    steps.append({"step": i + 1, "strict": bool(partial["strict"]),
                                  "outcome": partial["outcome"],
                                  "status": partial["status"]})
                    if not last.ok:
                        break
                row = _task_result(task, "longrun", ws, guard, args, t0=t0, res=last,
                                   step_scores=steps,
                                   step=(len(task["prompts"]) - 1) if steps else None,
                                   session=getattr(ref, "session", ""))
                row["rep"] = rep
                _write(Path(out) / "longrun" / _slug(task["id"]) / ("r%d" % rep)
                       / "result.json", row)
                rows.append(row)
                print("  %-9s %-24s r%d %-7s outcome=%.2f (%.0fs)"
                      % ("longrun", task["id"], rep, row["status"], row["outcome"],
                         row["duration_s"]), flush=True)
                ad.delete_agent(ref)
    finally:
        ad.teardown()
    return rows, ad.provenance()


def _run_raw(tasks, out, args):
    """The no-harness floor: one chat call. It cannot write files, so any strict
    pass here would mean the verifier is broken — the `--check` control exists for
    exactly that."""
    from benchmarks.bare_adapter import BareAdapter
    ad = BareAdapter(base=args.judge_base, api_key=args.key,
                     model=bare_model_id(args.model), timeout=args.timeout)
    rows = []
    for task in tasks:
        for rep in range(1, args.repeat + 1):
            ws = Path(out) / "raw" / _slug(task["id"]) / ("r%d" % rep) / "workspace"
            lhb.stage(task, ws)
            guard = lhb.guard_snapshot(task, ws)
            t0 = time.time()
            res = None
            for i in range(len(task["prompts"])):
                res = ad.send_task(None, lhb.prompt_for(task, ws, i),
                                   timeout=_timeout(task, args))
            row = _task_result(task, "raw", ws, guard, args, t0=t0, res=res)
            row["rep"] = rep
            _write(Path(out) / "raw" / _slug(task["id"]) / ("r%d" % rep)
                   / "result.json", row)
            rows.append(row)
            print("  %-9s %-24s r%d %-7s outcome=%.2f"
                  % ("raw", task["id"], rep, row["status"], row["outcome"]), flush=True)
    return rows, ad.provenance()


def _run_cli(arm, tasks, out, args, cmd_fn, env_fn, usage_fn):
    """Drive a CLI harness (openclaw / opencode) turn by turn.

    THREE rules this loop exists to honour (each was a silent zero before):

    * A multi-turn task must keep ONE session: the chain tasks re-check turn 1's
      contract at turn 3, so a fresh key per turn would measure three unrelated
      agents. The key is per task+repeat, never per step.
    * The usage envelope `--json` returns is the ONLY cost evidence a CLI arm
      leaves; it is summed into the row, otherwise the arm reports 0 tokens / $0
      next to a harness that logs every call (a free-looking arm is a broken arm).
    * A failed `communicate` must not read `err_s` from a variable that was never
      bound — that `UnboundLocalError` killed the whole run after the first
      timeout.
    """
    rows = []
    run_tag = Path(out).name
    for task in tasks:
        for rep in range(1, args.repeat + 1):
            slug = _slug(task["id"]) + ("__r%d" % rep)
            ws = Path(out) / arm / slug / "workspace"
            lhb.stage(task, ws)
            guard = lhb.guard_snapshot(task, ws)
            model = args.model.replace(":", "/", 1)
            session_key = ("lhb:%s:%s:r%d" % (run_tag, task["id"], rep)) \
                if arm == "openclaw" else ""
            steps, t0 = [], time.time()
            tokens = 0
            cost = 0.0
            tool_calls = 0
            err_tail = ""
            for i in range(len(task["prompts"])):
                prompt = lhb.prompt_for(task, ws, i)
                if arm == "openclaw":
                    cmd = openclaw_command(ws, model, prompt, _timeout(task, args),
                                           session_key=session_key)
                else:
                    cmd = cmd_fn(ws, model, prompt)
                try:
                    proc = subprocess.Popen(cmd, cwd=str(DEFAULT_HARNESS2),
                                            env=env_fn(args.key), text=True,
                                            stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            start_new_session=True)
                    out_s, err_s = proc.communicate(timeout=_timeout(task, args))
                    err_tail = (err_s or "")[-300:]
                except subprocess.TimeoutExpired:
                    _kill_tree(proc)
                    steps.append({"step": i + 1, "strict": False, "outcome": 0.0,
                                  "status": "timeout"})
                    break
                except OSError as exc:
                    steps.append({"step": i + 1, "strict": False, "outcome": 0.0,
                                  "status": "error", "detail": str(exc)[:200]})
                    break
                usage, _reply = usage_fn(out_s)
                tokens += int(usage.get("tokens_in") or 0) + int(usage.get("tokens_out") or 0)
                cost += float(usage.get("total_usd") or 0.0)
                tool_calls += int(usage.get("tool_calls") or 0)
                partial = lhb.verify(task, ws, guard, step=i)
                steps.append({"step": i + 1, "strict": bool(partial["strict"]),
                              "outcome": partial["outcome"],
                              "status": partial["status"], "usage": usage})
            ver = lhb.verify(task, ws, guard, step=len(task["prompts"]) - 1)
            vis = lhb.visible_check(task, ws)
            row = {"task": task["id"], "family": task["family"], "arm": arm,
                   "status": ver["status"], "strict": bool(ver["strict"]),
                   "outcome": ver["outcome"], "procedure": ver["procedure"],
                   "visible": (None if vis is None else bool(vis["ok"])),
                   "validation_gap": bool(vis and vis["ok"] and not ver["strict"]),
                   "checks": ver["checks"], "gates": ver["gates"],
                   "tamper": ver["tamper"], "detail": ver["detail"],
                   "duration_s": round(time.time() - t0, 1), "steps": steps,
                   "tokens": tokens, "cost_usd": round(cost, 6),
                   "tool_calls": tool_calls, "session_key": session_key,
                   "rep": rep, "stderr_tail": err_tail}
            _write(Path(out) / arm / slug / "result.json", row)
            rows.append(row)
            print("  %-9s %-24s r%d %-7s outcome=%.2f (%.0fs, %d tok)"
                  % (arm, task["id"], rep, row["status"], row["outcome"],
                     row["duration_s"], tokens), flush=True)
    return rows, {"model": args.model, "transport": arm, "cwd": str(DEFAULT_HARNESS2)}


# ------------------------------------------------------------------ reports --
def _aggregate(rows, arms):
    """Per arm: strict passes, outcome, procedure, gap, cost, duration, pass^k."""
    by = {}
    for r in rows:
        rec = by.setdefault(r["arm"], {"n": 0, "strict": 0, "outcome": 0.0,
                                       "procedure": 0.0, "visible": 0, "gap": 0,
                                       "invalid": 0, "tokens": 0, "usd": 0.0,
                                       "duration_s": 0.0, "timeouts": 0, "runs": {}})
        rec["n"] += 1
        rec["timeouts"] += 1 if r.get("turn_timeout") else 0
        rec["strict"] += 1 if r.get("strict") else 0
        rec["outcome"] += float(r.get("outcome") or 0.0)
        rec["procedure"] += float(r.get("procedure") or 0.0)
        rec["visible"] += 1 if r.get("visible") else 0
        rec["gap"] += 1 if r.get("validation_gap") else 0
        rec["invalid"] += 1 if r.get("status") == "invalid" else 0
        rec["tokens"] += int(r.get("tokens") or 0)
        rec["usd"] += float(r.get("cost_usd") or 0.0)
        rec["duration_s"] += float(r.get("duration_s") or 0.0)
        rec["runs"].setdefault(r["task"], []).append(bool(r.get("strict")))
    for rec in by.values():
        rec["pass@1"] = round(rec["strict"] / rec["n"], 3) if rec["n"] else 0.0
        rec["outcome_mean"] = round(rec["outcome"] / rec["n"], 3) if rec["n"] else 0.0
        rec["procedure_mean"] = round(rec["procedure"] / rec["n"], 3) if rec["n"] else 0.0
        rec["pass^k"] = round(
            sum(1 for v in rec["runs"].values() if v and all(v)) / len(rec["runs"]), 3
        ) if rec["runs"] else 0.0
        rec["outcome_sum"] = round(rec.pop("outcome"), 3)
        rec["procedure_sum"] = round(rec.pop("procedure"), 3)
        rec["usd"] = round(rec["usd"], 4)
        rec["duration_s"] = round(rec["duration_s"], 1)
        del rec["runs"]
    return by


def _per_task(rows):
    per = {}
    for r in rows:
        per.setdefault(r["task"], {}).setdefault(r["arm"], []).append(r)
    return per


def _discrimination(per, arms):
    """Tasks whose strict verdict separates at least two arms."""
    full = {t: d for t, d in per.items() if len(d) == len(arms)}
    disc = [t for t, d in full.items()
            if len({all(x.get("strict") for x in d[a]) for a in arms}) > 1]
    return disc, len(full)


def _report(out, rows, parity, arms):
    agg = _aggregate(rows, arms)
    per = _per_task(rows)

    lines = ["| arm | strict | n | pass@1 | pass^k | outcome | procedure | invalid "
             "| turn timeouts | visible gap | time | usd |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for arm in sorted(agg):
        a = agg[arm]
        lines.append("| %s | %d | %d | %.3f | %.3f | %.3f | %.3f | %d | %d | %d | %ss | %s |"
                     % (arm, a["strict"], a["n"], a["pass@1"], a["pass^k"],
                        a["outcome_mean"], a["procedure_mean"], a["invalid"],
                        a["timeouts"], a["gap"],
                        a["duration_s"], ("$%.4f" % a["usd"]) if a["usd"] else "-"))

    families = sorted({r["family"] for r in rows})
    fam_lines = ["| family | " + " | ".join(sorted(agg)) + " |",
                 "|---|" + "---|" * len(agg)]
    for fam in families:
        cells = []
        for arm in sorted(agg):
            got = [r for r in rows if r["family"] == fam and r["arm"] == arm]
            cells.append("%d/%d" % (sum(1 for r in got if r["strict"]), len(got))
                         if got else "-")
        fam_lines.append("| %s | %s |" % (fam, " | ".join(cells)))

    task_lines = ["| task | family | mechanism | " + " | ".join(sorted(agg)) + " |",
                  "|---|---|---|" + "---|" * len(agg)]
    for task in sorted(per):
        d = per[task]
        first = next(iter(d.values()))[0]
        cells = []
        for arm in sorted(agg):
            got = d.get(arm) or []
            if not got:
                cells.append("-")
            elif all(x.get("strict") for x in got):
                cells.append("pass")
            elif any(x.get("status") == "invalid" for x in got):
                cells.append("INVALID")
            else:
                cells.append("fail %.2f" % (sum(x.get("outcome") or 0 for x in got)
                                            / len(got)))
        task_lines.append("| %s | %s | %s | %s |"
                          % (task, first["family"], task and
                             next((s["mechanism"] for s in parity.get("task_stats") or []
                                   if s["id"] == task), ""), " | ".join(cells)))

    disc, scored = _discrimination(per, arms)
    saturated = len(agg) >= 2 and bool(scored) and not disc
    degenerate = len(agg) >= 2 and all(a["strict"] == 0 for a in agg.values())
    if len(agg) < 2:
        verdict = ("**Single arm** — this run proves the instrument, not a ranking; "
                   "run at least `raw` and one harness to compare.")
    elif degenerate:
        verdict = ("**DEGENERATE — no arm passes any task.** The suite or the run is "
                   "broken; run `--check` before reading this table.")
    elif saturated:
        verdict = ("**SATURATED — every arm passes every task.** This set cannot rank "
                   "the arms; add tasks or keep the per-axis columns as the result.")
    else:
        verdict = ("Discriminating tasks: **%d/%d** (at least two arms disagree)."
                   % (len(disc), scored))

    md = ("# LHB — Longrun Harness Bench\n\n"
          "Deterministic, judge-free tasks over seven harness axes: delivery, state, "
          "policy, honesty, guard, recovery, context.\n\n"
          "model `%s` · tasks %d · repeats %d · arms %s · task-set `%s`\n"
          "infra: `%s` · tie band: differences below 1 task are not a ranking\n\n"
          "%s\n\n## Per family (strict passes)\n\n%s\n\n"
          "## Per task\n\n%s\n\n%s\n"
          % (parity.get("model"), parity.get("n_tasks"), parity.get("repeat"),
             ", ".join(sorted(agg)), parity.get("task_set", "")[:12],
             parity.get("infra", ""), "\n".join(lines),
             "\n".join(fam_lines), "\n".join(task_lines), verdict))
    (Path(out) / "compare.md").write_text(md, encoding="utf-8")
    _write(Path(out) / "run.json", {"parity": parity, "arms": agg,
                                    "saturated": saturated,
                                    "discriminating_tasks": len(disc),
                                    "generated": round(time.time(), 3)})
    print(md)
    if saturated:
        print("WARNING: saturated set — every arm passed every task.")
    return saturated


# -------------------------------------------------------------------- check --
def _offline_state(task, ws, which):
    """Stage, apply a control arm (replaying turns when the task is a chain)."""
    lhb.stage(task, ws)
    guard = lhb.guard_snapshot(task, ws)
    if which == "stub":
        return lhb.verify(task, ws, guard), True, ""
    if lhb.is_chain(task):
        last, ok, why = None, True, ""
        for i in range(len(task["prompts"])):
            ok, why = lhb.apply_artifacts(task, ws, which, step=i + 1)
            if not ok:
                break
            last = lhb.verify(task, ws, guard, step=i)
        return last or {"status": "error", "strict": False, "outcome": 0.0,
                        "detail": why}, ok, why
    ok, why = lhb.apply_artifacts(task, ws, which)
    return lhb.verify(task, ws, guard), ok, why


def check(tasks, timeout=180.0):
    """Offline proof of the instrument: ORACLE passes, STUB and CHEATER fail.

    Also refuses a task whose planted answers are visible in the staged tree
    (a gold leak makes every score above it meaningless).
    """
    bad = []
    tmp = Path(tempfile.mkdtemp(prefix="lhb-check-"))
    try:
        for task in tasks:
            ws = tmp / _slug(task["id"])
            lhb.stage(task, ws)
            leak = lhb.leak_probe(task, ws)
            orc, orc_ok, orc_why = _offline_state(task, ws, "oracle")
            stub, _stub_ok, _stub_why = _offline_state(task, ws, "stub")
            cheat, ch_ok, ch_why = _offline_state(task, ws, "cheater")
            vis = lhb.visible_check(task, ws)
            ok = (leak["ok"] and orc_ok and orc and orc["strict"]
                  and not (stub or {}).get("strict") and ch_ok
                  and not (cheat or {}).get("strict"))
            print("  %-24s oracle=%-6s stub=%-6s cheater=%-8s leak=%-5s %s"
                  % (task["id"], (orc or {}).get("status"), (stub or {}).get("status"),
                     (cheat or {}).get("status"),
                     "ok" if leak["ok"] else "LEAK", "OK" if ok else "BROKEN"),
                  flush=True)
            if not ok:
                why = []
                if not leak["ok"]:
                    why.append("leak: %s" % leak["hits"][:2])
                if not orc_ok or not (orc or {}).get("strict"):
                    why.append("oracle=%s %s" % ((orc or {}).get("status"),
                                                 (orc or {}).get("detail") or orc_why))
                if (stub or {}).get("strict"):
                    why.append("stub passed")
                if not ch_ok:
                    why.append("cheater arm missing: %s" % ch_why)
                elif (cheat or {}).get("strict"):
                    why.append("cheater passed")
                bad.append((task["id"], "; ".join(why)))
            elif vis is not None and not vis["ok"]:
                print("           note: cheater did not pass the visible check "
                      "(no validation gap measured)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d/%d tasks verified (oracle passes; stub and cheater fail)"
          % (len(tasks) - len(bad), len(tasks)))
    for tid, why in bad:
        print("  BROKEN %s :: %s" % (tid, why))
    return 0 if not bad else 1


# --------------------------------------------------------------------- main --
def main(argv=None):
    ap = argparse.ArgumentParser(prog="benchmarks.lhb_compare")
    ap.add_argument("--arms", default=DEFAULT_ARMS,
                    help="raw,longrun,openclaw,opencode,oracle,stub,cheater")
    ap.add_argument("--model", default="openrouter:z-ai/glm-5.3-flash")
    ap.add_argument("--judge-base", default="https://openrouter.ai/api/v1",
                    help="only the raw arm uses it: the model endpoint")
    ap.add_argument("--only", default="", help="comma list of task ids")
    ap.add_argument("--family", default="", help="comma list of families")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--repeat", type=int, default=1, help="runs per task per arm (pass^k)")
    ap.add_argument("--timeout", type=float, default=900.0, help="seconds per task")
    ap.add_argument("--max-steps", type=int, default=40)
    ap.add_argument("--out", default=None)
    ap.add_argument("--keep-sessions", action="store_true")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--check", action="store_true",
                    help="offline instrument proof (oracle/stub/cheater); no model")
    args = ap.parse_args(argv)

    only = [s.strip() for s in args.only.split(",") if s.strip()]
    fams = [s.strip() for s in args.family.split(",") if s.strip()]
    try:
        tasks = lhb.load_tasks(only=only, family=fams, limit=args.limit or None)
    except ValueError as exc:
        print("LHB: %s" % exc)
        return 2
    if not tasks:
        print("no tasks under %s" % lhb.dataset_root())
        return 2
    if args.check:
        return check(tasks)
    refused = _refuse_local_model(args.model)
    if refused:
        print("LHB: %s" % refused)
        return 2
    if args.repeat < 1:
        print("--repeat must be >= 1")
        return 2

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    unknown = [a for a in arms if a not in ("raw", "longrun", "openclaw", "opencode")
               + OFFLINE_ARMS]
    if unknown:
        print("unknown arm(s): %s" % ", ".join(unknown))
        return 2

    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    out = Path(args.out or (".agent/BENCHMARKS/runs/%s_lhb_%s_n%d_r%d"
                            % (stamp, _slug(args.model), len(tasks), args.repeat))).resolve()
    if out.exists() and any(out.iterdir()):
        # A reused folder overwrites the evidence of a finished run.
        print("refusing existing non-empty --out: %s" % out)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    args.key = _openrouter_key()

    infra = ("python %s · %s · %s" % (sys.version.split()[0], os.uname().machine
                                     if hasattr(os, "uname") else sys.platform,
                                     "offline tasks, no container"))
    parity = {"model": args.model, "n_tasks": len(tasks), "repeat": args.repeat,
              "tasks": [t["id"] for t in tasks],
              "task_set": lhb.task_set_digest(tasks),
              "task_stats": [lhb.task_stats(t) for t in tasks],
              "scoring": "declarative hidden checks + procedural gates; no judge",
              "infra": infra,
              "git": subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                    capture_output=True, text=True).stdout.strip(),
              "started": stamp}

    rows = []
    for arm in arms:
        if arm in OFFLINE_ARMS:
            got, _prov = _run_offline(arm, tasks, out, args)
        elif arm == "longrun":
            got, _prov = _run_longrun(tasks, out, args)
        elif arm == "raw":
            got, _prov = _run_raw(tasks, out, args)
        elif arm == "opencode":
            got, _prov = _run_cli("opencode", tasks, out, args, opencode_command,
                                  _h2_env, _oc_usage)
        else:
            got, _prov = _run_cli("openclaw", tasks, out, args, None,
                                  _openclaw_env, _openclaw_usage)
        rows += got
    _report(out, rows, parity, arms)
    print("wrote %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
