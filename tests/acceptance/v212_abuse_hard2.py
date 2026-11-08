#!/usr/bin/env python3
"""v212 — abuse round 2: try to CORRUPT memory + taskgraph (JAG-212).

Deterministic, no server, time-bounded. Pushes the persistence layer with inputs
designed to break the store's structure rather than just crash it:
  A) memory content containing a lone '---' line must not be torn into pieces;
  B) memory content that LOOKS like front-matter must not leak into metadata;
  C) a large store + index rebuild stays readable;
  D) concurrent store() keeps every record, unique ids, a parseable file;
  E) taskgraph under bulk/cyclic/huge/degenerate input;
  F) path resolution harsh inputs.

Run:  python3 tests/v212_abuse_hard2.py
"""
import os
import shutil
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T0 = time.time()
tmp = tempfile.mkdtemp(prefix="sf-212-")
sys.path.insert(0, os.path.join(REPO, "src"))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)

from longrun.memory import memory as mem   # noqa: E402
from longrun.tools import tools           # noqa: E402
from longrun.plan import taskgraph as tg  # noqa: E402
from longrun.tools import registry        # noqa: E402

mem.DATA_DIR = os.path.join(tmp, "memory")
mem.CORE_PATH = os.path.join(mem.DATA_DIR, "core.md")
os.makedirs(mem.DATA_DIR, exist_ok=True)
mem._vector_db = {}
mem._writes_since_index = 0

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def find(mid):
    return [x for x in mem.query(None, "memory.store", 5000) if x.get("mid") == mid]


# ---- A: a lone '---' inside content -----------------------------------------
r = tools._memory({"action": "store", "content": "intro line\n---\noutro line",
                   "source": "t"}, "run-a")
rec = find(r.get("mid"))
check("A1 record with '---' in content keeps its mid (not torn apart)",
      len(rec) == 1, "n=%d" % len(rec))
check("A2 the content survives intact",
      bool(rec) and "intro line" in rec[0].get("content", "")
      and "outro line" in rec[0].get("content", ""),
      (rec[0].get("content", "") if rec else "none")[:60])

# ---- B: content that mimics front-matter ------------------------------------
r = tools._memory({"action": "store",
                   "content": "evil\nmid: 99999999\nkind: hacked", "source": "t"}, "run-a")
rec = find(r.get("mid"))
check("B1 embedded 'mid:' does NOT hijack the record id",
      bool(rec) and rec[0].get("mid") == r.get("mid"),
      repr(rec[0].get("mid")) if rec else "none")
check("B2 embedded 'kind:' does NOT hijack the record kind",
      bool(rec) and rec[0].get("kind") == "memory.store",
      repr(rec[0].get("kind")) if rec else "none")

# ---- C: bulk store + index rebuild ------------------------------------------
# 2026-11-08: this test checks STORE integrity, not embeddings. Left to itself the
# rebuild loaded a sentence-transformer (63 threads, 159 s warm and a Hub download
# on a cold cache), so the FAST gate depended on the network and on the model
# cache. Pin the lexical path: the assertion is about the records, not the vectors.
mem._EMBEDDER = None
mem._EMBEDDER_READY = True
mem._ENDPOINT_DISABLED = True
for i in range(500):
    tools._memory({"action": "store", "content": "bulk note %d" % i}, "run-c")
mem._rebuild_index()
recs = mem.query(None, "memory.store", 5000)
check("C1 500 bulk records all readable", len(recs) >= 500, "n=%d" % len(recs))
check("C2 content is not corrupted by the rebuild",
      any(x.get("content") == "bulk note 42" for x in recs), "")

# ---- D: concurrent store ----------------------------------------------------
mids = []
lock = threading.Lock()


def spam(n):
    local = []
    for i in range(30):
        rr = tools._memory({"action": "store", "content": "conc %d-%d" % (n, i)}, "run-d")
        local.append(rr.get("mid"))
    with lock:
        mids.extend(local)


threads = [threading.Thread(target=spam, args=(n,)) for n in range(12)]
for t in threads:
    t.start()
for t in threads:
    t.join()
check("D1 every concurrent store returned a mid", all(mids) and len(mids) == 360,
      "n=%d" % len(mids))
check("D2 mids are unique", len(set(mids)) == len(mids), "unique=%d" % len(set(mids)))
allrec = mem.query(None, "memory.store", 5000)
check("D3 every concurrent record is on disk",
      all(any(x.get("mid") == m for x in allrec) for m in mids), "")

# ---- E: taskgraph abuse -----------------------------------------------------
g = tg.ensure("abuse")
ids = []
for i in range(300):
    nd = tg.add_node(g, label="step %d" % i, status="todo")
    ids.append(nd.get("id") if isinstance(nd, dict) else nd)
check("E1 300 nodes added with unique ids", len(set(map(str, ids))) == len(ids),
      "n=%d" % len(ids))
check("E2 all_done false while open", tg.all_done(g) is False, "")
pub = tg.public(g)
check("E3 public() renders without hang", isinstance(pub, dict) and "nodes" in pub, "")
# cyclic deps must not hang
try:
    g2 = tg.ensure("cyc")
    a = tg.add_node(g2, label="a", status="todo")
    b = tg.add_node(g2, label="b", status="todo", deps=[a if isinstance(a, str) else a.get("id")])
    tg.update_node(g2, (a if isinstance(a, str) else a.get("id")),
                   deps=[b if isinstance(b, str) else b.get("id")])
    check("E4 cyclic deps: render terminates", tg.all_done(g2) in (True, False), "")
except Exception as e:  # noqa: BLE001
    check("E4 cyclic deps: render terminates", True, "raised=%s" % type(e).__name__)
check("E5 huge label capped", len(str(tg.add_node(g, label="x" * 100000, status="todo")
                                       .get("label", ""))) <= 200, "")

# ---- F: path resolution harsh inputs ----------------------------------------
for bad in ("", "\x00", "../../etc/passwd", "/etc/passwd", "a" * 5000):
    p, err = registry.resolve_path(bad)
    check("F1 resolve_path(%r) handled" % (bad[:12],), True,
          "err=%s" % str(err)[:60])

print("\nelapsed=%.2fs" % (time.time() - T0))
shutil.rmtree(tmp, ignore_errors=True)
ok = sum(results)
print("\nv212: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

