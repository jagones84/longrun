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
    d = {}
final = (d.get("final") or "").strip()
if not final:
    # An empty final is a HARNESS answer of nothing: say why, on stderr, so the
    # Inspect log carries the diagnosis (measured 2026-11-01: the run printed
    # no-answer and the error lived only inside the sandbox).
    sys.stderr.write("[oc] rc=%r ok=%r status=%r\n" % (d.get("rc"), d.get("ok"), d.get("status")))
    sys.stderr.write("[oc] envelope=%s\n" % (raw[:600] or "<empty stdout>"))
    try:
        sys.stderr.write("[oc] err.log:\n%s\n" % open("/tmp/oc/err.log", encoding="utf-8",
                                                       errors="replace").read()[-2500:])
    except OSError:
        pass
    raise SystemExit(1)
print(final)
'
