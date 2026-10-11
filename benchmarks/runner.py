#!/usr/bin/env python3
"""Generic benchmark runner (JAG-426 · Domain 3).

Drives ANY `HarnessAdapter` (benchmarks/protocol.py) over a list of tasks and
writes the two artifacts every benchmark harness needs:

    <out>/predictions.jsonl   one line per task: {task_id, prediction}
    <out>/summary.json        ok/fail counts + provenance (version, sha, model)

It never scores: scoring belongs to the benchmark's OWN official scorer, which
this runner is not allowed to re-implement (a re-implemented scorer silently
drifts from the leaderboard).
"""
import json
import os
import time


def _default_prompt(task):
    return (task.get("prompt") or task.get("question") or task.get("problem_statement")
            or task.get("goal") or "")


def run_suite(adapter, tasks, out_dir, prompt_fn=None, limit=None, model=None):
    """Run every task through the adapter. Returns the artifact paths + stats."""
    os.makedirs(out_dir, exist_ok=True)
    prompt_fn = prompt_fn or _default_prompt
    rows, preds = [], []
    t0 = time.time()
    for task in (tasks or [])[: (limit or len(tasks or []))]:
        tid = task.get("id") or task.get("task_id") or task.get("instance_id") or ""
        ref = adapter.create_agent(task)
        res = adapter.send_task(ref, prompt_fn(task))
        preds.append({"task_id": tid, "prediction": res.output})
        rows.append({"task_id": tid, "ok": bool(res.ok), "run_id": res.run_id,
                     "duration_s": res.duration_s, "tokens": res.tokens,
                     "error": res.error})
        try:
            adapter.delete_agent(ref)
        except Exception:  # noqa: BLE001 — cleanup must not fail the run
            pass
    preds_path = os.path.join(out_dir, "predictions.jsonl")
    with open(preds_path, "w", encoding="utf-8") as f:
        for p in preds:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    summary = {
        "adapter": getattr(adapter, "name", "unknown"),
        "model": model,
        "n": len(rows),
        "ok": sum(1 for r in rows if r["ok"]),
        "failed": sum(1 for r in rows if not r["ok"]),
        "duration_s": round(time.time() - t0, 2),
        "provenance": adapter.provenance(),
        "rows": rows,
    }
    summary_path = os.path.join(out_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    return {"preds": preds_path, "summary": summary_path, "n": len(rows),
            "ok": summary["ok"], "failed": summary["failed"]}
