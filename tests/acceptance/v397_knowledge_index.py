"""v397 — knowledge index: codebase + docs (JAG-397).

Deterministic, stdlib-only. Exercises the real index module on a temp workspace:
AST chunking, FTS5/bm25 ranking, the built-in ignores (.git, .gitignore-ignored
dirs), incremental rebuild, doc sources, status counts — plus source-text
guards that the API/CLI/tool/UI are wired.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="v397-")
os.environ["LONGRUN_INDEX_DIR"] = os.path.join(tmp, "index")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if (detail and not ok) else ""))


from longrun.memory import index as idx  # noqa: E402
from longrun.util import paths  # noqa: E402

# ---- fixture workspace ------------------------------------------------------
ws = os.path.join(tmp, "ws")
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

# ---- build ------------------------------------------------------------------
st = idx.build(ws)
check("A1 build indexes the code + docs files", st["files"] == 4, st)
check("A2 built-in ignores drop .git and .gitignore'd dirs/files",
      not any(r["path"].startswith(".git") or r["path"].startswith("data") or r["path"].endswith(".log")
              for r in idx.search(ws, "hidden secret parse config log", k=20)["results"]),
      [r["path"] for r in idx.search(ws, "hidden secret", k=20)["results"]])
check("A3 FTS5 is enabled (bm25 + snippet)", st["fts"] is True)
check("A4 the DB lives in the app data dir, never in the project",
      idx.db_path(ws).startswith(os.environ["LONGRUN_INDEX_DIR"]) and not idx.db_path(ws).startswith(ws),
      idx.db_path(ws))
check("A5 AST chunking names python functions and methods",
      "parse_config" in idx.search(ws, "parse config", k=5)["results"][0]["name"])
check("A5b a class method is its own chunk (Loader.read)",
      any(r["name"] == "Loader.read" for r in idx.search(ws, "Loader read", k=10)["results"]))

# ---- search ranking + filters ----------------------------------------------
res = idx.search(ws, "parse config")
check("B1 bm25 ranks the python function first", bool(res["results"]) and res["results"][0]["path"] == "a.py", res["results"][:1])
check("B2 results carry path/start/snippet",
      all(r.get("path") and "start" in r and r.get("snippet") for r in res["results"]))
doc = idx.search(ws, "config loader", kind="doc")
check("B3 kind=doc returns only doc chunks", bool(doc["results"]) and all(r["kind"] == "doc" for r in doc["results"]))
check("B4 no match -> empty, no crash", idx.search(ws, "zzzznotpresentzzz", k=5)["results"] == [])

# ---- incremental rebuild ----------------------------------------------------
c1 = idx.status(ws)["chunks"]
build2 = idx.build(ws)
check("C1 unchanged files are not re-chunked (chunk count stable)", idx.status(ws)["chunks"] == c1, (c1, build2["chunks"]))
with open(os.path.join(ws, "a.py"), "a") as f:
    f.write("\n\ndef brand_new_helper(x):\n    return x + 1\n")
idx.build(ws)
check("C2 a changed file is re-indexed (new symbol searchable)",
      any("brand_new_helper" in r["name"] for r in idx.search(ws, "brand new helper", k=5)["results"]))

# ---- doc sources ------------------------------------------------------------
add = idx.add_source(ws, os.path.join(ws, "docs", "guide.md"))
check("D1 add_source indexes a local doc", add.get("ok") is True and add.get("chunks", 0) >= 1, add)
check("D2 the doc source is listed", any(s["ref"].endswith("guide.md") for s in idx.list_sources(ws)))
check("D3 the doc content is searchable", any("gadget" in (r["snippet"] or "").lower()
      for r in idx.search(ws, "gadgets widgets", k=10)["results"]))
idx.remove_source(ws, add.get("source"))
check("D4 remove_source drops the source", not any(s["ref"].endswith("guide.md") for s in idx.list_sources(ws)))
check("D5 bad ref fails gracefully", idx.add_source(ws, "/no/such/path").get("ok") is False)

# ---- status / clear ---------------------------------------------------------
check("E1 status reports the counts", idx.status(ws)["chunks"] > 0 and idx.status(ws)["files"] >= 4)
idx.clear(ws)
check("E2 clear empties the index", idx.status(ws)["chunks"] == 0)

# ---- wiring guards (source text) -------------------------------------------
registry = open(os.path.join(REPO, "src", "longrun", "tools", "registry.py"), encoding="utf-8").read()
toolspy = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"), encoding="utf-8").read()
toolsyaml = open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8").read()
apiv02 = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
forge = open(os.path.join(REPO, "src", "longrun", "core", "forge.py"), encoding="utf-8").read()
embedpy = open(os.path.join(REPO, "src", "longrun", "model", "embed.py"), encoding="utf-8").read()
webui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

check("G1 the `index` tool is declared + dispatched", '"index":' in registry and '"index": _index' in toolspy and "def _index(" in toolspy)
check("G2 config/tools.yaml enables the index tool", "index:" in toolsyaml and "knowledge index" in toolsyaml)
check("G3 the API exposes /api/index/* + embed-test",
      "/api/index/build" in apiv02 and "/api/index/search" in apiv02 and "/api/index/docs" in apiv02
      and "/api/index/files" in apiv02 and "def index_files(" in apiv02
      and "/api/index/embed-test" in apiv02)
check("G4 the CLI has `forge index`", "def cmd_index(" in forge and 'sub.add_parser("index")' in forge)
check("G5 embeddings module offers provider refs", "SUGGESTED" in embedpy and "def embed_texts(" in embedpy and "def probe(" in embedpy)
check("G6 the WebUI has the Knowledge section + embedding picker",
      'data-insp="index"' in webui and ">Knowledge</button>" in webui
      and 'id="embedModel"' in webui and "function indexBuild(" in webui and "async function loadEmbedModel(" in webui)
check("G7 the index dir is a paths constant (overridable)", hasattr(paths, "INDEX_DIR") and paths.INDEX_DIR.endswith("index"))
check("G8 the Knowledge panel lists the indexed files + shows the scope",
      'id="indexFilesBox"' in webui and "async function indexFiles(" in webui and "scope:" in webui)
check("G9 the slash menu is keyboard-navigable",
      "let _slashItems" in webui and "#slashMenu .slashrow.hl" in webui
      and 'e.key === "ArrowDown"' in webui and "_paintSlashHi()" in webui)
check("G10 providers start collapsed (click to expand)",
      "modelsBox.hidden = true" in webui and "caret.textContent" in webui)

# list_files on a real index (fixture rebuilt at the end)
idx.build(ws)
lf = idx.list_files(ws)
check("H1 list_files reports the indexed files with chunk counts",
      lf["files"] and all("path" in f and "chunks" in f for f in lf["files"]),
      lf.get("files", [])[:2])

print("----")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
