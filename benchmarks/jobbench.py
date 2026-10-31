#!/usr/bin/env python3
"""JobBench corpus adapter — the OFFICIAL workplace benchmark, shared by every arm.

JobBench is the workplace benchmark shipped with Google's Harness² (arXiv
2610.14224). Nothing here re-implements it: the tasks, the instruction file, the
rubrics and the judge all come from the pinned upstream checkout
(`dependencies/job-bench-eval`, recipe in its `PINNED.md`).

Provenance (verbatim from Harness² `harness2/benchmarks/jb_opencode_runner.py`,
Apache-2.0): the agent prompt below and the `model_output/<label>/` layout. They are
copied rather than imported so an external arm can be driven without making one
repo a runtime dependency of the other — but they must stay IDENTICAL, because the
prompt is part of the benchmark: two arms with two prompts are not comparable.

Layout of one task (upstream):

    dataset/main/<profession>/task<N>/
        task_folder/            inputs the agent may read (TASK_INSTRUCTIONS.txt inside)
        files_required_to_search/  MORE inputs, 57 tasks ship this folder
        RUBRICS.json            the weighted criteria the official judge grades
        task_card.md            human description (not shown to the agent)

Deliverables must land in the workspace's `output/` directory only.
"""
import json
import os
import shutil
from pathlib import Path

#: The pinned upstream checkout. Override with `JOB_BENCH_REPO` to run elsewhere.
DEFAULT_REPO = Path(os.environ.get(
    "JOB_BENCH_REPO",
    "/home/jagones/Repositories/Harness2/dependencies/job-bench-eval")).expanduser()

#: The instruction every arm receives (Harness² `PROMPT`, verbatim).
PROMPT = """=== TASK FOLDER ===
{task_folder}

=== INSTRUCTIONS ===
1. Read the TASK_INSTRUCTIONS.txt file in the task folder above
2. Based on the Reference Files section in TASK_INSTRUCTIONS.txt, read the corresponding files from the same task folder using appropriate tools.
3. Complete the task as specified in TASK_INSTRUCTIONS.txt
4. Only save the final deliverables to the output directory specified below. Do not save any intermediate or temporary files.

=== OUTPUT DIRECTORY ===
{output_dir}

IMPORTANT:
- All reference files are in the task folder: {task_folder}
- Only save the final deliverables to the output directory {output_dir}. Do not save any intermediate or temporary files.
- You MUST only access files within {workspace} or search online for new reference files if you find needed. Do NOT access any files or directories in this system outside of this path.
- If you encounter ambiguous or conflicting information, analyze the conflict, explain your reasoning, and justify the approach you choose.
- If a file cannot be read directly (e.g., .xlsx, .docx, .db, .pptx), use appropriate tools, MCP servers, or code to extract and process its contents."""


def repo():
    """The upstream JobBench checkout (raises when it is missing)."""
    root = Path(os.environ.get("JOB_BENCH_REPO") or DEFAULT_REPO).expanduser()
    if not (root / "dataset" / "main").is_dir():
        raise FileNotFoundError(
            "JobBench dataset not found under %s — materialise "
            "dependencies/job-bench-eval (see its PINNED.md) or set JOB_BENCH_REPO" % root)
    return root


def tasks(profession="", limit=None):
    """Discover the official tasks: `[{id, profession, folder, rubrics, instructions}]`.

    A task exists when `<task>/task_folder/TASK_INSTRUCTIONS.txt` does, so a
    partially-materialised checkout cannot silently become a benchmark with
    missing instructions.
    """
    base = repo() / "dataset" / "main"
    out = []
    for prof_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        if profession and prof_dir.name != profession:
            continue
        for task_dir in sorted(p for p in prof_dir.iterdir() if p.is_dir()):
            folder = task_dir / "task_folder"
            instructions = folder / "TASK_INSTRUCTIONS.txt"
            if not instructions.is_file():
                continue
            out.append({
                "id": "%s/%s" % (prof_dir.name, task_dir.name),
                "profession": prof_dir.name,
                "task": task_dir.name,
                "folder": folder,
                "rubrics": task_dir / "RUBRICS.json",
                "instructions": instructions.read_text(encoding="utf-8", errors="replace"),
            })
            if limit and len(out) >= int(limit):
                return out
    return out


def prompt_for(task, workspace):
    """The official instruction, with this arm's real paths substituted."""
    ws = Path(workspace)
    return PROMPT.format(task_folder=ws / "task_folder",
                         output_dir=ws / "output", workspace=ws)


def stage(task, workspace):
    """Materialise a clean workspace: `task_folder/` (a copy) + an empty `output/`.

    The task's SECOND input set is merged INTO `task_folder/`, because the official
    prompt promises "all reference files are in the task folder". Measured
    2026-10-31 on `bookkeeping_accounting_and_auditing_clerks/task1`: the AP
    subledger lived in `files_required_to_search/`, which the staging ignored, so
    the honest arm reported "AP subledger not provided" and scored 0/88 while an
    arm that walked the dataset outside its own workspace scored 50/88. The folder
    is an input like any other: copy it in, and the sentence becomes true.
    """
    ws = Path(workspace)
    shutil.rmtree(ws, ignore_errors=True)
    (ws / "output").mkdir(parents=True)
    shutil.copytree(Path(task["folder"]), ws / "task_folder")
    for extra in search_folders(task):
        for src in sorted(extra.rglob("*")):
            if not src.is_file():
                continue
            dst = ws / "task_folder" / src.relative_to(extra)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    return ws


def search_folders(task):
    """The extra input folders shipped next to `task_folder/` (may be empty)."""
    extra = Path(task["folder"]).parent / "files_required_to_search"
    return [extra] if extra.is_dir() else []


def deliverables(workspace):
    """Files the arm delivered under `output/` (relative paths, sorted)."""
    out = Path(workspace) / "output"
    if not out.is_dir():
        return []
    return sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())


def rubric_weights(rubrics_path):
    """`(max_weight, criteria_count)` from the official RUBRICS.json."""
    try:
        data = json.loads(Path(rubrics_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0.0, 0
    total, count = 0.0, 0
    for row in data.get("rubrics") or []:
        if not isinstance(row, dict):
            continue
        try:
            total += float(row.get("weight") or 0)
        except (TypeError, ValueError):
            continue
        crit = row.get("criterion", [])
        count += 1 if isinstance(crit, str) else len(list(crit))
    return total, count


def no_output_score(task):
    """A run that delivered nothing is a REAL zero, built from the rubric weights.

    Same semantics as the official adapter: an empty `output/` must not be
    confused with a judge failure (which is `None`, never `0`).
    """
    mx, n_c = rubric_weights(task.get("rubrics"))
    if not mx:
        return None
    return {"ok": True, "score": 0.0, "max": mx, "criteria_passed": 0,
            "criteria_count": n_c, "all_pass": False, "metric": "weighted",
            "no_output": True, "judge_model": ""}
