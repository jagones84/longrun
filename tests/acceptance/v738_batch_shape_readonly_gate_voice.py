#!/usr/bin/env python3
"""v738 — a batch payload is still a batch, a read-only probe needs no grant,
and voice input starts instead of explaining itself.

Operator reports (live 2026-10-30), three symptoms, one theme: the harness knew
the right thing and did the wrong one.

  A  "batch is broken": the model emitted `{"action":"batch","calls":[…]}` and the
     chat echoed the JSON back as PROSE while nothing ran. The dispatcher was
     fine; the PARSER dropped the envelope whenever the action name arrived apart
     from its payload (`<action>batch</action>` + JSON, or no `action` key at
     all), so the dict had no action, matched no tool and became the answer.
     Pinned: a payload whose only meaningful key is a list of calls IS a batch.
  B  `mcp.test` answered 126 in a normal chat with `approvals.mode=full` on: the
     dual-permission gate covers the whole `mcp.*` namespace, but `mcp.test` only
     OBSERVES an already-configured client — it cannot rewire anything — so it is
     read-only and must run from any session. Every MUTATING exclusive tool keeps
     the gate.
  C  The 🎙 mic dead-ended on a wall of instructions. The server already speaks
     TLS on port+1: the UI now upgrades itself once the certificate is trusted
     (flag written by the HTTPS page) and otherwise offers ONE click, which it
     only offers after probing the TLS port — an unaccepted certificate would
     park the browser on an interstitial, and that is the "blocked page" the fix
     must never cause.

Deterministic: temp dirs, no server, no model, no network, no browser.
Run: python3 tests/acceptance/v738_batch_shape_readonly_gate_voice.py
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="sf-v738-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _srv  # noqa: E402,F401 — import first: agent<->server cycle
from longrun.agent import agent as A  # noqa: E402
from longrun.agent import longrun_agent as LRA  # noqa: E402
from longrun.memory import stores as STORES  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# ---------------- A: a calls list IS a batch ----------------------
_act = A._normalize_action({"calls": [{"tool": "self.info", "args": {}},
                                      {"tool": "sysprobe.mem", "args": {}}]})
check("A1 a bare `calls` payload becomes a batch action",
      _act.get("action") == "batch" and len(A._batch_items(_act)) == 2, _act)
check("A2 `tool_calls` is the same payload under its other name",
      A._normalize_action({"tool_calls": [{"tool": "a"}]}).get("action") == "batch")
check("A3 an explicit action is never overwritten by the shape rule",
      A._normalize_action({"action": "todo.write", "calls": [{"tool": "a"}]})["action"]
      == "todo.write"
      and A._normalize_action({"action": "batch", "calls": [{"tool": "a"}]})["action"]
      == "batch")
check("A4 an EMPTY calls list is not a batch (nothing to run)",
      "action" not in A._normalize_action({"calls": []}))
_ex = A._extract_action('{"calls": [{"tool": "self.info", "args": {}}]}')
check("A5 end to end: the parser routes the payload to the batch lane",
      isinstance(_ex, dict) and _ex.get("action") == "batch"
      and len(A._batch_items(_ex)) == 1, _ex)
_ex2 = A._extract_action('<action>batch</action> {"calls": [{"tool": "self.info"}]}')
check("A6 the tag+JSON spelling still reaches the batch lane",
      isinstance(_ex2, dict) and _ex2.get("action") == "batch", _ex2)

# ---------------- B: read-only probes need no grant ----------------------
SID = "v738-gate-probe"
STORES.get_or_create_session(SID)
_ok_probe, _why_probe = LRA.check_dual_permission("mcp.test", SID)
check("B1 mcp.test runs from a plain session (observed, cannot rewire)",
      _ok_probe is True and "not authorized" not in str(_why_probe), _why_probe)
_ok_mut, _why_mut = LRA.check_dual_permission("mcp.upsert", SID)
check("B2 a MUTATING exclusive tool keeps the gate",
      _ok_mut is False and "dual-permission gate" in str(_why_mut), _why_mut)
check("B3 the exemption is a named set, not a namespace wildcard",
      set(LRA.READ_ONLY_EXCLUSIVE) == {"mcp.test", "agent.get", "agent.list",
                                       "team.get", "team.list"}
      and "mcp.remove" not in LRA.READ_ONLY_EXCLUSIVE)
check("B5 an orchestrator reads its org chart without a grant (names + roles)",
      LRA.check_dual_permission("agent.list", SID)[0] is True
      and LRA.check_dual_permission("agent.get", SID)[0] is True
      and LRA.check_dual_permission("team.list", SID)[0] is True)
check("B6 every org-chart WRITE keeps the gate",
      all(LRA.check_dual_permission(t, SID)[0] is False
          for t in ("agent.create", "agent.update", "agent.delete",
                    "team.member_add", "team.member_remove")))
PROMPT_SRC = _read("src", "longrun", "model", "prompt.py")
check("B7 the roster says it is rebuilt each turn and how to re-read it",
      "rebuilt from live state every turn" in PROMPT_SRC
      and "`agent.list` re-reads" in PROMPT_SRC
      and "never keep your own copy" in PROMPT_SRC)
LRA.set_session_access(SID, True)
check("B4 the Teamorg grant still opens the mutating path",
      LRA.check_dual_permission("mcp.upsert", SID)[0] is True)
LRA.set_session_access(SID, False)

# ---------------- C: voice input starts, never blocks ----------------------
UI = _read("webui", "index.html")
check("C1 the TLS origin is derived from the served port, localhost exempt",
      "function voiceTlsOrigin()" in UI and "Number(u.port) + 1" in UI
      and "localhost|127" in UI)
check("C2 the secure URL carries the API token and the open session",
      "function voiceSecureUrl(extra)" in UI and 'qs.push("token="' in UI
      and 'qs.push("session="' in UI)
check("C3 the mic click probes TLS before navigating (no cert interstitial)",
      "await voiceHttpsReachable()" in UI
      and 'location.assign(voiceSecureUrl("voice=1"))' in UI)
check("C4 a proven origin upgrades by itself on boot (voice is the default)",
      "function voiceUpgrade()" in UI and 'localStorage.getItem("lr_voice_https")' in UI
      and "location.replace(voiceSecureUrl(\"voice=1\"))" in UI
      and "voiceUpgrade,   // JAG-417" in UI)
check("C5 `?voice=1` starts the recognizer on the secure page",
      'searchParams.get("voice")' in UI and "setTimeout(() => { try { micToggle(); }" in UI)
check("C6 the help dialog is actionable, not just instructive",
      'id="voiceGoSecure"' in UI and "Open the secure version" in UI
      and UI.count("voiceGoSecure") >= 2)
check("C7 the insecure-origin help survives (Win+H, tunnel, Chrome flag)",
      "window.isSecureContext" in UI and "Win + H" in UI
      and "ssh -L 8790" in UI and "unsafely-treat-insecure-origin-as-secure" in UI)

print("---")
ok = sum(results)
print("\nv738: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
