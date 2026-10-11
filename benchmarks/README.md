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

## Safety

`humaneval.check()` executes candidate code in-process — run it on a trusted or
sandboxed evaluation host, never on untrusted code.
