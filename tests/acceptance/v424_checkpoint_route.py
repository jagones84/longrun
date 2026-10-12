#!/usr/bin/env python3
"""v424 — the checkpoint/rewind route must be REACHABLE (JAG-426 follow-up).

Two live-end-to-end bugs found while QA-ing the WebUI:

1. ROUTE SHADOWING: `httpapi.do_GET` calls `api_v02.handle(...)` FIRST, and the
   v0.3 handler in api_v02 owned `GET /api/checkpoints` — so the newer JAG-426
   handler in httpapi was DEAD CODE. The live route returned the newest N
   checkpoints of EVERY session, with NO `session` filter and NO `marks` (the turn
   anchors a rewind needs). A client literally could not discover a rewind point.
   Fix: api_v02's handler is now session-aware and returns `marks`; the duplicate
   GET handler in httpapi was removed.

2. WORKSPACE REVERT: `rewind.restore_workspace` only reverts files the harness
   wrote through the edit journal (fs.write/fs.edit). Verified live: a journaled
   `notes.txt` is removed on rewind. (Files a turn creates via `shell` are NOT
   journaled — a documented limitation, asserted here so it stays explicit.)

Deterministic, no live server. Run: python3 tests/acceptance/v424_checkpoint_route.py
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v424-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as s            # noqa: E402
from longrun.memory import checkpoints          # noqa: E402
from longrun.memory import rewind               # noqa: E402
from longrun.tools import edits                 # noqa: E402

checkpoints.CKPT_DIR = os.path.join(TMP, "ckpt")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


api = _read("src", "longrun", "core", "api_v02.py")
http = _read("src", "longrun", "core", "httpapi.py")

# ---- 1. the live GET /api/checkpoints route (in api_v02) is session-aware -----
i = api.index('if path == "/api/checkpoints":')
block = api[i:i + 1200]
check("1a the v0.3 GET /api/checkpoints handler returns `marks`",
      '"marks": marks' in block)
check("1b it filters by the `session` query param",
      'qs.get("session")' in block)
check("1c it delegates the anchors to rewind.marks",
      "rewind as _rew" in block and ".marks(sid)" in block)

# ---- 2. httpapi no longer shadows it with a dead duplicate --------------------
# httpapi keeps ONLY the POST handler; the GET duplicate was removed.
check("2a httpapi has exactly ONE /api/checkpoints branch (the POST)",
      http.count('if path == "/api/checkpoints":') == 1)
check("2b the POST /api/rewind route lives in httpapi still",
      'if path == "/api/rewind":' in http)
check("2c dispatch order is documented (api_v02 runs first)",
      "api_v02.handle(self, \"GET\"" in http)

# ---- 3. behavioural: a journaled created file is reverted by rewind ----------
s.get_or_create_session("v424s", title="v424")
rewind.mark("v424s", 0)
time.sleep(0.02)
f_new = os.path.join(TMP, "created-by-harness.txt")
with open(f_new, "w", encoding="utf-8") as f:
    f.write("NEW\n")
edits.record("v424s", f_new, "", "NEW\n", "created")
r = rewind.rewind("v424s", 0)
check("3a rewind removes a file the harness CREATED (journaled)",
      r.get("ok") is True and not os.path.exists(f_new)
      and any(x.get("action") == "removed" for x in r.get("workspace", {}).get("restored", [])),
      r.get("workspace"))

# ---- 4. the documented limitation stays explicit -----------------------------
rsrc = _read("src", "longrun", "memory", "rewind.py")
check("4a restore_workspace is journaled (fs.write/fs.edit) only",
      "edits.entries" in rsrc and "harness" in rsrc.lower())

print("---")
okc = sum(results)
print("\nv424: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
