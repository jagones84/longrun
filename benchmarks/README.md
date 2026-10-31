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

## JobBench — the official suite, three arms, one judge (EV-23 / EV-26)

`jobbench.py` / `jobbench_judge.py` / `jobbench_compare.py` drive the JobBench
tasks shipped with Google's Harness² (arXiv 2610.14224) and grade them with the
UPSTREAM `eval/judge.py` against each task's `RUBRICS.json`:

```bash
python3 -m benchmarks.jobbench_compare \
  --profession biostatisticians --tasks 2 \
  --arms raw,longrun,harness2 \
  --model openrouter:z-ai/glm-5.3-flash \
  --judge-model z-ai/glm-5.3-flash --judge-base https://openrouter.ai/api/v1 \
  --max-steps 40
```

The three arms are always reported in one fixed order — `raw` (no harness at all)
→ `longrun` (this harness) → `harness2` (Google) — and `compare.md` ends with the
plain sentence of who scored better on that run. The raw arm is the FLOOR: one
plain `chat/completions` call with no tools and no system prompt, whose text is
saved as `output/answer.md` so the judge can read it. An arm that does not beat
the floor is not paying for itself.

Without `--out` the runner names the folder itself
(`.agent/BENCHMARKS/runs/<date>_jobbench_<model>_<arms>_<scope>_n<N>`, `-2` on a
repeat) and writes `run.json` + `compare.{json,md}` inside it; `runs/INDEX.md` is
derived from the manifests. `--max-steps` is the per-turn real-tool budget for the
Longrun arm (chat default 8 truncates a multi-artifact task). `--only-task task2`
re-runs ONE task by name instead of "the first N" (Longrun arm only: Harness²
sweeps a whole domain). `--harness2-from <run>` grades an earlier run's Harness²
sweep instead of spending a second one — a sweep costs four ~12-minute rollouts.

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

## Polyglot (Exercism) — deterministic harness comparison, no judge (2026-10-31)

The JobBench judge moves ±8-12 points on the SAME artefact, so it can rank a
harness against itself. For "is harness A better than harness B" the score must be
mechanical. `polyglot.py` + `polyglot_compare.py` run the **Aider polyglot corpus**
(`Aider-AI/polyglot-benchmark`, the Exercism exercises the Aider leaderboard uses)
and decide every task by running the exercise's OWN test suite:

```bash
# 1. prove the suite itself (no model, no spend): exemplar must pass, stub must fail
python3 -m benchmarks.polyglot_compare --check              # python track
python3 -m benchmarks.polyglot_compare --check --language go

# 2. same model, three harnesses, ten exercises
python3 -m benchmarks.polyglot_compare \
  --arms longrun,openclaw,opencode \
  --model openrouter:z-ai/glm-5.3-flash --limit 10 \
  --keep-sessions --out .agent/BENCHMARKS/runs/2026-11-01_polyglot_py10
```

- **Score** = `pytest` (python) or `go test` (Go, in `golang:1.22-bookworm` with the
  network off) exit code inside the task workspace. `tests_modified` is reported as
  an INVALID row: an arm that edits the grader did not solve the task.
- **No leak**: `.meta/example.*` (the reference solution) is never staged.
- **Wired tracks**: `python` (33 tasks, native `pytest`) and `go` (14 tasks, in a
  container). JS/Rust/Java need their own image with npm/cargo/mvn deps;
  `load_tasks` refuses them by name instead of scoring 0. `go/ledger` is excluded
  (`KNOWN_BAD`): its tests pass on the untouched stub, so it would pay free points.
- **Dataset**: clone `https://github.com/Aider-AI/polyglot-benchmark` next to the
  repo (default `/home/jagones/Repositories/polyglot-benchmark`, override with
  `POLYGLOT_DIR`). `run.json` records the dataset commit.
- `--check` is the suite's own regression test: a task whose exemplar does not pass
  or whose stub does pass is a broken task, and the runner refuses it.

Why not SWE-bench / Claw-SWE-Bench here: their evaluation images are `x86_64` only
(`sweb.eval.x86_64.<instance>`), and this host is `aarch64` with no x86 emulation —
the containers cannot run. Polyglot needs no prebuilt image, so it is the only
deterministic SWE-shaped suite this machine can execute today.

## Safety

`humaneval.check()` executes candidate code in-process — run it on a trusted or
sandboxed evaluation host, never on untrusted code.
