#!/usr/bin/env bash
# SWE-bench Verified — the SCREENED slice that runs on this aarch64 host.
#
# The official images are `sweb.eval.x86_64.*`: they cannot run here, and x86
# emulation is not allowed. This keeps the instance's OWN contract (base commit,
# test_patch, FAIL_TO_PASS/PASS_TO_PASS) on a host venv built with `uv`.
#
# Usage:
#   scripts/bench-swebench.sh check                 # offline dataset proof (500 rows)
#   scripts/bench-swebench.sh list [N]              # instance ids + f2p/p2p counts
#   scripts/bench-swebench.sh verify <instance>     # screen: gold passes, base fails
#   scripts/bench-swebench.sh run <instance> [arm]  # longrun (default) or openclaw
#
# Env: MODEL (allow-list, same policy as LHB: no local DGX model).
set -u
cd /home/jagones/Repositories/longrun || exit 1

MODE="${1:-check}"
MODEL="${MODEL:-openrouter:z-ai/glm-5.3-flash}"
case "$MODEL" in
  openrouter:z-ai/glm-5.3-flash|deepseek:deepseek-flash*) : ;;
  *)
    echo "refusing MODEL=$MODEL — allowed: openrouter:z-ai/glm-5.3-flash, deepseek:deepseek-flash" >&2
    exit 2
    ;;
esac

case "$MODE" in
  check)  exec python3 -m benchmarks.swebench_slice --check ;;
  list)   exec python3 -m benchmarks.swebench_slice --list "${2:-20}" ;;
  verify) exec python3 -m benchmarks.swebench_slice --verify "$2" ;;
  run)
    exec python3 -m benchmarks.swebench_slice --run "$2" \
      --arm "${3:-longrun}" --model "$MODEL"
    ;;
  *)
    echo "usage: $0 check|list [N]|verify <instance>|run <instance> [arm]" >&2
    exit 2
    ;;
esac
