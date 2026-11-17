#!/usr/bin/env python3
"""v1069 — rejecting a plan/spec CLOSES the entity, in every state it can be in (JAG-935).

Operator, 2026-11-17: *"rejecting spec or plan into the approvals RH panel doesn't
make the approval entity to disappear! also in the msg box in chat maybe"*.

Reproduced against the live server (session `5671e8b2c493`, screenshot state):
once the CONTENT is approved the inbox shows the row again (it awaits ▶), with
`can_approve: false` and `can_implement: true` — and `reject` refused it:

    POST /api/approvals/doc:<sid> {"decision":"deny"}
    -> 400 {"error": "document decision failed: reject_plan: no proposed plan …"}

so the row stayed for ever and a second defect surfaced: the route then read
`rec["id"]` on a record that no longer existed (KeyError, the connection was
dropped mid-answer).

Contract pinned here:
  A1 rejecting a `proposed` document works (unchanged)
  A2 rejecting an `approved`, never-implemented document works too
  A3 an IMPLEMENTED document has nothing left to reject (explicit refusal)
  A4 a rejected document is not an inbox row, not even as `decided`
  A5 the decision answers with the id (no empty body), so the event can be published
  A6 the API never indexes `rec["id"]`/`rec["status"]` after a decision
  A7 an approved row says what is actually open (▶ / reject), not "approve"
  A8 the composer bar closes on a rejected document (the "msg box in chat" half)
  A9 the REJECTED record stays on the session, so the model is told (agent context
     reads it verbatim), and the session is unlocked

Deterministic: temp data home, no server, no model, no network.
Run: python3 tests/acceptance/v1069_doc_reject_closes_entity.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1069-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for _d in ("cfg", "data", "sessions"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores          # noqa: E402
from longrun.tools import approvals        # noqa: E402
from longrun.core import api_v02           # noqa: E402
from longrun.core import server            # noqa: E402,F401 — agent imports it (circular otherwise)
from longrun.agent import agent            # noqa: E402

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as _f:
    HTML = _f.read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


DOC = os.path.join(TMP, "plan.md")
with open(DOC, "w", encoding="utf-8") as f:
    f.write("# plan\n")


def make(sid, approve=False, implement=False):
    stores.get_or_create_session(sid, title="t-" + sid)
    stores.propose_plan(sid, ["step one"],
                        doc={"kind": "plan", "title": "Plan — " + sid, "path": DOC,
                             "rel_path": ".longrun/documents/plans/%s.md" % sid},
                        lock=True, origin="composer", intent="document")
    if approve:
        stores.approve_plan(sid, implement=implement)
    return sid


def plan_of(sid):
    return (stores.load_session(sid) or {}).get("plan") or {}


def rows(sid, status=None):
    return [r for r in approvals._document_records(status) if r.get("id") == "doc:" + sid]


# --- A1/A2/A3: reject is possible while the decision is still open ----------
S1 = make("proposed1")
check("A1 a proposed document can be rejected",
      stores.reject_plan(S1) and plan_of(S1).get("status") == "rejected"
      and plan_of(S1).get("decided_ts"), plan_of(S1).get("status"))

S2 = make("approved1", approve=True)
check("A2 an approved, never-implemented document can be rejected",
      stores.reject_plan(S2) and plan_of(S2).get("status") == "rejected"
      and plan_of(S2).get("implement") is False, plan_of(S2).get("status"))

S3 = make("implemented1", approve=True, implement=True)
try:
    stores.reject_plan(S3)
    check("A3 an implemented document has nothing left to reject", False, "no raise")
except ValueError as exc:
    check("A3 an implemented document has nothing left to reject",
          "already authorised" in str(exc) and plan_of(S3).get("status") == "approved", str(exc))

# --- A4: a rejected document is not an entity in the inbox -------------------
check("A4 a rejected document has no inbox row (pending)",
      rows(S2, "pending") == [], rows(S2, "pending"))
check("A4b a rejected document has no inbox row (decided either)",
      rows(S2) == [] and approvals.get_any("doc:" + S2) is None, rows(S2))

# --- A5: the decision answers with the id (the event needs it) ---------------
res = approvals.decide_any("doc:" + make("deny1", approve=True), "deny")
check("A5 deciding a document answers with an id and a status",
      res.get("ok") is True and (res.get("approval") or {}).get("id", "").startswith("doc:")
      and (res.get("approval") or {}).get("status"), str(res)[:160])

# --- A6: the route must not index a record that left the inbox ---------------
API_SRC = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
               encoding="utf-8").read()
check("A6 the approval event takes the REQUESTED id, never `rec[\"id\"]`",
      'id=(rec.get("id") or aid)' in API_SRC
      and 'status=rec.get("status") or "decided"' in API_SRC
      and 'by=rec.get("decided_by"), status=rec["status"])' not in API_SRC, "")

# --- A7: an approved row names the decision that is open ---------------------
S7 = make("approved2", approve=True)
row = rows(S7, "pending")[0]
check("A7 the approved row is about ▶ and says reject withdraws it",
      row.get("can_implement") is True and "▶ authorises" in row.get("reason", "")
      and "reject withdraws" in row.get("reason", ""), row.get("reason"))

# --- A8: the composer bar closes on a rejected document ----------------------
check("A8 the doc bar hides when the active document is rejected",
      'if (a && a.status === "rejected" && !r.plan_mode) { bar.hidden = true;' in HTML, "")

# --- A9: the record stays for the model, and the session is unlocked ---------
from longrun.plan import docs as docs_mod     # noqa: E402
S9 = make("unlock1", approve=True)
docs_mod.reject(S9)
st = docs_mod.status(S9)
check("A9 reject unlocks the session and keeps the record on disk",
      st.get("plan_mode") is False and (st.get("active") or {}).get("status") == "rejected",
      (st.get("plan_mode"), (st.get("active") or {}).get("status")))
block = agent._document_block(S9)
check("A9b the next turn tells the model the document was REJECTED",
      "REJECTED" in block and "do NOT implement" in block, block[:160])

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
raise SystemExit(0 if all(results) else 1)
