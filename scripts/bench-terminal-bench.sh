#!/usr/bin/env bash
# Terminal-Bench — the OFFICIAL, end-state graded harness benchmark, with Longrun as
# an arm. The score is the task's own tests against the final machine state: no
# transcript, no judge, so the harness is the only variable.
#
# Usage: scripts/bench-terminal-bench.sh <tag> <task-id> [task-id ...]
# Env:   MODEL (longrun model id), TASK_TIMEOUT (s per task), TB_HOME (checkout)
#
# Why the wrapper exists: `tb` must import benchmarks/terminal_bench_agent.py (host
# side) while itself running from its own venv, and the run folder must refuse to be
# reused — the same two rules every other suite here follows.
#
# Prove the harness side for free first (no model): the oracle agent runs the task's
# own reference solution.
#   cd $TB_HOME && .venv/bin/tb run -p original-tasks -t hello-world --agent oracle
set -u
REPO="/home/jagones/Repositories/longrun"
cd "$REPO" || exit 1
TB_HOME="${TB_HOME:-/home/jagones/Repositories/terminal-bench}"
TB="$TB_HOME/.venv/bin/tb"

TAG="${1:?usage: bench-terminal-bench.sh <tag> <task-id> [task-id ...]}"
shift || true
[ "$#" -ge 1 ] || { echo "need at least one task id" >&2; exit 2; }

STAMP="$(date +%Y-%m-%d_%H%M%S)"
OUT="$REPO/.agent/BENCHMARKS/runs/${STAMP}_tb_${TAG}"
if [ -e "$OUT" ]; then
  echo "refusing to reuse existing run folder: $OUT (choose another tag)" >&2
  exit 2
fi
mkdir -p "$OUT"
echo "$OUT" > "$REPO/.agent/trash/last_tb_run.txt"

ARGS=""
for t in "$@"; do ARGS="$ARGS -t $t"; done

# shellcheck disable=SC2086
PYTHONPATH="$REPO" "$TB" run -p "$TB_HOME/original-tasks" \
  --output-path "$OUT" --run-id "$TAG" --no-upload-results \
  --agent-import-path benchmarks.terminal_bench_agent:LongrunAgent \
  --agent-kwarg "model_name=${MODEL:-openrouter:z-ai/glm-5.3-flash}" \
  --agent-kwarg "timeout=${TASK_TIMEOUT:-1800}" $ARGS
rc=$?
echo "tb exit=$rc"
echo "run folder: $OUT"
exit "$rc"
