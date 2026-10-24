#!/usr/bin/env python3
"""v462 — JAG-465: live honesty (vision, realtime UI, cross-chat links).

One round, five operator-reported defects:
  * a local model that HAS a projector was treated as text-only, so image
    attachments were never delivered (the harness even told the model it cannot
    see) — detection must trust the router's REAL launch args (`--mmproj`);
  * the WebUI did not apply the events it missed while the SSE feed was
    disconnected, so a chat kept a stale `doing`/empty todo row until a manual
    reload — the backlog must be replayed into the same handlers as live events;
  * a `dispatch`ed assignment was invisible in the receiving chat until a reload,
    and neither chat linked to the other;
  * the `/` picker only offered 8 skills by name prefix out of 174;
  * the full SYSTEM prompt card was re-printed on every user message.

Deterministic: no model, server, network or browser. The vision checks patch the
HTTP call and the provider resolver in-memory and restore them.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (("  :: " + str(detail)) if detail and not ok else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")
AGENT = _read("src", "longrun", "agent", "agent.py")
HTTPAPI = _read("src", "longrun", "core", "httpapi.py")
PROVIDERS = _read("config", "providers.yaml")

# ---------------------------------------------------------------- A: vision --
from longrun.model import rllm  # noqa: E402
from longrun.model import providers  # noqa: E402

_roster = rllm._parse_roster({"data": [
    {"id": "with-proj", "status": {"value": "loaded",
                                   "args": ["-m", "w.gguf", "--mmproj", "p.gguf"]}},
    {"id": "no-proj", "status": {"value": "loaded", "args": ["-m", "n.gguf"]}},
]})
_by = {m["alias"]: m for m in _roster}
check("A1 the roster exposes the live --mmproj signal",
      _by["with-proj"]["mmproj"] is True and _by["no-proj"]["mmproj"] is False,
      _roster)


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_payload = {"data": [
    {"id": "m", "status": {"value": "loaded",
                           "args": ["-m", "x.gguf", "--mmproj", "mm.gguf"]}},
]}
_orig_resolve, _orig_open = providers.resolve, rllm.urllib.request.urlopen
try:
    providers.resolve = lambda a: ({"local": True, "models": []}, "m")
    rllm.urllib.request.urlopen = lambda *a, **k: _Resp(_payload)
    check("A2 a loaded projector makes the model vision-capable (live args, not the dead meta field)",
          rllm.model_supports_vision("m") is True)

    _payload = {"data": [{"id": "m", "status": {"value": "loaded", "args": ["-m", "x.gguf"]}}]}
    check("A3 no projector -> still text-only (no false positive)",
          rllm.model_supports_vision("m") is False)

    providers.resolve = lambda a: ({"local": False, "models": []}, "m")
    _payload = {"data": [{"id": "m", "status": {"value": "loaded",
                                                "args": ["--mmproj", "p.gguf"]}}]}
    check("A4 a REMOTE provider is never granted vision by a local roster",
          rllm.model_supports_vision("m") is False)
finally:
    providers.resolve = _orig_resolve
    rllm.urllib.request.urlopen = _orig_open

# Secondary hint: `architecture.input_modalities` WITHOUT a projector. The live
# router exposes `architecture` at the TOP LEVEL of the roster entry; older
# shapes nest it under `meta`. Both must grant vision, and a text-only
# architecture must not.
try:
    providers.resolve = lambda a: ({"local": True, "models": []}, "m")
    _payload = {"data": [{"id": "m", "status": {"value": "loaded", "args": ["-m", "x.gguf"]},
                           "architecture": {"input_modalities": ["text", "image"]}}]}
    rllm.urllib.request.urlopen = lambda *a, **k: _Resp(_payload)
    check("A4b top-level architecture.input_modalities grants vision without --mmproj",
          rllm.model_supports_vision("m") is True)

    _payload = {"data": [{"id": "m", "status": {"value": "loaded", "args": ["-m", "x.gguf"]},
                           "meta": {"architecture": {"input_modalities": ["text", "image"]}}}]}
    rllm.urllib.request.urlopen = lambda *a, **k: _Resp(_payload)
    check("A4c meta-nested architecture.input_modalities grants vision too",
          rllm.model_supports_vision("m") is True)

    _payload = {"data": [{"id": "m", "status": {"value": "loaded", "args": ["-m", "x.gguf"]},
                           "architecture": {"input_modalities": ["text"]}}]}
    rllm.urllib.request.urlopen = lambda *a, **k: _Resp(_payload)
    check("A4d a text-only architecture stays text-only (no false positive)",
          rllm.model_supports_vision("m") is False)
finally:
    providers.resolve = _orig_resolve
    rllm.urllib.request.urlopen = _orig_open

for _mid in ("qwen-3.8-27b-abliterated-q3", "qwen3.6-35b-a3b-uncensored-iq4xs",
             "nex-n2.5-mini-uncensored-iq4xs", "muse-glimmer-30b-abliterated-q3",
             "gemma-4-26b-a4b"):
    check("A5 %s declares vision in the catalogue" % _mid,
          ("{id: %s," % _mid) in PROVIDERS and
          any(_mid in ln and "vision: true" in ln for ln in PROVIDERS.splitlines()),
          _mid)
check("A6 a model WITHOUT a projector is not flagged",
      "qwen-3.8-27b-abliterated-q4, vision" not in PROVIDERS)
check("A7 the live roster id is matched case-insensitively",
      'str(m.get("id") or "").lower() != str(mid or "").lower()' in _read(
          "src", "longrun", "model", "rllm.py"))

# ------------------------------------------------------- B: system card ------
check("B1 the full SYSTEM card is published only the FIRST time for a session",
      "_prev = _LAST_SYS_INJECT.get(sess[\"id\"])" in AGENT
      and "if _prev is None:" in AGENT)
check("B2 later changes publish a compact delta instead of the whole prompt",
      'inject_kind="system-delta"' in AGENT
      and "system prompt updated for this turn" in AGENT)
check("B3 the system prompt is still sent to the model every turn (display rule only)",
      "msgs[0].get(\"content\")" in AGENT and "text=_sys_txt)" in AGENT)

# ------------------------------------------------- C: dispatch + links -------
check("C1 chat_stream_gen accepts and persists the ORIGINATING session",
      "sender_session=None" in HTTPAPI and '"sender_session": sender_session' in HTTPAPI
      and "sender_session=sender_session)" in HTTPAPI)
check("C2 the attach replay carries the assignment message",
      '"chat.run", "chat.delta", "chat.done", "chat.user",' in HTTPAPI)
check("C3 a dispatch card remembers the teammate's session",
      '"goal": goal, "session": sid2' in AGENT)
check("C4 the receiver's chat renders the assignment live and attributed",
      'es.addEventListener("chat.user"' in HTML
      and "who(\"user\", clean || txt, null, d.sender, d.subjob, null, d.sender_session);" in HTML)
check("C5 both directions get a one-click cross-chat link",
      "_openSessionAt(senderSession, { tool: \"dispatch\" })" in HTML
      and "function _openSessionAt(sid, want)" in HTML
      and "function _alignElTop(log, el)" in HTML)
check("C6 the delegated bubble is attributed with a link button",
      'd.className = "msg " + (role === "user" ? "user" : "ai") + (sender ? " deleg" : "")' in HTML
      and "function _xlinkBtn(label, title, fn)" in HTML)

# ------------------------------------------------------------- D: realtime ---
check("D1 one dispatcher applies BOTH live and replayed feed events",
      "function _feedReplay(ev)" in HTML and "arr.forEach(_feedReplay)" in HTML)
check("D2 the reconnect resumes from the last seen event id",
      '"since=" + feedSince' in HTML)
check("D3 a missed gap is repaired from the durable stores (no manual reload)",
      "function _resyncDurable()" in HTML and "_resyncDurable();" in HTML
      and 'document.addEventListener("visibilitychange"' in HTML)
check("D4 already-rendered todo rows are repainted from the loaded graph",
      "function _repaintChatNodes()" in HTML
      and HTML.count("_repaintChatNodes();") >= 2)
check("D5 another session's turn end no longer rebuilds THIS Context panel",
      "if (!d.session || d.session === sessionId) loadCtx();" in HTML)

# --------------------------------------------------------------- E: skills ---
check("E1 the picker searches the WHOLE catalogue, not 8 name prefixes",
      ".slice(0, 8)" not in HTML.split("function skillsAutocomplete")[1][:2200]
      and "_SLASH_CAP" in HTML and "const _matched" in HTML)
check("E2 the popup scrolls instead of clipping the results",
      "#slashMenu { max-height: 46vh; overflow-y: auto; }" in HTML)

# ------------------------------------------------------------- F: plan / UI ---
check("F1 only a step of a LIVE turn is marked (persisted 'doing' is not)",
      'el.classList.add("live")' in HTML and 'n.status === "doing" && runningSessions[sessionId]' in HTML)
check("F2 the marker follows the turn's start/stop",
      "if (sid === sessionId) { try { renderGraph(); } catch (e) {} }" in HTML)
check("F3 the badge borders derive from the theme colour (cream readability)",
      "color-mix(in srgb, currentColor 45%, transparent)" in HTML
      and "rgba(74,222,128,.4)" not in HTML)
check("F4 the pulse respects prefers-reduced-motion",
      "@media (prefers-reduced-motion: reduce) { .task.live .st.doing { animation: none; } }" in HTML)

# ------------------------------------------------- G: mid-turn compaction ----
check("G1 a long turn trims its own oldest context between rounds",
      "def _trim_midturn():" in AGENT and "_tr = _trim_midturn()" in AGENT)
check("G2 the trim never drops the system prompt or the last few entries",
      '_m.get("role") == "system":' in AGENT and "_keep = 6" in AGENT)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
