#!/usr/bin/env python3
"""Head-to-head harness comparison, SAME model + SAME tasks (JAG-454).

Answers the question "how much is the harness worth?" the only fair way: run one
task file through several harness arms with the model held fixed, score with the
benchmark's OWN check, and emit a side-by-side artifact.

    python3 -m benchmarks.compare --tasks tasks.jsonl \
        --arms bare,longrun,hermes --model deepseek-reasoner --out out/cmp-001

Scoring is HumanEval-shaped (each task owns its `test`). Any delta between arms
on the same task id + model is the harness contribution; `bare` is the control
(the raw model API with no tools, no system prompt, no memory).

Nothing here re-implements an official scorer: for SWE-bench/GAIA the arms emit
predictions and the OFFICIAL runner scores them (see benchmarks/README.md).
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks import humaneval                        # noqa: E402
from benchmarks.runner import run_suite                 # noqa: E402


def _split_arm(spec):
    """`longrun:reasoner` -> ('longrun', 'reasoner') so TWO models can run as two
    arms of the SAME harness (model-vs-model, in parallel, inside one harness)."""
    if ":" in spec:
        base, label = spec.split(":", 1)
        return base.strip(), label.strip()
    return spec.strip(), spec.strip()


def _make_arm(name, model, upstream_base=None, upstream_key=None, provider=None,
              keep_sessions=False, tag=None):
    """Build one adapter by name. Imported lazily so a missing dep on one arm
    (e.g. no Hermes install) never breaks the others.

    `upstream_base`/`upstream_key` point the bare + hermes arms at the SAME model
    endpoint the harness uses (e.g. the local llama.cpp router), so "same model"
    is literal and not just "same model name on three different providers".
    """
    if name == "bare":
        from benchmarks.bare_adapter import BareAdapter
        return BareAdapter(base=upstream_base, api_key=upstream_key, model=model)
    if name == "longrun":
        from benchmarks.longrun_adapter import LongrunAdapter
        return LongrunAdapter(model=model, keep_sessions=keep_sessions, tag=tag)
    if name == "hermes":
        from benchmarks.hermes_adapter import HermesAdapter
        return HermesAdapter(model=model, provider=provider, base_url=upstream_base,
                             api_key=upstream_key or "local")
    raise SystemExit("unknown arm %r (bare|longrun|hermes)" % name)


def _md_table(results):
    lines = ["| arm | pass@1 | passed | n | ok | failed | total_s |",
             "|---|---|---|---|---|---|---|"]
    for name, r in results.items():
        lines.append("| %s | %s | %d | %d | %d | %d | %s |"
                     % (name, r.get("pass@1"), r.get("passed", 0), r.get("n", 0),
                        r.get("ok", 0), r.get("failed", 0), r.get("duration_s")))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="benchmarks.compare")
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--arms", default="bare,longrun",
                    help="comma-separated: bare,longrun,hermes")
    ap.add_argument("--model", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--base", default=os.environ.get("LONGRUN_BASE",
                                                     "http://127.0.0.1:8790"))
    ap.add_argument("--upstream-base", default=None,
                    help="model endpoint the bare/hermes arms call (e.g. "
                         "http://127.0.0.1:8080/v1 for the local router)")
    ap.add_argument("--upstream-key", default=None)
    ap.add_argument("--provider", default=None, help="hermes --provider value")
    ap.add_argument("--model-map", default="",
                    help="per-arm model override, e.g. "
                         "'longrun=dgx:nex-n25-mini-uncensored-q8' — the harness "
                         "takes a provider:model ref while a raw endpoint takes the "
                         "bare alias; SAME weights, two spellings")
    ap.add_argument("--keep-sessions", action="store_true",
                    help="do NOT delete the Longrun sessions — open them in the "
                         "WebUI to see exactly what the harness did")
    ap.add_argument("--tag", default=None,
                    help="prefix for the Longrun session titles (find the run fast)")
    ap.add_argument("--jobs", type=int, default=1,
                    help="run this many TASKS in parallel inside one arm "
                         "(each in its own Longrun session)")
    args = ap.parse_args(argv)
    model_map = dict(kv.split("=", 1) for kv in args.model_map.split(",") if "=" in kv)

    tasks = humaneval.load_tasks(args.tasks)
    if not tasks:
        print("no tasks in %s" % args.tasks)
        return 2
    os.makedirs(args.out, exist_ok=True)

    results, summary = {}, {"model": args.model, "tasks": args.tasks,
                            "n_tasks": len(tasks), "arms": {}}
    for spec in [a.strip() for a in args.arms.split(",") if a.strip()]:
        name, label = _split_arm(spec)
        arm_model = model_map.get(label, model_map.get(name, args.model))
        ad = _make_arm(name, arm_model, upstream_base=args.upstream_base,
                       upstream_key=args.upstream_key, provider=args.provider,
                       keep_sessions=args.keep_sessions,
                       tag=(args.tag or label) if args.keep_sessions else None)
        if hasattr(ad, "base") and name == "longrun":
            try:
                ad.base = args.base
            except Exception:  # noqa: BLE001
                pass
        arm_dir = os.path.join(args.out, label)
        out = run_suite(ad, tasks, arm_dir, prompt_fn=humaneval.prompt_for,
                        limit=args.limit, model=arm_model, jobs=args.jobs)
        with open(out["preds"], encoding="utf-8") as f:
            preds = [json.loads(ln) for ln in f if ln.strip()]
        sc = humaneval.score(preds, tasks)
        with open(os.path.join(arm_dir, "score.json"), "w", encoding="utf-8") as f:
            json.dump(sc, f, indent=2)
        with open(out["summary"], encoding="utf-8") as f:
            s = json.load(f)
        results[label] = {"pass@1": sc["pass@1"], "passed": sc["passed"], "n": sc["n"],
                          "ok": s["ok"], "failed": s["failed"],
                          "duration_s": s["duration_s"], "provenance": s["provenance"]}
        summary["arms"][label] = results[label]
        print("%-16s pass@1=%s (%d/%d) ok=%d failed=%d in %ss"
              % (label, sc["pass@1"], sc["passed"], sc["n"], s["ok"], s["failed"],
                 s["duration_s"]))

    summary["generated"] = round(time.time(), 3)
    with open(os.path.join(args.out, "compare.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    md = "# Harness comparison — same model, same tasks\n\n"
    md += "Model: `%s` · tasks: %d · arms: %s\n\n" % (args.model, len(tasks),
                                                      ", ".join(results))
    md += _md_table(results) + "\n"
    with open(os.path.join(args.out, "compare.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print("wrote %s" % os.path.join(args.out, "compare.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())