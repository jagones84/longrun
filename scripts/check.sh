#!/usr/bin/env bash
# Longrun guardrail — the fast deterministic check to run after every edit.
#
#   bash scripts/check.sh                  # syntax + lint (ruff) + types (mypy)
#   bash scripts/check.sh --fast           # syntax + lint only (skips the slow mypy)
#   bash scripts/check.sh --require-tools  # a missing ruff/mypy is a failure (CI)
#
# It is a RATCHET, not a plain lint. The tree carries a known number of findings
# (scripts/guardrail-baseline.txt), so a fatal lint would be red on day one and get
# ignored; the guardrail instead fails only when a count INCREASES. A NEW unused
# import, undefined name or type slip is therefore caught in seconds, while the
# existing findings are paid down over time.
#
# This is the ONE definition of the repo's static analysis — tests/mega_test.sh calls
# it, so the two cannot drift.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

BASELINE_FILE="scripts/guardrail-baseline.txt"
TARGET="src/longrun"
REQUIRE_TOOLS=0
FAST=0
for arg in "$@"; do
  case "$arg" in
    --require-tools) REQUIRE_TOOLS=1 ;;
    --fast) FAST=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

# Prefer a project venv, else PATH.
tool() {
  if [ -x ".venv/bin/$1" ]; then echo ".venv/bin/$1"; else command -v "$1" 2>/dev/null; fi
}
base() { grep -E "^$1=" "$BASELINE_FILE" 2>/dev/null | head -1 | cut -d= -f2; }

FAIL=0
echo "-- Longrun guardrail ------------------------------------------"

# 1) syntax — fatal, zero dependencies, and NO bytecode left next to the source
#    (the repo's rule: a stale .pyc has made a test assert on an old function body).
PYC="$(mktemp -d "${TMPDIR:-/tmp}/lr-guardrail-XXXXXX")"
if PYTHONPYCACHEPREFIX="$PYC" python3 -m compileall -q "$TARGET" >/dev/null 2>&1; then
  echo "[1/3] syntax : OK"
else
  echo "[1/3] syntax : FAIL"
  PYTHONPYCACHEPREFIX="$PYC" python3 -m compileall -q "$TARGET" 2>&1 | head -5
  FAIL=1
fi
rm -rf "$PYC"

# 2) lint (ruff), ratcheted
if [ "$FAIL" = 0 ]; then
  RUFF="$(tool ruff)"
  if [ -z "$RUFF" ]; then
    echo "[2/3] lint   : SKIP (ruff not installed - pip install -r requirements-dev.txt)"
    [ "$REQUIRE_TOOLS" = 1 ] && FAIL=1
  else
    n="$("$RUFF" check "$TARGET" --output-format=json 2>/dev/null \
         | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null)"
    b="$(base ruff)"
    case "$n" in
      ""|*[!0-9]*)
        echo "[2/3] lint   : FAIL (ruff output not parseable)"
        "$RUFF" check "$TARGET" 2>&1 | tail -5
        FAIL=1 ;;
      *)
        if [ -n "$b" ] && [ "$n" -gt "$b" ]; then
          echo "[2/3] lint   : FAIL ($n findings > baseline $b)"
          "$RUFF" check "$TARGET" 2>&1 | head -15
          FAIL=1
        else
          echo "[2/3] lint   : OK ($n findings, baseline ${b:-none})"
        fi ;;
    esac
  fi
fi

# 3) types (mypy), ratcheted
if [ "$FAIL" = 0 ] && [ "$FAST" = 0 ]; then
  MYPY="$(tool mypy)"
  if [ -z "$MYPY" ]; then
    echo "[3/3] types  : SKIP (mypy not installed)"
    [ "$REQUIRE_TOOLS" = 1 ] && FAIL=1
  else
    n="$("$MYPY" "$TARGET" --ignore-missing-imports --follow-imports=silent --no-error-summary 2>&1 \
         | grep -c 'error:')"
    b="$(base mypy)"
    if [ -n "$b" ] && [ "$n" -gt "$b" ]; then
      echo "[3/3] types  : FAIL ($n errors > baseline $b)"
      "$MYPY" "$TARGET" --ignore-missing-imports --follow-imports=silent --no-error-summary 2>&1 \
        | grep 'error:' | head -15
      FAIL=1
    else
      echo "[3/3] types  : OK ($n errors, baseline ${b:-none})"
    fi
  fi
elif [ "$FAST" = 1 ] && [ "$FAIL" = 0 ]; then
  echo "[3/3] types  : skipped (--fast)"
fi

echo "---------------------------------------------------------------"
if [ "$FAIL" = 0 ]; then echo "guardrail: PASS"; else echo "guardrail: FAIL"; fi
exit "$FAIL"
