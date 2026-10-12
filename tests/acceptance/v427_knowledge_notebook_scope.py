#!/usr/bin/env python3
"""v427 — knowledge base: notebook scoping by ID *or* NAME (JAG-427 RAG fix).

Live QA of the knowledge agent found a real defect: `knowledge action=list_notebooks`
printed only NAMES + source counts, but `action=search` scopes by notebook ID. The model
therefore passed the NAME it was shown and got a silent "(no matches)" — notebook-scoped
agentic RAG looked broken even though the retrieval backend was correct.

Pinned here:
  * `list_notebooks` now surfaces each notebook's ID;
  * `search` / `add_text` accept a notebook by NAME or ID (resolved internally);
  * an empty scoped search explains itself (lists the valid notebooks).

Deterministic + offline (embeddings disabled, temp knowledge dir).

Run: python3 tests/acceptance/v427_knowledge_notebook_scope.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="sf-v427-kb-")
os.environ["LONGRUN_KNOWLEDGE_DIR"] = os.path.join(TMP, "knowledge")
os.environ["LONGRUN_DATA_DIR"] = TMP
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import knowledge as kb          # noqa: E402
from longrun.tools import tools as T                # noqa: E402

# Offline: no embedding model, minimal chunk config.
kb._cfg.embed_model = lambda: ""
kb._cfg.load_config = lambda: {"chunk_lines": 60, "overlap_lines": 8, "max_file_kb": 512}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- 1: a notebook can be addressed by NAME ----------------------------------
made = kb.create_notebook("Foo Book")
nid = made.get("id")
check("1a a notebook is created with a distinct id", bool(nid) and nid != "default", nid)
kb.add_text(nid, "note", "the quick brown fox jumps over the lazy dog")

by_name = kb.search("quick brown", notebook="Foo Book", k=3, embed_model="")
check("1b search scopes by the notebook NAME", bool(by_name.get("results")),
      "hits=%d" % len(by_name.get("results", [])))
by_id = kb.search("quick brown", notebook=nid, k=3, embed_model="")
check("1c search scopes by the notebook ID (unchanged)", bool(by_id.get("results")),
      "hits=%d" % len(by_id.get("results", [])))

# a source added by NAME lands in the right notebook
kb.add_text("Foo Book", "note2", "alpha beta gamma delta")
sources = kb.list_sources(nid)
check("1d add_text accepts the notebook NAME too", len(sources) >= 2,
      "sources=%d" % len(sources))

# --- 2: the AGENT tool surfaces the ID and self-explains empty scopes ---------
tel = T._knowledge({"action": "list_notebooks"}, "r")
check("2a list_notebooks stdout includes the notebook id", ("id=%s" % nid) in tel.get("stdout", ""),
      tel.get("stdout", "").replace("\n", " | "))
check("2b the standard tool schema still exposes .notebooks",
      isinstance(tel.get("notebooks"), list) and any(n.get("id") == nid for n in tel["notebooks"]))

tname = T._knowledge({"action": "search", "query": "quick brown", "notebook": "Foo Book"}, "r")
check("2c the tool search works with a notebook NAME", (tname.get("count") or 0) > 0,
      "count=%s" % tname.get("count"))

tbogus = T._knowledge({"action": "search", "query": "quick brown", "notebook": "no-such-nb"}, "r")
check("2d an unknown notebook scope explains itself (lists valid notebooks)",
      "no matches" in tbogus.get("stdout", "") and "Valid notebooks:" in tbogus.get("stdout", ""),
      tbogus.get("stdout", "").replace("\n", " | ")[:160])

# --- 3: global search (no notebook) still spans every notebook ---------------
glob = kb.search("alpha beta", notebook=None, k=5, embed_model="")
check("3 omitting the notebook searches across all notebooks", bool(glob.get("results")),
      "hits=%d" % len(glob.get("results", [])))

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
