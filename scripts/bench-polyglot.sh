#!/usr/bin/env bash
# Polyglot (Exercism) head-to-head — the DETERMINISTIC code benchmark.
# Every task is scored by the exercise's own pytest suite (exit code only): no
# judge, no rubric, no ±12-point noise. This is the default benchmark whenever
# the question is "can the harness code", not "does it write a report".
#
# Usage: scripts/bench-polyglot.sh <tag> [limit] [arms] [language]
#   tag    required; names the run folder (never reused)
#   limit  tasks from the track (default 10; --check always covers all)
#   arms   comma list: longrun,openclaw,opencode,raw (default longrun,openclaw)
#   language  python (wired) | go (wired, needs docker)
# Env: MODEL, TASK_TIMEOUT, MAX_STEPS, ORDER.
#
# ORDER is `hardest` by default: ranking by test breadth × exemplar size, so the
# set is not the alphabetically-first easy head of the track (that one produced
# 10/10 for every arm and ranked nothing — measured 2026-10-31). Set ORDER=alpha
# for the plain track order, or LIMIT=33 for the whole python track.
# The report refuses to look like a ranking when every arm solves every task: it
# prints SATURATED instead.
#
# Prove the suite before spending: python3 -m benchmarks.polyglot_compare --check
set -u
cd /home/jagones/Repositories/longrun || exit 1

TAG="${1:?usage: bench-polyglot.sh <tag> [limit] [arms] [language]}"
LIMIT="${2:-10}"
ARMS="${3:-longrun,openclaw}"
LANG="${4:-python}"
# Model policy (project rule 2026-11-06): NEVER a local DGX model in a benchmark —
# a local 25B run measures the model's loop, not the harness. Same allow-list as
# bench-lhb.sh / bench-swebench.sh.
MODEL="${MODEL:-openrouter:z-ai/glm-5.3-flash}"
case "$MODEL" in
  openrouter:z-ai/glm-5.3-flash|deepseek:deepseek-flash*) : ;;
  *)
    echo "refusing MODEL=$MODEL — allowed: openrouter:z-ai/glm-5.3-flash, deepseek:deepseek-flash" >&2
    exit 2
    ;;
esac
ORDER="${ORDER:-hardest}"
STAMP="$(date +%Y-%m-%d_%H%M%S)"
OUT=".agent/BENCHMARKS/runs/${STAMP}_polyglot_${TAG}"
LOG="${OUT}/bench.log"

if [ -e "$OUT" ]; then
  echo "refusing to reuse existing run folder: $OUT (choose another tag)" >&2
  exit 2
fi
mkdir -p "$OUT"
echo "$OUT" > .agent/trash/last_polyglot_run.txt

{
  echo "=== polyglot ${TAG} START $(date -Is) git=$(git rev-parse --short HEAD) arms=${ARMS} limit=${LIMIT} order=${ORDER} lang=${LANG}"
  python3 -u -m benchmarks.polyglot_compare \
    --language "$LANG" --limit "$LIMIT" --order "$ORDER" --arms "$ARMS" \
    --model "${MODEL}" \
    --timeout "${TASK_TIMEOUT:-600}" --max-steps "${MAX_STEPS:-40}" \
    --keep-sessions --tag "$TAG" --out "$OUT"
  echo "=== polyglot ${TAG} DONE $(date -Is)"
} >> "$LOG" 2>&1

echo "$OUT"
