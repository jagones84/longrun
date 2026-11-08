#!/usr/bin/env python3
"""v873 — a tool query ranks by HOW a word matches, not merely that it does (Pareto).

Measured live 2026-11-08: `self.tools {query:"time date now"}` answered with 12
tools and NO time tool — "now" scored a full point inside "knowledge" and "date"
inside "update", so 65 candidates crowded out the three `time__*` tools (rank
15-17). The fix keeps every match (a substring still counts, so no query loses a
hit) and only weights it: whole token 3 > token PREFIX 2 > inside a token 1, for
both the score and the NAME boost. This pins the lossless contract:

  A1 the live trap: the time tool reaches the cap window for "time date now"
  A2 it outranks the tools that only hold "now"/"date" mid-word
  A3 recall is NOT reduced: a mid-word-only hit still answers when nothing better
  A4 a real prefix still matches ("download" -> a description saying "downloads")
  A5 an exact phrase still wins outright
  A6 a zero-hit query still answers with the search hint
  A7 a function word ("the") no longer scores on its own
  A8 a full-phrase hit in a DESCRIPTION does not hide the tool whose NAME holds it
  A9 a full-phrase hit in a NAME still collapses the answer to that tool

Deterministic: fixture catalog, no MCP client, no network.
Run: python3 tests/acceptance/v873_tool_query_tiers.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v873-")
os.environ.setdefault("LONGRUN_DATA_DIR", os.path.join(TMP, "data"))
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(TMP, "cfg"))
os.environ.setdefault("LONGRUN_DB", os.path.join(TMP, "events.db"))
os.environ.setdefault("LONGRUN_SESSIONS_DIR", os.path.join(TMP, "sessions"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import diag             # noqa: E402
from longrun.tools import registry         # noqa: E402


def tool(name, desc):
    return {"name": name, "enabled": True, "origin": "native",
            "approval": "auto", "description": desc}


_CATALOG = [
    tool("time__get_current_time", "Get the current time and date in a timezone."),
    tool("time__get_time_ago", "How long ago a past date was."),
    tool("knowledge.discover", "Discover sources for a knowledge notebook."),
    tool("agent.update", "Update an agent definition."),
    tool("web.fetch", "Fetch a URL; downloads the page body into the workspace."),
    tool("web.search", "Search the web."),
    tool("knowledge.discover", "Search the web for sources and add them to a notebook."),
    tool("diff.text", "Compare two texts."),
    tool("diff.files", "Compare two files."),
    tool("sysprobe.runtime", "Snapshot the runtime of the host."),
    tool("memory.recall", "Recall memories matching a query."),
    tool("memory.store", "Store a durable note the harness remembers."),
]
_orig_catalog = registry.catalog
registry.catalog = lambda: list(_CATALOG)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


try:
    # ---------------------------------------------- A1/A2 the live trap ------
    rep = diag.tools_report(query="time date now")
    names = list((rep.get("tools") or {}))
    tct = "time__get_current_time"
    check("A1 the time tool is in the cap window for 'time date now'",
          rep.get("ok") is True and tct in names
          and names.index(tct) < diag.TOOL_QUERY_LIMIT,
          "%s at %s of %s" % (tct, names.index(tct) + 1 if tct in names else None, len(names)))
    check("A2 it outranks the mid-word accidents ('knowledge' holds 'now', "
          "'update' holds 'date')",
          tct in names and tct in names and
          (("knowledge.discover" not in names
            or names.index(tct) < names.index("knowledge.discover")) and
           ("agent.update" not in names
            or names.index(tct) < names.index("agent.update"))), names)

    # ------------------------------------------------- A3 no recall loss ----
    now = diag.tools_report(query="now")
    check("A3 a MID-WORD-only hit still answers when nothing matches better",
          "knowledge.discover" in (now.get("tools") or {}),
          list((now.get("tools") or {})))
    date = diag.tools_report(query="date")
    check("A3b same for 'date' inside 'update'",
          "agent.update" in (date.get("tools") or {}), list((date.get("tools") or {})))

    # -------------------------------------------------- A4 prefix recall ----
    dl = diag.tools_report(query="download")
    check("A4 a token PREFIX still matches ('download' -> 'downloads')",
          "web.fetch" in (dl.get("tools") or {}), list((dl.get("tools") or {})))

    # ------------------------------------------------- A5 exact phrase ------
    ph = diag.tools_report(query="memory.recall")
    check("A5 a full-phrase hit stays the only answer",
          list((ph.get("tools") or {})) == ["memory.recall"],
          list((ph.get("tools") or {})))

    # ------------------------------------------------- A6 no-hit honesty -----
    none = diag.tools_report(query="qqqzzzwwwxxx")
    check("A6 a zero-hit query answers with the search hint, not silence",
          "no tool matches those words" in (none.get("hint") or ""), none.get("hint"))

    # ------------------------------------------- A7/A8 stopwords + phrase -----
    show = diag.tools_report(query="show me the memory")
    check("A7 a function word ('the') does not score on its own",
          "memory.recall" in (show.get("tools") or {})
          and "sysprobe.runtime" not in (show.get("tools") or {}),
          list((show.get("tools") or {})))
    web = diag.tools_report(query="search the web")
    order = list((web.get("tools") or {}))
    check("A8 a phrase found only in a DESCRIPTION does not hide the NAME match",
          order[:1] == ["web.search"] and "knowledge.discover" in order, order)

    # ------------------------------------------------- A9 name phrase ---------
    dt = diag.tools_report(query="diff.text")
    check("A9 a full-phrase hit in a NAME still collapses the answer",
          list((dt.get("tools") or {})) == ["diff.text"],
          list((dt.get("tools") or {})))
finally:
    registry.catalog = _orig_catalog

print("---")
okc = sum(results)
print("\nv873: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
