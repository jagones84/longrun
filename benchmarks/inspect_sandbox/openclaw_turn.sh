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
# openclaw needs a HOME it can write its catalog/state into.
export HOME="${HOME:-/root}"
mkdir -p "$HOME" 2>/dev/null || true
export OPENAI_BASE_URL="${OC_BASE_URL:-http://localhost:13131/v1}"
export OPENAI_API_KEY="${OC_API_KEY:-inspect}"
MODEL="${OC_MODEL:-z-ai/glm-5.3-flash}"

# openclaw refuses a model id that its catalog does not contain ("Unknown model:
# openai/inspect"), and `--isolated` has no catalog at all. So the run carries its own
# config: one provider (`api: openai-completions`) whose single model is named the way
# the sandbox bridge answers, `inspect`. Schema from openclaw's own
# docs/providers/litellm.md (baseUrl + api + models[]).
CFG=/tmp/oc/config.json
python3 - "$CFG" <<'PY'
import json, os, sys
# The bridge serves `<origin>/v1/chat/completions`, and an `openai-completions`
# provider APPENDS `/chat/completions` to baseUrl: stripping the `/v1` sent the turn
# to `http://localhost:<port>/chat/completions` and the bridge answered 404, which
# openclaw surfaces as the misleading "This model was not found" (measured 2026-11-01
# from the sandbox err.log: `status=404 rawError=404 Path /chat/completions not found`).
base = os.environ.get("OC_BASE_URL", "http://localhost:13131/v1").rstrip("/")
# openclaw's own idle timeout is 300 s per model call, and the sandbox model streams
# slowly through the bridge: two GAIA samples died on `LLM idle timeout (300s)` while
# longrun was still working (measured 2026-11-01). The error message names the knob —
# `models.providers.<id>.timeoutSeconds` and `agents.defaults.timeoutSeconds` — so a
# run budget of OC_TIMEOUT is written into BOTH, keeping the arms on one clock.
_budget = int(os.environ.get("OC_TIMEOUT", "1200"))
cfg = {
    "models": {"mode": "replace", "providers": {"litellm": {
        "baseUrl": base,
        "apiKey": os.environ.get("OC_API_KEY", "inspect"),
        "api": "openai-completions",
        "timeoutSeconds": _budget,
        "models": [{"id": os.environ.get("OC_MODEL", "inspect"),
                    "name": "Inspect sandbox bridge",
                    "contextWindow": 200000, "maxTokens": 32000}],
    }}},
    "agents": {"defaults": {"timeoutSeconds": _budget, "model": {
        "primary": "litellm/" + os.environ.get("OC_MODEL", "inspect")}}},
}
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(cfg, fh)
sys.stderr.write("[oc] config=%s\n" % json.dumps(cfg))
PY

/opt/oc/node /opt/oc/openclaw/openclaw.mjs agent exec \
  --config "$CFG" --model "litellm/$MODEL" --cwd /tmp/oc/work \
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
