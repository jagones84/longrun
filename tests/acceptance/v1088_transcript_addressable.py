#!/usr/bin/env python3
"""v1088 — a transcript message is ADDRESSABLE: `#N` is the model-cf index.

Round 18 shipped `sessions.model_counterfactual`, whose `index` is a position in
the stored transcript. The agent reads that transcript through `sessions.read`,
which printed roles but no numbers — so the address the new action needs was not
observable. This round prints `#N` on every MESSAGE row (cards and harness notes
keep their old shape, they are not addressable that way) and round-trips the
printed number into `harness.modelcf.plan`.

Contract:
  T  every message row prints its index; the number matches the stored array
  C  cards and injects keep their shape (no `#N`, no false address)
  R  the printed index round-trips into modelcf.plan
  G  the guidance names the `#N` for both `sessions.read` and the new action
  L  the existing transcript contract survives (role labels, header counts)

Deterministic: no server, no model, no store write.
Run: python3 tests/acceptance/v1088_transcript_addressable.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import modelcf as M  # noqa: E402
from longrun.tools import registry  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SESS = {"id": "s1", "workspace": "/tmp", "title": "probe", "messages": [
    {"role": "user", "content": "hi", "ts": 10.0},
    {"role": "assistant", "content": "first", "ts": 11.0},
    {"role": "user", "content": "[harness] Observation for tool shell.exec: nope",
     "ts": 12.0},
    {"role": "assistant", "content": '{"action":"tool","tool":"fs.read",'
                                     '"args":{"path":"a.py"}}', "ts": 13.0},
], "tool_cards": [
    {"tool": "shell.exec", "args": "{\"command\": \"grep x f\"}", "ok": True,
     "result": "nothing", "ts": 12.5},
], "injects": [
    {"kind": "nudge", "text": "keep going", "ts": 12.7},
]}

out = T._render_transcript(SESS, limit=30)

# ---- T: message rows carry their index --------------------------------------
check("T1 message 0 is printed with #0", "#0 USER: hi" in out, out[:300])
check("T2 message 1 is printed with #1", "#1 ASSISTANT: first" in out, out[:300])
check("T3 message 3 is printed with #3",
      "#3 ASSISTANT: {\"action\"" in out, out[:400])
for i in range(4):
    check("T4 #%d appears exactly once" % i, out.count("#%d " % i) == 1,
          out.count("#%d " % i))

# ---- C: cards and injects keep their shape ---------------------------------
check("C1 a tool card line is not addressable",
      "TOOL shell.exec(" in out and "#TOOL" not in out, out[:600])
check("C2 a harness note line is not addressable",
      "HARNESS(nudge)" in out and "#HARNESS" not in out, out[:600])

# ---- R: the printed index is the plan's index -------------------------------
_mentions = [ln for ln in out.splitlines() if ln.startswith("#2 ") or " #2 " in ln]
check("R1 the observation row is findable by its printed number",
      bool(_mentions) and "Observation for tool" in _mentions[0], _mentions)
plan, why = M.plan(SESS, 2, {"content": "a different observation"})
check("R2 index 2 from the transcript plans cleanly", not why
      and plan.get("index") == 2, (why, plan.get("index")))
check("R3 the plan shows the same text the transcript numbered",
      "Observation for tool" in str(plan.get("original")), plan.get("original"))

# ---- G: the guidance names the address -------------------------------------
g_read = registry._SUBTOOL_GUIDANCE.get("sessions.read") or ""
g_cf = registry._SUBTOOL_GUIDANCE.get("sessions.model_counterfactual") or ""
check("G1 sessions.read guidance names the #N", "`#N`" in g_read, g_read)
check("G2 model_counterfactual guidance points at it", "`#N`" in g_cf, g_cf)
check("G3 the index property mentions #N too",
      "`#N`" in str(((registry.TOOL_SCHEMAS.get("sessions") or {}).get("properties")
                     or {}).get("index", {}).get("description")),
      ((registry.TOOL_SCHEMAS.get("sessions") or {}).get("properties")
       or {}).get("index"))

# ---- L: the old contract survives ------------------------------------------
check("L1 a USER: label is unescaped", "USER: hi" in out and "\\USER:" not in out)
check("L2 the header still counts messages, cards and notes",
      "4 message(s), 1 tool card(s), 1 harness note(s)" in out, out[:160])

print("\n---\nv1088: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
