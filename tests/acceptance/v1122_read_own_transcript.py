#!/usr/bin/env python3
"""v1122 — reading your OWN transcript is not messaging yourself.

Round 56. The register's `sessions.read · permission` row (4 cards, 4 unresolved)
held two shapes, both produced by the MESSAGING rule applied to a READ:

    read refused: a session cannot message itself through this tool
    read refused: A48 and A2 are in different teams — message inside your team …

A session must be able to read its own transcript (the harness's own rules say
"read the stored history before re-briefing"), and a cross-team refusal must say
it refused a READ. The policy itself does not widen: an agent still reads only
its own session, its team, its reporting line, or the Architect (top leader).

  A  a session reads its own transcript; messaging itself stays refused
  B  a cross-team read is refused and the sentence names the READ
  C  a cross-team message keeps the MESSAGE sentence
  D  same-team and reporting-line reads stay allowed
  E  an unknown session keeps the truthful "no such session"
  F  the Architect rule is unchanged for reads
  G  end to end: `sessions.read` / `sessions.card` on your own session is not 126

Deterministic: temp stores, no server, no model, no network, no delivery.
Run: python3 tests/acceptance/v1122_read_own_transcript.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1122-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents as AG           # noqa: E402
from longrun.agent import architect as LRA      # noqa: E402
from longrun.memory import stores as STORES      # noqa: E402
from longrun.tools import tools as T             # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


reg = AG.REGISTRY
reg.designate("s-lead", name="Lead")
reg.designate("s-sub", name="Sub", reports_to="s-lead")
reg.designate("s-worker", name="Worker", reports_to="s-sub")
reg.designate("s-outside", name="Outsider")
for _sid in ("s-lead", "s-sub", "s-worker", "s-outside"):
    STORES.get_or_create_session(_sid)

# A — your own transcript is yours; messaging yourself is not.
ok, why = T._may_message("s-lead", "s-lead", "read")
check("A1 a session may read its own transcript", ok is True, why)
ok, why = T._may_message("s-lead", "s-lead")
check("A2 it still may not MESSAGE itself", ok is False and "message itself" in why, why)

# B / C — the refusal names the act.
ok, why = T._may_message("s-sub", "s-outside", "read")
check("B1 a cross-team read is refused", ok is False, why)
check("B2 and the sentence names the READ, not a message",
      "read your own transcript" in why and "message inside your team" not in why, why)
ok, why = T._may_message("s-sub", "s-outside")
check("C1 a cross-team message keeps the message sentence",
      ok is False and "message inside your team" in why, why)

# D — the allowed relationships do not change for reads.
check("D1 the same team may read each other",
      T._may_message("s-lead", "s-sub", "read")[0] is True)
check("D2 a report may read up its line",
      T._may_message("s-worker", "s-lead", "read")[0] is True)
check("D3 a manager may read down its line",
      T._may_message("s-lead", "s-worker", "read")[0] is True)

# E — an unknown id stays truthful.
ok, why = T._may_message("s-lead", "s-nope", "read")
check("E1 an unknown session says so", ok is False and "no such session" in why, why)

# F — the Architect rule is the same for a read.
check("F1 a top leader may read the Architect",
      T._may_message("s-lead", "architect", "read")[0] is True)
ok, why = T._may_message("s-sub", "architect", "read")
check("F2 a non-top leader may not, and the reason is the top-leader rule",
      ok is False and "top leader" in why, why)

# G — the handler itself, with the caller's own run id.
r = T._sessions({"action": "read", "session": "s-lead", "limit": 2}, "s-lead")
check("G1 sessions.read on your own session is not refused",
      not r.get("permission_denied") and r.get("exit_code") != 126,
      {k: r.get(k) for k in ("ok", "exit_code", "error")})
r = T._sessions({"action": "card", "session": "s-lead", "handle": "#1"}, "s-lead")
check("G2 sessions.card on your own session is not refused by permission",
      not r.get("permission_denied") and r.get("exit_code") != 126,
      {k: r.get(k) for k in ("ok", "exit_code", "error")})
r = T._sessions({"action": "read", "session": "s-outside", "limit": 2}, "s-sub")
check("G3 a cross-team read through the handler is refused with a read sentence",
      r.get("permission_denied") is True and r.get("exit_code") == 126
      and "read your own transcript" in str(r.get("error") or ""), r.get("error"))

# H — the prompt states the same rule the code enforces.
from longrun.tools import registry  # noqa: E402
desc = registry._LEGACY_SCHEMAS["sessions"]["description"]
check("H1 the schema says the own session is readable, not messageable",
      "always readable" in desc and "cannot message yourself" in desc.lower(),
      desc[-300:])
check("H2 and it no longer claims the line is downward-only",
      "Never upward" not in desc and "in either direction" in desc, desc[-300:])

print("\n---\nv1122: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
