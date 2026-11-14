#!/usr/bin/env python3
"""v1005 — "all sessions" must be a SUPERSET of every session's folder.

Operator: *"non wait i see that all sessions doesnt have the html (and so also other data may
be compromised) instead the current session has that impossible since all session contains
the specific session. BUG!"*.

Root cause: `edits.workspaces_artifacts` walked the folders with ONE shared
`MAX_WORKSPACE_FILES` budget and `break`-ed on the first folder that hit it. The folders are
visited outermost-first, so the alphabetically earlier project (`Repositories/jevarium`)
exhausted the budget and `Repositories/longrun` — the current session's folder — was never
scanned at all: "all sessions" showed 0 HTML while "this session" showed 14. Every later
folder was starved the same way, which is why the operator expected *other data* to be
wrong too.

Locked here:
  S1 every root gets its own budget; no root stops another (`capped` is per root, not a gate);
  S2 the union is a real SUPERSET: every file a single-folder scan returns is in the union,
     for every root — the operator's own invariant, checked at the smallest cap that bites;
  S3 the union with one root equals that root's own scan;
  S4 the cap is reported honestly (`capped`) instead of silently reshaping the answer.

Deterministic: no model, no network, no server. Run:
python3 tests/acceptance/v1005_union_is_a_superset.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v1005-")
BIG = os.path.join(TMP, "a-big-project")
SMALL = os.path.join(TMP, "z-current-session")
for _d in ("config", "sessions", "edits", "runs", "graphs", BIG, SMALL):
    os.makedirs(_d if _d.startswith(TMP) else os.path.join(TMP, _d), exist_ok=True)
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_BROWSE_ROOTS"] = TMP
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import edits as E          # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail and not ok else ""))


def touch(path, text="x\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# The bigger project comes FIRST in the outermost-first order, exactly like jevarium
# before longrun on the live home.
for i in range(6):
    touch(os.path.join(BIG, "note%02d.md" % i))
touch(os.path.join(BIG, "page.html"), "<h1>big</h1>\n")
touch(os.path.join(SMALL, "deck.html"), "<h1>current session</h1>\n")
touch(os.path.join(SMALL, "table.csv"), "a,b\n")

src = open(os.path.join(REPO, "src/longrun/tools/edits.py"), encoding="utf-8").read()
check("S1 no shared budget and no early stop (a root cannot starve the next)",
      "budget - scanned" not in src
      and "_scan_root(root, kind, needle, own, MAX_WORKSPACE_FILES)" in src
      and "        if cut:\n            capped = True\n            break" not in src)

REAL_CAP = E.MAX_WORKSPACE_FILES
try:
    # 2 entries per root: enough for the bug to bite (the shared budget would be
    # gone after the first root) and small enough to make the fixture instant.
    E.MAX_WORKSPACE_FILES = 2
    union = E.workspaces_artifacts([BIG, SMALL])
    union_paths = {r["path"] for r in union["artifacts"]}
    alone = {root: {r["path"] for r in E.workspace_artifacts(root)["artifacts"]}
             for root in (BIG, SMALL)}
    missing = {root: sorted(paths - union_paths) for root, paths in alone.items() if paths - union_paths}
    check("S2 the union contains every file of every single-folder scan",
          not missing, missing)
    check("S3 both folders were really walked (each contributes its own rows)",
          {r["workspace"] for r in union["artifacts"]} == {os.path.realpath(BIG), os.path.realpath(SMALL)},
          sorted({r["workspace"] for r in union["artifacts"]}))
    check("S4 a root that hits its cap is reported, and the others are still read",
          union.get("capped") is True and len(union["artifacts"]) > 2, union.get("capped"))
finally:
    E.MAX_WORKSPACE_FILES = REAL_CAP

full = E.workspaces_artifacts([BIG, SMALL])
check("S5 with the real cap nothing is truncated and the set is stable",
      full.get("capped") is False and full.get("count") == len(full["artifacts"]) == 9,
      {"count": full.get("count"), "capped": full.get("capped")})
check("S6 one root: the union is that root's own scan",
      E.workspaces_artifacts([SMALL])["count"] == E.workspace_artifacts(SMALL)["count"] == 2)

print("---")
passed = sum(RESULTS)
print("v1005: %d/%d PASS" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
