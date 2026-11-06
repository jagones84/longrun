#!/usr/bin/env bash
# LHB — Longrun Harness Bench: the DETERMINISTIC harness instrument.
# Scores procedure, honesty, policy retention, recovery, injection resistance and
# the visible-vs-hidden gap. No judge, no network, no container: every task is
# decided by declarative checks executed outside the arm's workspace.
#
# Usage:
#   scripts/bench-lhb.sh check                 # prove the instrument (oracle passes,
#                                              # stub and cheater fail). No model.
#   scripts/bench-lhb.sh <tag> [tasks|all] [arms] [repeat]
#     tag     required; names the run folder (never reused)
#     tasks   `all` or a number (default all)
#     arms    comma list: raw,longrun,openclaw,opencode (default raw,longrun)
#     repeat  runs per task per arm (default 3 -> pass@1 and pass^k)
# Env: MODEL, TASK_TIMEOUT, MAX_STEPS, ONLY, FAMILY, ORDER.
#
# Before ANY paid run: `scripts/bench-lhb.sh check` must print
# `8/8 tasks verified`. The runner refuses a non-empty --out folder, so two
# results never share a directory.
set -u
cd /home/jagones/Repositories/longrun || exit 1

MODE="${1:-check}"

if [ "$MODE" = "check" ]; then
  python3 -m benchmarks.lhb_compare --check
  exit $?
fi

# Model policy (project rule 2026-11-06): NEVER a local DGX model. A local 25B
# loop measures itself, not the harness. Allowed: glm-5.3-flash, deepseek flash.
MODEL="${MODEL:-openrouter:z-ai/glm-5.3-flash}"
case "$MODEL" in
  openrouter:z-ai/glm-5.3-flash|deepseek:deepseek-flash*) : ;;
  *)
    echo "refusing MODEL=$MODEL — allowed: openrouter:z-ai/glm-5.3-flash, deepseek:deepseek-flash" >&2
    exit 2
    ;;
esac

TAG="$1"
LIMIT="${2:-0}"
ARMS="${3:-raw,longrun}"
REPEAT="${4:-3}"
[ "$LIMIT" = "all" ] && LIMIT=0
STAMP="$(date +%Y-%m-%d_%H%M%S)"
OUT=".agent/BENCHMARKS/runs/${STAMP}_lhb_${TAG}"
LOG=".agent/logs/lhb_${STAMP}_${TAG}.log"

if [ -e "$OUT" ]; then
  echo "refusing to reuse existing run folder: $OUT (choose another tag)" >&2
  exit 2
fi
# The runner CREATES `--out` itself and refuses a non-empty one; pre-creating it
# here (with the log inside) made every run abort in 1 s — measured 2026-11-06.
mkdir -p .agent/logs
echo "$OUT" > .agent/trash/last_lhb_run.txt

{
  echo "=== lhb ${TAG} START $(date -Is) git=$(git rev-parse --short HEAD) arms=${ARMS} limit=${LIMIT} repeat=${REPEAT}"
  python3 -u -m benchmarks.lhb_compare \
    --arms "$ARMS" --limit "$LIMIT" --repeat "$REPEAT" \
    --model "${MODEL}" \
    --timeout "${TASK_TIMEOUT:-600}" --max-steps "${MAX_STEPS:-40}" \
    --only "${ONLY:-}" --family "${FAMILY:-}" \
    --keep-sessions --tag "$TAG" --out "$OUT"
  echo "=== lhb ${TAG} DONE $(date -Is)"
} >> "$LOG" 2>&1

echo "$OUT"
