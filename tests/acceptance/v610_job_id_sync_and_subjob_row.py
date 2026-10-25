#!/usr/bin/env python3
"""v610 — job lookup never misses on id shape; subjob is its own row.

v609's bridge stripped the J before lookup while the registry is keyed "JN",
so a plan chip read "job not found" for a job the deck showed fine. And a
subjob chip led to the parent instead of its own row (J17 vs J17.4 are
different entities). Locks: backend _norm_jid, full ids on chips,
parent+subjob split in _showJobDetail, deck focusJob rings the exact row.
Deterministic, no network, no model.
"""
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="sf-v610-")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(_tmp, "jobs.json")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


from longrun.orchestrate import jobs as J  # noqa: E402

check("T1 _norm_jid keeps full ids", J._norm_jid("J17") == "J17"
      and J._norm_jid("J17.4") == "J17.4", "full")
check("T2 _norm_jid repairs bare/lowercase ids",
      J._norm_jid("17") == "J17" and J._norm_jid("j17") == "J17"
      and J._norm_jid("17.4") == "J17.4", "repaired")

made = J.JOBS.create("v610 probe job", coordinator="A1", agents=["A1"])
assert made.get("ok"), made
jid = made["job"]["id"]
bare = jid[1:] if jid.startswith("J") else jid
check("T3 backend get() hits on bare digits too",
      (J.JOBS.get(jid) or {}).get("id") == jid
      and (J.JOBS.get(bare) or {}).get("id") == jid, jid)
check("T4 backend detail() hits on bare digits too",
      (J.JOBS.detail(bare) or {}).get("id") == jid, jid)

HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("T5 chips carry FULL store ids (the stripped-id bug is gone)",
      'data-job="${_attr(_fullJ(n.jid))}"' in HTML
      and 'data-job="${_attr(_fullJ(n.subjob))}"' in HTML
      and 'replace(/^J/i, ""))" style=' not in HTML, "data-job")
check("T6 _showJobDetail splits parent/subjob and renders the subjob row",
      "const parent = dot < 0 ? full : full.slice(0, dot)" in HTML
      and "subjob ${esc(sub)}</b>" in HTML
      and '_showJobInControl(sub || parent)' in HTML, "split")
check("T7 bridge posts the FULL id (deck keys are full ids)",
      "id: full }, " in HTML or 'id: full }' in HTML, "postMessage")

ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()
check("T8 deck focusJob expands the parent for dotted ids",
      'const parent = dot < 0 ? full : full.slice(0, dot)' in ORBIT, "parent")
check("T9 deck rings the exact subjob row, job row as fallback",
      '.runrow[data-sub="' in ORBIT and '.runrow.focusring' in ORBIT, "ring")
check("T10 deck never steals a stacked board for the handover",
      '!== "all"' in ORBIT, "layout guard")

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
