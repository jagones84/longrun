#!/usr/bin/env python3
"""v1139 — a pending proposal that can no longer apply is not pending work.

Round 74. Measured 2026-11-18 on the live store: the only pending proposal removes
`grep[^\\n]*\\.env`, a hard-deny rule deleted in round 65. `registry.delta_error`
already refuses it and the approvals inbox already blocks the button — yet
`GET /api/improvement` still listed it as `pending` and the Improvement panel
counted it, so the operator was offered a decision that cannot be taken.

  A  a pending registry proposal whose delta the registry refuses carries `stale`
  B  a pending proposal whose delta still applies does not
  C  a decided proposal and a non-registry proposal are never annotated
  D  the stored status is untouched (the listing annotates, it does not rewrite)
  E  the panel excludes stale rows from the pending list and names them apart

Deterministic: a temporary proposals dir + the repo's own policy; no server, no model.
Run: python3 tests/acceptance/v1139_stale_pending_proposal.py
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1139-")
PROPS = os.path.join(TMP, "proposals")
os.makedirs(PROPS, exist_ok=True)
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_PROPOSALS_DIR"] = PROPS
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402
from longrun.util import improve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def put(pid, rec):
    rec = dict(rec, id=pid, ts=time.time())
    with open(os.path.join(PROPS, pid + ".json"), "w", encoding="utf-8") as f:
        json.dump(rec, f)
    return rec


live_deny = registry._effective_list("shell.exec", "deny")
check("A0 the policy has a rule to remove (fixture precondition)", len(live_deny) >= 1, live_deny)

gone = {"target": "shell.exec", "field": "deny",
        "remove": ["grep[^\\n]*\\.env"], "reason": "round 65 removed it"}
check("A0b the registry refuses that delta (the premise)",
      bool(registry.delta_error(gone)), registry.delta_error(gone))

put("1-pending-gone", {"scope": "registry", "status": "pending", "delta": gone,
                       "content": "drop the .env grep block", "origin": "agent"})
put("2-pending-live", {"scope": "registry", "status": "pending",
                       "delta": {"target": "shell.exec", "field": "deny",
                                 "remove": [live_deny[0]], "reason": "one live rule"},
                       "content": "drop one live rule", "origin": "agent"})
put("3-approved-gone", {"scope": "registry", "status": "approved", "delta": gone,
                        "content": "decided long ago", "origin": "agent"})
put("4-project", {"scope": "project", "status": "pending",
                  "content": "a rule for the project", "origin": "agent"})

rows = {r["id"]: r for r in improve.list_proposals()}
check("A1 the impossible pending delta carries `stale`",
      bool(rows.get("1-pending-gone", {}).get("stale"))
      and "cannot be applied" in rows["1-pending-gone"]["stale"],
      rows.get("1-pending-gone"))
check("A2 the reason names the registry's own refusal",
      "not in the live" in (rows.get("1-pending-gone", {}).get("stale") or ""),
      rows.get("1-pending-gone"))
check("B1 a pending delta that still applies is untouched",
      "stale" not in rows.get("2-pending-live", {}), rows.get("2-pending-live"))
check("C1 a decided proposal is never annotated", "stale" not in rows.get("3-approved-gone", {}))
check("C2 a non-registry proposal is never annotated", "stale" not in rows.get("4-project", {}))
check("D1 the stored status is untouched (annotate, never rewrite)",
      rows.get("1-pending-gone", {}).get("status") == "pending"
      and json.load(open(os.path.join(PROPS, "1-pending-gone.json")))["status"] == "pending")

src = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("E1 the panel keeps stale rows out of the pending list",
      'p.status === "pending" && !p.stale' in src)
check("E2 and names them apart with their reason",
      "pending proposal(s) no longer apply" in src and "esc(p.stale" in src)
check("E3 the pending count is the filtered list", src.count("pend.length") >= 3)

api = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
check("E4 the panel payload is the annotated listing (one owner)",
      "raw = improve_mod.list_proposals()" in api)

print("\n---\nv1139: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
