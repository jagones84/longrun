#!/usr/bin/env python3
"""v1233 — team jobs (J<n>) and in-chat Session Jobs (SJ<n>) are separate objects.

Measured 2026-11-20 (operator): the Jobs panel opened on a wall of `SJ` rows
(goal "batch") and the live team job `J47` sat below the fold; the header merged
both ledgers into one `29`, and `/clear` left the SJ ledger alive. The two layers
were already segregated on disk, but the PAYLOAD did not say which kind a row was
and the panel treated them as one list.

This test pins the contract and the presentation:

  A team jobs are self-describing: kind="team" on the list, its rows and detail
  B Session Jobs are self-describing: kind="session", read_only, SJ ids
  C no cross-contamination between the two stores
  D /clear kills the in-chat cognition (SJ ledger + durable subagent records)
  E route separation and the /sj 404 for an unknown session
  F the Jobs panel renders two hard-separated sections with per-kind counters
  G the per-kind counter still counts every state present (executed under node)

Deterministic: temp stores, no model, no network, no server.
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

TMP = tempfile.mkdtemp(prefix="sf-v1233-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR", "SUBAGENT_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_SJ_DIR"] = os.path.join(TMP, "session_jobs")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")

# core/server.py imports the prompt constants out of agent.py, so import it first.
from longrun.core import server as _server  # noqa: E402,F401
from longrun.agent import session_jobs as SJ  # noqa: E402
from longrun.agent import subagent as SUB  # noqa: E402
from longrun.memory import stores  # noqa: E402
from longrun.orchestrate import jobs as J  # noqa: E402
from longrun.orbit import api as OAPI  # noqa: E402

results = []


def check(name, passed, detail=""):
    results.append(bool(passed))
    print(("PASS " if passed else "FAIL ") + name
          + ((" :: " + str(detail)) if (detail and not passed) else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


SID = "v1233sess001"

# --------------------------------------------------------- A: team payload ----
made = J.JOBS.create("v1233 team job", coordinator="A1", agents=["A1", "A2"])
JID = ((made or {}).get("job") or {}).get("id") or ""
lst = J.JOBS.list()
check("A1 the team-jobs list is self-describing",
      lst.get("kind") == "team" and JID.startswith("J"), (lst.get("kind"), JID))
check("A2 every team-job row says kind=team and no row is an SJ",
      all(j.get("kind") == "team" and not str(j.get("id", "")).startswith("SJ")
          for j in (lst.get("jobs") or [])),
      [(j.get("id"), j.get("kind")) for j in (lst.get("jobs") or [])])
det = J.JOBS.detail(JID) or {}
check("A3 the team-job detail keeps the kind", det.get("kind") == "team", det.get("kind"))

# ------------------------------------------------------ B: session payload ----
sj_job = SJ.create(SID, "v1233 in-chat batch", [{"label": "one"},
                                                {"label": "two", "deps": ["one"]}])
desc = SJ.describe(SID)
check("B1 the SJ read model is self-describing and read-only",
      desc.get("kind") == "session" and desc.get("read_only") is True,
      (desc.get("kind"), desc.get("read_only")))
check("B2 every SJ job says kind=session and carries an SJ id",
      (desc.get("jobs") or [])
      and all(j.get("kind") == "session" and str(j.get("id", "")).startswith("SJ")
              for j in desc.get("jobs") or []),
      [(j.get("id"), j.get("kind")) for j in (desc.get("jobs") or [])])
check("B3 the ledger file is named as an SJ store, never jobs.json",
      "/session_jobs/" in str(desc.get("file")) and str(desc.get("file")).endswith(".json"),
      desc.get("file"))

# --------------------------------------------------- C: no contamination ------
team_ids = [j.get("id") for j in (J.JOBS.list().get("jobs") or [])]
sj_ids = [j.get("id") for j in (SJ.describe(SID).get("jobs") or [])]
check("C1 the team store never holds an SJ id",
      all(not str(x).startswith("SJ") for x in team_ids), team_ids[-6:])
check("C2 the session ledger never holds a team job id",
      all(str(x).startswith("SJ") for x in sj_ids), sj_ids)
check("C3 the created objects stayed in their own store",
      JID in team_ids and sj_job.get("job") in sj_ids, (JID, sj_ids))

# --------------------------------------------- D: clear kills in-chat work ----
stores.save_session({"id": SID, "title": "v1233 clear me",
                     "messages": [{"role": "user", "content": "hello"}],
                     "tool_cards": [], "injects": []})
SUB._persist({"id": "sub_v1233", "parent": SID, "status": "done", "summary": "x"})
ledger = SJ.path_for(SID)
check("D1 the fixtures exist before the clear",
      os.path.isfile(ledger) and SUB.load_record("sub_v1233") is not None, ledger)
stores.clear_session(SID)
check("D2 /clear removes the SJ ledger",
      not os.path.isfile(ledger) and SJ.describe(SID).get("jobs") == [], ledger)
check("D3 /clear removes the durable subagent records of the chat",
      SUB.load_record("sub_v1233") is None, "sub_v1233 survived")
fresh = SJ.create(SID, "after clear", [{"label": "again"}])
check("D4 a cleared chat starts a fresh SJ sequence (SJ1 again)",
      fresh.get("job") == "SJ1", fresh)

# ------------------------------------------------ E: route separation ---------
HTTP = _read("src", "longrun", "core", "httpapi.py")
ORCH = _read("src", "longrun", "orchestrate", "orchestration.py")
check("E1 the SJ route lives in httpapi and reads the session ledger",
      'path.endswith("/sj")' in HTTP
      and "from longrun.agent import session_jobs as _sj" in HTTP
      and "_sj.describe(" in HTTP)
check("E2 the SJ route refuses an unknown/deleted session",
      "if not load_session(sid):" in HTTP
      and '"session not found"' in HTTP)
check("E3 the team-jobs routes are owned by orchestrate/orchestration.py",
      "jobs_mod.JOBS.list()" in ORCH and "jobs_mod.JOBS.detail(jid)" in ORCH
      and "session_jobs" not in ORCH)
check("E4 neither module reaches into the other store",
      "session_jobs" not in ORCH and "jobs.json" not in HTTP)

# ------------------------------------------------ F: panel contract -----------
UI = _read("src", "longrun", "orbit", "web", "orbit.html")
check("F1 the Jobs header counts TEAM jobs only (no merged ledger)",
      "this._countText(this.jobs)" in UI
      and "this._countText(this.jobs.concat(_sjJobs))" not in UI
      and "_sjJobs" not in UI)
check("F2 the in-chat section has its own counter and says it is not dispatched",
      "In-chat subagents" in UI and "this._countText(jobs)" in UI
      and "not dispatched \u00b7 read-only" in UI)
check("F3 the panel renders the team rows FIRST and the SJ section after them",
      "const _teamHtml" in UI
      and UI.find("this._sjHtml()") > UI.find("const _teamHtml"))
check("F4 both kinds carry an explicit DOM marker",
      'data-kind="team"' in UI and 'data-kind="session"' in UI)
check("F5 SJ subjobs use their own marker (never focusJob's data-sub)",
      'data-sjsub="' in UI
      and 'return \'<div class="runrow" data-sjsub="' in UI)
check("F6 the old ambiguous wording is gone",
      "In-session jobs" not in UI and "no subagent job" not in UI
      and "no in-chat subagent batch in this session" in UI)
check("F7 embed mode still carries an h1 (axe page-has-heading-one)",
      'embed-title' in UI and '<h1 class="sr-only embed-title">' in UI
      and "html.embed .embed-title{display:block}" in UI)

# ------------------------------------------------ G: counter behaviour --------
_C = ""
_i = UI.find("  _countText(rows){")
if _i >= 0:
    _e = UI.find("\n  }", _i)
    if _e > 0:
        _C = UI[_i:_e + 4]
if not _C:
    check("G1 the count block is present and delimited", False, "markers missing")
elif not shutil.which("node"):
    print("SKIP the count block was not executed (node not installed)")
else:
    _harness = r"""
