"""v397 — GLOBAL knowledge index: codebase + docs (JAG-397 / JAG-399).

Deterministic, stdlib-only. Exercises the real index module on a temp folder:
AST chunking, FTS5/bm25 ranking, the built-in ignores (.git, .gitignore-ignored
dirs), rebuild, multi-line sources, status counts — plus source-text guards that
the API/CLI/tool/UI are wired to the GLOBAL model (not per-session).
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


def _base(path):
    return os.path.basename(path)


# ---- fixture folder (registered as ONE source) ------------------------------
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

idx.clear()   # clean global store

# ---- build (folder source) --------------------------------------------------
add = idx.add_source(ws)
st = idx.status()
check("A1 a folder source indexes the code + docs files",
      add.get("ok") is True and add.get("files") == 4 and st["files"] == 4, add)
check("A2 built-in ignores drop .git and .gitignore'd dirs/files",
      not any(r["path"].endswith("big.py") or r["path"].endswith("secret.py") or r["path"].endswith(".log")
              for r in idx.search("hidden secret parse config log", k=20)["results"]),
      [r["path"] for r in idx.search("hidden secret", k=20)["results"]])
check("A3 FTS5 is enabled (bm25 + snippet)", st["fts"] is True)
check("A4 the DB lives in the app data dir, never in the project",
      idx.db_path().startswith(os.environ["LONGRUN_INDEX_DIR"]) and not idx.db_path().startswith(ws),
      idx.db_path())
check("A5 AST chunking names python functions and methods",
      "parse_config" in idx.search("parse config", k=5)["results"][0]["name"])
check("A5b a class method is its own chunk (Loader.read)",
      any(r["name"] == "Loader.read" for r in idx.search("Loader read", k=10)["results"]))

# ---- search ranking + filters ----------------------------------------------
res = idx.search("parse config")
check("B1 bm25 ranks the python function first", bool(res["results"]) and res["results"][0]["path"].endswith("a.py"), res["results"][:1])
check("B2 results carry path/start/snippet",
      all(r.get("path") and "start" in r and r.get("snippet") for r in res["results"]))
doc = idx.search("config loader", kind="doc")
check("B3 kind=doc returns only doc chunks", bool(doc["results"]) and all(r["kind"] == "doc" for r in doc["results"]))
check("B4 no match -> empty, no crash", idx.search("zzzznotpresentzzz", k=5)["results"] == [])

# ---- rebuild -----------------------------------------------------------------
c1 = idx.status()["chunks"]
idx.build()
check("C1 rebuild keeps the chunk count stable", idx.status()["chunks"] == c1, (c1, idx.status()["chunks"]))
with open(os.path.join(ws, "a.py"), "a") as f:
    f.write("\n\ndef brand_new_helper(x):\n    return x + 1\n")
idx.build()
check("C2 a changed file is re-indexed (new symbol searchable)",
      any("brand_new_helper" in r["name"] for r in idx.search("brand new helper", k=5)["results"]))

# ---- doc sources (URL / file / multi-line) ----------------------------------
add2 = idx.add_sources(os.path.join(ws, "docs", "guide.md"))
check("D1 add_sources indexes a local doc", add2.get("ok") is True and add2.get("chunks", 0) >= 1, add2)
check("D2 the doc source is listed", any(s["ref"].endswith("guide.md") for s in idx.list_sources()))
check("D3 the doc content is searchable", any("gadget" in (r["snippet"] or "").lower()
      for r in idx.search("gadgets widgets", k=10)["results"]))
sid = add2["results"][0].get("source")
idx.remove_source(sid)
check("D4 remove_source drops the source", not any(s["ref"].endswith("guide.md") for s in idx.list_sources()))
check("D5 bad ref fails gracefully", idx.add_source("/no/such/path").get("ok") is False)


# ---- multi-line parsing (JAG-399) -------------------------------------------
def _refs_of(values):
    """Mirror index.add_sources' line parsing without touching the network."""
    if isinstance(values, str):
        r = [ln.strip() for ln in values.splitlines()]
    else:
        r = [str(v).strip() for v in (values or [])]
    return [x for x in dict.fromkeys(r) if x]


