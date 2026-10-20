#!/usr/bin/env python3
"""v458 — compaction model routing, abortable compaction and honest replay (JAG-461).

The operator's live incident: clicking "Compact" loaded 121GB of LOCAL weights and
the chat then repeated a junk summary on every turn. Root cause (evidence from
`data/events.db`): `stream_with_fallback` walked `routing.fallback_chain(role)`,
which resolved the role PATTERN against the LOCAL llama.cpp roster — so when the
configured CLOUD summarizer failed, the very next candidate was a LOCAL alias
(`glm-5.3-flash-iq2`). A model the user chose must never silently become another.

Deterministic: no live model, no network, no server.
"""
import os
import sys
import tempfile
import yaml
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v458-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for _d in ("cfg", "sessions", "threads", "graphs"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S            # noqa: E402
from longrun.core import httpapi                 # noqa: E402
from longrun.model import routing, context_engine  # noqa: E402
from longrun.agent import agent as A             # noqa: E402
from longrun.util import steering                # noqa: E402

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """Record and print one deterministic acceptance check."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(rel: str) -> str:
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


# ---- A) a configured CLOUD model must never silently become a LOCAL one -------
_srv = _read("src/longrun/core/server.py")
check("A1 the failover chain is built from explicit refs, not roster patterns",
      "routing.model_chain(role)" in _srv
      and "routing.fallback_chain(role) if a != primary" not in _srv)
check("A2 routing defaults carry no hardcoded alias/pattern",
      all("pattern" not in r and "model" not in r
          for r in routing.DEFAULT_CONFIG.get("roles", {}).values()))

_orig_mc, _orig_fc, _orig_rs = routing.model_chain, routing.fallback_chain, S._router_stream
_attempts: list = []


def _fake_stream(messages, model, on_delta, timeout=300, usage=None, guard=None,
                 cancel=None, no_reasoning=False, max_tokens=None):
    """Cloud primary fails; the fake LOCAL alias would 'answer' — it must never be tried."""
    _attempts.append(model)
    if model == "openrouter:cloud-sum":
        raise RuntimeError("cloud summarizer unavailable")
    return "LOCAL-ANSWER", ""


routing.model_chain = lambda role: ["openrouter:cloud-sum", "openrouter:cloud-backup"]
routing.fallback_chain = lambda role: ["glm-5.3-flash-iq2"]   # the LOCAL roster alias
S._router_stream = _fake_stream
try:
    try:
        S.stream_with_fallback([{"role": "user", "content": "hi"}],
                               "openrouter:cloud-sum", "summarizer", lambda c, t: None)
    except Exception:  # noqa: BLE001 — the failover itself is what we assert on
        pass
finally:
    routing.model_chain, routing.fallback_chain = _orig_mc, _orig_fc
    S._router_stream = _orig_rs
check("A3 a failing cloud model never falls over to a LOCAL roster alias",
      "glm-5.3-flash-iq2" not in _attempts and "openrouter:cloud-backup" in _attempts,
      str(_attempts))

_rr = yaml.safe_load(_read("config/routing.yaml")) or {}
_roles = _rr.get("roles") or {}
check("A4 config/routing.yaml has NO local-matching pattern on summarizer/subagent",
      "pattern" not in (_roles.get("summarizer") or {})
      and "pattern" not in (_roles.get("subagent") or {}))
check("A5 the team model policy is not a hardcoded literal in Python",
      "openrouter:z-ai/glm-5.3-flash" not in _read("src/longrun/orchestrate/teams.py"))

# ---- B) Stop aborts a running compaction (transcript untouched) --------------
_orig_sum = httpapi._summarize_with_llm
httpapi._summarize_with_llm = (lambda messages, model=None, session=None, meta=None,
                               cancel=None: "S")
SID = "v458abort"
_sess = S.get_or_create_session(SID)
for _i in range(12):
    S.append_message(_sess, "user", "u%d %s" % (_i, "x" * 200))
    S.append_message(_sess, "assistant", "a%d %s" % (_i, "y" * 200))
_before = len(S.load_session(SID)["messages"])
steering.push_abort(SID)
try:
    _res = S.compact_session(SID)
finally:
    steering.clear_abort(SID)
    httpapi._summarize_with_llm = _orig_sum
_after = len(S.load_session(SID)["messages"])
check("B1 a Stop during compaction leaves the transcript untouched",
      _res.get("aborted") is True and _before == _after,
      "aborted=%s before=%d after=%d" % (_res.get("aborted"), _before, _after))
check("B2 the abort path never claims a summary",
      _res.get("summary") is None and _res.get("compacted") == 0, str(_res)[:120])

# ---- C) a MANUAL compaction always leaves a visible card ---------------------
httpapi._summarize_with_llm = (lambda messages, model=None, session=None, meta=None,
                               cancel=None: "S")
SID2 = "v458card"
_s2 = S.get_or_create_session(SID2)
for _i in range(10):
    S.append_message(_s2, "user", "u%d %s" % (_i, "z" * 300))
    S.append_message(_s2, "assistant", "a%d" % _i)
_res2 = S.compact_session(SID2)
httpapi._summarize_with_llm = _orig_sum
_cards = [r for r in (S.load_session(SID2).get("injects") or []) if r.get("kind") == "compact"]
check("C1 a MANUAL compaction leaves a visible compact card",
      bool(_cards) and "manual" in _cards[-1].get("text", ""),
      (_cards[-1].get("text", "")[:90] if _cards else "no card"))
check("C2 it reports the failure honestly (no silent 'done')",
      _res2.get("summary") in ("llm", "extractive"), str(_res2.get("summary")))

# ---- D) the extractive fallback drops harness scaffolding --------------------
_msgs = [{"role": "user", "content": "[harness] Observation for tool shell: LARGE output"},
         {"role": "assistant", "content": "the real decision about the plan"},
         {"role": "user", "content": "normal user line"}]
_out, _st = context_engine.compact(_msgs, 10, keep_recent=0,
                                   summarizer=lambda old: None, force=True)
_summary = _out[0]["content"]
check("D1 harness scaffolding never enters the extractive summary",
      "[harness]" not in _summary and "real decision" in _summary, _summary[:160])

# ---- E) the replay contract (WebUI) -----------------------------------------
_html = _read("webui/index.html")
check("E1 a system summary replays as a collapsed harness card",
      'if (m.role === "system")' in _html and 't: "s", v: m' in _html
      and 'inject_kind: "compacted history"' in _html
      and 'typeof e.v.ts === "number" ? e.v.ts : null' in _html)
check("E2 the compact button reports abort and the local fallback honestly",
      "compaction aborted — context unchanged" in _html
      and "local fallback (summarizer model unavailable)" in _html
      and 'who("ai", `🗜 compacted (manual)' not in _html)

# ---- F) vision ---------------------------------------------------------------
_p = os.path.join(TMP, "img.png")
with open(_p, "wb") as _f:
    _f.write(b"\x89PNG\r\nmock")
_text = "Look at this:\n%s" % _p
check("F1 a bare absolute image path is detected",
      A._extract_image_paths(_text) == [_p], str(A._extract_image_paths(_text)))
_vmsg = [{"role": "user", "content": _text}]
with mock.patch.object(A, "model_supports_vision", return_value=True):
    _vis = A._inject_vision_blocks(_vmsg, "dgx:vision")
check("F2 a vision-capable model receives image blocks",
      isinstance(_vis[-1]["content"], list)
      and _vis[-1]["content"][-1]["type"] == "image_url",
      type(_vis[-1]["content"]).__name__)
with mock.patch.object(A, "model_supports_vision", return_value=False):
    _txt = A._inject_vision_blocks(_vmsg, "dgx:text-only")
check("F3 a text-only model is told the truth (it cannot see the image)",
      isinstance(_txt[-1]["content"], str) and "cannot" in _txt[-1]["content"]
      and "[harness]" in _txt[-1]["content"])

# ---- G) compaction can follow the CHAT model dynamically (JAG-509) ----------
# The operator asked for a "same as chat model" voice in the compaction picker, so
# compaction uses whichever model the chat turn is using right now.
check("G1 routing defines the chat-following sentinel and keeps it out of the chain",
      getattr(routing, "CHAT_MODEL_REF", None) == "@chat"
      and routing.is_dynamic_ref("@chat") is True
      and routing.is_dynamic_ref("openrouter:a/b") is False)
_prev_load = routing.load_config
routing.load_config = lambda reload=False: {
    "roles": {"summarizer": {"model": "@chat", "fallbacks": ["openrouter:backup"]}},
    "default_fallbacks": []}
try:
    _sentinel_chain = routing.model_chain("summarizer")
finally:
    routing.load_config = _prev_load
check("G2 the sentinel is never a literal fallback candidate",
      _sentinel_chain == ["openrouter:backup"], str(_sentinel_chain))

_used: dict = {}
_prev_swf, _prev_role_model, _prev_turn_model = (
    httpapi.stream_with_fallback, routing.role_model, routing.turn_model)
httpapi.stream_with_fallback = lambda msgs, model, role, on_delta, **kw: (
    _used.update(model=model, role=role) or ("SUMMARY", "", model))
routing.role_model = lambda role: "@chat"
routing.turn_model = lambda sess=None, model=None: "openrouter:chat-live"
try:
    _dyn_ok = True
    try:
        _dyn = httpapi._summarize_with_llm(
            [{"role": "user", "content": "old turns"}], meta={}, session="sess-9")
    except TypeError as _e:
        _dyn_ok, _dyn = False, "TypeError: %s" % _e
    _dyn_used = dict(_used)
    _used.clear()
    routing.role_model = lambda role: "openrouter:pinned-compaction"
    routing.turn_model = lambda sess=None, model=None: "openrouter:chat-live"
    _pinned = httpapi._summarize_with_llm(
        [{"role": "user", "content": "old turns"}], meta={}, session="sess-9")
    _pinned_used = dict(_used)
finally:
    httpapi.stream_with_fallback = _prev_swf
    routing.role_model, routing.turn_model = _prev_role_model, _prev_turn_model
check("G3 the sentinel resolves to the model the CHAT is using right now",
      _dyn_ok and _dyn_used.get("model") == "openrouter:chat-live"
      and _dyn_used.get("role") == "summarizer" and _dyn == "SUMMARY",
      "used=%s dyn=%s" % (_dyn_used.get("model"), _dyn))
check("G4 an explicitly pinned compaction model is still used verbatim",
      _pinned_used.get("model") == "openrouter:pinned-compaction" and _pinned == "SUMMARY",
      str(_pinned_used.get("model")))
check("G5 the Models compaction picker offers the dynamic chat option",
      '"@chat"' in _html and "same as chat model" in _html)

print("---")
okc = sum(results)
print("\nv458: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
