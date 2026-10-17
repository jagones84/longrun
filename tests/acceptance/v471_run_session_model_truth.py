#!/usr/bin/env python3
"""v471 — a run's model and its session's model are the SAME model (JAG-478).

Operator report: a Paperclip task's session showed `deepseek:deepseek-reasoner`
in the composer while the run really executed on the LOCAL role model. Two
INDEPENDENT resolutions of "which model?" can drift; this test locks ONE.

Root cause (proved by reading the code, not guessed):
  * the chat honours the session's model — `resolve_ctx_model(ctx_model)`;
  * `POST /api/agent/run/stream` did NOT: it forwarded `body["model"]` (None for
    Paperclip) straight into `agent_run_v2`, which then resolved the ROLE hint
    (`pick("agent")` = local weights). The session was read for its WORKSPACE
    only, never for its model;
  * the session JAG-476 auto-creates recorded NO model, so the composer fell back
    to the global `localStorage.sf_model` — a label with no relation to the run.

Contract locked here:
  * an explicit `model` in the run body wins;
  * else the SESSION's own model is authoritative (the same rule as chat) — a
    session pinned to X must RUN on X;
  * else the role-routing hint resolves it (unchanged behaviour);
  * whichever ref the run was launched with is RECORDED on the session it runs
    in, including the auto-created one, so the WebUI can never display a model
    the run did not use.

Deterministic: the run worker is stubbed, so no provider/model is contacted.
Isolated: throwaway LONGRUN_* dirs.

Run: python3 tests/acceptance/v471_run_session_model_truth.py
"""
import io
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="sf-v471-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR",
           "ROLES_DIR", "DATA_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_PRICES_FILE"] = os.path.join(TMP, "prices.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as API  # noqa: E402
from longrun.memory import stores as STORES  # noqa: E402

RESULTS = []
CALLS = []
ROUTED = []

PIN = "deepseek:deepseek-reasoner"


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


class _WFile(io.BytesIO):
    def flush(self):
        pass


class _Conn:
    def setsockopt(self, *a):
        pass

    def shutdown(self, *a):
        pass


class FakeHandler:
    """Minimal stand-in for the HTTP handler used by the SSE writer."""

    def __init__(self):
        self.wfile = _WFile()
        self.connection = _Conn()
        self.close_connection = False
        self.resp_code = None
        self.headers = []
        self.sent = None

    def send_response(self, code):
        self.resp_code = code

    def send_header(self, k, v):
        self.headers.append((k, v))

    def end_headers(self):
        pass

    def _send(self, code, obj):
        self.sent = (code, obj)


def post_stream(body):
    h = FakeHandler()
    API.handle(h, "POST", "/api/agent/run/stream", {}, body)
    return h


# --- stubbed run worker: records the model it was handed ---------------------
def _scripted_run(goal, max_steps=6, model=None, on_event=None, script=None,
                  run_id=None, workspace=None, fallbacks=None):
    CALLS.append({"goal": goal, "max_steps": max_steps, "model": model,
                  "run_id": run_id})
    on_event("agent.start", run=run_id, goal=goal, max_steps=max_steps)
    st = API.run_get(run_id)
    if st is not None:
        st.status, st.termination, st.summary = "done", "completed", "scripted done"
    on_event("agent.finish", run=run_id, summary="scripted done", termination="completed")
    return {"run_id": run_id, "goal": goal, "model": model, "status": "done",
            "termination": "completed", "summary": "scripted done", "trace": [], "prm": None}


def _routed(goal):
    """Stub of the role-routing resolution, so a non-pinned case is deterministic."""
    ROUTED.append(goal)
    return "local:routed-agent"


_ORIG_RUN = API.agent_run_v2
_ORIG_ROUTED = getattr(API, "_routed_agent_model", None)
API.agent_run_v2 = _scripted_run
API._routed_agent_model = _routed
try:
    # --- 1: a session pinned to X RUNS on X ----------------------------------
    pinned = STORES.get_or_create_session("sess-pinned", "pinned task")
    API._srv()._set_session_model("sess-pinned", PIN)
    ROUTED[:] = []
    before = len(CALLS)
    post_stream({"goal": "reply with pong", "session": "sess-pinned"})
    check("test_a_pinned_session_drives_the_run_model",
          len(CALLS) == before + 1 and CALLS[-1]["model"] == PIN,
          "model=%r" % (CALLS[-1]["model"] if CALLS else None))
    check("test_a_pinned_session_never_consults_the_roles",
          ROUTED == [], "routed=%r" % (ROUTED,))

    # --- 2: the auto-created session RECORDS the model the run used ----------
    ROUTED[:] = []
    post_stream({"goal": "summarize the repo"})
    used = CALLS[-1]["model"] if CALLS else None
    created = [s for s in STORES.list_sessions() if s.get("title") == "summarize the repo"]
    sd = STORES.load_session(created[0]["id"]) if created else {}
    check("test_the_self_created_session_records_the_model_that_ran",
          len(created) == 1 and (sd or {}).get("model") == used and used == "local:routed-agent",
          "recorded=%r used=%r" % ((sd or {}).get("model"), used))
    check("test_the_unpinned_case_still_routes_by_role",
          ROUTED == ["summarize the repo"], "routed=%r" % (ROUTED,))

    # --- 3: an explicit body model wins over the session pin -----------------
    post_stream({"goal": "reply with pong", "session": "sess-pinned",
                 "model": "openrouter:acme/big"})
    check("test_an_explicit_body_model_beats_the_session_pin",
          CALLS[-1]["model"] == "openrouter:acme/big",
          "model=%r" % CALLS[-1]["model"])
    check("test_an_explicit_body_model_is_recorded_on_the_session",
          (STORES.load_session("sess-pinned") or {}).get("model") == "openrouter:acme/big",
          "recorded=%r" % (STORES.load_session("sess-pinned") or {}).get("model"))

    # --- 4: the routed model is recorded too (no session supplied) -----------
    routed_sess = [s for s in STORES.list_sessions()
                   if s.get("title") == "summarize the repo"]
    check("test_every_run_lands_its_model_on_the_session_it_ran_in",
          len(routed_sess) == 1
          and routed_sess[0].get("model") == CALLS[1]["model"],
          "sessions=%d" % len(routed_sess))
finally:
    API.agent_run_v2 = _ORIG_RUN
    if _ORIG_ROUTED is not None:
        API._routed_agent_model = _ORIG_ROUTED


# --- 5: source locks: ONE resolver, used by BOTH the run and the session -----
with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8") as f:
    AV = f.read()
with open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8") as f:
    HA = f.read()

check("test_the_single_resolver_exists",
      "def agent_model_for(" in AV and "def _routed_agent_model(" in AV)
check("test_the_stream_route_resolves_then_records",
      "agent_model_for(goal, model, visible)" in AV
      and "_set_session_model(visible[\"id\"]" in AV)
check("test_the_agent_loop_reuses_the_same_resolver",
      "model = model or _routed_agent_model(goal)" in AV)
check("test_the_chat_keeps_the_same_precedence",
      "def resolve_ctx_model(" in HA and "return (sess.get(\"model\") if sess else None) or default_model()" in HA)

print("---")
ok = sum(RESULTS)
print("%d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
