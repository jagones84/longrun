#!/usr/bin/env python3
"""v866 — a file link in the answer OPENS, even when the model wrote it from
another folder (2026-11-07).

Live: agent A12 answered with `notes/PROPOSAL-longrun-changes.md` and
`VERIFICATION.md`. Its session workspace was `Repositories/TESTS/Jago`, the file
was at `Repositories/longrun/envs/osmani-2026-long-running-agents/notes/…`, so the
relative link resolved INTO THE WORKSPACE, the file did not exist there, and the
click did nothing at all (the dock only wrote "not a file" in its status line).

The contract this locks:

  A1  a link whose TAIL matches a file is found (bounded search, newest wins);
  A2  `_link_path` uses it only after the plain resolution misses;
  A3  `_resolve_fs_arg` keeps its old answer for a miss (v364 C4 untouched);
  A4  a ONE-component link (`VERIFICATION.md`) is never guessed — it is ambiguous;
  A5  the search never walks a browse root itself nor a VCS/cache folder;
  A6  the three click paths (`/api/fs/read`, `/api/fs/sheet`, `/api/fs/raw`) go
      through `_link_path`;
  A7  the editor SAYS why an open failed instead of dying silently.

Deterministic: no live model, no network.
Run: python3 tests/acceptance/v866_fs_link_resolution.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v866-")
os.environ.setdefault("LONGRUN_DATA_DIR", os.path.join(TMP, "data"))
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(TMP, "cfg"))
os.environ.setdefault("LONGRUN_DB", os.path.join(TMP, "events.db"))
os.environ.setdefault("LONGRUN_SESSIONS_DIR", os.path.join(TMP, "sessions"))
sys.path.insert(0, os.path.join(REPO, "src"))

with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8") as f:
    SRC = f.read()
with open(os.path.join(REPO, "webui", "assets", "editor.js"), encoding="utf-8") as f:
    EDITOR = f.read()

from longrun.core import api_v02 as api  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# A12, reproduced: the workspace is NOT where the file was written.
ws = os.path.join(TMP, "Repositories", "TESTS", "Jago")
os.makedirs(ws)
deep = os.path.join(TMP, "Repositories", "longrun", "envs", "osmani-2026", "notes")
os.makedirs(deep)
target = os.path.join(deep, "PROPOSAL-longrun-changes.md")
with open(target, "w", encoding="utf-8") as f:
    f.write("proposal")
# noise the resolver must NOT pick up (same tail, older, inside a VCS dir)
os.makedirs(os.path.join(ws, ".git", "notes"))
old = os.path.join(ws, ".git", "notes", "PROPOSAL-longrun-changes.md")
with open(old, "w", encoding="utf-8") as f:
    f.write("stale")
os.utime(old, (time.time() - 9000, time.time() - 9000))

LINK = "notes/PROPOSAL-longrun-changes.md"

_roots, _ws, _browse = api._link_roots, api._ws_root, api._browse_roots
api._browse_roots = lambda: [TMP]
api._ws_root = lambda qs=None: ws
try:
    # A1 — the bounded tail search finds the file the agent actually wrote.
    api._link_roots = lambda qs=None: [ws, os.path.join(TMP, "Repositories")]
    found = api._find_by_tail(LINK, {"session": "s"})
    check("A1 a link is found by its tail, newest first", found == target, found)

    # A2 — end-to-end: the plain resolution misses, the fallback opens it.
    got = api._link_path(LINK, {"session": "s"})
    check("A2 _link_path opens the file the agent wrote", got == target, got)

    # A3 — the old behaviour for a path that does not exist anywhere is kept.
    miss = api._resolve_fs_arg("nope/missing.py", {"session": "s"})
    check("A3 _resolve_fs_arg still answers with the workspace candidate",
          miss == os.path.join(ws, "nope/missing.py"), miss)

    # A4 — one component is ambiguous: never guessed.
    check("A4 a bare filename is not guessed",
          api._find_by_tail("PROPOSAL-longrun-changes.md", {"session": "s"}) == "", "")
    check("A4b .. is refused",
          api._find_by_tail("../notes/PROPOSAL-longrun-changes.md", {"session": "s"}) == "", "")
finally:
    api._link_roots, api._ws_root, api._browse_roots = _roots, _ws, _browse

# A5 — with the REAL roots: the HOME folder is never scanned.
roots = api._link_roots({"session": "s"})
HOME = os.path.realpath(os.path.expanduser("~"))
check("A5 the search never uses the HOME folder as a root",
      bool(roots) and all(os.path.realpath(r) != HOME for r in roots), roots)
check("A5b VCS/cache folders are skipped", ".git" in api.FS_TREE_SKIP
      and "node_modules" in api.FS_TREE_SKIP, sorted(api.FS_TREE_SKIP)[:4])
check("A5c the scan is bounded", "FS_LINK_SCAN_MAX = 20000" in SRC, "")

# A6 — every click path resolves through the SAME function (no second truth).
for route, fn in (("/api/fs/read", "fs_read"), ("/api/fs/sheet", "fs_sheet")):
    src = SRC.split("def %s(" % fn, 1)[-1][:1200]
    check("A6 %s resolves through _link_path" % route,
          "_safe_fs_path(_link_path(" in src, src[:80])
raw_src = SRC.split("def _fs_raw(", 1)[-1][:900]
check("A6c /api/fs/raw resolves through _link_path",
      "_safe_fs_path(_link_path(" in raw_src, raw_src[:80])

# A7 — a failed open is said out loud, with the path that was tried.
check("A7 the editor toasts the reason a link did not open",
      'window.toast("cannot open " + path + " — " + msg, "err")' in EDITOR, "")

# A8 — the CAUSE of A12's dead links: the org record moved, the live session did
# not. A running turn re-saved its stale copy and put the old workspace back.
with open(os.path.join(REPO, "src", "longrun", "agent", "agents.py"), encoding="utf-8") as f:
    AGENTS_SRC = f.read()
check("A8 set_workspace marks the field a running turn must not overwrite",
      "stores.live_fields_changed(sid, workspace=p)" in AGENTS_SRC, "")
from longrun.memory import stores  # noqa: E402
stores.live_fields_changed("v866live", workspace="/new/place")
_adopted = stores.adopt_live_choices({"id": "v866live", "workspace": "/old/place"})
check("A8b every later write of that session carries the NEW workspace",
      _adopted.get("workspace") == "/new/place", _adopted.get("workspace"))

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
