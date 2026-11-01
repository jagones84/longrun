#!/usr/bin/env bash
# GAIA level 1, the SAME questions and the SAME model for both harnesses.
#
#   scripts/bench-gaia.sh preflight                 # the rig, no model call
#   scripts/bench-gaia.sh <longrun|openclaw|both> [n] [tag]
#
# What makes the comparison a comparison:
#   * the model is the eval's model — the sandbox bridge relays every harness call to
#     it, so neither arm picks its own LLM;
#   * the questions are PINNED by id in benchmarks/gaia_instances.txt (first n), so
#     both arms answer exactly the same questions and the run is reproducible;
#   * the sandbox is benchmarks/inspect_sandbox/compose.yaml, which has a NETWORK:
#     Inspect hard-codes `network_mode: none` in the compose it generates for a
#     Dockerfile, and GAIA is a web benchmark — without this the arms answered from
#     memory (measured 2026-11-01: every fetch died on `dns resolution failed`);
#   * the scorer is the official GAIA one (copied verbatim into inspect_evals), so a
#     number must BE a number: `17 Note: …` is not 17.
#
# Env: GAIA_MODEL (openrouter/z-ai/glm-5.3-flash), ARM_TIMEOUT (600 s/sample),
#      ARM_MAX_STEPS (40, longrun only), MAX_CONN (2 samples at a time).
#
# The run is detached (a benchmark outlives a terminal) and its log is the handle:
#   tail -f .agent/logs/gaia_<arm>_<n>_<stamp>.log
set -u
REPO=/home/jagones/Repositories/longrun
IE=/home/jagones/Repositories/inspect_evals
SBX="$REPO/benchmarks/inspect_sandbox/compose.yaml"
IMAGE=inspect-arms:latest
MODEL="${GAIA_MODEL:-openrouter/z-ai/glm-5.3-flash}"
ARM_TIMEOUT="${ARM_TIMEOUT:-600}"
ARM_MAX_STEPS="${ARM_MAX_STEPS:-40}"
MAX_CONN="${MAX_CONN:-2}"
MANIFEST="$REPO/benchmarks/gaia_instances.txt"

cd "$IE" || exit 1
set -a
. /home/jagones/.hermes/.env 2>/dev/null || true
set +a

say() { printf '%s\n' "$*"; }
die() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- preflight ---
preflight() {
  say "== 1. image"
  docker image inspect "$IMAGE" >/dev/null 2>&1 \
    || bash "$REPO/benchmarks/inspect_sandbox/build_image.sh" >/dev/null 2>&1
  docker image inspect "$IMAGE" --format '   {{.RepoTags}} {{.Size}}' || die "no $IMAGE"
  say "   drivers in image:"
  docker run --rm --entrypoint bash "$IMAGE" -lc \
    'ls -l /opt/longrun/longrun_turn.sh /opt/longrun/openclaw_turn.sh | sed "s/^/   /"' \
    || die "the turn drivers are missing from the image"

  say "== 2. network (the point of the compose file)"
  docker run --rm --network bridge --entrypoint bash "$IMAGE" -lc \
    'getent hosts en.wikipedia.org >/dev/null || { echo "   no DNS"; exit 3; }; \
     code=$(curl -s -o /dev/null -w "%{http_code}" https://en.wikipedia.org/wiki/Mercedes_Sosa); \
     echo "   https://en.wikipedia.org -> $code"; test "$code" = 200' \
    || die "the sandbox image has no working network"

  say "== 3. offline control (proves the failure mode is real, not imagined)"
  docker run --rm --network none --entrypoint bash "$IMAGE" -lc \
    'python3 - <<PY
import socket
try:
    socket.getaddrinfo("en.wikipedia.org", 443)
except OSError as exc:
    print("   offline as expected:", exc)
else:
    raise SystemExit("DNS resolved without a network!?")
PY' || die "the --network none control did not fail"

  say "== 4. model key"
  [ -n "${OPENROUTER_API_KEY:-}" ] || die "OPENROUTER_API_KEY missing (source ~/.hermes/.env)"
  say "   model: $MODEL  (key present, value never printed)"

  say "== 5. dataset"
  .venv/bin/python3 - <<PY || die "GAIA dataset unavailable"
from inspect_evals.gaia.dataset import gaia_dataset
ds = gaia_dataset(subset="2023_level1", split="validation")
ids = [s.id for s in ds]
want = [l.strip() for l in open("$MANIFEST") if l.strip() and not l.startswith("#")]
missing = [w for w in want if w not in ids]
print("   validation samples:", len(ids), "| pinned:", len(want), "| missing:", missing)
raise SystemExit(1 if missing else 0)
PY
  say "== preflight OK — the rig is exactly what the run will use"
}

# -------------------------------------------------------------------- run ----
run_arm() {  # arm n tag
  local arm="$1" n="$2" tag="$3"
  local ids log
  if [ -n "${GAIA_IDS:-}" ]; then
    # A smoke test needs ONE named sample (e.g. the one that can only be answered by
    # reading a live page), not the first n of the pinned list.
    ids=$(.venv/bin/python3 -c 'import json,os,sys;print(json.dumps(os.environ["GAIA_IDS"].split(",")))')
  else
    ids=$(.venv/bin/python3 - "$MANIFEST" "$n" <<'PY'
import json, sys
lines = [l.strip() for l in open(sys.argv[1]) if l.strip() and not l.startswith("#")]
print(json.dumps(lines[:int(sys.argv[2])]))
PY
)
  fi
  log="$REPO/.agent/logs/gaia_${arm}_${n}_${tag}.log"
  [ -e "$log" ] && die "run log already exists: $log (one invocation per question)"
  say "starting $arm: n=$n model=$MODEL timeout=${ARM_TIMEOUT}s sandbox=$(basename "$SBX")"
  nohup env ARM_TIMEOUT="$ARM_TIMEOUT" ARM_MAX_STEPS="$ARM_MAX_STEPS" \
    .venv/bin/inspect eval inspect_evals/gaia \
    -T subset=2023_level1 \
    -T "instance_ids=$ids" \
    --sandbox "docker:$SBX" \
    --solver "$REPO/benchmarks/inspect_arms.py@${arm}_arm" \
    --model "$MODEL" \
    --max-connections "$MAX_CONN" \
    --log-dir "$REPO/.agent/BENCHMARKS/runs/gaia" \
    --epochs 1 > "$log" 2>&1 &
  say "  pid=$! log=$log"
}

case "${1:-}" in
  preflight)
    preflight
    ;;
  longrun|openclaw)
    preflight >/dev/null || die "preflight failed — run 'scripts/bench-gaia.sh preflight'"
    run_arm "$1" "${2:-6}" "${3:-$(date +%H%M%S)}"
    ;;
  both)
    preflight >/dev/null || die "preflight failed — run 'scripts/bench-gaia.sh preflight'"
    STAMP="${3:-$(date +%H%M%S)}"
    run_arm longrun "${2:-6}" "$STAMP"
    run_arm openclaw "${2:-6}" "$STAMP"
    ;;
  *)
    sed -n '2,12p' "$0"
    exit 2
    ;;
esac
