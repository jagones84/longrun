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
# The provider list is read from LONGRUN_PROVIDERS (`model/providers.py:25`), NOT from
# LONGRUN_CONFIG_DIR: without this the server boots with the shipped providers
# (`dgx` + `openrouter`) and `bridge:<model>` resolves to nothing — measured 2026-11-01
# as `provider.unreachable` with the model still printed as `bridge:inspect` in the
# events, while a raw POST to the bridge from the same container answered 200.
export LONGRUN_PROVIDERS=/tmp/lr/config/providers.yaml
export LONGRUN_PROVIDERS_LOCAL=/tmp/lr/config/providers.local.yaml
export PYTHONPATH=/opt/longrun/src
export LR_API_KEY="${LR_API_KEY:-inspect}"
echo "[turn] base=${LR_BASE_URL:-<unset>} model=${LR_MODEL:-<unset>} steps=${LR_MAX_STEPS:-40}" >&2

# Start from the shipped config, then replace the provider list with ONE provider
# that points at the endpoint Inspect gave us (the real schema: a LIST of providers).
cp -a /opt/longrun/config/. /tmp/lr/config/ 2>/dev/null || true
# No user overlay: the shipped one only adds providers this sandbox cannot reach.
printf 'providers: []\n' > /tmp/lr/config/providers.local.yaml
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
sed -n '1,12p' /tmp/lr/config/providers.yaml >&2

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

# What the harness ITSELF resolved for the provider, so the probes below cannot hide a
# config the running server did not actually read.
try:
    _cat = json.loads(urllib.request.urlopen(
        "http://127.0.0.1:8791/api/providers", timeout=30).read())
    print("[catalog]", json.dumps(_cat)[:900], file=sys.stderr)
except Exception as _ce:  # noqa: BLE001
    print("[catalog] failed", repr(_ce), file=sys.stderr)

# Raw calls to the bridge, so a rejected request reports the bridge's own body
# instead of a bare 502 the harness can only summarize. The variants replicate the
# fields the harness actually sends (stream, stream_options, a long system prompt).
_base = os.environ.get("LR_BASE_URL", "")
if _base:
    _probes = [
        ("stream+options", {"model": model, "stream": True,
                            "stream_options": {"include_usage": True},
                            "temperature": 0.7,
                            "messages": [{"role": "user", "content": "say ok"}]}),
        ("long-system", {"model": model, "stream": False, "temperature": 0.7,
                         "messages": [{"role": "system", "content": "x" * 20000},
                                      {"role": "user", "content": "say ok"}]}),
    ]
    for _name, _payload in _probes:
        _r = urllib.request.Request(
            _base.rstrip("/") + "/chat/completions",
            data=json.dumps(_payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer inspect"}, method="POST")
        try:
            with urllib.request.urlopen(_r, timeout=120) as _x:
                print("[bridge-probe %s]" % _name, _x.status,
                      _x.read()[:160], file=sys.stderr)
        except Exception as _e:  # noqa: BLE001
            _err = getattr(_e, "read", lambda: b"")()
            print("[bridge-probe %s]" % _name, repr(_e)[:200],
                  _err[:600], file=sys.stderr)
    # Exactly what the harness does before every call (rllm._reachable): a bare TCP
    # connect + close. A server that does not tolerate a connection with no request
    # would look "unreachable" here and the harness would never send the call.
    try:
        import socket
        from urllib.parse import urlsplit
        _u = urlsplit(_base)
        _sock = socket.create_connection((_u.hostname, _u.port or 80), timeout=3)
        _sock.close()
        print("[reachable] ok", file=sys.stderr)
    except OSError as _re:
        print("[reachable] FAIL", repr(_re), file=sys.stderr)

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
try:
    out = post("/api/chat", {"session": sid, "message": q, "headless": True,
                             "model": "bridge:" + model,
                             "max_steps": int(os.environ.get("LR_MAX_STEPS", "40"))})
except Exception as exc:  # noqa: BLE001 — a failed turn must say WHY, not just 502
    print("chat failed: %r" % (exc,), file=sys.stderr)
    # The harness's durable record: the exact provider error and the failover chain.
    try:
        import sqlite3
        _db = sqlite3.connect("/tmp/lr/events.db")
        for _kind, _data in _db.execute(
                "SELECT kind, data FROM events WHERE kind IN "
                "('chat.error','model.failover','cost.usage','settings.diagnostic') "
                "ORDER BY id DESC LIMIT 8"):
            print("[event]", _kind, (_data or "")[:700], file=sys.stderr)
    except Exception as _db_exc:  # noqa: BLE001
        print("[event] unreadable: %r" % (_db_exc,), file=sys.stderr)
    try:
        print("\n".join(open("/tmp/lr-turn.log", encoding="utf-8",
                             errors="replace").read().splitlines()[-25:]), file=sys.stderr)
    except OSError:
        pass
    raise SystemExit(1)
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
