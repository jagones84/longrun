#!/usr/bin/env python3
"""v567 — consumable approvals (M4a, Petri AEPN spent vs tested).

An approved mark is consumed once: a replayed approval id cannot execute
again. `approvals.mode=full` and auto patterns never enter `consume`
(owner present / tested conditions by design) — only granted `required`
approvals are spent.

Deterministic, no live server, no network.
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v567-")
os.environ["LONGRUN_APPROVALS"] = os.path.join(TMP, "approvals.json")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import approvals  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _grant(tool="fs.read", args=None, **kw):
    args = {"path": "a.txt"} if args is None else args
    rec = approvals.create(tool, args, run_id="v567", decision="pending",
                           reason="test", **kw)
    approvals.decide(rec["id"], "approve", by="test")
    return approvals.get(rec["id"])


# ---- 1. create carries the consumable mark ------------------------------------
r0 = approvals.create("fs.read", {"path": "a.txt"}, run_id="v567")
check("1a create stamps uses_left=1, no expiry, a 64-hex digest",
      r0.get("uses_left") == 1 and r0.get("expires_at") is None
      and isinstance(r0.get("digest"), str) and len(r0["digest"]) == 64,
      {k: r0.get(k) for k in ("uses_left", "expires_at", "digest")})

# ---- 2. single use -------------------------------------------------------------
rec = _grant()
ok, msg = approvals.consume(rec["id"], "fs.read", {"path": "a.txt"})
check("2a first consume of the approved call succeeds",
      ok is True and approvals.get(rec["id"])["uses_left"] == 0, msg)
ok, msg = approvals.consume(rec["id"], "fs.read", {"path": "a.txt"})
check("2b the replayed approval id is denied (spent)",
      ok is False and "spent" in msg, msg)

# ---- 3. digest binds the exact call ----------------------------------------------
rec = _grant()
ok, msg = approvals.consume(rec["id"], "fs.read", {"path": "OTHER.txt"})
check("3a different args are denied (digest mismatch)",
      ok is False and "match" in msg, msg)
ok, msg = approvals.consume(rec["id"], "fs.read", {"path": "a.txt"})
check("3b the exact call still consumes afterwards",
      ok is True, msg)
ok, msg = approvals.consume(rec["id"], "fs.write", {"path": "a.txt"})
check("3c a different tool is denied even when spent",
      ok is False, msg)

# ---- 4. canonical form: key order never breaks a legitimate call -----------------
r1 = approvals.create("fs.read", {"b": 1, "a": 2}, run_id="v567")
r2 = approvals.create("fs.read", {"a": 2, "b": 1}, run_id="v567")
check("4a reordered args share the digest",
      r1.get("digest") == r2.get("digest"))

# ---- 5. expiry -------------------------------------------------------------------
rec = _grant(expires_at=time.time() - 10)
ok, msg = approvals.consume(rec["id"], "fs.read", {"path": "a.txt"})
check("5a a past expiry denies and marks the record expired",
      ok is False and "expired" in msg
      and approvals.get(rec["id"])["status"] == "expired", msg)

# ---- 6. legacy records (no digest, no uses_left) ---------------------------------
rec = _grant()
rec.pop("digest", None)
rec.pop("uses_left", None)
ok, msg = approvals.consume(rec["id"], "fs.read", {"path": "a.txt"})
check("6a legacy records consume once (verification skipped)",
      ok is True, msg)
ok, msg = approvals.consume(rec["id"], "fs.read", {"path": "a.txt"})
check("6b legacy records deny the replay too",
      ok is False, msg)

# ---- 7. fail-closed edges ----------------------------------------------------------
ok, msg = approvals.consume("no-such-id", "fs.read", {"path": "a.txt"})
check("7a unknown ids are denied",
      ok is False and "unknown" in msg, msg)
_pend = approvals.create("fs.read", {"path": "a.txt"}, run_id="v567")
ok, msg = approvals.consume(_pend["id"], "fs.read", {"path": "a.txt"})
check("7b non-approved records are denied",
      ok is False and "approved" in msg, msg)

# ---- 8. both gate paths spend the mark ----------------------------------------------
with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
          encoding="utf-8") as f:
    _api = f.read()
check("8a tool_action and gated_call both consume after a grant",
      _api.count("approvals.consume(") >= 2, _api.count("approvals.consume("))
check("8b every consume is observed",
      _api.count("approval.consumed") >= 2, _api.count("approval.consumed"))

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
