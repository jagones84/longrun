#!/usr/bin/env python3
"""v1169 — global KB search must see shared notebooks; ids must be strings.

A54 P2: `knowledge.search` without a notebook searched the session notebook,
and when that had one hit it NEVER queried the shared base. The contract says
"session first, then shared notebooks".

A54 P6: `knowledge.search` (and the library) coerced a non-string notebook id
and answered a normal result. The tool dispatcher already rejects it; the direct
wrapper, the library and the HTTP route still do not.

A54 P7 is refuted here: `add_text` returns `source_id`, which `read_source` and
`remove_source` accept. The check is a pin, not a new feature.

Run: python3 tests/acceptance/v1169_kb_global_scope_and_ids.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1169-kb-")
os.environ["LONGRUN_KNOWLEDGE_DIR"] = os.path.join(TMP, "knowledge")
os.environ["LONGRUN_DATA_DIR"] = TMP
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_OFFLINE"] = "1"
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import knowledge as kb  # noqa: E402
from longrun.tools import registry          # noqa: E402
from longrun.tools import tools as T        # noqa: E402

registry._external_tools = lambda: {}
registry._matrix_tools = lambda: {}

# Offline: no embedding model, minimal chunk config (same shape as v427).
kb._cfg.embed_model = lambda: ""
kb._cfg.load_config = lambda: {"chunk_lines": 60, "overlap_lines": 8,
                               "max_file_kb": 512}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail else ""))


MARKER = "A48-KB-MARKER-C5VD-XZ7Q"
shared = kb.create_notebook("Shared A54")
shared_id = shared.get("id")
kb.add_text(shared_id, "shared note", MARKER + " shared body")
kb.add_text(None, "session note", MARKER + " session body", session_id="sessA")

# ---- P2: the global tool search must return BOTH scopes --------------------
res = T._dispatch_execute("knowledge.search", {"query": MARKER}, "sessA")
hits = res.get("results") or []
notebooks = {r.get("notebook") for r in hits}
check("A1 a global search returns the session hit AND the shared hit",
      (res.get("count") or 0) >= 2 and shared_id in notebooks,
      "count=%s notebooks=%s" % (res.get("count"), sorted(str(n) for n in notebooks)))
check("A2 the scope says both scopes were searched",
      "session" in str(res.get("scope") or "").lower()
      and "shared" in str(res.get("scope") or "").lower(), res.get("scope"))
_global_only = T._dispatch_execute("knowledge.search", {"query": MARKER})
check("A3 without a session notebook the shared hit is still found",
      (_global_only.get("count") or 0) >= 1, _global_only.get("count"))
explicit = T._dispatch_execute("knowledge.search",
                               {"query": MARKER, "notebook": shared_id})
check("A4 an explicit notebook keeps the single-notebook scope",
      bool(explicit.get("results"))
      and all(r.get("notebook") == shared_id for r in explicit["results"]),
      explicit.get("results"))

# ---- P6: a non-string notebook id is refused, not silently coerced --------
dispatch_int = T._dispatch_execute("knowledge.search",
                                   {"query": MARKER, "notebook": 5254})
check("B1 the agent dispatcher already rejects an integer notebook (exit 64)",
      dispatch_int.get("exit_code") == 64, dispatch_int.get("error"))
wrapper_int = T._knowledge({"action": "search", "query": MARKER,
                            "notebook": 5254}, "sessA")
check("B2 the direct wrapper rejects an integer notebook (exit 64)",
      wrapper_int.get("exit_code") == 64
      and "notebook" in str(wrapper_int.get("error") or "").lower(),
      wrapper_int)
library_int = kb.search(MARKER, notebook=5254)
check("B3 the library rejects an integer notebook instead of searching",
      library_int.get("ok") is False
      and "notebook" in str(library_int.get("error") or "").lower(), library_int)

# ---- P7 pin: add_text's source_id is the reference the tools use ----------
added = T._dispatch_execute("knowledge.add_text",
                            {"title": "p7 note", "text": "chunk contract body"},
                            "sessP7")
source_id = added.get("source_id")
check("C1 add_text returns a source id", bool(source_id)
      and str(source_id).startswith("src:"), added)
read_back = kb.read_source(source_id, session="sessP7") if source_id else {}
check("C2 read_source accepts the returned id",
      read_back.get("ok") is True
      and "chunk contract body" in str(read_back.get("text") or ""), read_back)
removed = kb.remove_source(source_id) if source_id else {}
after = kb.read_source(source_id, session="sessP7") if source_id else {}
check("C3 remove_source accepts the returned id and the source is gone",
      removed.get("ok") is True and after.get("ok") is False, (removed, after))

print("---")
ok = sum(results)
print("\nv1169: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