const view = {
__BLOCK__
};
const t = (name, rows) => console.log(name + "\t" + view._countText(rows));
t("A", [{status:"running"},{status:"blocked"},{status:"error"},{status:"partial"},
        {status:"done"},{status:"done"}]);
t("B", [{status:"done"},{status:"done"}]);
t("C", []);
""".replace("__BLOCK__", _C)
    _js = os.path.join(tempfile.gettempdir(), "v1233_count_text.js")
    with open(_js, "w", encoding="utf-8") as _fh:
        _fh.write(_harness)
    _run = subprocess.run(["node", _js], capture_output=True, text=True, timeout=60)
    _got = dict(ln.split("\t") for ln in _run.stdout.strip().splitlines() if "\t" in ln)
    check("G2 every state present is counted, done last",
          _got.get("A") == "1 running \u00b7 1 blocked \u00b7 1 partial \u00b7 1 error \u00b7 2 done / 6",
          _got.get("A") or _run.stderr[-200:])
    check("G3 a settled list and an empty list stay truthful",
          _got.get("B") == "2 done / 2" and _got.get("C") == "\u2014", _got)

# ------------------------------------------------ H: cross-kind identity ------
# 2026-11-20: an explicit TEAM-job id must never resolve to an unrelated SJ.
# SJ-shaped unknown ids keep the legacy fallback (v611 T11 / v613 T4).
check("H1 a team-job id is not answered with the newest Session Job",
      SJ.describe(SID, "J1").get("jobs") == [],
      SJ.describe(SID, "J1"))
check("H1b an SJ-shaped unknown id keeps the documented fallback",
      [j.get("id") for j in SJ.describe(SID, "SJ99").get("jobs") or []] == ["SJ1"],
      SJ.describe(SID, "SJ99"))
_no_run = SJ.run(SID, "J1")
check("H1c running a team-job id fails loudly and does not touch the SJ engine",
      _no_run.get("ok") is False and "no such SJ: J1" in str(_no_run.get("error")),
      _no_run)

# ------------------------------------------------ H2: write responses ---------
check("H2 team create/update responses carry kind=team",
      made.get("job", {}).get("kind") == "team"
      and J.JOBS.update(JID, aim="v1233 team job").get("job", {}).get("kind") == "team",
      (made.get("job"), J.JOBS.update(JID, aim="v1233 team job").get("job")))
check("H2b the SJ create response carries kind=session",
      sj_job.get("kind") == "session" and sj_job.get("job", "").startswith("SJ"),
      sj_job)

# ------------------------------------------------ H3: constellation -----------
_cns = OAPI._constellation()
_cjobs = _cns.get("jobs") or []
_sj_now = [j.get("id") for j in SJ.describe(SID).get("jobs") or []]
check("H3 the constellation lists team jobs only, with kind=team",
      bool(_cjobs)
      and all(j.get("kind") == "team" and str(j.get("id", "")).startswith("J")
              for j in _cjobs)
      and not (_sj_now and set(_sj_now) & {j.get("id") for j in _cjobs}),
      [(j.get("id"), j.get("kind")) for j in _cjobs])

# ------------------------------------------------ H4: empty-state copy ---------
check("H4 the all-scope empty state names the team-jobs section",
      "no team jobs yet" in UI, "")

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
