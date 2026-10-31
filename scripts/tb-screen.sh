#!/usr/bin/env bash
# arm64 screening of OFFICIAL Terminal-Bench tasks, with ZERO model calls: the oracle
# agent runs each task's own reference solution, so a PASS proves the image BUILDS
# here, the tests RUN here, and the task is sound. A FAIL means this host cannot run
# that task (x86-only binary, GPU, huge download) and it must leave the suite.
#
# Usage: scripts/tb-screen.sh <out.tsv> [task-id ...]   (defaults to the manifest)
set -u
REPO="/home/jagones/Repositories/longrun"
cd "$REPO" || exit 1
TB_HOME="${TB_HOME:-/home/jagones/Repositories/terminal-bench}"
TB="$TB_HOME/.venv/bin/tb"
OUT="${1:-$REPO/.agent/BENCHMARKS/tb_arm64_screen.tsv}"
shift || true

if [ "$#" -ge 1 ]; then
  TASKS="$*"
else
  TASKS="$(grep -v '^#' "$REPO/benchmarks/terminal_bench_tasks.txt" | tr '\n' ' ')"
fi

mkdir -p "$(dirname "$OUT")"
[ -f "$OUT" ] || printf 'task\tscreen\tscope\tseconds\n' > "$OUT"

for t in $TASKS; do
  start=$(date +%s)
  if timeout 1500 "$TB" run -p "$TB_HOME/original-tasks" -t "$t" --agent oracle \
       --no-upload-results --no-cleanup --run-id "screen-$t" \
       --output-path "$TB_HOME/runs" > "/tmp/tb-screen-$t.log" 2>&1; then
    verdict=PASS
  else
    verdict=FAIL
  fi
  scope=$(grep -cE 'is_resolved": true' "$TB_HOME/runs/screen-$t/$t/"*/results.json 2>/dev/null || echo 0)
  secs=$(( $(date +%s) - start ))
  printf '%s\t%s\t%s\t%s\n' "$t" "$verdict" "$scope" "$secs" >> "$OUT"
  echo "$t $verdict ${secs}s"
  # keep the host clean: the screen image is not evidence
  docker rmi -f "$(docker images -q --filter "reference=*$t*")" >/dev/null 2>&1 || true
done
echo "wrote $OUT"
