#!/usr/bin/env python3
"""v834 — a search tool must look where the SESSION works, not where the server lives.

Live 2026-11-06 (SWE slice, session dbaa607aa31b, `pylint-dev__pylint-6386`):
the turn opened the benchmark repo as its workspace, and

    grep.search {"pattern": "verbose", "path": "pylint/config"}
      -> ERROR: path does not exist: /home/jagones/Repositories/longrun/pylint/config

`grep.search` resolved the RELATIVE path against the harness checkout (`REPO`),
while `fs.read` resolved the same kind of path against the session workspace
(JAG-191). Two tools, two answers to one question: the model spent four rounds
(`grep`, `fs.read`, `grep`, `fs.read`) rediscovering the same tree before it
switched to a path relative to the server root — in a session whose workspace
was a *different* repository.

Deterministic and offline: temp dirs only, no model, no network, no server.
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# The fs tools only touch their allow-list (`.`, the checkout's parent), so the
# fixture lives BESIDE the repository: that is what makes this a real call
# through the production resolver instead of a bypassed one.
BASE = os.path.dirname(REPO)
TMP = tempfile.mkdtemp(prefix=".v834-", dir=BASE)
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDIT_DIR", "RUNS_DIR", "GRAPH_DIR", "DATA_DIR"):
    os.environ.setdefault("LONGRUN_" + _k, os.path.join(TMP, _k))
# The battery points LONGRUN_MATRIX_SRC at an empty temp dir, so the Matrix tools
# would not exist: hold ONE copy of the production module so the dispatch path,
# the schema and the handler are the real ones and the repository is never written.
MSRC = os.path.join(TMP, "matrix_src")
os.makedirs(os.path.join(MSRC, "tools"), exist_ok=True)
shutil.copyfile(os.path.join(REPO, "src", "Matrix", "tools", "grep.py"),
                os.path.join(MSRC, "tools", "grep.py"))
os.environ["LONGRUN_MATRIX_SRC"] = MSRC
os.environ["LONGRUN_MATRIX_DOT"] = os.path.join(TMP, "matrix_dot")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- fixture: a workspace that is NOT the harness checkout -------------------
WORK = os.path.join(TMP, "ws")
os.makedirs(os.path.join(WORK, "src"), exist_ok=True)
with open(os.path.join(WORK, "src", "app.py"), "w", encoding="utf-8") as f:
    f.write("alpha\n"
            "def run():\n"
            "    return 'V834-MARKER'\n")
# A decoy with the SAME relative shape inside the server repo: if a tool resolves
# against REPO it finds this one and the assertion below names the wrong path.
DECOY = os.path.join(TMP, "repo_decoy", "src")
os.makedirs(DECOY, exist_ok=True)
with open(os.path.join(DECOY, "app.py"), "w", encoding="utf-8") as f:
    f.write("DECOY\n")

# ---- A: a RELATIVE path means "relative to the session working dir" ----------
_res = T.execute("grep.search", {"pattern": "V834-MARKER", "path": "src",
                                 "workspace": WORK})
_path = str(_res.get("path") or "")
check("A1 grep.search resolves a relative `path` against the session workspace",
      _res.get("ok") is True and _path == os.path.join(WORK, "src"),
      (_res.get("ok"), _res.get("error"), _path))
check("A2 the hit is the workspace file, not one under the harness checkout",
      [m.get("file") for m in (_res.get("matches") or [])] == ["app.py"]
      and "V834-MARKER" in str(_res.get("stdout") or ""),
      (_res.get("matches"), _res.get("stdout")))

# ---- B: an ABSOLUTE path is honored as-is -----------------------------------
_abs = T.execute("grep.search", {"pattern": "V834-MARKER",
                                 "path": os.path.join(WORK, "src"), "workspace": WORK})
check("B1 an absolute `path` is used untouched (never re-based)",
      _abs.get("ok") is True and str(_abs.get("path") or "") == os.path.join(WORK, "src"),
      (_abs.get("ok"), _abs.get("error"), _abs.get("path")))

# ---- C: no `path` at all means the workspace --------------------------------
_default = T.execute("grep.search", {"pattern": "V834-MARKER", "workspace": WORK})
check("C1 without `path` grep.search searches the workspace",
      _default.get("ok") is True and str(_default.get("path") or "") == WORK,
      (_default.get("ok"), _default.get("error"), _default.get("path")))

# ---- D: the fs tools keep the SAME rule (the fix must not split them) -------
_fs_rel = T.execute("fs.read", {"path": "src/app.py", "workspace": WORK})
check("D1 fs.read resolves a relative path against the same workspace",
      _fs_rel.get("ok") is True and "V834-MARKER" in str(_fs_rel.get("content") or ""),
      (_fs_rel.get("ok"), _fs_rel.get("error")))
_fs_abs = T.execute("fs.read", {"path": os.path.join(WORK, "src", "app.py"),
                                "workspace": WORK})
check("D2 fs.read takes an absolute path untouched",
      _fs_abs.get("ok") is True and "V834-MARKER" in str(_fs_abs.get("content") or ""),
      (_fs_abs.get("ok"), _fs_abs.get("error")))

# ---- E: the DIFF tool had the same defect (it compared the checkout's files) --
with open(os.path.join(WORK, "src", "b.py"), "w", encoding="utf-8") as f:
    f.write("alpha\n"
            "def run():\n"
            "    return 'V834-OTHER'\n")
_diff = T.execute("diff.files", {"a": "src/app.py", "b": "src/b.py", "workspace": WORK})
check("E1 diff.files resolves BOTH relative paths against the session workspace",
      _diff.get("ok") is True and "V834-MARKER" in str(_diff.get("stdout") or "")
      and "V834-OTHER" in str(_diff.get("stdout") or ""),
      (_diff.get("ok"), _diff.get("error"), str(_diff.get("stdout"))[:200]))

print("\n---")
print("v834: %d/%d PASS" % (sum(results), len(results)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if all(results) else 1)
