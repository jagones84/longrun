#!/usr/bin/env python3
"""v1017 — demo artifacts inside `trash/` are visible, the rest of trash is not.

The workspace scan skips `trash/` on purpose (1 500+ scratch files would bury the
real deliverables), so the operator's dummy artifacts had no card at all — the
panel showed PPT 0 / Sheet 0 / Video 0 / Audio 0. One kept subtree
(`trash/artifacts-demo`) now opts back in; every sibling in trash stays skipped.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1017-")
for _k in ("LONGRUN_CONFIG_DIR", "LONGRUN_SESSIONS_DIR", "LONGRUN_EDITS_DIR",
           "LONGRUN_RUNS_DIR", "LONGRUN_GRAPH_DIR", "LONGRUN_ROLES_DIR"):
    os.environ[_k] = os.path.join(TMP, _k)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import edits as E  # noqa: E402

RESULT = []


def check(name, ok, detail=""):
    RESULT.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def touch(rel):
    p = os.path.join(TMP, "ws", rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(b"x")
    return p


touch("report.html")
touch("trash/scratch.py")
touch("trash/other/deep.pptx")
touch("trash/artifacts-demo/deck.pptx")
touch("trash/artifacts-demo/book.xlsx")
touch("trash/artifacts-demo/clip.mp4")
touch("trash/artifacts-demo/voice.wav")
touch("trash/artifacts-demo/complex.json")
touch("trash/artifacts-demo/nested/more.json")

E.WORKSPACE_KEEP_PATHS = {"trash/artifacts-demo"}
res = E.workspace_artifacts(os.path.join(TMP, "ws"))
names = sorted(r["name"] for r in res["artifacts"])
kinds = res.get("kinds") or {}

check("A1 the demo deck/workbook/media/json are listed",
      names == sorted(["complex.json", "more.json", "deck.pptx", "book.xlsx",
                       "clip.mp4", "voice.wav", "report.html"]), names)
check("A2 kinds are classified, not lumped into 'other'",
      kinds.get("slides") == 1 and kinds.get("sheet") == 1 and kinds.get("video") == 1
      and kinds.get("audio") == 1 and kinds.get("data") == 2 and kinds.get("html") == 1,
      kinds)
check("A3 a sibling of the kept subtree inside trash stays hidden",
      "scratch.py" not in names and not any("trash/other" in r["path"] for r in res["artifacts"]))
check("A4 the rest of the workspace is still scanned", "report.html" in names)
check("A5 a nested folder UNDER the kept path is scanned", "more.json" in names)

print("---")
passed = sum(RESULT)
print("%d/%d PASS" % (passed, len(RESULT)))
sys.exit(0 if passed == len(RESULT) else 1)
