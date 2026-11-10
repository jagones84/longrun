#!/usr/bin/env python3
"""v959 — an access GRANT survives the retired identity.

Regression, verified live on 2026-11-11: `migrate_legacy_identity` rewrote the
access field only inside the files it RENAMED — that is the Architect's own
record. A session that had been GRANTED `allow_longrun_agent` carries its own id
as file name, so it kept the old field and `session_has_access` refused it every
exclusive tool without saying why (session `b7329cccf94c`, "Head of Longrun
Testing": `session_has_access` False, `check_dual_permission` → 126).

Locks:
  A  the grant is renamed on a session whose NAME never carried the retired id;
  B  it also happens on a data home whose MAIN migration already ran (marker);
  C  message PROSE is never touched;
  D  the pass is one-shot: a second call rewrites nothing;
  E  a session without the grant stays without it.

Deterministic: temp data home, no server, no model, no network.
Run: python3 tests/acceptance/v959_grant_survives_rename.py
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v959-")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(TMP, "workspaces")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for d in ("sessions", "graphs", "workspaces"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import architect as LRA        # noqa: E402
from longrun.core import events as EV             # noqa: E402

NEW = LRA.ARCHITECT_SESSION_ID
OLD = LRA._LEGACY_SESSION_ID
results = []


def check(name, ok, detail=None):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- fixture: a GRANTED session whose file name is its own id -----------------
_granted = {"id": "abc123", "title": "granted session",
            LRA._LEGACY_FIELD: True,
            "messages": [{"role": "user",
                          "content": "the note says " + OLD + " in prose"}]}
with open(os.path.join(TMP, "sessions", "abc123.json"), "w", encoding="utf-8") as f:
    json.dump(_granted, f)
_plain = {"id": "plain9", "title": "no grant",
          "messages": [{"role": "user", "content": "hello"}]}
with open(os.path.join(TMP, "sessions", "plain9.json"), "w", encoding="utf-8") as f:
    json.dump(_plain, f)
with open(os.path.join(TMP, "sessions", "broken.json"), "w", encoding="utf-8") as f:
    f.write("{not json")
# A data home migrated by the PREVIOUS code: the main marker is already written.
with open(os.path.join(TMP, ".identity-migrated"), "w", encoding="utf-8") as f:
    f.write(NEW + "\n")

check("E0 before the fix the grant is invisible",
      LRA.session_has_access("abc123") is False)

# --- the repair --------------------------------------------------------------
LRA._MIGRATED = False
LRA._FLAGS_MIGRATED = False
res = LRA.migrate_legacy_identity()
check("B1 the main migration is skipped (its marker exists)",
      res.get("skipped") is True, res)
check("A1 the grant was renamed anyway", res.get("flags") == 1, res)

_g = json.load(open(os.path.join(TMP, "sessions", "abc123.json"), encoding="utf-8"))
check("A2 the session now carries the new field and not the old one",
      _g.get("allow_architect") is True and LRA._LEGACY_FIELD not in _g, _g)
check("A3 the gate now authorizes the granted session",
      LRA.session_has_access("abc123") is True)
check("C1 message prose is untouched",
      _g["messages"][0]["content"] == "the note says " + OLD + " in prose",
      _g["messages"][0]["content"])
_p = json.load(open(os.path.join(TMP, "sessions", "plain9.json"), encoding="utf-8"))
check("E1 a session without the grant stays ungranted",
      "allow_architect" not in _p and LRA.session_has_access("plain9") is False, _p)
check("E2 a malformed record is left alone",
      open(os.path.join(TMP, "sessions", "broken.json"), encoding="utf-8").read() == "{not json")
check("B2 the repair has its own marker",
      os.path.exists(os.path.join(TMP, LRA._FLAGS_MARKER)))

# --- idempotent -------------------------------------------------------------
LRA._MIGRATED = False
LRA._FLAGS_MIGRATED = False
res2 = LRA.migrate_legacy_identity()
check("D1 a second call rewrites nothing", res2.get("flags") == 0, res2)
check("D2 ... and stays skipped", res2.get("skipped") is True, res2)
_g2 = json.load(open(os.path.join(TMP, "sessions", "abc123.json"), encoding="utf-8"))
check("D3 the record is byte-stable after the second call", _g2 == _g)

shutil.rmtree(TMP, ignore_errors=True)
ok = sum(1 for r in results if r)
print("\n%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
