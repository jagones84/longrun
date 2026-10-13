#!/usr/bin/env python3
"""HumanEval-shaped tasks (JAG-426 · Domain 3).

Loads the standard HumanEval JSONL shape (`task_id`, `prompt`, `test`,
`entry_point`) and provides the functional check locally — the same contract the
official `evaluate_functional_correctness` uses (a `check(candidate)` in the
task's own `test`). Scoring is NOT re-implemented: we run the task's own test.

SECURITY: `check()` executes the candidate source in-process. It is meant for a
trusted/sandboxed evaluation host (the harness's own `shell`/sandbox tool), never
for untrusted code on a workstation.
"""
import json
import re


def load_tasks(path):
    """Read a HumanEval-style .jsonl into a list of task dicts."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def extract_code(text):
    """Pull the candidate source out of a chatty model reply (JAG-454).

    Applied UNIFORMLY to every arm (bare / longrun / hermes) by `score()`, so a
    harness that answers in prose is not penalised relative to one that happens
    to emit bare code — the standard bigcode-evaluation-harness behaviour.
    """
    t = str(text or "").strip()
    if not t:
        return ""
    m = _FENCE.search(t)
    if m:
        return m.group(1).strip("\n")
    if t.startswith("```"):
        body = t[3:]
        return body.rsplit("```", 1)[0].lstrip("\n")
    return t


def prompt_for(task):
    """The exact prompt handed to the harness (the official delta form)."""
    return ("Complete the following Python function. Reply with ONLY the code "
            "(no prose, no markdown fences).\n\n" + (task.get("prompt") or ""))


def check(candidate_src, task):
    """Run the task's own functional test against `candidate_src`.

    Returns {ok, passed, error?}. `ok` means the check RAN; `passed` is the
    functional result.
    """
    src = task.get("test") or ""
    entry = task.get("entry_point") or "candidate"
    if not src:
        return {"ok": False, "passed": False, "error": "task has no `test`"}
    ns = {}
    # The OFFICIAL HumanEval contract evaluates `prompt + completion + test`: the
    # prompt carries the `from typing import ...` / `import math` preamble that both
    # the hidden test and the signature rely on. Evaluating the completion ALONE made
    # a correct answer fail with `NameError: name 'List' is not defined` — a SCORER
    # artefact, not a model error (it depressed both arms by ~15 points).
    prog = (task.get("prompt") or "") + "\n" + (candidate_src or "")
    try:
        exec(compile(prog, "<candidate>", "exec"), ns)
        exec(compile(src + "\ncheck(%s)\n" % entry, "<test>", "exec"), ns)
        return {"ok": True, "passed": True}
    except Exception as e:  # noqa: BLE001 — a failing candidate is data, not a crash
        return {"ok": True, "passed": False, "error": "%s: %s" % (type(e).__name__, e)[:300]}


def score(predictions, tasks):
    """Pair predictions with tasks and run each functional check."""
    by_id = {t.get("task_id") or t.get("id"): t for t in tasks}
    rows = []
    for p in predictions:
        task = by_id.get(p.get("task_id"))
        if not task:
            rows.append({"task_id": p.get("task_id"), "passed": False,
                         "error": "unknown task_id"})
            continue
        r = check(extract_code(p.get("prediction", "")), task)
        rows.append({"task_id": p.get("task_id"), **r})
    passed = sum(1 for r in rows if r.get("passed"))
    return {"n": len(rows), "passed": passed,
            "pass@1": round(passed / len(rows), 4) if rows else 0.0, "rows": rows}
