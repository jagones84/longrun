#!/usr/bin/env python3
"""v1318 — a file the agent wrote into the system temp dir opens in the editor.

The transcript links the artifacts an agent produces. An agent exports a CSV/XLSX
into the system temp dir (pandas `to_excel`, a shell `>` redirect) and clicking the
link died with "cannot open /tmp/x.csv — path outside allowed roots", because the
browse roots were HOME + the workspaces root only. The default roots now include
the temp directories, so the link opens — while `/etc` stays out and `../`
traversal is still denied.

  A  the default browse roots include the system temp dir; HOME stays [0];
  B  a real file under temp reads through /api/fs/read; /etc and `../` stay denied;
  C  an explicit LONGRUN_BROWSE_ROOTS override is honoured exactly (no auto-append).

Deterministic: no model, no network, no server turn. Run:
    python3 tests/acceptance/v1318_fs_temp_root.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

_TMP = tempfile.mkdtemp(prefix="sf-v1318-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "RUNS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(_TMP, _k)
    os.makedirs(os.path.join(_TMP, _k), exist_ok=True)
os.environ["LONGRUN_DATA_HOME"] = _TMP
os.environ.pop("LONGRUN_BROWSE_ROOTS", None)   # exercise the DEFAULT branch

from longrun.core import api_v02 as API  # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


HOME = os.path.realpath(os.path.expanduser("~"))
TEMP = os.path.realpath(tempfile.gettempdir())

# ── A · the default roots ───────────────────────────────────────────────────
check("A1 the default browse roots include the system temp dir",
      TEMP in API._browse_roots(), API._browse_roots())
check("A2 HOME stays roots[0] (the workspace picker still opens there)",
      API._browse_roots()[0] == HOME, API._browse_roots()[0])

# ── B · a real temp artifact opens; the sandbox edge is intact ──────────────
_probe_dir = tempfile.mkdtemp(prefix="sf-v1318-art-", dir=TEMP)
_probe = os.path.join(_probe_dir, "probe.csv")
with open(_probe, "w", encoding="utf-8") as _f:
    _f.write("a,b\n1,2\n")

check("B1 a temp artifact resolves inside the allowed roots",
      API._safe_fs_path(_probe, API._browse_roots()) == os.path.realpath(_probe), _probe)
_read = API.fs_read({"path": _probe})
check("B2 /api/fs/read serves the temp artifact (the reported failure)",
      not _read.get("error") and str(_read.get("text") or "").startswith("a,b"), _read)
check("B3 /etc stays outside the roots", API._safe_fs_path("/etc/passwd", API._browse_roots()) is None, "")
_trav = API.fs_read({"path": "../../../../../../etc/passwd"})
check("B4 `../` traversal is still denied",
      _trav.get("error") == "path outside allowed roots", _trav)

# ── C · an explicit override is honoured exactly ────────────────────────────
_saved = os.environ.get("LONGRUN_BROWSE_ROOTS")
os.environ["LONGRUN_BROWSE_ROOTS"] = _probe_dir
try:
    check("C1 an explicit LONGRUN_BROWSE_ROOTS is honoured exactly (no temp auto-append)",
          API._browse_roots() == [os.path.realpath(_probe_dir)], API._browse_roots())
finally:
    if _saved is None:
        os.environ.pop("LONGRUN_BROWSE_ROOTS", None)
    else:
        os.environ["LONGRUN_BROWSE_ROOTS"] = _saved

print()
if FAILED:
    print("FAILED %d/%d: %s" % (len(FAILED), len(CHECKS), ", ".join(FAILED)))
    sys.exit(1)
print("OK %d/%d" % (len(CHECKS), len(CHECKS)))
