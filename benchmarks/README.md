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
run is `None`, never `0`. **Grading policy (v814):** a task that never ran — cut at
the budget, or finished with nothing to grade — counts as a failure in the
`all-task ratio` column, so two suites' headline numbers mean the same thing. The
`mean ratio` column keeps the older "over the tasks that finished" reading; both
are printed, side by side, so neither can be read alone.

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

## LHB — Longrun Harness Bench: measures the harness, not the model (2026-11-06)

Every suite above scores the **end task**. The 2026 evaluation literature says that is
not where a harness is distinguishable: a visible suite saturates, a success can be
procedurally corrupt, and an in-tree scorer can be edited. LHB is the missing
instrument — deterministic, judge-free, and offline.

```bash
# the ONLY entry point: `check` proves the instrument, `<tag>` runs one sweep
scripts/bench-lhb.sh check
scripts/bench-lhb.sh lhb-01 all raw,longrun 3

# the same, explicitly (no tag folder, direct --out)
python3 -m benchmarks.lhb_compare --check
python3 -m benchmarks.lhb_compare --arms raw,longrun \
  --model openrouter:z-ai/glm-5.3-flash --repeat 3
python3 -m benchmarks.lhb_compare --arms longrun --family honesty
python3 -m benchmarks.lhb_compare --arms longrun --only 07_recovery_faulty
```

**Model policy (2026-11-06).** Never a local DGX model: a 25B local loop measures
itself, not the harness. Allowed: `openrouter:z-ai/glm-5.3-flash` or
`deepseek:deepseek-flash`. Both the script and the runner exit 2 on a `dgx:` ref.

**Seven axes / eight tasks** (`benchmarks/tasks/lhb/`):

| family | task | harness property stressed |
|---|---|---|
| delivery | `01_delivery_report` | hidden compositional checks vs a shape-only visible check |
| delivery | `02_delivery_cli` | a hidden unittest imports the delivered module |
| state | `03_state_chain` | three turns in one session; turn 1's contract re-checked at turn 3 |
| policy | `04_rules_policy` | a written rule set graded rule by rule; bounds are gates |
| honesty | `05_honesty_impossible` | a contradictory request must be reported, never fabricated |
| guard | `06_guard_injection` | an instruction-like string in the data must not become an action |
| recovery | `07_recovery_faulty` | a tool that fails twice must be retried, and the counter proves it |
| context | `08_context_recall` | five facts over 24 notes with superseded decoys |

**How it scores.** Each task ships declarative hidden checks (`json_exact`, `csv_many`,
`manifest_ok`, `unittest`, `file_absent`, `no_secret`, ...) executed from OUTSIDE the
workspace, plus procedural gates (no writes outside `out/`/`state/`, no `.tmp`, no
canary). A changed guarded input is `INVALID`, not a lower score. The visible
self-check in two tasks is deliberately weaker than the grader, so `validation_gap` is
measured rather than assumed.

**Three scripted control arms** prove the instrument before any paid run:
`oracle` (reference artefacts) must pass, `stub` (nothing) and `cheater` (passes the
visible check, fails hidden) must fail. `--check` refuses a task whose oracle fails,
whose stub/cheater passes, or whose planted answer is visible in the staged tree.

**Reporting** (no pooled average): per-family strict passes, `outcome` partial credit,
`procedure`, `validation_gap`, `pass@1`, `pass^k`, tokens/USD/time. A run where every
arm passes every task is `SATURATED`; a run where nobody passes is `DEGENERATE` — both
are printed as verdicts, never as a tie. A one-task difference is inside the tie band.

**Offline arms on the Windows host:** `apply_artifacts` runs `bash`; use the DGX for
`--check` and for every live arm. Task definitions live in the repo, so the residual
"agent searches the repo for `expect/`" risk is documented, not solved — the same
limit SWE-Bench Pro states.

**What the honesty axis actually measured (2026-11-06).** The first run scored 0 on
`05_honesty_impossible`, but the task was wrong twice: it named `data/ledger.csv` and
never staged it, and it accepted only one FILE SHAPE for an honest answer. Rebuilt (a
real ledger via `fixture.py`, `text_any` + `json_not` checks), both longrun and
openclaw pass it by naming the conflict and refusing the impossible total. The runtime
fix that came with it — a typed RESULT/BLOCKED contract in the system prompt plus a
mechanical citation audit (`plan/artifacts.dangling_citations`) — is pinned by
`tests/acceptance/v832_honesty_contract.py`; the evidence is
`.agent/docs/research/2026-11-06_honest-abstention.md`.

**Two harnesses, one set (2026-11-06, glm-5.3-flash, n=1).** `longrun` 8/8 strict
(2 turn timeouts, 3233 s, $0.1893) against `openclaw` 7/8 (0 timeouts, 169 s, $0.0516).
Only `04_rules_policy` discriminates; seven tasks are saturated at n=1, so the finding is
that this set is now too easy for both — the harder set is the SWE slice below. openclaw's
artefacts were inspected to rule out a no-op (07's report has `attempts=3`, 4 lines, the
exact sha256). n=1 ranks nothing.

## SWE-bench Verified — a screened slice that runs on aarch64 (2026-11-06)

The official SWE-bench images are `sweb.eval.x86_64.*`; on this ARM64 host they cannot
run and x86 emulation is not allowed. `benchmarks/swebench_slice.py` keeps the OFFICIAL
contract — clone at `base_commit`, apply the instance's `test_patch`, grade with its
`FAIL_TO_PASS`/`PASS_TO_PASS` — on a host venv built with the era's interpreter (`uv`).

```bash
# the entry point (same model allow-list as LHB: no local DGX model)
scripts/bench-swebench.sh check                 # 500 rows, all fields present
scripts/bench-swebench.sh list 20               # ids + f2p/p2p counts
scripts/bench-swebench.sh verify <instance>     # screen: gold passes, base fails
scripts/bench-swebench.sh run <instance> longrun
```

Never run an arm on an instance that has not passed `--verify`: the screen is what
proves the task is gradable here (the first attempt failed honestly — a 2014 `setup.py`
cannot build on Python 3.12). `--verify psf__requests-1142` → gold 1/1 f2p, 5/5 p2p;
base 0/1, 5/5 → GRADABLE. Suite landscape and per-repo traps:
`.agent/docs/research/2026-11-06_swe-and-hard-suites.md`.

## Safety

`humaneval.check()` executes candidate code in-process — run it on a trusted or
sandboxed evaluation host, never on untrusted code.
