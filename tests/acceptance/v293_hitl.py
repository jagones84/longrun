#!/usr/bin/env python3
"""v293 — HITL: no gate on a headless turn + the card survives a reload (JAG-295);
plus the Orbit tactical view / role editor / main-app link.

Locked here:
  * keepgoing.hitl_gate: open steps + a real stop + a human present; NEVER on a
    headless (autonomous) job/routine turn;
  * the server gates via the helper and persists the open list (hitl_open) so the
    card is replayable;
  * the WebUI rebuilds the card from history when a message carries meta.hitl;
  * Orbit: clicking an org-chart box opens the constellation window; the role
    editor is large and says it is the shared ROLE.md; the main-app link carries
    the token.

Deterministic, no live model. Run: python3 tests/v293_hitl.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


from longrun.plan import keepgoing as kg  # noqa: E402

# --- the gate helper -------------------------------------------------------
check("the gate fires with open steps + a real stop + a human",
      kg.hitl_gate("budget", [1, 2, 3]) is True)
check("the gate does NOT fire on a headless (autonomous) turn",
      kg.hitl_gate("budget", [1, 2], autonomous=True) is False)
check("the gate does NOT fire with no open steps",
      kg.hitl_gate("goal_reached", []) is False)
check("the gate does NOT fire on a user pivot", kg.hitl_gate("user_pivot", [1]) is False)

# --- server wiring ---------------------------------------------------------
with open(os.path.join(REPO, "src", "longrun", "core/server.py"), encoding="utf-8") as f:
    srv = f.read()
with open(os.path.join(REPO, "src", "longrun", "agent/agent.py"), encoding="utf-8") as f:
    srv += f.read()
check("the card is the AGENT's call (human.ask), never a harness stop reflex",
      "_human_ask_args(act)" in srv and '"reason": "asked"' in srv
      and '_kg.hitl_gate(_dec["reason"], _open,' not in srv)
check("a headless turn cannot park for a human who is not there",
      "nobody is attached" in srv)
check("the server persists the open list (hitl_open)",
      '"hitl_open": _hitl["open"]' in srv)
check("append_message merges meta FLAT into the message",
      "msg.update(meta)" in open(os.path.join(REPO, "src", "longrun", "memory/stores.py"), encoding="utf-8").read())

# --- WebUI replay ----------------------------------------------------------
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    gui = f.read()
check("the WebUI rebuilds the HITL card from history (flat keys)",
      "m.hitl" in gui and "m.hitl_open" in gui and "hitlCard(" in gui)
check("the WebUI does NOT read a nested meta.hitl (contract mismatch)",
      "m.meta.hitl" not in gui)

# --- Orbit deck ------------------------------------------------------------
with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8") as f:
    ui = f.read()
check("Orbit opens the constellation from an org-chart box",
      'id="constPanel"' in ui and 'id="constSvg"' in ui and "class Constellation" in ui
      and "this.tac.open(a" in ui)
check("the constellation labels nodes AX.nY", ".nY" in ui and "'.n' +" in ui)
check("the Orbit role editor is large", "min-height:190px" in ui)
check("the Orbit role editor says it is the shared ROLE.md",
      "SAME <b>ROLE.md</b>" in ui and "Inspector" in ui)
check("the Orbit main-app link carries the token",
      '"/?token="' in ui and "encodeURIComponent(this.api.token)" in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
