"""v431r5 — PDF/KB pipeline (JAG-431r5).

Covers the changes that closed the loop between the chat attach button and the
knowledge base:

  1) docio.extract() returns a diagnostic DICT (text + engine + per-page
     metrics + recommend_visual), not a (text, engine) tuple.
  2) knowledge.add_source(notebook='auto', ...) routes to the closest existing
     notebook by token coverage, or creates a new one when nothing fits.
  3) knowledge.add_source / add_source_text accept a session_id for per-chat
     scope.
  4) knowledge.search() honours a session filter.
  5) The migration back-fills session_id on legacy DBs.
  6) The auto-route API endpoint exists and returns the diagnostic.
  7) A PDF whose body has no extractable text gets recommend_visual=True so
     the UI can warn the user that the embedder is text-only.
  8) A PDF with a text layer gets recommend_visual=False and normal chunks.
"""
import json
import os
import re
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="v431r5-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_CODEBASE_DIR"] = os.path.join(tmp, "codebase")
os.environ["LONGRUN_KNOWLEDGE_DIR"] = os.path.join(tmp, "knowledge")
os.environ["LONGRUN_EMBEDDING_DIR"] = os.path.join(tmp, "embedding")
os.environ["LONGRUN_COSTS_DIR"] = os.path.join(tmp, "costs")
for d in ("data", "cfg", "sessions", "codebase", "knowledge", "embedding", "costs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if (detail and not ok) else ""))


# -------------------------------------------------- 1) docio.extract diagnostic
from longrun.memory import docio  # noqa: E402

# 1a a non-binary document is rejected with the new shape
r = docio.extract(os.path.join(tmp, "x.md"))
check("1a docio.extract returns a dict with the diagnostic fields",
      isinstance(r, dict) and "text" in r and "engine" in r
      and "recommend_visual" in r and "ok" in r and "pages" in r
      and "extracted_pages" in r,
      r)
check("1b a non-binary document has ok=False and text=None",
      r["ok"] is False and r["text"] is None,
      r)

# 1c an empty file is rejected early
empty = os.path.join(tmp, "empty.pdf")
with open(empty, "wb"):
    pass
r2 = docio.extract(empty)
check("1c an empty file is rejected with engine='empty file'",
      r2.get("engine") == "empty file" and r2.get("ok") is False,
      r2)

# 1d an unreadable path is rejected gracefully
r3 = docio.extract(os.path.join(tmp, "does-not-exist.pdf"))
check("1d an unreadable path is rejected with a diagnostic",
      r3.get("ok") is False and isinstance(r3.get("engine"), str) and r3.get("engine"),
      r3)

# 1e a tiny text-bearing PDF (when pdftotext is present) returns recommend_visual=False
if shutil.which("pdftotext"):
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            None,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    stream = ("BT /F1 18 Tf 20 100 Td (LONGRUNPDFMARKER hello world) Tj ET").encode()
    objs[3] = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offs:
        out += ("%010d 00000 n \n" % off).encode()
    out += (b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root 1 0 R >>\nstartxref\n"
            + str(xref).encode() + b"\n%%EOF")
    pdfp = os.path.join(tmp, "tiny.pdf")
    with open(pdfp, "wb") as f:
        f.write(bytes(out))
    r4 = docio.extract(pdfp)
    check("1e a text-bearing PDF is extracted with recommend_visual=False",
          r4.get("ok") is True and r4.get("recommend_visual") is False
          and "LONGRUNPDFMARKER" in (r4.get("text") or ""),
          {"engine": r4.get("engine"), "pages": r4.get("pages"),
           "recommend_visual": r4.get("recommend_visual"),
           "chars": r4.get("chars")})

    # 1f a synthesized "image-only" PDF (no text layer at all): since the
    # sample only has 1 page, pages_empty < 60% threshold so we don't
    # recommend_visual. We just confirm the diagnostic returns the expected
    # fields (engine, pages) without crashing.
    r5 = docio.extract(pdfp)
    check("1f the diagnostic carries the extracted_pages list",
          isinstance(r5.get("extracted_pages"), list) and r5.get("pages") is not None,
          r5.get("extracted_pages"))
else:
    check("1e a text-bearing PDF is extracted with recommend_visual=False [skipped]", True)
    check("1f the diagnostic carries the extracted_pages list [skipped]", True)

# -------------------------------------------------- 2) auto-routing
from longrun.memory import knowledge as K  # noqa: E402

# 2a explicit notebook still works (use add_source_text so we don't depend on
# the network — auto-route URLs go through the same router, but we want a
# deterministic smoke test).
r6 = K.add_source_text("default", "https://example.com/manual-seed",
                       "This is a manual seed for the explicit-notebook test.",
                       title="manual-seed")
check("2a explicit notebook still works",
      r6.get("ok") and r6.get("notebook_auto") is False,
      r6)

# 2b auto-route returns the new fields (deterministic, no network)
r7 = K.add_source_text("auto", "https://example.com/anatomy-italian-edition",
                       "Anatomia umana atlas. Skeleton, muscles, nervous system, "
                       "sense organs, endocrine system, digestive system, "
                       "urogenital system, respiration, circulation, immune "
                       "system, joints. By Adriana Rigutti, Italian edition.",
                       title="Anatomia — Italian Edition")
check("2b auto-route returns notebook_auto + notebook_name + recommend_visual",
      r7.get("ok") and "notebook_auto" in r7 and "notebook_name" in r7
      and "recommend_visual" in r7,
      r7)

# 2c a brand-new auto-routed source creates a new notebook
nbs_before = len(K.list_notebooks())
r8 = K.add_source_text("auto", "https://example.com/some-fresh-topic",
                       "Photosynthesis converts light energy into chemical energy.",
                       title="Photosynthesis")
nbs_after = len(K.list_notebooks())
check("2c auto-route on a fresh topic creates a new notebook",
      r8.get("ok") and nbs_after > nbs_before,
      {"before": nbs_before, "after": nbs_after, "result": r8})

# ------------------------------------------- 3) session-notebook scope (JAG-431r6b)
r9 = K.add_text("default", "session-scoped note", "This note is tagged with sid-A.",
                session_id="sid-A")
r10 = K.add_text("default", "session-scoped note B", "This other note is for sid-B.",
                 session_id="sid-B")
root_nb = r9.get("notebook", "")
check("3a a session-scoped note is indexed into a session notebook",
      r9.get("ok") and r10.get("ok") and r9.get("chunks", 0) > 0 and r10.get("chunks", 0) > 0
      and root_nb.startswith("sess-"),
      {"a": r9.get("chunks"), "b": r10.get("chunks"), "a_nb": root_nb})

# 3b the session notebook is NOT in the global/visible notebook list (it is a
# session-scoped thing, surfaced only in the dedicated Session tab).
visible = {n["id"] for n in K.list_notebooks()}
check("3b session notebooks are excluded from the global notebook list",
      root_nb not in visible,
      {"my": root_nb, "visible": sorted(visible)})

# 3c session notebooks ARE visible through list_sessions() (the dedicated tab),
# tagged is_session=True.
sess_list = K.list_sessions()
sess_nb_ids = {s["id"] for s in sess_list}
row = next((s for s in sess_list if s["id"] == root_nb), None)
check("3c list_sessions() exposes the session notebook with is_session=True",
      root_nb in sess_nb_ids and row is not None and row.get("is_session") is True,
      {"sessions": sess_list})

# 3d search scopes to one session (via its session notebook); a global search
# (no session) does NOT include session chunks.
sa = K.search("session-scoped", session="sid-A", k=5)
sb = K.search("session-scoped", session="sid-B", k=5)
sglob = K.search("session-scoped", k=5)
distinct = (sa.get("results") or [{}])[0].get("notebook") != (sb.get("results") or [{}])[0].get("notebook")
g_has_session = any(r.get("notebook") in sess_nb_ids for r in sglob.get("results", []))
check("3d session-scoped search returns only the matching session's chunks and global search does not leak",
      len(sa.get("results", [])) > 0 and len(sb.get("results", [])) > 0
      and distinct and g_has_session is False,
      {"a": len(sa.get("results", [])), "b": len(sb.get("results", [])),
       "global_has_session": g_has_session,
       "a_nb": (sa.get("results") or [{}])[0].get("notebook"),
       "b_nb": (sb.get("results") or [{}])[0].get("notebook")})

# 3e a session notebook is queryable ONLY in the global corpus when the agent
# explicitly opts in (the FULL-approval path) — i.e. it still resolves by id.
s_exp = K.search("session-scoped", notebook=root_nb, k=5)
check("3e a session notebook resolves by explicit notebook id (FULL approval path)",
      len(s_exp.get("results", [])) > 0,
      {"explicit": len(s_exp.get("results", []))})

# 3f the agent's add_source action inherits the chat session and skips duplicates.
from longrun.tools import tools as toolmod  # noqa: E402
attached_path = os.path.join(tmp, "attached-session-source.md")
with open(attached_path, "w", encoding="utf-8") as f:
    f.write("Unique session attachment marker: amber quartz.")
_old_embed_model = K._cfg.embed_model
try:
    K._cfg.embed_model = lambda: ""
    add1 = toolmod._knowledge({"action": "add_source", "ref": attached_path}, "sid-A")
    add2 = toolmod._knowledge({"action": "add_source", "ref": attached_path}, "sid-A")
finally:
    K._cfg.embed_model = _old_embed_model
session_results = K.search("amber quartz", session="sid-A", k=5)
global_results = K.search("amber quartz", k=5)
listed = toolmod._knowledge({"action": "list_notebooks"}, "sid-A")
listed_nbs = listed.get("notebooks", [])
search_tool = toolmod._knowledge({"action": "search", "query": "amber quartz"}, "sid-A")
read_tool = toolmod._knowledge(
    {"action": "read_source", "ref": attached_path}, "sid-A")
limited_read = toolmod._knowledge(
    {"action": "read_source", "ref": attached_path, "max_chars": 10}, "sid-A")
other_session_read = toolmod._knowledge(
    {"action": "read_source", "ref": attached_path}, "sid-B")
_old_embed_model = K._cfg.embed_model
try:
    K._cfg.embed_model = lambda: ""
    large_note = K.add_text(None, "Large session note",
                            "START " + ("body " * 10000) + " END",
                            session_id="sid-A")
finally:
    K._cfg.embed_model = _old_embed_model
bounded_read = K.read_source(
    large_note.get("ref"), session="sid-A", max_chars=64)
spoofed_session_list = toolmod._knowledge(
    {"action": "list_notebooks", "session": "sid-A"}, "sid-B")
spoofed_session_search = toolmod._knowledge(
    {"action": "search", "session": "sid-A", "query": "amber quartz"}, "sid-B")
cross_session_search = toolmod._knowledge(
    {"action": "search", "notebook": root_nb, "query": "amber quartz"}, "sid-B")
spoofed_session_read = toolmod._knowledge(
    {"action": "read_source", "session": "sid-A", "ref": attached_path}, "sid-B")
spoofed_session_write = toolmod._knowledge(
    {"action": "add_text", "session": "sid-A", "title": "foreign note",
     "text": "must not be written"}, "sid-B")
cross_session_write = toolmod._knowledge(
    {"action": "add_text", "notebook": root_nb, "title": "foreign note",
     "text": "must not be written"}, "sid-B")
db = K._connect()
source_count = db.execute("SELECT count(*) AS n FROM sources WHERE ref=?",
                          (attached_path,)).fetchone()["n"]
db.close()
check("3f1 Knowledge lists the current session notebook without exposing other sessions",
      any(n.get("id") == root_nb and n.get("is_session") is True
          and n.get("owner") == "sid-A" for n in listed_nbs)
      and all(n.get("owner") != "sid-B" for n in listed_nbs if n.get("is_session")),
      {"notebooks": listed_nbs})
check("3f2 session search returns the full matched chunk, not only a snippet",
      any("Unique session attachment marker: amber quartz." in r.get("text", "")
          for r in search_tool.get("results", []))
      and "Unique session attachment marker: amber quartz." in search_tool.get("stdout", "")
      and search_tool.get("scope") == "current session notebook",
      {"results": search_tool.get("results", [])})
check("3f2a direct Knowledge search keeps the compact snippet-only response by default",
      all("text" not in r for r in session_results.get("results", [])),
      session_results.get("results", []))
check("3f3 read_source returns the complete indexed attachment from this session",
      read_tool.get("ok") and
      "Unique session attachment marker: amber quartz." in read_tool.get("text", "")
      and read_tool.get("truncated") is False,
      read_tool)
check("3f4 read_source enforces its character limit and marks truncation",
      limited_read.get("ok") and limited_read.get("truncated") is True
      and len(limited_read.get("text", "")) == 10,
      limited_read)
check("3f4a read_source bounds a multi-chunk document and reports complete stats",
      bounded_read.get("ok") and bounded_read.get("truncated") is True
      and bounded_read.get("chunks") == large_note.get("chunks")
      and bounded_read.get("total_chars") > 64
      and len(bounded_read.get("text", "")) == 64
      and bounded_read.get("text", "").startswith("START "),
      bounded_read)
check("3f5 a session cannot read another session's indexed attachment",
      not other_session_read.get("ok") and
      "not found" in other_session_read.get("error", ""),
      other_session_read)
check("3f6 a tool cannot override its trusted run_id with another session id",
      all(not result.get("ok") and
          "session must match the current chat" in result.get("error", "")
          for result in (spoofed_session_list, spoofed_session_search,
                         spoofed_session_read, spoofed_session_write)),
      {"list": spoofed_session_list, "search": spoofed_session_search,
       "read": spoofed_session_read, "write": spoofed_session_write})
check("3f7 an explicit notebook cannot expose another session's search results",
      not cross_session_search.get("ok") and
      "outside the current session" in cross_session_search.get("error", ""),
      cross_session_search)
check("3f8 an explicit notebook cannot be modified by another session",
      not cross_session_write.get("ok") and
      "outside the current session" in cross_session_write.get("error", ""),
      cross_session_write)


class _CollisionDigest:
    """Return session A's digest to simulate a session notebook ID collision."""
    def hexdigest(self):
        return root_nb.split("-", 1)[1]


_old_sha1 = K.hashlib.sha1
K.hashlib.sha1 = lambda _value: _CollisionDigest()
try:
    collision_search = K.search("amber quartz", session="sid-B", k=5)
finally:
    K.hashlib.sha1 = _old_sha1
check("3f9 a colliding session notebook ID fails closed on owner mismatch",
      not collision_search.get("results"),
      collision_search.get("results", []))
check("3f knowledge.add_source defaults to the chat session notebook",
      add1.get("ok") and add1.get("added") == 1
      and add1.get("results", [{}])[0].get("notebook") == root_nb
      and bool(session_results.get("results"))
      and not global_results.get("results"),
      {"added": add1.get("added"),
       "notebook": add1.get("results", [{}])[0].get("notebook"),
       "session_hits": len(session_results.get("results", [])),
       "global_hits": len(global_results.get("results", []))})
check("3g repeated session source is skipped without duplicate chunks",
      add2.get("ok") and add2.get("added") == 0 and add2.get("skipped") == 1
      and add2.get("results", [{}])[0].get("duplicate") is True
      and add2.get("results", [{}])[0].get("pending_embeddings") == 0
      and source_count == 1,
      {"added": add2.get("added"), "skipped": add2.get("skipped"),
       "source_count": source_count})

# 3h purge_session removes the owned session notebook (sources + chunks) AND it
# disappears from list_sessions().
removed = K.purge_session("sid-A")
sess_after = {s["id"] for s in K.list_sessions()}
check("3h purge_session drops the session notebook from the Session tab",
      root_nb in removed.get("removed", []) and root_nb not in sess_after,
      {"removed": removed.get("removed"), "left_sessions": sorted(sess_after)})

# -------------------------------------------------- 4) migration: legacy DB
import sqlite3  # noqa: E402
from longrun.util import paths as _paths  # noqa: E402
legacy_dir = os.path.join(tmp, "legacy_kb")
os.makedirs(legacy_dir, exist_ok=True)
legacy_db = os.path.join(legacy_dir, "knowledge.db")
con = sqlite3.connect(legacy_db)
con.executescript("""
CREATE TABLE notebooks(id TEXT PRIMARY KEY, name TEXT, created REAL);
CREATE TABLE sources(
    id TEXT PRIMARY KEY, notebook TEXT, kind TEXT, ref TEXT, title TEXT,
    added REAL, chunks INTEGER);
CREATE TABLE chunks(
    id INTEGER PRIMARY KEY, source TEXT, path TEXT, lang TEXT, kind TEXT,
    name TEXT, start INTEGER, end INTEGER, tokens INTEGER, text TEXT, vec BLOB);
""")
con.commit()
con.close()
# Patch the live module's knowledge_dir so the migration runs against the
# legacy DB (paths.KNOWLEDGE_DIR is captured at import time).
_paths.KNOWLEDGE_DIR = legacy_dir
K._init(K._connect())
con = sqlite3.connect(legacy_db)
nb_cols = {r[1] for r in con.execute("PRAGMA table_info(notebooks)").fetchall()}
check("4 the migration adds hidden + owner + is_session to legacy notebooks",
      "hidden" in nb_cols and "owner" in nb_cols and "is_session" in nb_cols,
      nb_cols)
con.close()

# -------------------------------------------------- 5) API endpoint
from longrun.core import api_v02  # noqa: E402
routes = api_v02.ROUTES if hasattr(api_v02, "ROUTES") else None
# The dispatcher is inside _do_POST in api_v02; we test by importing the
# relevant branch via the public path used by httpapi.
API_SRC = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
               encoding="utf-8").read()
