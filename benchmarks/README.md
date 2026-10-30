# Benchmark drivers (JAG-426 · Domain 3)

A harness that cannot be measured cannot be improved. This package drives Longrun
through the **public REST API** so an external benchmark orchestrator sees exactly
what a user sees.

## Harness-agnostic adapter

`protocol.py` defines the contract every harness adapter implements (the shape
popularised by Claw-SWE-Bench, arXiv 2606.12344):

| method | purpose |
|---|---|
| `create_agent(task)` | open a session ("agent") for a task |
| `send_task(ref, prompt)` | run one blocking turn, return the reply |
| `backup_session(ref)` | take a restore point (turn-anchored checkpoint) |
| `restore(ref, ckpt)` | roll the session back |
| `delete_agent(ref)` | tear the session down |
| `docker_args()` | extra container args the harness needs (none: it runs on the host) |
| `provenance()` | version + git sha + model, so a run is reproducible |

`longrun_adapter.py` is the Longrun implementation. It imports nothing from
`longrun.*` on purpose.

## Harness comparison — "how much is the harness worth?" (JAG-454)

Three arms implement the SAME protocol, so a run is apples-to-apples by
construction:

| arm | what it is | file |
|---|---|---|
| `bare` | **control** — the model API with no tools, no system prompt, no memory | `bare_adapter.py` |
| `longrun` | this harness (public REST API) | `longrun_adapter.py` |
| `hermes` | a second real harness (Hermes CLI one-shot) | `hermes_adapter.py` |

```bash
# same weights, same tasks, three harnesses
python3 -m benchmarks.compare \
  --tasks benchmarks/tasks/humaneval_n20.jsonl \
  --arms bare,longrun,hermes --limit 20 \
  --model nex-n25-mini-uncensored-q8 \
  --upstream-base http://127.0.0.1:8080/v1 --upstream-key local \
  --model-map longrun=dgx:nex-n25-mini-uncensored-q8 \
  --out outputs/compare-001
# -> <out>/compare.json + <out>/compare.md (pass@1 per arm + provenance)
```

`--model-map` exists because the harness takes a `provider:model` ref while a raw
endpoint takes the bare alias — the SAME weights, two spellings.

**Fairness, made explicit.** The scorer applies `humaneval.extract_code()` to
EVERY arm (a chatty arm is not penalised vs a terse one), and the Longrun arm
calls `setup()`/`teardown()` to lift its approval gate for the run and restore the
operator's settings afterwards. Without that lift a headless run measures a
harness whose `shell`/`fs.write` calls never execute — "hands tied", not "no
tools".

## Running

```bash
# HumanEval (self-contained: adapter -> predictions -> the task's own test)
python3 -m benchmarks.run --bench humaneval --tasks tasks.jsonl --out out/humaneval-001

# SWE-bench / GAIA: emits predictions.jsonl for the OFFICIAL scorer
python3 -m benchmarks.run --bench swebench  --tasks instances.jsonl --out out/swe-001
```

`humaneval` scores locally with `humaneval.score()` — it runs the task's own
`test` (`check(candidate)`), never a re-implemented scorer.

**SWE-bench / GAIA are not scored here on purpose.** Their official harnesses own
container orchestration, hidden tests and judge models; re-implementing them would
silently drift from the leaderboard. This repo produces the prediction artifact
(plus a `summary.json` with provenance) and hands it to the official runner.

## JobBench — the official suite, both harnesses, one judge (EV-23)

`jobbench.py` / `jobbench_judge.py` / `jobbench_compare.py` drive the JobBench
tasks shipped with Google's Harness² (arXiv 2610.14224) and grade them with the
UPSTREAM `eval/judge.py` against each task's `RUBRICS.json`:

```bash
python3 -m benchmarks.jobbench_compare \
  --profession biostatisticians --tasks 2 --arms longrun,harness2 \
  --model openrouter:z-ai/glm-5.3-flash \
  --judge-model z-ai/glm-5.3-flash --judge-base https://openrouter.ai/api/v1 \
  --max-steps 40
```

Without `--out` the runner names the folder itself
(`.agent/BENCHMARKS/runs/<date>_jobbench_<model>_<arms>_<scope>_n<N>`, `-2` on a
repeat) and writes `run.json` + `compare.{json,md}` inside it; `runs/INDEX.md` is
derived from the manifests. `--max-steps` is the per-turn real-tool budget for the
Longrun arm (chat default 8 truncates a multi-artifact task). `--only-task task2`
re-runs ONE task by name instead of "the first N" (Longrun arm only: Harness²
sweeps a whole domain).

The Longrun arm sends `headless: true`: a benchmark has nobody attached to answer
a HUMAN IN THE LOOP card, so the turn reports its real reply instead of parking.
It is **not** `mode: goal` — that would wrap the message in GOAL MODE prose and
break the verbatim-instruction parity the comparison depends on.

One model, three spellings (`provider:model` for Longrun, `provider/model` for
Harness²/OpenCode, the bare id for the judge), and one scorer for both arms.
Longrun is driven over `POST /api/chat`; Harness² has **no task endpoint**, so its
arm is its own CLI sweep (`harness2 ... --bench jb`) — recorded as an asymmetry in
every report. Artifacts live under `.agent/BENCHMARKS/` (never in this repo).

A run that delivered nothing is a rubric-weighted **zero**; a judge that could not
run is `None`, never `0`.

## Safety

`humaneval.check()` executes candidate code in-process — run it on a trusted or
sandboxed evaluation host, never on untrusted code.
