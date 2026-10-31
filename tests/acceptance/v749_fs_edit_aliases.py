#!/usr/bin/env python3
"""v749 — fs.edit accepts the argument names models actually send.

Measured 2026-10-31 in the post-fix benchmark run: two `fs.edit` calls died with
`missing REQUIRED argument(s) 'replace'; unknown argument 'content'` and one with
`'new_string'`. The repair layer already mapped old_string→search; the WRITE side
was missing, so the model lost a whole round in each case.

Deterministic, no model, no network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v749-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for d in ("cfg", "sessions", "data"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry             # noqa: E402
from longrun.tools import tools                # noqa: E402

registry._external_tools = lambda: {}
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A. the two spellings the run used -------------------------------------
a = tools.normalize_args("fs.edit", {"path": "f.py", "old_string": "a", "new_string": "b"})
check("A1 old_string/new_string -> search/replace",
      a.get("search") == "a" and a.get("replace") == "b"
      and "old_string" not in a and "new_string" not in a, a)

a = tools.normalize_args("fs.edit", {"path": "f.py", "search": "a", "content": "b"})
check("A2 content -> replace when the tool has no content argument",
      a.get("replace") == "b" and "content" not in a, a)

a = tools.normalize_args("fs.edit", {"path": "f.py", "new_text": "b", "needle": "a"})
check("A3 new_text/needle -> replace/search",
      a.get("replace") == "b" and a.get("search") == "a", a)

# ---- B. fs.write must NOT lose its own `content` ----------------------------
a = tools.normalize_args("fs.write", {"path": "f.py", "content": "x"})
check("B1 fs.write keeps content", a.get("content") == "x" and "replace" not in a, a)

# ---- C. the repaired call really edits the file ----------------------------
# The file lives INSIDE the repo: fs.edit enforces its roots, and the point here
# is the argument repair, not the boundary.
work = tempfile.mkdtemp(prefix=".tmp-v749-", dir=REPO)
p = os.path.join(work, "target.txt")
with open(p, "w", encoding="utf-8") as f:
    f.write("hello old world\n")
res = tools.execute("fs.edit", tools.normalize_args(
    "fs.edit", {"path": p, "old_string": "old", "new_string": "new"}), run_id="v749")
body = open(p, encoding="utf-8").read()
check("C1 the edited file carries the replacement", "hello new world" in body, body.strip())
check("C2 the tool reports success", bool(res.get("ok")), res.get("error"))
import shutil  # noqa: E402 — cleanup only
shutil.rmtree(work, ignore_errors=True)

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