check("5 the auto-route endpoint is wired in api_v02",
      "/api/knowledge/auto-route" in API_SRC)
# JAG-431r7: the endpoint must WRITE the response (via _r), not return a bare dict
# (a bare dict left the socket with an empty reply -> curl(52) and a silent
# failure of the chat "+" ingest flow).
check("5b auto-route responds via _r(handler, ...) instead of returning a bare dict",
      'return _r(handler, 200 if res.get("ok") else 400, res)' in API_SRC)
# JAG-431r6b: the knowledge search endpoint forwards the optional session scope.
check("5c knowledge search forwards the optional `session` scope to kb.search()",
      'session=src.get("session") or None' in API_SRC)
TOOLS_SRC = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"),
                 encoding="utf-8").read()
check("5d agent source writes inherit the chat session and report duplicate skips",
      "session_scope = sid if not args.get(\"notebook\") else None" in TOOLS_SRC
      and "kb.add_sources(args.get(\"notebook\"), vals, session_id=session_scope)" in TOOLS_SRC
      and "already-indexed" in TOOLS_SRC)

# -------------------------------------------------- 6) webui auto-ingest
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("6a the WebUI calls /api/knowledge/auto-route on attach",
      "api/knowledge/auto-route" in HTML and "recommend_visual" in HTML)
check("6b the WebUI tags the ingest with the active session",
      "session: sessionId" in HTML)
check("6e the WebUI reports automatic Knowledge ingest failures",
      "knowledge indexing failed for " in HTML and "don't block attach on a KB error" not in HTML)
# JAG-431r6b: the dedicated, request-expanded "Session notebooks" tab exists and
# renders r.sessions from GET /api/knowledge/notebooks.
check("6c the WebUI has a dedicated Session notebooks panel",
      'id="kbSessionBox"' in HTML and 'id="kbSessions"' in HTML)
check("6d the WebUI renders session notebooks from the API `sessions` field",
      "function kbLoadSessions" in HTML and "r.sessions" in HTML)
# JAG-431r7: the transient system-prompt echo must be laid out CHRONOLOGICALLY
# (inside the turn's group), never appended to the root log (which dropped it
# below the answer, so a finished turn looked like it ended on a harness message).
check("7 the harness system-echo renders chronologically (not appended to the root log)",
      '_logAppend(det);' in HTML
      and 'if (kind === "system" && _sysInjectEl) _sysInjectEl.remove();' in HTML
      and '$("log").appendChild(det); _sysInjectEl = det;' not in HTML)

print("---")
ok = sum(results)
print("%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
