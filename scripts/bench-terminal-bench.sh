#!/usr/bin/env bash
# Terminal-Bench — the OFFICIAL, end-state graded harness benchmark, with Longrun as
# an arm. The score is the task's own tests against the final machine state: no
# transcript, no judge, so the harness is the only variable.
#
# Usage: scripts/bench-terminal-bench.sh <tag> <task-id> [task-id ...]
# Env:   ARM (longrun | openclaw — which harness is measured; default longrun),
#        MODEL (model id, both arms), TASK_TIMEOUT (s per task), TB_HOME (checkout),
#        N_CONCURRENT (trials at once, default 2 — each trial runs its own harness
#        server, and 4 of them on one GB10 is where memory pressure starts)
#
# Two arms, one suite: the oracle proves a task is runnable here, the ARM is what
# gets ranked. Each arm carries its own runtime into the task container (the score
# is the machine's end state), so both are measured on the same terms.
set -u
REPO="/home/jagones/Repositories/longrun"
cd "$REPO" || exit 1
TB_HOME="${TB_HOME:-/home/jagones/Repositories/terminal-bench}"
TB="$TB_HOME/.venv/bin/tb"

case "${ARM:-longrun}" in
  longrun)  AGENT="benchmarks.terminal_bench_agent:LongrunAgent" ;;
  openclaw) AGENT="benchmarks.terminal_bench_openclaw:OpenClawAgent" ;;
  *) echo "unknown ARM='${ARM}' (longrun|openclaw)" >&2; exit 2 ;;
esac

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
  --agent-import-path "$AGENT" \
  --agent-kwarg "model_name=${MODEL:-openrouter:z-ai/glm-5.3-flash}" \
  --agent-kwarg "timeout=${TASK_TIMEOUT:-1800}" \
  --n-concurrent "${N_CONCURRENT:-2}" $ARGS
rc=$?
echo "tb exit=$rc"
echo "run folder: $OUT"
exit "$rc"
