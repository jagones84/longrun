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
# The per-CALL model timeout is the caller's budget, not an undocumented 300 s cap:
# measured 2026-11-01 (`46719c30`, `ec09fa32`) the turn budget was 600 s but each
# model call died at 300 s twice, and the arm answered nothing.
export LONGRUN_MODEL_CALL_TIMEOUT="${LR_TURN_TIMEOUT:-1800}"
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
# The HTTP call waits for the WHOLE turn, so its timeout must be the turn budget —
# not a smaller number nobody configured. Measured 2026-11-01: a 300 s client timeout
# threw away a GAIA turn that was still reasoning (its answer was already persisted).
# A client timeout that fires BEFORE the sandbox's own deadline is a silent loss: the
# server keeps working, the arm returns "", and the scorer records "no answer".
TURN_TIMEOUT = int(os.environ.get("LR_TURN_TIMEOUT", "1800"))

def post(path, body):
    r = urllib.request.Request("http://127.0.0.1:8791" + path,
                              data=json.dumps(body).encode(),
                              headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(r, timeout=TURN_TIMEOUT) as x:
        return json.loads(x.read().decode())

def get(path, timeout=30):
    with urllib.request.urlopen("http://127.0.0.1:8791" + path, timeout=timeout) as x:
        return json.loads(x.read().decode())

def persisted_reply(sid):
    """The last assistant message the harness already saved for this session.

    A transport failure (timeout, dropped socket) does not unsay an answer: the turn
    keeps running server-side and persists its reply. Returning that is the difference
    between "the arm answered" and "the arm reported its own plumbing".
    """
    try:
        sess = get("/api/sessions/%s" % sid)
    except Exception:  # noqa: BLE001
        return ""
    for m in reversed(sess.get("messages") or []):
        if str(m.get("role") or "") != "assistant":
            continue
        c = m.get("content")
        if isinstance(c, dict):
            c = c.get("content") or c.get("text") or ""
        elif isinstance(c, list):
            c = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
        if str(c or "").strip():
            return str(c)
    return ""

def diag(tag):
    """Why the turn produced no answer: the durable events, then the server log tail."""
    print("[turn] %s: no reply" % tag, file=sys.stderr)
    try:
        import sqlite3
        _db = sqlite3.connect("/tmp/lr/events.db")
        for _kind, _data in _db.execute(
                "SELECT kind, data FROM events WHERE kind IN "
                "('chat.error','model.failover','cost.usage','settings.diagnostic',"
                "'plan.no_valid_action','plan.stopped') ORDER BY id DESC LIMIT 8"):
            print("[event]", _kind, (_data or "")[:700], file=sys.stderr)
    except Exception as _db_exc:  # noqa: BLE001
        print("[event] unreadable: %r" % (_db_exc,), file=sys.stderr)
    try:
        print("\n".join(open("/tmp/lr-turn.log", encoding="utf-8",
                             errors="replace").read().splitlines()[-25:]), file=sys.stderr)
    except OSError:
        pass
    return tag


def dump_forensic(sid, text, error=""):
    """Everything needed to reconstruct the turn, in one file the arm can read out.

    The container is DESTROYED when the trial ends, so the session store, the plan
    and the events DB die with it and a lost sample can only be explained by
    re-running it (measured 2026-11-01). The answer is graded; this file is the
    diagnosis: every message, every durable event, the plan, the workspace listing,
    the transport error and the server log tail.
    """
    rec = {"answer": text, "session": sid, "question": q[:4000], "error": error}
    try:
        rec["server_log"] = "\n".join(
            open("/tmp/lr-turn.log", encoding="utf-8", errors="replace")
            .read().splitlines()[-60:])
    except OSError:
        pass
    try:
        rec["plan"] = get("/api/sessions/%s/graph" % sid, timeout=20)
    except Exception as exc:  # noqa: BLE001
        rec["plan_error"] = repr(exc)
    try:
        sess = get("/api/sessions/%s" % sid, timeout=20)
        msgs = []
        for m in (sess.get("messages") or [])[-200:]:
            c = m.get("content")
            if not isinstance(c, str):
                c = json.dumps(c, ensure_ascii=False)
            msgs.append({"role": m.get("role"), "content": c[:6000]})
        rec["messages"] = msgs
        rec["turns"] = sum(1 for m in msgs if m.get("role") == "assistant")
    except Exception as exc:  # noqa: BLE001
        rec["messages_error"] = repr(exc)
    try:
        import sqlite3
        _db = sqlite3.connect("/tmp/lr/events.db")
        rec["events"] = [
            {"ts": r[0], "kind": r[1], "data": str(r[2] or "")[:2000]}
            for r in _db.execute("SELECT ts, kind, data FROM events ORDER BY id")]
    except Exception as exc:  # noqa: BLE001
        rec["events_error"] = repr(exc)
    try:
        out = []
        for root, _dirs, files in os.walk("/tmp/lr/data"):
            for f in files:
                p = os.path.join(root, f)
                try:
                    out.append({"path": p, "size": os.path.getsize(p)})
                except OSError:
                    pass
        rec["workspace"] = out[:200]
    except Exception:  # noqa: BLE001
        pass
    try:
        with open("/tmp/lr/forensic.json", "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        print("[turn] forensic dump failed: %r" % (exc,), file=sys.stderr)


post("/api/tools", {"approvals": {"mode": "full"}, "verifier": {"enabled": False}})
post("/api/routing", {"roles": {r: {"model": "bridge:" + model}
                               for r in ("chat", "agent", "subagent", "summarizer")}})
sid = post("/api/sessions", {"title": "gaia"})["id"]
post("/api/workspace", {"session": sid, "workspace": "/tmp/lr/data"})
text = ""
_err = ""
try:
    out = post("/api/chat", {"session": sid, "message": q, "headless": True,
                             "model": "bridge:" + model,
                             "max_steps": int(os.environ.get("LR_MAX_STEPS", "40"))})
    text = out.get("reply") or out.get("message") or ""
    if isinstance(text, dict):
        text = text.get("content") or ""
except Exception as exc:  # noqa: BLE001 — a failed turn must say WHY, not just 502
    _err = repr(exc)
    print("chat failed: %r" % (exc,), file=sys.stderr)
    text = persisted_reply(sid)
    print("[turn] persisted reply: %s" % ("yes" if text.strip() else "no"), file=sys.stderr)
    if not text.strip():
        diag("transport failed")
        # The turn is not over because our client gave up: the harness is still
        # working server-side. Measured 2026-11-01 (`72e110e7`, 26 turns, 44 tool
        # calls): the client timed out at 390 s, the arm returned "", and the scorer
        # recorded "no answer" for work that was still in flight. Bounded wait.
        import time as _t
        for _i in range(15):
            _t.sleep(3)
            text = persisted_reply(sid)
            if text.strip():
                print("[turn] late reply captured %ds after the client timeout"
                      % (3 * (_i + 1)), file=sys.stderr)
                break

dump_forensic(sid, text, _err)

# The scorer compares the ANSWER: the harness's own think markup must not travel with
# it (measured 2026-11-01: the reply began with `<think signature="reasoning-details://…">`
# and GAIA scored it wrong although the answer was inside).
try:
    from longrun.util.textkit import strip_think
    text, _think = strip_think(text)
except Exception as _se:  # noqa: BLE001
    print("[turn] strip_think unavailable: %r" % (_se,), file=sys.stderr)
clean = text.strip()
if not clean:
    # An empty reply is a FAILURE, not an answer: say so on stdout (a bare "(no answer)"
    # told the operator nothing) and dump the durable reason on stderr.
    # Measured 2026-11-01: two GAIA samples were graded on this marker while the cause
    # (a reasoning-only model message, an aborted turn) was only in the events DB.
    diag("empty reply")
    print("(no answer: the harness returned an empty reply)")
    raise SystemExit(1)
print(clean)
PY
RC=$?
kill "$SRV" 2>/dev/null
exit $RC
