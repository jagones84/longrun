#!/usr/bin/env python3
"""v1127 — a repair draft carries the register's numbers, not the ones it was born with.

Round 61. `issue_drafts` skipped an existing draft on the mere presence of
`proposal.json`, so an unfixed draft was never updated. Measured live 2026-11-18:
37 drafts, 34 of them `proposed` and frozen — e.g. `fail-shell-exec-nonzero-exit`
still claimed "18 failure(s) in 2 session(s)" while the register (after round 53
re-classified the cards) counts 3. The draft is the artifact a reader acts on, so
that is a second truth: the register and the draft disagree and nothing reconciles
them.

The fix: on a re-run, an UNFIXED draft whose evidence changed is rewritten from the
current issue (count, family, classes, samples, whoever), keeping `created` and
recording the prior numbers in `previous`; a draft that carries a `fix` is history
and is never rewritten; an unchanged draft is not touched; and a WINDOWED read
(`since`) never rewrites an all-time draft with a partial count.

  A  a fresh draft is written with the issue's numbers
  B  a stale unfixed draft is REFRESHED (count, REPAIR.md, previous, created kept)
  C  an unchanged draft is left alone (skipped, no rewrite)
  D  a draft carrying a fix is history: never refreshed, its fix survives
  E  a windowed read does not rewrite an all-time draft
  F  the answer names the refresh (a re-run is not "nothing happened")

Deterministic: the register is stubbed; no session store, no model, no network.
Run: python3 tests/acceptance/v1127_repair_drafts_refresh.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1127-")
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


ISSUE = {
    "id": "fail-shell-exec-nonzero-exit", "tool": "shell.exec",
    "family": "nonzero-exit", "severity": "warning",
    "count": 3, "sessions": 1, "from_sessions": 0, "from_runs": 3,
    "repeats": 0, "retry_rate": 0.0, "recovered": 0, "recovery_rate": None,
    "refusal": False, "runs": 1, "source": "runs",
    "classes": [{"error": "exit=<n> (no error text)", "count": 3,
                 "from_sessions": 0, "from_runs": 3, "overlap": 0,
                 "repeats": 0, "recovered": 0, "unresolved": 3}],
    "samples": [], "agents": [],
    "action": "read stderr in the observation and correct the command",
    "check": "v523",
}

_register = {"issues": [ISSUE], "since": None, "runs": 1, "sessions": 0, "ok": True}
_orig_fc = selfevolve.failure_candidates


def _fake_candidates(**kw):
    out = dict(_register)
    out["since"] = kw.get("since")
    return out


selfevolve.failure_candidates = _fake_candidates
out = os.path.join(_tmp, "repairs")
pj = os.path.join(out, ISSUE["id"], "proposal.json")
md = os.path.join(out, ISSUE["id"], "REPAIR.md")

# --- A: the first run writes the draft with the register's numbers -------------
r1 = selfevolve.issue_drafts(out, limit=5, min_severity="info")
p1 = json.load(open(pj)) if os.path.isfile(pj) else {}
check("A1 a fresh draft is written",
      [w["issue"] for w in r1.get("written") or []] == [ISSUE["id"]], r1.get("written"))
check("A2 and carries the issue's count", p1.get("count") == 3, p1.get("count"))
check("A3 the markdown states that count", "**3**" in open(md).read(), open(md).read()[:200])
created = p1.get("created")

# --- B: a stale unfixed draft is refreshed ------------------------------------
p = json.load(open(pj))
p["count"] = 999
json.dump(p, open(pj, "w"))
open(md, "w").write("# Repair: shell.exec · nonzero-exit\n\n**Severity:** error — **999** failure(s)\n")
r2 = selfevolve.issue_drafts(out, limit=5, min_severity="info")
p2 = json.load(open(pj))
check("B1 the stale draft is reported as refreshed",
      [w["issue"] for w in r2.get("refreshed") or []] == [ISSUE["id"]], r2.get("refreshed"))
check("B2 the count is the register's, not the old one", p2.get("count") == 3, p2.get("count"))
check("B3 the old number is kept in `previous`",
      (p2.get("previous") or {}).get("count") == 999, p2.get("previous"))
check("B4 `created` is preserved", p2.get("created") == created, p2.get("created"))
check("B5 a refresh stamps its own clock", bool(p2.get("refreshed_ts")), p2.get("refreshed_ts"))
txt = open(md).read()
check("B6 REPAIR.md is regenerated with the new count", "999" not in txt and "**3**" in txt,
      txt[:200])
check("B7 the refreshed draft is not also counted as written",
      not (r2.get("written") or []), r2.get("written"))

# --- C: an unchanged draft is left alone --------------------------------------
stamp = p2.get("refreshed_ts")
r3 = selfevolve.issue_drafts(out, limit=5, min_severity="info")
p3 = json.load(open(pj))
check("C1 an unchanged draft is skipped",
      ISSUE["id"] in (r3.get("skipped") or []), r3.get("skipped"))
check("C2 nothing is refreshed", not (r3.get("refreshed") or []), r3.get("refreshed"))
check("C3 its refresh clock does not move", p3.get("refreshed_ts") == stamp,
      (stamp, p3.get("refreshed_ts")))

# --- D: a fixed draft is history ----------------------------------------------
p = json.load(open(pj))
p["count"] = 777
p["status"] = "fixed"
p["fix"] = {"commit": "abc1234", "date": "2026-11-18", "note": "test"}
json.dump(p, open(pj, "w"))
r4 = selfevolve.issue_drafts(out, limit=5, min_severity="info")
p4 = json.load(open(pj))
check("D1 a fixed draft is never refreshed",
      not (r4.get("refreshed") or []) and ISSUE["id"] in (r4.get("skipped") or []),
      (r4.get("refreshed"), r4.get("skipped")))
check("D2 its count is untouched", p4.get("count") == 777, p4.get("count"))
check("D3 and its fix survives", (p4.get("fix") or {}).get("commit") == "abc1234",
      p4.get("fix"))

# --- E: a windowed read does not rewrite an all-time draft ---------------------
p = json.load(open(pj))
p.pop("fix", None)
p["status"] = "proposed"
p["count"] = 555
json.dump(p, open(pj, "w"))
r5 = selfevolve.issue_drafts(out, limit=5, min_severity="info", since=1794900000)
p5 = json.load(open(pj))
check("E1 a windowed read refreshes nothing",
      not (r5.get("refreshed") or []), r5.get("refreshed"))
check("E2 and leaves the all-time numbers alone", p5.get("count") == 555, p5.get("count"))

# --- F: the tool's answer names the refresh -----------------------------------
p = json.load(open(pj))
p["count"] = 999
json.dump(p, open(pj, "w"))
_orig_dir = improve.PROPOSAL_DIR
improve.PROPOSAL_DIR = _tmp
try:
    ans = T._improve({"action": "repairs", "limit": 5, "min_severity": "info"})
finally:
    improve.PROPOSAL_DIR = _orig_dir
check("F1 the answer is ok", ans.get("ok") is True, ans.get("error"))
stdout = str(ans.get("stdout") or "")
check("F2 it names the refreshed draft", "refreshed" in stdout.lower(), stdout[:400])
check("F3 and states the new count", "3" in stdout, stdout[:400])
check("F4 the payload carries what it refreshed",
      [w.get("issue") for w in ans.get("refreshed") or []] == [ISSUE["id"]],
      ans.get("refreshed"))

selfevolve.failure_candidates = _orig_fc
print("\n---\nv1127: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
