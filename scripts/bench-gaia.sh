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
  # FRESHNESS: the arm ships this code INTO the task container, so an image built
  # before the last edit silently benchmarks the old harness (measured 2026-11-01:
  # a smoke run graded a fix that was not in the image). Rebuild, never assume.
  _img_epoch=$(docker image inspect "$IMAGE" --format '{{.Created}}' 2>/dev/null \
               | xargs -r -I{} date -d {} +%s 2>/dev/null || echo 0)
  _src_epoch=$(find "$REPO/src" "$REPO/config" "$REPO/server.py" \
                    "$REPO/benchmarks/inspect_sandbox" -printf '%T@\n' 2>/dev/null \
               | sort -n | tail -1 | cut -d. -f1)
  say "   image built $(date -d "@${_img_epoch:-0}" '+%Y-%m-%d %H:%M:%S'), source touched $(date -d "@${_src_epoch:-0}" '+%Y-%m-%d %H:%M:%S')"
  if [ "${_src_epoch:-0}" -gt "${_img_epoch:-0}" ]; then
    say "   STALE: the image predates the source — rebuilding"
    bash "$REPO/benchmarks/inspect_sandbox/build_image.sh" >/dev/null 2>&1 \
      || die "rebuild failed — run build_image.sh by hand to see why"
  fi
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
  # PRESENT is not USABLE. Measured 2026-11-01: run `final5` started with a key at its
  # spend limit and every sample of BOTH arms answered `403 Key limit exceeded` — twelve
  # minutes of wall clock and a 0/12 that looks like a harness regression. Ask the
  # provider how much budget is left before the first container starts.
  _kr=$(curl -s -m 20 -H "Authorization: Bearer $OPENROUTER_API_KEY" \
             https://openrouter.ai/api/v1/key 2>/dev/null \
        | .venv/bin/python3 -c 'import json,sys
try:
    d = json.load(sys.stdin).get("data") or {}
except Exception:
    raise SystemExit(3)
lim, rem, use = d.get("limit"), d.get("limit_remaining"), d.get("usage")
print("%s %s %s" % (lim, rem, use))
raise SystemExit(0 if (lim is None or (rem or 0) > 0) else 4)')
  case "$?" in
    0) say "   budget: limit=${_kr%% *} (unlimited when empty) — usable" ;;
    3) say "   budget: /api/v1/key unreadable — continuing (a 403 will surface in the log)" ;;
    *) die "the key has NO budget left ($_kr = limit remaining usage) — the run would score 0/12 on both arms. Raise the key's limit, then re-run." ;;
  esac

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
  # The containers die with the trial, so each arm lifts its own record here (every
  # message, every event, the plan): a lost sample is then readable without paying
  # for a re-run. `scripts/gaia_postmortem.py` reads this folder.
  export GAIA_FORENSIC_DIR="$REPO/.agent/BENCHMARKS/forensic/$tag"
  mkdir -p "$GAIA_FORENSIC_DIR"
  say "starting $arm: n=$n model=$MODEL timeout=${ARM_TIMEOUT}s sandbox=$(basename "$SBX")"
  nohup env ARM_TIMEOUT="$ARM_TIMEOUT" ARM_MAX_STEPS="$ARM_MAX_STEPS" \
    GAIA_FORENSIC_DIR="$GAIA_FORENSIC_DIR" \
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
