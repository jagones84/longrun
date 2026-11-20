#!/usr/bin/env python3
"""v1243 — the post-turn completeness verifier (the operator's "generic verifier").

Operator, 2026-11-20: *"non doveva esserci dopo ogni fine messaggio (che non
prosegue naturalmente con continuing involvement) una LLM call in versione
verificatore che il suo stesso ultimo messaggio non abbia lasciato lavoro
incompiuto? … non basterebbe vedere todo aperti perché potrebbe non esserci."*

After a turn that produced a final answer, an INDEPENDENT model reads ONLY the
operator's request + the agent's own final message + the still-open plan steps
and returns `{complete, missing}`. On `complete=false` the harness gives the agent
at most `turn_verify.max_rounds` more round(s) — bounded, so no infinite loop. It
shares ONE judge call with the L3 goal judge (`plan/judge.py`).

Deterministic and offline: a scripted model + a scripted verifier, no network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v1243-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
for d in ("cfg", "sessions", "graphs", "data"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}

from longrun.core import server  # noqa: E402
from longrun.agent import agent as A  # noqa: E402
from longrun.plan import judge as JUDGE  # noqa: E402
from longrun.plan import turn_verify as TV  # noqa: E402

SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
           encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- A: the shared judge call ----------------------------------------------
_orig_router = getattr(server, "_router_stream", None)


def _with_router(fn):
    server._router_stream = fn


_with_router(lambda msgs, model, on_delta, **kw: ('noise {"a": 1} tail', ""))
check("A1 ask_json parses the first JSON object in a noisy reply",
      JUDGE.ask_json("p", "m") == {"a": 1}, JUDGE.ask_json("p", "m"))
_with_router(lambda msgs, model, on_delta, **kw: ("plain text, no json", ""))
check("A2 ask_json returns _raw when the reply holds no JSON",
      "_raw" in JUDGE.ask_json("p", "m"), JUDGE.ask_json("p", "m"))


def _boom(*a, **k):
    raise RuntimeError("no model")


_with_router(_boom)
check("A3 no model -> None (a silent judge, never a failure)",
      JUDGE.ask_json("p", "m") is None)
if _orig_router is not None:
    server._router_stream = _orig_router

# ---- B: the config section --------------------------------------------------
cfg = TV.config()
check("B1 turn_verify reads the YAML with the operator's defaults",
      cfg.get("enabled") is True and cfg.get("model") == "openrouter:z-ai/glm-5.3-flash"
      and int(cfg.get("max_rounds")) >= 1, cfg)
check("B2 it is a real config section (defaults owner + merge list)",
      '"turn_verify": {}' in open(os.path.join(REPO, "src", "longrun", "tools",
                                               "registry.py"), encoding="utf-8").read()
      and "turn_verify:" in open(os.path.join(REPO, "config", "tools.yaml"),
                                 encoding="utf-8").read())

# ---- C: verify_turn mapping -------------------------------------------------
_orig_ask = TV.judge.ask_json
TV.judge.ask_json = lambda prompt, model=None: {"complete": False, "missing": ["n1 not done"]}
_v = TV.verify_turn("do X", "ho finito", ["n1 not done"])
check("C1 complete=false maps to ok=False with the missing list",
      _v == {"ok": False, "missing": ["n1 not done"]}, _v)
TV.judge.ask_json = lambda prompt, model=None: {"complete": True, "missing": []}
check("C2 complete=true maps to ok=True", TV.verify_turn("do X", "done")["ok"] is True)
TV.judge.ask_json = lambda prompt, model=None: {"_raw": "garbage"}
check("C3 an unparseable verdict is 'no verdict' (None)",
      TV.verify_turn("do X", "done") is None)
check("C4 a DISABLED section never calls the model",
      TV.verify_turn("r", "m", cfg={"enabled": False}) is None)
_p = TV._prompt("REQ-MARK", "LAST-MARK", ["OPEN-MARK"], [])
check("C5 the independent message carries request + last message + open steps",
      "THE AGENT'S FINAL MESSAGE" in _p and "REQ-MARK" in _p
      and "LAST-MARK" in _p and "OPEN-MARK" in _p, _p[:200])
TV.judge.ask_json = _orig_ask

# ---- D: the agent helper ----------------------------------------------------
_cfg_a, _orig_vt = TV.config, TV.verify_turn
TV.verify_turn = lambda *a, **k: {"ok": False, "missing": ["n1 not done"]}
TV.config = lambda: {"enabled": False, "model": "m", "max_rounds": 2}
check("D1 a DISABLED verifier returns no bounce",
      A._turn_verify_bounce("last", "req", {"id": "v1243d"}, 0) is None)
TV.config = lambda: {"enabled": True, "model": "m", "max_rounds": 1}
check("D1b a spent budget (used >= max_rounds) returns no bounce",
      A._turn_verify_bounce("last", "req", {"id": "v1243d"}, 1) is None)
check("D1c an INCOMPLETE verdict returns the CONTINUE text",
      "CONTINUE" in (A._turn_verify_bounce("last", "req", {"id": "v1243d"}, 0) or ""))
TV.config, TV.verify_turn = _cfg_a, _orig_vt


def run_turn(sid, script, verifier):
    """Drive chat_once with a scripted model AND a scripted verifier."""
    state = {"n": 0}

    def fake_stream(msgs, model, role, on_delta, usage=None, cancel=None, **kw):
        text = script(state["n"])
        state["n"] += 1
        on_delta("answer", text)
        return text, "", model

    events = []
    _cfg, _vt = TV.config, TV.verify_turn
    TV.config = lambda: {"enabled": True, "model": "mock", "max_rounds": 2}
    TV.verify_turn = verifier
    server.stream_with_fallback = fake_stream
    try:
        server.chat_once({"id": sid, "messages": [], "workspace": ""}, "do the task",
                         model="mock", on_delta=lambda c, t: None,
                         on_event=lambda kind, **d: events.append((kind, d)))
    finally:
        TV.config, TV.verify_turn = _cfg, _vt
    return events, state["n"]


# D2: verifier says INCOMPLETE once, then COMPLETE -> exactly ONE verifier bounce.
_seq = {"i": 0}


def _one_bounce(*a, **k):
    _seq["i"] += 1
    if _seq["i"] == 1:
        return {"ok": False, "missing": ["the screenshot was not pulled"]}
    return {"ok": True, "missing": []}


_ev, _calls = run_turn("v1243a", lambda n: "ho finito", _one_bounce)
_vinj = [d.get("text") or "" for k, d in _ev if k == "harness.inject"
         and "INDEPENDENT verifier" in str(d.get("text") or "")]
check("D2 the verifier bounces the turn exactly once (then it closes)",
      len(_vinj) == 1, _vinj)
check("D3 the bounce names the missing work, not a generic sentence",
      _vinj and "screenshot was not pulled" in _vinj[0], _vinj[:1])

# D4: verifier ALWAYS incomplete -> bounded by max_rounds (no infinite loop).
_seq2 = {"i": 0}


def _always_bad(*a, **k):
    _seq2["i"] += 1
    return {"ok": False, "missing": ["never done #%d" % _seq2["i"]]}


_ev2, _calls2 = run_turn("v1243b", lambda n: "fatto", _always_bad)
_b2 = [d for k, d in _ev2 if k == "harness.inject"
       and "INDEPENDENT verifier" in str(d.get("text") or "")]
check("D4 an always-FAIL verifier is bounded by max_rounds (no infinite loop)",
      len(_b2) == 2, _b2)

# D5: verifier says COMPLETE -> no verifier round at all.
_ev3, _calls3 = run_turn("v1243c", lambda n: "fatto",
                         lambda *a, **k: {"ok": True, "missing": []})
_b3 = [d for k, d in _ev3 if k == "harness.inject"
       and "INDEPENDENT verifier" in str(d.get("text") or "")]
check("D5 a COMPLETE turn buys no verifier round", len(_b3) == 0, _b3)

# ---- E: static wiring (the hook lives in the loop, one source) --------------
check("E1 the close calls the verifier before break",
      "_turn_verify_bounce(answer, _request_thread_text, sess," in SRC)
check("E2 the counter is per-turn (bounded)",
      "_turn_verify_used = 0" in SRC and "_turn_verify_used += 1" in SRC)
check("E3 the goal judge reuses the ONE shared judge call (no duplicate call)",
      "from longrun.plan import judge as _judge" in
      open(os.path.join(REPO, "src", "longrun", "plan", "goal.py"),
           encoding="utf-8").read()
      and "judge.ask_json" in
      open(os.path.join(REPO, "src", "longrun", "plan", "turn_verify.py"),
           encoding="utf-8").read())

print("\n---")
print("v1243: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
