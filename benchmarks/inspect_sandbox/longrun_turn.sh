#!/usr/bin/env bash
# Turn driver for the LONGRUN arm inside an Inspect sandbox.
# Reads the question file, runs one headless turn, prints the final answer on stdout.
#
# The model endpoint and key arrive in the environment from the Inspect agent:
#   LR_BASE_URL  e.g. http://localhost:13131/v1   (the sandbox bridge)
#   LR_API_KEY   a placeholder; the bridge relays to the eval's real model
#   LR_MODEL     the model id to request
set -u
QFILE="${1:?question file}"
LOG=/tmp/lr-turn.log
mkdir -p /tmp/lr/data /tmp/lr/sessions /tmp/lr/config /tmp/lr/costs /tmp/lr/threads
export LONGRUN_CONFIG_DIR=/tmp/lr/config
export LONGRUN_SESSIONS_DIR=/tmp/lr/sessions
export LONGRUN_DATA_DIR=/tmp/lr/data
export LONGRUN_DB=/tmp/lr/events.db
export LONGRUN_COSTS_DIR=/tmp/lr/costs
export LONGRUN_THREADS_DIR=/tmp/lr/threads
export LONGRUN_TOKENS_OFF=1
export PYTHONPATH=/opt/longrun/src
export LR_API_KEY="${LR_API_KEY:-inspect}"

# Start from the shipped config, then replace the provider list with ONE provider
# that points at the endpoint Inspect gave us (the real schema: a LIST of providers).
cp -a /opt/longrun/config/. /tmp/lr/config/ 2>/dev/null || true
python3 - "$QFILE" <<'PY' > /dev/null
import os, pathlib
base = os.environ.get("LR_BASE_URL", "https://openrouter.ai/api/v1")
model = os.environ.get("LR_MODEL", "z-ai/glm-5.3-flash")
pathlib.Path("/tmp/lr/config/providers.yaml").write_text(
    'version: "1"\nenv_files: []\ndefault: bridge:%s\nproviders:\n'
    '  - id: bridge\n    name: Inspect bridge\n    kind: openai\n'
    '    base_url: %s\n    api_key_env: LR_API_KEY\n    models:\n'
    '      - {id: "%s"}\n' % (model, base, model))
PY

nohup python3 /opt/longrun/server.py --host 127.0.0.1 --port 8791 > "$LOG" 2>&1 &
SRV=$!
for _ in $(seq 1 60); do
  python3 - <<'PY' >/dev/null 2>&1 && break
import urllib.request
urllib.request.urlopen("http://127.0.0.1:8791/api/status", timeout=2)
PY
  sleep 1
done

python3 - "$QFILE" <<'PY'
import json, os, sys, urllib.request
q = open(sys.argv[1]).read()
model = os.environ.get("LR_MODEL", "z-ai/glm-5.3-flash")

def post(path, body):
    r = urllib.request.Request("http://127.0.0.1:8791" + path,
                              data=json.dumps(body).encode(),
                              headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(r, timeout=300) as x:
        return json.loads(x.read().decode())

post("/api/tools", {"approvals": {"mode": "full"}, "verifier": {"enabled": False}})
post("/api/routing", {"roles": {r: {"model": "bridge:" + model}
                               for r in ("chat", "agent", "subagent", "summarizer")}})
sid = post("/api/sessions", {"title": "gaia"})["id"]
post("/api/workspace", {"session": sid, "workspace": "/tmp/lr/data"})
out = post("/api/chat", {"session": sid, "message": q, "headless": True,
                         "model": "bridge:" + model,
                         "max_steps": int(os.environ.get("LR_MAX_STEPS", "40"))})
text = out.get("reply") or out.get("message") or ""
if isinstance(text, dict):
    text = text.get("content") or ""
print(text.strip() or "(no answer)")
try:
    c = json.loads(urllib.request.urlopen(
        "http://127.0.0.1:8791/api/costs?session=%s" % sid, timeout=10).read())
    t = c.get("total") or {}
    print("[usage] in=%s out=%s" % (t.get("tokens_in"), t.get("tokens_out")), file=sys.stderr)
except Exception:
    pass
PY
RC=$?
kill "$SRV" 2>/dev/null
exit $RC
