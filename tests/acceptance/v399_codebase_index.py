"""v399 — CODEBASE index, PER WORKSPACE (JAG-400).

Deterministic, stdlib-only. The codebase index is scoped to a workspace PATH
(like project rules), NOT global and NOT per-session. Exercises the real module
on a temp folder: AST chunking, FTS5/bm25 ranking, ignores, incremental rebuild,
per-workspace isolation, status/clear — plus source-text wiring guards.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="v399-")
data_dir = os.path.join(tmp, "data")
os.makedirs(data_dir, exist_ok=True)
os.environ["LONGRUN_DATA_DIR"] = data_dir
with open(os.path.join(data_dir, "index.overlay.yaml"), "w", encoding="utf-8") as f:
    f.write("embed_model: ''\n")
os.environ["LONGRUN_CODEBASE_DIR"] = os.path.join(tmp, "codebase")
os.environ["LONGRUN_KNOWLEDGE_DIR"] = os.path.join(tmp, "knowledge")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if (detail and not ok) else ""))


from longrun.memory import codeindex as ci  # noqa: E402
from longrun.util import paths  # noqa: E402


def _mkws(name):
    ws = os.path.join(tmp, name)
    os.makedirs(os.path.join(ws, ".git"), exist_ok=True)
    os.makedirs(os.path.join(ws, "data"), exist_ok=True)
    os.makedirs(os.path.join(ws, "lib"), exist_ok=True)
    os.makedirs(os.path.join(ws, "docs"), exist_ok=True)
    open(os.path.join(ws, ".gitignore"), "w").write("data/\n*.log\n")
    open(os.path.join(ws, "a.py"), "w").write(
        '"""Demo module."""\nimport os\n\n\ndef parse_config(path):\n    """Load and parse a yaml config file."""\n    return path\n\n\nclass Loader:\n    def read(self):\n        return 1\n')
    open(os.path.join(ws, "lib", "util.py"), "w").write("def compute_total(items):\n    return sum(items)\n")
    open(os.path.join(ws, "README.md"), "w").write("# Demo\n\nParse config docs live here.\n\n## Usage\nRun the loader.\n")
    open(os.path.join(ws, "docs", "guide.md"), "w").write("# Guide\n\nWidgets and gadgets.\n")
    open(os.path.join(ws, "data", "big.py"), "w").write("def hidden(): return 1\n")
    open(os.path.join(ws, "noise.log"), "w").write("log line parse config\n")
    open(os.path.join(ws, ".git", "secret.py"), "w").write("def secret(): return 1\n")
    return ws


ws = _mkws("wsA")
progress = []
st = ci.build(ws, progress=progress.append)
check("A0 build reports scan and completion progress",
      any(x.get("phase") == "scan" for x in progress) and
      any(x.get("phase") == "complete" for x in progress), progress)
check("A1 build indexes the workspace code + docs files", st["files"] == 4, st)
check("A2 built-in ignores drop .git and .gitignore'd dirs/files",
      not any(r["path"].endswith("big.py") or r["path"].endswith("secret.py") or r["path"].endswith(".log")
              for r in ci.search(ws, "hidden secret parse config log", k=20)["results"]))
check("A3 FTS5 is enabled (bm25 + snippet)", st["fts"] is True)
check("A4 the DB lives OUTSIDE the workspace (app data dir)",
      ci.db_path(ws).startswith(os.environ["LONGRUN_CODEBASE_DIR"]) and not ci.db_path(ws).startswith(ws),
      ci.db_path(ws))
check("A5 AST chunking names python functions and methods",
      "parse_config" in ci.search(ws, "parse config", k=5)["results"][0]["name"])
check("A5b a class method is its own chunk (Loader.read)",
      any(r["name"] == "Loader.read" for r in ci.search(ws, "Loader read", k=10)["results"]))

res = ci.search(ws, "parse config")
check("B1 bm25 ranks the python function first", bool(res["results"]) and res["results"][0]["path"].endswith("a.py"), res["results"][:1])
check("B2 results carry path/start/snippet",
      all(r.get("path") and "start" in r and r.get("snippet") for r in res["results"]))
doc = ci.search(ws, "config loader", kind="doc")
check("B3 kind=doc returns only doc chunks", bool(doc["results"]) and all(r["kind"] == "doc" for r in doc["results"]))
check("B4 no match -> empty, no crash", ci.search(ws, "zzzznotpresentzzz", k=5)["results"] == [])

# ---- incremental -------------------------------------------------------------
c1 = ci.status(ws)["chunks"]
ci.build(ws)
check("C1 rebuild keeps the chunk count stable", ci.status(ws)["chunks"] == c1, (c1, ci.status(ws)["chunks"]))
with open(os.path.join(ws, "a.py"), "a") as f:
    f.write("\n\ndef brand_new_helper(x):\n    return x + 1\n")
ci.build(ws)
check("C2 a changed file is re-indexed (new symbol searchable)",
      any("brand_new_helper" in r["name"] for r in ci.search(ws, "brand new helper", k=5)["results"]))
os.remove(os.path.join(ws, "lib", "util.py"))
ci.build(ws)
check("C3 a deleted file is dropped from the index",
      not any(r["path"].endswith("util.py") for r in ci.search(ws, "compute total", k=10)["results"]))

# JAG-530 (live audit): after `rm _idx_probe.md` the index still returned
# `_idx_probe.md:1` as a hit, so the agent cited a file that no longer existed.
# A search must never return a chunk whose source is gone, even before a rebuild.
stale_path = os.path.join(ws, "stale_probe.md")
with open(stale_path, "w") as f:
    f.write("# Probe\n\nThe token QWXZLEMON47 lives here.\n")
ci.build(ws)
check("C4a the new file is searchable after a build",
      any(r["path"] == os.path.realpath(stale_path)
          for r in ci.search(ws, "QWXZLEMON47", k=5)["results"]))
os.remove(stale_path)
check("C4b a DELETED file is never a hit, even before a rebuild",
      ci.search(ws, "QWXZLEMON47", k=5)["results"] == [],
      ci.search(ws, "QWXZLEMON47", k=5)["results"])

# ---- per-workspace isolation (the whole point) -------------------------------
ws_b = _mkws("wsB")
open(os.path.join(ws_b, "only_b.py"), "w").write("def only_in_workspace_b_marker():\n    return 42\n")
ci.build(ws_b)
check("D1 two workspaces get DIFFERENT DB files", ci.db_path(ws) != ci.db_path(ws_b))
check("D2 a symbol in wsB is NOT in wsA (isolated)",
      ci.search(ws, "only in workspace b marker", k=10)["results"] == [])
check("D3 the wsB index sees its own symbol",
      any(r["path"].endswith("only_b.py") for r in ci.search(ws_b, "only in workspace b marker", k=5)["results"]))
check("D4 each index reports its own workspace",
      ci.status(ws)["workspace"] == os.path.realpath(ws) and
      ci.status(ws_b)["workspace"] == os.path.realpath(ws_b))

# ---- status / clear ----------------------------------------------------------
check("E1 status reports the counts", ci.status(ws)["chunks"] > 0 and ci.status(ws)["files"] >= 2)
ci.clear(ws)
check("E2 clear empties only THIS workspace's index",
      ci.status(ws)["chunks"] == 0 and ci.status(ws_b)["chunks"] > 0)

# ---- wiring guards -----------------------------------------------------------
registry = open(os.path.join(REPO, "src", "longrun", "tools", "registry.py"), encoding="utf-8").read()
toolspy = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"), encoding="utf-8").read()
apiv02 = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
webui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
forge = open(os.path.join(REPO, "src", "longrun", "core", "forge.py"), encoding="utf-8").read()

check("G1 the `index` tool now targets the CODEBASE (per workspace)",
      '"index":' in registry and "def _index(" in toolspy and "/api/codebase" in apiv02)
check("G2 the WebUI has a Codebase inspector section (separate from Files)",
      'data-insp="codebase"' in webui and "function indexStatus(" not in webui)
check("G3 the codebase dir is a paths constant (overridable)",
      hasattr(paths, "CODEBASE_DIR") and paths.CODEBASE_DIR.endswith("codebase"))
check("G4 the CLI exposes `forge index` for the codebase", "def cmd_index(" in forge)
check("G5 the old per-session/global store is gone",
      not os.path.exists(os.path.join(REPO, "src", "longrun", "memory", "index.py")))
check("G6 build publishes progress and durable errors",
      '"index.error"' in apiv02 and "progress=_index_progress" in apiv02)
check("G7 the WebUI renders live index progress and failures",
      '"index.progress"' in webui and '"index.error"' in webui)

print("----")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
