#!/usr/bin/env python3
"""v574 (STAGED — audit F3): an index search must surface freshness —
built_at/embed_error/stale — instead of silently serving a failed rebuild.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TMP = tempfile.mkdtemp(prefix="sf-v574-")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402
from longrun.memory import codeindex as ci  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


ws = os.path.join(TMP, "ws")
os.makedirs(ws)
with open(os.path.join(ws, "hello.py"), "w", encoding="utf-8") as f:
    f.write("def hello_world():\n    return 42\n")

r = T._index({"workspace": ws, "action": "search", "query": "hello world"}, None)
check("1a search carries freshness fields",
      "index_built_at" in r and "index_embed_error" in r and "index_stale" in r,
      sorted(r.keys()))
check("1b a fresh index is not stale",
      r.get("index_stale") is False, {k: r.get(k) for k in ("index_stale", "index_embed_error")})
check("1c matches still come through",
      r.get("ok") is True and "hello.py" in (r.get("stdout") or ""), r.get("stdout"))

_real_build = ci.build
try:
    def _boom(ws, **kw):
        raise RuntimeError("disk on fire")
    ci.build = _boom
    stale_ws = os.path.join(TMP, "ws2")
    os.makedirs(stale_ws)
    with open(os.path.join(stale_ws, "a.py"), "w", encoding="utf-8") as f:
        f.write("x = 1\n")
    r2 = T._index({"workspace": stale_ws, "action": "search", "query": "x"}, None)
    check("2a a failed rebuild is surfaced as stale, not silent",
          r2.get("index_stale") is True, {k: r2.get(k) for k in ("index_stale",)})
    check("2b the stale reason is present",
          bool(r2.get("index_stale_reason")), r2.get("index_stale_reason"))
finally:
    ci.build = _real_build

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
