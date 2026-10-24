#!/usr/bin/env python3
"""v573 (STAGED — audit F6): a duplicate basename must not silently resolve
to the newest source. Exactly one loose match -> it; several -> ambiguity
error listing the candidates.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
tmp = tempfile.mkdtemp(prefix="v573-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_KNOWLEDGE_DIR"] = os.path.join(tmp, "knowledge")
for d in ("data", "sessions", "knowledge"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import knowledge as K  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


nb = K.create_notebook("audit-f6")
nid = nb.get("id")
K.add_source_text(nid, "/docs/a/report.md", "alpha content here", title="Report A")
K.add_source_text(nid, "/docs/b/report.md", "beta content here", title="Report B")

dup = K.read_source("report.md", notebook=nid)
check("1a duplicate basenames are NOT silently resolved",
      dup.get("ok") is False and "ambig" in (dup.get("error") or "").lower(),
      dup)
check("1b the ambiguity names both candidates",
      "docs/a" in str(dup) and "docs/b" in str(dup), dup)

K.add_source_text(nid, "/docs/c/unique.md", "only here", title="Unique C")
one = K.read_source("unique.md", notebook=nid)
check("2a a single loose match still resolves",
      one.get("ok") is True and "only here" in str(one), one)

exact = K.read_source("/docs/a/report.md", notebook=nid)
check("2b an exact path still wins over the ambiguity",
      exact.get("ok") is True and "alpha" in str(exact), exact)

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
