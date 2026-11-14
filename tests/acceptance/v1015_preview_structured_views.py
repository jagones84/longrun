#!/usr/bin/env python3
"""v1015 — YAML/JSON (and XML) get a structured TREE next to their source.

The preview window used to offer only Source for a `.yaml`: the operator reads a
configuration in My Artifacts and cannot see its structure. The tree is parsed by
the SERVER with the same loader the harness uses (PyYAML safe_load / json), so
the browser never grows a second parser and can never disagree with the effective
config; XML uses the browser's own DOMParser. Values are painted as text nodes,
never as markup.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


API = _read("src", "longrun", "core", "api_v02.py")
UI = _read("webui", "index.html")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- server: one parser, bounded output, an honest error ---------------------
check("A1 the structured route exists and is wired",
      'if path == "/api/fs/structured":' in API
      and "fs_structured(qs)" in API)
check("A2 YAML uses the harness loader (PyYAML safe_load), never eval",
      "doc = yaml.safe_load(text)" in API and "yaml.unsafe_load" not in API)
check("A3 JSON uses the stdlib parser",
      "doc = _json.loads(text)" in API)
check("A4 only the structured families are served",
      'if ext in (".json", ".geojson", ".ipynb"):' in API
      and 'elif ext in (".yaml", ".yml"):' in API)
check("A5 the tree is bounded (nodes, depth, items, chars)",
      "FS_STRUCT_MAX_NODES = 4000" in API and "FS_STRUCT_MAX_DEPTH = 24" in API
      and "FS_STRUCT_MAX_ITEMS = 200" in API and "FS_STRUCT_MAX_CHARS = 400" in API
      and 'budget["cut"] = True' in API)
check("A6 a parse failure is a message, not an empty tree",
      '"cannot parse %s: %s"' in API and 'return {"ok": False, "path": p, "format": fmt,' in API)
check("A7 the same path safety as /api/fs/read is reused",
      "def fs_structured(qs=None)" in API
      and '_safe_fs_path(_link_path(q.get("path"), q), _fs_allowed_roots(q))' in API)

# --- client: which families get the switch, and what each view is -------------
check("B1 YAML/JSON are a STRUCTURED kind, XML a tree (SVG stays text)",
      'const PV_STRUCT_EXT = [".yaml", ".yml", ".json", ".geojson", ".ipynb"];' in UI
      and 'const PV_XML_EXT = [".xml", ".xsl", ".xsd", ".plist"];' in UI
      and 'if (_pvIsStruct(path)) return "structured";' in UI
      and 'if (_pvIsXmlTree(path)) return "xmltree";' in UI
      and '".svg"' not in 'const PV_XML_EXT = [".xml", ".xsl", ".xsd", ".plist"];')
check("B2 the switch offers Tree ⇄ Source for both families",
      'if (kind === "structured" || kind === "xmltree") return ["tree", "source"];' in UI
      and 'tree: "Tree"' in UI)
check("B3 the tree is the FIRST view (structure before raw text)",
      'if (kind === "structured" && _pv.view === "tree") return _pvRenderStruct(body, note);' in UI
      and 'if (kind === "xmltree" && _pv.view === "tree") return _pvRenderXmlTree(body, note);' in UI)
check("B4 the YAML/JSON tree comes from the server endpoint",
      'api("GET", "/api/fs/structured?path=" + encodeURIComponent(_pv.path))' in UI)
check("B5 XML parses with the browser's DOMParser and reports a parsererror",
      'new DOMParser().parseFromString(r.text || "", "application/xml")' in UI
      and 'doc.querySelector("parsererror")' in UI)
check("B6 file values are TEXT nodes, never innerHTML",
      "k.textContent = key == null ? \"value\" : key;" in UI
      and "v.textContent = node.t === \"str\"" in UI
      and "av.textContent = '\"' + node.attrs[a] + '\"'" in UI
      and re.search(r"_pvRenderStruct[\s\S]{0,700}?\.innerHTML", UI) is None)
check("B7 the tree folds: details/summary with the top levels open",
      'd.className = "pv-tnode";' in UI and "d.open = depth < 2;" in UI
      and "summary::before { content:" in UI)
check("B8 leaves are coloured by TYPE (str/num/bool/null)",
      ".pv-tree .pv-tval.str" in UI and ".pv-tree .pv-tval.num" in UI
      and ".pv-tree .pv-tval.bool" in UI and ".pv-tree .pv-tval.null" in UI)
check("B9 the ⋯ toggle returns to the FIRST view, whatever it is",
      'const alt = _pv.views[0] || "render";' in UI
      and '_pv.view = _pv.view === "source" ? alt : "source";' in UI)

print("---")
passed = sum(RESULTS)
print("%d/%d PASS" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
