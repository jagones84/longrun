#!/usr/bin/env bash
# Turn driver for the OPENCLAW arm inside an Inspect sandbox.
# Reads the question file, runs one headless embedded turn, prints the final answer.
#
# Env from the Inspect agent:
#   OC_BASE_URL  http://localhost:<bridge port>/v1
#   OC_API_KEY   placeholder (the bridge relays to the eval's model)
#   OC_MODEL     model id to request (openclaw spells providers `openai/<id>`)
set -u
QFILE="${1:?question file}"
mkdir -p /tmp/oc/work
export OPENAI_BASE_URL="${OC_BASE_URL:-http://localhost:13131/v1}"
export OPENAI_API_KEY="${OC_API_KEY:-inspect}"
MODEL="${OC_MODEL:-z-ai/glm-5.3-flash}"

/opt/oc/node /opt/oc/openclaw/openclaw.mjs agent exec \
  --isolated --auth-env-only --model "openai/$MODEL" --cwd /tmp/oc/work \
  --timeout "${OC_TIMEOUT:-1200}" --json --message-file "$QFILE" \
  2> /tmp/oc/err.log \
| python3 -c '
import json, sys
raw = sys.stdin.read()
try:
    d = json.loads(raw)
except Exception:
    print((raw or "").strip() or "(no answer)")
    raise SystemExit(0)
print((d.get("final") or "").strip() or "(no answer)")
'
