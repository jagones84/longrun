#!/usr/bin/env python3
"""v1128 — a repair draft whose class is gone is stale, not open work.

Round 62. Round 61 made a draft carry the register's current numbers, but only for
ids the register still produces. Measured live 2026-11-18: 37 drafts, 6 of them
`proposed` with NO class at their id any more — `fail-http-fetch-nonzero-exit` and
`fail-web-fetch-nonzero-exit` both exist and only `web.fetch` is a current tool, so
the old one names a tool nothing answers to. Nothing marks them, the panel shows
them as "not fixed yet", and `open` counts work nobody can do.

The rule: in an ALL-TIME read, a draft with no `fix` whose id is not among the
register's issues is marked `stale` — status, `stale {ts, reason, successor}` and a
regenerated Status section — and reported. It keeps the record (the reason the
draft existed is evidence) but stops reading as open. Idempotent; a fixed draft is
history; a WINDOWED read marks nothing.

  A  an orphan draft is marked stale (status, stamp, reason, Status section)
  B  the stamp is idempotent (a second read marks nothing new)
  C  a fixed draft with no class at its id is NOT marked — it is history
  D  a windowed read marks nothing
  E  a live draft is not marked
  F  the successor is named when a current issue shares the tool
  G  `repair_states` reports `stale` and `improvement_repairs` counts it apart
  H  the tool's answer names it

Deterministic: the register is stubbed; no session store, no model, no network.
Run: python3 tests/acceptance/v1128_stale_repair_drafts.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1128-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402
from longrun.util import improve, selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def issue(ident, tool, family, count=3):
    return {"id": ident, "tool": tool, "family": family, "severity": "warning",
            "count": count, "sessions": 1, "from_sessions": 0, "from_runs": count,
            "repeats": 0, "retry_rate": 0.0, "recovered": 0, "recovery_rate": None,
            "refusal": False, "runs": 1, "source": "runs",
            "classes": [{"error": "exit=<n> (no error text)", "count": count,
                         "from_sessions": 0, "from_runs": count, "overlap": 0,
                         "repeats": 0, "recovered": 0, "unresolved": count}],
            "samples": [], "agents": [],
            "action": "read stderr in the observation and correct the command",
            "check": "v523"}


LIVE = issue("fail-web-fetch-nonzero-exit", "web.fetch", "nonzero-exit")
CUR = {"issues": [LIVE], "since": None, "runs": 1, "sessions": 0, "ok": True}
_orig_fc = selfevolve.failure_candidates


def _fake_candidates(**kw):
    out = dict(CUR)
    out["since"] = kw.get("since")
    return out


selfevolve.failure_candidates = _fake_candidates
out = os.path.join(_tmp, "repairs")
orphan = os.path.join(out, "fail-web-fetch-timeout")


def write_draft(name, tool, family, fix=None, status="proposed"):
    d = os.path.join(out, name)
    os.makedirs(d, exist_ok=True)
    p = {"kind": "repair", "status": status, "name": name, "issue": name,
         "tool": tool, "family": family, "severity": "warning", "count": 1,
         "sessions": 1, "from_sessions": 0, "from_runs": 1, "repeats": 0,
         "retry_rate": 0.0, "recovered": 0, "recovery_rate": None,
         "refusal": False, "runs": 1, "source": "runs",
         "classes": [], "samples": [], "agents": [],
         "action": "read stderr in the observation and correct the command",
         "check": "v523", "since": None, "created": 1794000000.0,
         "origin": "auto", "next": "state the fix"}
    if fix:
        p["fix"] = fix
    json.dump(p, open(os.path.join(d, "proposal.json"), "w"))
    open(os.path.join(d, "REPAIR.md"), "w").write(
        "# Repair: %s · %s\n\n**Severity:** warning — **1** failure(s)\n\n## Status\n\nDRAFT — material, not a change.\n"
        % (tool, family))
    return p


# --- A: an orphan draft is marked stale ---------------------------------------
write_draft("fail-web-fetch-timeout", "web.fetch", "timeout")
r1 = selfevolve.issue_drafts(out, limit=5, min_severity="info")
p1 = json.load(open(os.path.join(orphan, "proposal.json")))
check("A1 the orphan is reported stale",
      [w["issue"] for w in r1.get("stale") or []] == ["fail-web-fetch-timeout"],
      r1.get("stale"))
check("A2 its status says stale", p1.get("status") == "stale", p1.get("status"))
check("A3 it carries a stamp and a reason",
      bool((p1.get("stale") or {}).get("ts")) and "no class" in (p1.get("stale") or {}).get("reason", ""),
      p1.get("stale"))
check("A4 the successor is named when a current issue shares the tool",
      (p1.get("stale") or {}).get("successor") == "fail-web-fetch-nonzero-exit",
      (p1.get("stale") or {}).get("successor"))
txt = open(os.path.join(orphan, "REPAIR.md")).read()
check("A5 REPAIR.md Status says STALE", "STALE" in txt, txt[-400:])

# --- B: idempotent ------------------------------------------------------------
stamp = p1["stale"]["ts"]
r2 = selfevolve.issue_drafts(out, limit=5, min_severity="info")
p2 = json.load(open(os.path.join(orphan, "proposal.json")))
check("B1 a second read marks nothing new", not (r2.get("stale") or []), r2.get("stale"))
check("B2 the stamp does not move", p2["stale"]["ts"] == stamp, (stamp, p2["stale"]["ts"]))

# --- C: a fixed draft is history ---------------------------------------------
write_draft("fail-grep-search-nonzero-exit", "grep.search", "nonzero-exit",
            fix={"commit": "abc1234", "date": 1794800000.0, "note": "done"},
            status="fixed")
selfevolve.issue_drafts(out, limit=5, min_severity="info")
pc = json.load(open(os.path.join(out, "fail-grep-search-nonzero-exit", "proposal.json")))
check("C1 a fixed draft is not marked stale", not pc.get("stale"), pc.get("stale"))
check("C2 its status is untouched", pc.get("status") == "fixed", pc.get("status"))

# --- D: a windowed read marks nothing ----------------------------------------
write_draft("fail-sessions-read-nonzero-exit", "sessions.read", "nonzero-exit")
r4 = selfevolve.issue_drafts(out, limit=5, min_severity="info", since=1794900000)
pd = json.load(open(os.path.join(out, "fail-sessions-read-nonzero-exit", "proposal.json")))
check("D1 a windowed read marks nothing", not (r4.get("stale") or []), r4.get("stale"))
check("D2 and the draft keeps its status", pd.get("status") == "proposed", pd.get("status"))

# --- E: a live draft is not marked -------------------------------------------
selfevolve.issue_drafts(out, limit=5, min_severity="info")
pe = json.load(open(os.path.join(out, "fail-web-fetch-nonzero-exit", "proposal.json")))
check("E1 a live draft exists and is not stale", not pe.get("stale"), pe.get("stale"))

# --- G: the lifecycle and the panel agree ------------------------------------
st = selfevolve.repair_states(out)
by = {s["issue"]: s for s in st.get("states") or []}
check("G1 repair_states reports the stale draft as stale",
      (by.get("fail-web-fetch-timeout") or {}).get("status") == "stale",
      (by.get("fail-web-fetch-timeout") or {}).get("status"))
from longrun.core import server as _srv  # noqa: E402,F401 — httpapi imports it first
from longrun.core import httpapi  # noqa: E402
_orig_dir = improve.PROPOSAL_DIR
improve.PROPOSAL_DIR = _tmp
try:
    panel = httpapi.improvement_repairs()
finally:
    improve.PROPOSAL_DIR = _orig_dir
check("G2 the panel counts it apart from open work",
      int(panel.get("stale") or 0) >= 1, panel.get("stale"))
check("G3 and leaves it out of `open`",
      int(panel.get("open") or 0) == 1, panel.get("open"))

# --- H: the answer names it --------------------------------------------------
write_draft("fail-python-run-tool-error", "python.run", "tool-error")
improve.PROPOSAL_DIR = _tmp
try:
    ans = T._improve({"action": "repairs", "limit": 5, "min_severity": "info"})
finally:
    improve.PROPOSAL_DIR = _orig_dir
stdout = str(ans.get("stdout") or "")
check("H1 the answer is ok", ans.get("ok") is True, ans.get("error"))
check("H2 it names the stale draft", "stale" in stdout.lower(), stdout[:400])
check("H3 and invents no window for it",
      "0 occurrence(s) in the 0 session(s)" not in stdout, stdout[-400:])

selfevolve.failure_candidates = _orig_fc
print("\n---\nv1128: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