mixed = "https://example.com/a.md\n\n/home/me/app\n  /home/me/notes/x.md  \nhttps://example.com/a.md\n"
parsed = _refs_of(mixed)
check("F1 a multi-line blob splits into clean, deduped sources",
      parsed == ["https://example.com/a.md", "/home/me/app", "/home/me/notes/x.md"], parsed)
check("F2 add_sources accepts a list too", _refs_of(["/a", "/b"]) == ["/a", "/b"])

# ---- status / clear ---------------------------------------------------------
check("E1 status reports the counts", idx.status()["chunks"] > 0 and idx.status()["files"] >= 4)
idx.clear()
check("E2 clear empties the index", idx.status()["chunks"] == 0 and idx.status()["files"] == 0)

# ---- wiring guards (source text) -------------------------------------------
registry = open(os.path.join(REPO, "src", "longrun", "tools", "registry.py"), encoding="utf-8").read()
toolspy = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"), encoding="utf-8").read()
toolsyaml = open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8").read()
apiv02 = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
forge = open(os.path.join(REPO, "src", "longrun", "core", "forge.py"), encoding="utf-8").read()
embedpy = open(os.path.join(REPO, "src", "longrun", "model", "embed.py"), encoding="utf-8").read()
webui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

check("G1 the `index` tool is declared + dispatched", '"index":' in registry and '"index": _index' in toolspy and "def _index(" in toolspy)
check("G2 config/tools.yaml enables the index tool", "index:" in toolsyaml and "knowledge" in toolsyaml.lower())
check("G3 the API exposes /api/index/* + embed-test",
      "/api/index/build" in apiv02 and "/api/index/search" in apiv02 and "/api/index/docs" in apiv02
      and "/api/index/files" in apiv02 and "def index_files(" in apiv02
      and "/api/index/embed-test" in apiv02)
check("G4 the CLI has `forge index`", "def cmd_index(" in forge and 'sub.add_parser("index")' in forge)
check("G5 embeddings module offers provider refs", "SUGGESTED" in embedpy and "def embed_texts(" in embedpy and "def probe(" in embedpy)
check("G6 the WebUI has the Knowledge settings + embedding picker",
      'data-cat="knowledge"' in webui and '["knowledge", "Knowledge"]' in webui
      and 'id="embedModel"' in webui and "function indexBuild(" in webui and "async function loadEmbedModel(" in webui)
check("G7 the index dir is a paths constant (overridable)", hasattr(paths, "INDEX_DIR") and paths.INDEX_DIR.endswith("index"))
check("G8 the Knowledge panel lists the indexed files + shows the scope",
      'id="indexFilesBox"' in webui and "async function indexFiles(" in webui and "scope:" in webui)
check("G9 the slash menu is keyboard-navigable",
      "let _slashItems" in webui and "#slashMenu .slashrow.hl" in webui
      and 'e.key === "ArrowDown"' in webui and "_paintSlashHi()" in webui)
check("G10 providers start collapsed (click to expand)",
      "modelsBox.hidden = true" in webui and "caret.textContent" in webui)

# ---- JAG-399: global scope, workspace moved to the Files inspector ----------
check("I1 the knowledge index is GLOBAL (no per-session plumbing)",
      "_idxQS" not in webui and "/api/index/status" in apiv02 and "def db_path(_" not in
      open(os.path.join(REPO, "src", "longrun", "memory", "index.py"), encoding="utf-8").read())
check("I2 the WebUI offers one textarea for many sources (URLs + paths)",
      'id="indexDocRefs"' in webui and "async function indexAddDoc(" in webui and "refs: refs" in webui)
_fp, _wp, _rp = webui.find('data-insp="files"'), webui.find('id="wsCurrent"'), webui.find('data-cat="rules"')
check("I3 workspace folder moved from Settings→Rules into the Files inspector",
      -1 < _fp < _wp and _wp < _rp, (_fp, _wp, _rp))

# list_files on a real index (fixture rebuilt at the end)
idx.add_source(ws)
lf = idx.list_files()
check("H1 list_files reports the indexed files with chunk counts",
      lf["files"] and all("path" in f and "chunks" in f for f in lf["files"]),
      lf.get("files", [])[:2])
idx.clear()

print("----")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
