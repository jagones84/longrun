#!/usr/bin/env bash
# JobBench launcher (the official one — this replaces the ad-hoc copies that used
# to live under .agent/trash/). Runs the three benchmark professions in parallel,
# one task each, and keeps the Longrun sessions so a run can be inspected after.
#
# Usage: scripts/bench-jobbench.sh <tag> [tasks] [arms] [model]
#   tag    required; becomes the session-title prefix and the run folder suffix
#   tasks  tasks per profession (default 1)
#   arms   comma list accepted by benchmarks.jobbench_compare (default longrun;
#          use longrun,openclaw,opencode,raw for the cross-harness comparison)
#   model  Longrun model id (default openrouter:z-ai/glm-5.3-flash)
# Env: JUDGE_MODEL, MAX_STEPS, TASK_TIMEOUT, JUDGE_TIMEOUT.
set -u
cd /home/jagones/Repositories/longrun || exit 1

TAG="${1:?usage: bench-jobbench.sh <tag> [tasks] [arms] [model]}"
TASKS="${2:-1}"
ARMS="${3:-longrun}"
MODEL="${4:-openrouter:z-ai/glm-5.3-flash}"
JUDGE="${JUDGE_MODEL:-z-ai/glm-5.3-flash}"
STAMP="$(date +%Y-%m-%d_%H%M)"
OUTROOT=".agent/BENCHMARKS/runs/${STAMP}_${TAG}"
LOG="${OUTROOT}/bench.log"

mkdir -p "$OUTROOT"

one() {
  local prof="$1" label="$2"
  python3 -u -m benchmarks.jobbench_compare \
    --profession "$prof" --tasks "$TASKS" --arms "$ARMS" \
    --model "$MODEL" --judge-model "$JUDGE" \
    --judge-base https://openrouter.ai/api/v1 \
    --max-steps "${MAX_STEPS:-40}" --timeout "${TASK_TIMEOUT:-1800}" \
    --judge-timeout "${JUDGE_TIMEOUT:-1800}" \
    --keep-sessions --tag "$TAG" \
    --out "$OUTROOT/$label" >> "$LOG" 2>&1
}

echo "=== ${TAG} START $(date -Is) git=$(git rev-parse --short HEAD)" > "$LOG"
one medical_secretaries "medical" &
one police_fire_and_ambulance_dispatchers "dispatch" &
one bookkeeping_accounting_and_auditing_clerks "bookkeeping" &
wait
echo "=== ${TAG} DONE $(date -Is)" >> "$LOG"
echo "$OUTROOT"
