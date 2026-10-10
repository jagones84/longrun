"""v400 — KNOWLEDGE base: GLOBAL, notebook-scoped (JAG-401).

Deterministic, stdlib-only, OFFLINE (the URL fetch is stubbed). The knowledge base
is GLOBAL and organised in NOTEBOOKS; it is separate from the per-workspace codebase
index. Exercises: notebook CRUD, sources (path / text / URL), scoped search,
web-discover -> import, status/clear — plus wiring guards.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="v400-")
os.environ["LONGRUN_CODEBASE_DIR"] = os.path.join(tmp, "codebase")
os.environ["LONGRUN_KNOWLEDGE_DIR"] = os.path.join(tmp, "knowledge")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if (detail and not ok) else ""))


from longrun.memory import knowledge as kb  # noqa: E402

# ---- offline fixtures: stub the URL fetch -----------------------------------
kb.fetch_text = lambda url, *a, **k: ("# %s\n\nFetched knowledge about widgets and gadgets.\n" % url)

doc1 = os.path.join(tmp, "arch.md")
doc2 = os.path.join(tmp, "notes.md")
open(doc1, "w").write("# Architecture\n\nThe parser lives in the loader module.\n")
open(doc2, "w").write("# Notes\n\nRemember the deployment checklist.\n")

kb.clear()

# ---- notebooks --------------------------------------------------------------
nbs = kb.list_notebooks()
check("A1 a default notebook exists out of the box",
      any(n["id"] == "default" for n in nbs), nbs)
nb1 = kb.create_notebook("Web research")
check("A2 create_notebook returns a stable id + name", nb1.get("ok") and nb1.get("name") == "Web research", nb1)
nb2 = kb.create_notebook("Project docs")
check("A3 two named notebooks coexist", len(kb.list_notebooks()) == 3, [n["name"] for n in kb.list_notebooks()])
kb.rename_notebook(nb1["id"], "Web research v2")
check("A4 rename_notebook updates the name",
      any(n["id"] == nb1["id"] and n["name"] == "Web research v2" for n in kb.list_notebooks()))

# ---- sources into notebooks -------------------------------------------------
a = kb.add_source(nb1["id"], doc1)
check("B1 add_source indexes a local doc into a notebook", a.get("ok") is True and a.get("chunks", 0) >= 1, a)
t = kb.add_text(nb1["id"], "Deploy notes", "Kubernetes rollout uses blue green deployment strategy.")
check("B2 add_text stores a pasted note", t.get("ok") is True and t.get("chunks", 0) >= 1, t)
u = kb.add_source(nb1["id"], "https://example.com/guide")
check("B3 add_source accepts a URL (fetch stub)", u.get("ok") is True and u.get("kind") == "url", u)
multi = kb.add_sources(nb2["id"], doc2 + "\n" + doc1)
check("B4 add_sources takes a multi-line list", multi.get("ok") is True and multi.get("added") == 2, multi)
check("B5 sources are listed per notebook",
      all(s["notebook"] == nb1["id"] for s in kb.list_sources(nb1["id"])) and
      all(s["notebook"] == nb2["id"] for s in kb.list_sources(nb2["id"])))

# ---- scoped search ----------------------------------------------------------
hit1 = kb.search("parser loader", notebook=nb1["id"])
check("C1 search finds a source inside its notebook", bool(hit1["results"]) and hit1["results"][0]["notebook"] == nb1["id"], hit1)
check("C2 search can be scoped to ONE notebook (nb2 can't see nb1's chunks)",
      all(r["notebook"] == nb2["id"] for r in kb.search("kubectl blue green", notebook=nb2["id"])["results"]))
allhit = kb.search("parser")
check("C3 an unscoped search spans every notebook", bool(allhit["results"]))

# ---- discover (web -> candidate URLs -> import) -----------------------------
kb.SEARCH = lambda q, n: ([{"title": "Widget guide", "url": "https://ex.com/w"},
                           {"title": "Gadget ref", "url": "https://ex.com/g"}], "stub")
disc = kb.discover("widgets")
check("D1 discover returns candidate URLs (no import yet)",
      disc.get("ok") and len(disc.get("candidates", [])) == 2 and disc["candidates"][0]["url"] == "https://ex.com/w", disc)
imp = kb.import_candidates(nb1["id"], [c["url"] for c in disc["candidates"]])
check("D2 import_candidates adds each URL as a source in the notebook",
      imp.get("ok") and imp.get("added") == 2, imp)
check("D3 the imported URLs are searchable in that notebook",
      any(r["source"].startswith("src:") or "example" in (r.get("ref") or "")
          for r in kb.search("widgets gadgets", notebook=nb1["id"])["results"]) or
      any("ex.com" in (s.get("ref") or "") for s in kb.list_sources(nb1["id"])))

# ---- remove / delete / status ----------------------------------------------
sid = a["source_id"]
kb.remove_source(sid)
check("E1 remove_source drops it from the notebook",
      not any(s["id"] == sid for s in kb.list_sources(nb1["id"])))
kb.delete_notebook(nb2["id"])
check("E2 delete_notebook removes the notebook and its sources",
      not any(n["id"] == nb2["id"] for n in kb.list_notebooks()) and
      not any(s["notebook"] == nb2["id"] for s in kb.list_sources()))
check("E3 the default notebook cannot be deleted", kb.delete_notebook("default").get("ok") is False)
st = kb.status()
check("E4 status reports notebooks + sources + chunks",
      st["notebooks"] >= 2 and st["sources"] >= 1 and st["chunks"] > 0, st)

# ---- wiring guards ----------------------------------------------------------
apiv02 = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
registry = open(os.path.join(REPO, "src", "longrun", "tools", "registry.py"), encoding="utf-8").read()
toolsyaml = open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8").read()
webui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

check("G1 the API exposes /api/knowledge (notebooks + sources + discover)",
      "/api/knowledge/notebooks" in apiv02 and "/api/knowledge/sources" in apiv02
      and "/api/knowledge/discover" in apiv02 and "/api/knowledge/search" in apiv02)
check("G2 a `knowledge` agent tool exists", '"knowledge":' in registry)
check("G3 config/tools.yaml enables the knowledge tool", "knowledge:" in toolsyaml)
check("G4 the WebUI has the notebook UI + discover",
      'id="kbNotebooks"' in webui and 'id="kbDiscoverQ"' in webui
      and "function kbDiscover(" in webui and "function kbImport(" in webui)

print("----")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
