#!/usr/bin/env python3
"""v611 — SJ lifecycle: create/validate/describe/isolate/purge (data layer).

Session Jobs are the in-session twin of team jobs: SJ<n>/SJ<n>.k in
data/session_jobs/<sid>.json, dying with the session. Locks: id shape,
validation refusals, seq monotonicity, dep id mapping, describe contract,
per-session isolation, and the delete-cascade path.
Deterministic, no network, no model, no server.
"""
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="sf-v611-")
os.environ["LONGRUN_DATA_HOME"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_SJ_DIR"] = os.path.join(_tmp, "sj")
for _d in (os.environ["LONGRUN_DATA_HOME"], os.environ["LONGRUN_SESSIONS_DIR"],
           os.environ["LONGRUN_SJ_DIR"]):
    os.makedirs(_d, exist_ok=True)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


from longrun.agent import session_jobs as SJ  # noqa: E402

SID = "sess-v611-probe"

r = SJ.create(SID, "probe goal", [{"label": "a"}, {"label": "b", "deps": ["a"]}])
check("T1 create ok with SJ ids + dep mapped to subjob ids",
      r.get("ok") and r.get("job") == "SJ1"
      and r.get("subjobs") == ["SJ1.1", "SJ1.2"]
      and r.get("labels") == {"SJ1.1": "a", "SJ1.2": "b"}, r)
doc_jobs = r.get("record", {})
check("T2 record carries goal/mode/pending status",
      doc_jobs.get("goal") == "probe goal"
      and doc_jobs.get("status") == "created", doc_jobs.get("status"))

check("T3 empty subjobs refused",
      SJ.create(SID, "g", []) == {"ok": False, "error": "an SJ needs at least one subjob"} or
      (not SJ.create(SID, "g", []).get("ok")), "")
check("T4 duplicate labels refused",
      not SJ.create(SID, "g", [{"label": "x"}, {"label": "x"}]).get("ok"), "")
check("T5 unknown dep refused",
      not SJ.create(SID, "g", [{"label": "x", "deps": ["nope"]}]).get("ok"), "")
check("T6 cyclic deps refused",
      not SJ.create(SID, "g", [{"label": "x", "deps": ["y"]},
                               {"label": "y", "deps": ["x"]}]).get("ok"), "")
check("T7 fan-out bound refused",
      not SJ.create(SID, "g", [{"label": "s%d" % i} for i in range(SJ.MAX_SUBJOBS + 1)]).get("ok"),
      "max=%d" % SJ.MAX_SUBJOBS)
check("T8 missing session refused",
      SJ.create("", "g", [{"label": "x"}]).get("error") == "session id required", "")

r2 = SJ.create(SID, "second", [{"label": "only"}])
check("T9 seq monotonic per session (SJ2 after SJ1)",
      r2.get("ok") and r2.get("job") == "SJ2", r2.get("job"))

d = SJ.describe(SID)
check("T10 describe lists newest-first with subjob rows",
      d.get("ok") and [j["id"] for j in d["jobs"]] == ["SJ2", "SJ1"]
      and d["jobs"][1]["subjobs"][1]["deps"] == ["SJ1.1"], d.get("jobs"))
d1 = SJ.describe(SID, "SJ1")
d9 = SJ.describe(SID, "SJ99")
check("T11 describe filters to one job; unknown id falls back to latest open (never a traceback)",
      len(d1["jobs"]) == 1 and d1["jobs"][0]["id"] == "SJ1"
      and d9.get("ok") and len(d9["jobs"]) == 1 and d9["jobs"][0]["id"] == "SJ2",
      [j["id"] for j in d9["jobs"]])
check("T12 subagent slots start empty (spawned later by the scheduler)",
      all(s.get("subagent_id") is None and s.get("status") == "pending"
          for j in d["jobs"] for s in j["subjobs"]), "")

OTHER = "sess-v611-other"
SJ.create(OTHER, "other goal", [{"label": "z"}])
check("T13 ledgers isolated per session",
      SJ.describe(OTHER)["jobs"][0]["id"] == "SJ1"
      and len(SJ.describe(SID)["jobs"]) == 2, "")

from longrun.memory import stores as ST  # noqa: E402
removed = ST._purge_session_artifacts(SID)
sj_file = os.path.basename(SJ.path_for(SID))
check("T14 delete cascade removes the SJ ledger with the session",
      sj_file in removed and not os.path.isfile(SJ.path_for(SID))
      and os.path.isfile(SJ.path_for(OTHER)), removed)
check("T15 ledger dies with the session (describe empty after purge)",
      SJ.describe(SID)["jobs"] == [], "")

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
