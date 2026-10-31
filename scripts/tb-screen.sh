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
    rc=0
  else
    rc=1
  fi
  # A trial writes its results.json at a depth that is NOT fixed: this tb version puts
  # the AGGREGATE at `<run>/results.json` and a per-trial COPY two levels down. A
  # one-level glob found nothing and scored EVERY task FAIL (measured 2026-10-31 on
  # port-compressor); walking everything would count each trial twice. Read the
  # aggregate when it exists, and walk only as a fallback.
  scope=$(python3 - "$TB_HOME/runs/screen-$t" <<'PY' 2>/dev/null || echo 0/0
import json, os, sys
root = sys.argv[1]

def rows_of(path):
    try:
        d = json.load(open(path))
    except Exception:
        return None
    rows = d.get("results") if isinstance(d, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else None

rows = rows_of(os.path.join(root, "results.json"))
if rows is None:
    rows = []
    for dirpath, _dirs, files in os.walk(root):
        if "results.json" in files:
            rows.extend(rows_of(os.path.join(dirpath, "results.json")) or [])
print("%d/%d" % (sum(1 for r in rows if r.get("is_resolved")), len(rows)))
PY
)
  scope="${scope:-0/0}"
  # `tb` exits 0 even when the trial produced NO row (a build failure inside the task
  # is reported per-trial, not as an exit code). A pass with no trial row is not a
  # pass — measured 2026-10-31 on build-pmars, which read PASS/0 and would have entered
  # the suite with nothing behind it. `scope` is now `<resolved>/<trials>`.
  if [ "$rc" -eq 0 ] && [ "${scope%%/*}" -gt 0 ]; then
    verdict=PASS
  else
    verdict=FAIL
  fi
  secs=$(( $(date +%s) - start ))
  printf '%s\t%s\t%s\t%s\n' "$t" "$verdict" "$scope" "$secs" >> "$OUT"
  echo "$t $verdict ${secs}s"
  # keep the host clean: the screen image is not evidence
  docker rmi -f "$(docker images -q --filter "reference=*$t*")" >/dev/null 2>&1 || true
done
echo "wrote $OUT"
