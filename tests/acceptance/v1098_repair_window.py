#!/usr/bin/env python3
"""v1098 — a repair draft states the window of its evidence.

Round 29. Round 28 made the register readable as of a date; the WRITER (repair
drafts) still measured all time, so a draft could ask to fix a class that only
exists in history. `issue_drafts(since=…)` now scopes the evidence with the same
rule as the register, `proposal.json` carries the epoch, and `REPAIR.md` opens
with the window it used — "all time" is stated, never implied.

  A  a windowed draft exists only for the class inside the window
  B  proposal.json carries the epoch; REPAIR.md states the window
  C  without a window the draft says "the whole store (all time)"
  D  the surface: `improve.repairs` accepts `since` and reports it

Deterministic: temp session/runs dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1098_repair_window.py
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1098-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
for _d in (os.environ["LONGRUN_CONFIG_DIR"], os.environ["LONGRUN_SESSIONS_DIR"],
           os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")):
    os.makedirs(_d, exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402
from longrun.tools import tools as T  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SESS = os.environ["LONGRUN_SESSIONS_DIR"]
OLD = time.mktime(time.strptime("2026-01-15 12:00:00", "%Y-%m-%d %H:%M:%S"))
NEW = time.mktime(time.strptime("2026-06-15 12:00:00", "%Y-%m-%d %H:%M:%S"))
SINCE = "2026-03-01"


def session(sid, cards, mt):
    p = os.path.join(SESS, sid + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)
    os.utime(p, (mt, mt))


PERM = [{"tool": "shell.exec", "ok": False,
         "error": "permission denied by policy: <path>"}] * 10
MISS = [{"tool": "shell.exec", "ok": False,
         "error": "missing REQUIRED argument(s) 'command'"}] * 10
session("s_old", PERM, OLD)
session("s_new", MISS, NEW)

# ------------------------------------------------ A/B: the windowed draft ----
OUT = os.path.join(_tmp, "repairs-windowed")
rep = selfevolve.issue_drafts(OUT, limit=10, min_severity="info", since=SINCE)
names = sorted(w.get("issue") for w in rep.get("written") or [])
check("A1 one draft, for the class inside the window",
      names == ["fail-shell-exec-missing-argument"], names)
d = os.path.join(OUT, "fail-shell-exec-missing-argument")
prop = json.load(open(os.path.join(d, "proposal.json"), encoding="utf-8"))
body = open(os.path.join(d, "REPAIR.md"), encoding="utf-8").read()
check("B1 proposal.json carries the epoch",
      prop.get("since") == selfevolve._since_epoch(SINCE), prop.get("since"))
check("B2 REPAIR.md states the window it used",
      "**Window:** sessions and records written since 2026-03-01" in body, body[:400])
check("B3 the draft is the windowed count, not the all-time one",
      prop.get("count") == 10
      and all("permission" not in (c.get("error") or "") for c in prop.get("classes") or []),
      prop)

# --------------------------------------------- C: an all-time draft says so --
OUT2 = os.path.join(_tmp, "repairs-alltime")
all_rep = selfevolve.issue_drafts(OUT2, limit=10, min_severity="info")
check("C1 both classes are drafted", len(all_rep.get("written") or []) == 2,
      all_rep.get("written"))
perm_d = os.path.join(OUT2, "fail-shell-exec-permission")
body_all = (open(os.path.join(perm_d, "REPAIR.md"), encoding="utf-8").read()
            if os.path.isdir(perm_d) else "")
check("C2 the all-time draft names the whole store",
      "**Window:** the whole store (all time)" in body_all, body_all[:400])

# ----------------------------------------------------------- D: surface -----
check("D1 the `improve` schema gives `repairs` its third field",
      registry._SUBTOOL_FIELDS["improve"]["repairs"]
      == ["limit", "min_severity", "since"],
      registry._SUBTOOL_FIELDS["improve"]["repairs"])
res = T.execute("improve", {"action": "repairs", "limit": 5, "min_severity": "info",
                            "since": SINCE})
check("D2 the tool passes `since` and reports the window",
      res.get("ok") is True and res.get("since") == selfevolve._since_epoch(SINCE),
      (res.get("ok"), res.get("since")))
check("D3 and every draft it writes states it",
      all("since 2026-03-01" in open(os.path.join(w["path"], "REPAIR.md"),
                                     encoding="utf-8").read()
          for w in res.get("written") or []), res.get("written"))
again = T.execute("improve", {"action": "repairs", "limit": 5, "min_severity": "info",
                              "since": SINCE})
check("D4 a re-run says it skipped the existing drafts, not that nothing failed",
      (again.get("written") or []) == [] and bool(again.get("skipped"))
      and "already have one" in (again.get("stdout") or "")
      and "no issue at or above" not in (again.get("stdout") or ""),
      (again.get("skipped"), again.get("stdout")))

print("\n---\nv1098: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
