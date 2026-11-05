#!/usr/bin/env python3
"""v826 — the `harness → LLM` label is the WIRE, not a summary (2026-11-05).

Operator, verbatim: *"what i see in UI in the chat under harness label shall be
EXACTLY what the LLM receives not else. it s need for debug."* Before this test
the label lied in four ways:

  * a chip showed the injection TEXT without the `[harness] ` prefix and without
    the role the provider actually receives (agent.harness_wrap);
  * a byte-identical repeat was drawn as a message although no bytes were sent;
  * the session-start banner and the "system prompt updated" delta notice were
    summaries of harness state, never messages;
  * a message the mid-turn trim dropped still kept its chip, and the persisted
    reload record could silently merge two identical sends (RH-9 dedup).

The contract pinned here: ONE chip == ONE message in the outgoing list, its body
verbatim, its role named; nothing that was not appended is shown under the label;
a dropped message takes its chip with it; live == reload == wire.

Deterministic and offline: the LLM and the tool gate are mocked (v183/v736 pattern).
Run: python3 tests/acceptance/v826_harness_wire_label.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v826-")
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
from longrun.memory import stores  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


CALL_BAD = '{"action":"tool","tool":"shell","args":{"command":"false"}}'


def gated_bad():
    err = "tool error: the command failed"
    return {"status": "executed",
            "observation": "[shell] exit=1 ok=False backend=stub sandboxed=False\n"
                           "stderr: " + err,
            "result": {"ok": False, "exit_code": 1, "stdout": "", "stderr": err,
                       "backend": "stub"}}


def run_turn(sid, script):
    """Drive chat_once with a scripted model and a failing tool gate."""
    state = {"n": 0}

    def fake_stream(msgs, model, role, on_delta, usage=None, cancel=None, **kw):
        text = script(state["n"])
        state["n"] += 1
        on_delta("answer", text)
        return text, "", model

    events = []
    server.stream_with_fallback = fake_stream
    server.api_v02.gated_call = lambda tool, args, **kw: gated_bad()
    server.chat_once({"id": sid, "messages": [], "workspace": ""}, "go", model="mock",
                     on_delta=lambda c, t: None,
                     on_event=lambda kind, **d: events.append((kind, d)))
    return events, state["n"]


EV, _calls = run_turn("v826a", lambda n: CALL_BAD if n == 0 else "Done — the step failed, reported.")
sess = server.load_session("v826a") or {}
transcript = [str(m.get("content") or "") for m in (sess.get("messages") or [])
              if isinstance(m, dict)]
wire_msgs = [t for t in transcript if t.startswith(A.HARNESS_MARK)]

chips = [d for k, d in EV if k == "harness.inject"]
user_chips = [d for d in chips if (d.get("role") or "user") == "user"]
sys_chips = [d for d in chips if (d.get("role") or "") == "system"]

# ---- A. every chip is a message that was actually sent ----------------------
check("A0 the turn injected at least one harness message", len(user_chips) >= 1,
      [c.get("text", "")[:40] for c in user_chips])
check("A1 a user chip carries the WIRE text, prefix included",
      all(str(c.get("text") or "").startswith(A.HARNESS_MARK) for c in user_chips),
      [c.get("text", "")[:40] for c in user_chips if not str(c.get("text") or "").startswith(A.HARNESS_MARK)])
check("A2 every user chip exists VERBATIM in the transcript the turn persisted",
      all(str(c.get("text") or "") in wire_msgs for c in user_chips),
      [c.get("text", "")[:80] for c in user_chips if str(c.get("text") or "") not in wire_msgs])
check("A3 no harness message reached the transcript without a chip (nothing hidden)",
      all(t in [str(c.get("text") or "") for c in user_chips] for t in wire_msgs),
      [t[:80] for t in wire_msgs if t not in [str(c.get("text") or "") for c in user_chips]])
check("A4 the persisted reload record is the SAME text as the chip",
      sorted(str(r.get("text") or "") for r in (sess.get("injects") or [])) ==
      sorted(str(c.get("text") or "") for c in user_chips),
      (sorted(str(r.get("text") or "")[:40] for r in (sess.get("injects") or [])),
       sorted(str(c.get("text") or "")[:40] for c in user_chips)))

# ---- B. nothing that was not sent is shown under the label ------------------
check("B1 no session-start banner exists any more",
      not any(str(c.get("inject_kind") or "") == "harness-start" for c in chips)
      and not any(str(r.get("kind") or "") == "harness-start" for r in (sess.get("injects") or [])))
check("B2 no 'system prompt updated' delta summary",
      not any(str(c.get("inject_kind") or "") == "system-delta" for c in chips))
check("B3 the system chip carries the prompt itself, not a notice",
      all(len(str(c.get("text") or "")) > 200 for c in sys_chips),
      [len(str(c.get("text") or "")) for c in sys_chips])
check("B4 a suppressed repeat is announced, never appended as a message",
      'repeat=True' in open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
                            encoding="utf-8").read())

# ---- C. a dropped message takes its chip with it ----------------------------
_probe = {"id": "v826drop", "messages": []}
stores.persist_inject(_probe, "observation", "[harness] same", after=0)
stores.persist_inject(_probe, "observation", "[harness] same", after=0)
stores.persist_inject(_probe, "observation", "[harness] other", after=0)
_gone = stores.drop_inject(_probe, "[harness] same")
check("C1 drop_inject removes the LAST matching record", _gone is not None
      and [r["text"] for r in _probe["injects"]] == ["[harness] same", "[harness] other"],
      [r["text"] for r in _probe.get("injects") or []])
check("C2 a second identical send is recorded (no RH-9 merge: reload == wire)",
      len(stores.load_session("v826drop")["injects"]) == 2)
check("C3 dropping an unknown text is a no-op",
      stores.drop_inject(_probe, "[harness] absent") is None
      and len(_probe["injects"]) == 2)
_a = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
          encoding="utf-8").read()
check("C4 the mid-turn trim withdraws every [harness] message it drops",
      "_dropped_wire.append(_gone.get(\"content\"))" in _a
      and "for _w in _dropped_wire:" in _a and "_withdraw(_w)" in _a)

# ---- D. the UI renders the wire, one block per message ----------------------
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("D1 the chip body is written with the raw text (no transform)",
      'det.querySelector(".hbody").textContent = text;' in UI)
check("D2 the chip names the wire role", 'querySelector(".hrole")' in UI)
check("D3 the old ×N merge of identical messages is gone", 'class="hcount"' not in UI)
check("D4 a suppressed repeat is a counter on the previous message",
      'dataset.supp' in UI and "identical not re-sent" in UI)
check("D5 the drop event removes the chip live",
      "function harnessDrop(" in UI and 'addEventListener("harness.drop"' in UI)
check("D6 the system echo no longer deletes the previous prompt chip",
      "_sysInjectEl.remove()" not in UI)

print("\nv826: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
