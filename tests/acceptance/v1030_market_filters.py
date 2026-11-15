#!/usr/bin/env python3
"""v1030 — the marketplace filters by CATALOGUE, and the chips are scoped.

`#mktSource` only ever chose what a sync reads; no request carried a source, so the
"official MCP Registry / ClawHub" menu could not filter anything. This pins the real
filter plus the parts a refactor drops silently:

  A  `source=` narrows to one origin; `imported:` is a prefix over every adapter
  B  chips and counts are computed for the CURRENT scope, before the category filter
  C  `offset` pages without overlap and without changing the totals
  D  the page carries the filter (chips, Load more, sync label, cost line)
  E  every category the catalogue reports is a curated area
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-v1030-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_TMP, "data", "sessions")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_TMP, "skills")
os.environ["LONGRUN_SKILLS_LOCAL_DIR"] = os.path.join(_TMP, "skills", "local")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import market, market_sync  # noqa: E402

UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
JS = open(os.path.join(REPO, "webui", "assets", "market.js"), encoding="utf-8").read()
API = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


REGISTRY = {"servers": [
    {"server": {"name": "io.example/postgres-tools", "title": "Postgres database tools",
                "description": "Query a PostgreSQL database.", "version": "1.0.0",
                "packages": [{"registryType": "npm", "identifier": "pg-tools",
                              "version": "1.0.0", "runtimeHint": "npx",
                              "transport": {"type": "stdio"}}]},
     "_meta": {"io.modelcontextprotocol/registry/official": {"isLatest": True}}},
    {"server": {"name": "io.example/browser-agent", "title": "Browser automation",
                "description": "Drive Playwright in a browser.", "version": "1.0.0",
                "remotes": [{"type": "streamable-http", "url": "https://mcp.example.com/mcp"}]},
     "_meta": {"io.modelcontextprotocol/registry/official": {"isLatest": True}}},
    {"server": {"name": "io.example/maps", "title": "OpenStreetMap map lookup",
                "description": "Geocode places on a map.", "version": "1.0.0",
                "remotes": [{"type": "streamable-http", "url": "https://maps.example.com/mcp"}]},
     "_meta": {"io.modelcontextprotocol/registry/official": {"isLatest": True}}},
]}

CLAW = {"items": [
    {"slug": "research-helper", "displayName": "Research helper",
     "summary": "Search papers and summarize a survey.", "ownerHandle": "someone",
     "topics": ["Research"], "latestVersion": {"version": "1.0.0"},
     "stats": {"downloads": 2000}},
]}


def fake_fetch_json(url, cfg):
    if "registry.modelcontextprotocol.io" in url:
        return REGISTRY, ""
    if "/skills?" in url:
        return CLAW, ""
    return None, "unexpected url"


market._fetch_json = fake_fetch_json
market._fetch = lambda url, cfg, limit: (b"PK\x03\x04 fake-zip-bytes", "")
market_sync.sync("mcp-registry", limit=50)
market_sync.sync("clawhub", limit=5)

# ── A: the source filter ───────────────────────────────────────────────────
bundled = market.search(source="bundled", limit=5000)
check("A1 source=bundled returns only shipped entries",
      bundled["ok"] and bundled["items"]
      and all(i["origin"] == "bundled" for i in bundled["items"]),
      len(bundled["items"]))
reg = market.search(source="imported:mcp-registry", limit=5000)
check("A2 source=imported:mcp-registry returns only registry rows",
      reg["ok"] and reg["stats"]["matched"] == 3
      and all(i["origin"] == "imported:mcp-registry" for i in reg["items"]),
      reg["stats"]["matched"])
every = market.search(source="imported:", limit=5000)
check("A3 a trailing colon is a PREFIX over every adapter",
      {i["origin"] for i in every["items"]} == {"imported:mcp-registry", "imported:clawhub"},
      sorted({i["origin"] for i in every["items"]}))
local = market.search(source="local", limit=50)
check("A4 an empty origin is an empty page, not an error",
      local["ok"] is True and local["stats"]["matched"] == 0 and local["items"] == [],
      local["stats"]["matched"])
none = market.search(source="nope", limit=50)
check("A5 an unknown source matches nothing and does not crash",
      none["ok"] is True and none["stats"]["matched"] == 0)

# ── B: chips and counts are scoped ─────────────────────────────────────────
mcps = market.search(kind="mcp", limit=5000)
present = {i["category"] for i in mcps["items"]}
check("B1 the chips are exactly the categories in scope",
      set(mcps["categories"]) == present, sorted(mcps["categories"]))
check("B2 every chip has a count that matches the scope",
      mcps["stats"]["category_counts"] ==
      {c: sum(1 for i in mcps["items"] if i["category"] == c) for c in present},
      mcps["stats"]["category_counts"])
check("B3 by_kind sums to matched",
      sum(mcps["stats"]["by_kind"].values()) == mcps["stats"]["matched"],
      (mcps["stats"]["by_kind"], mcps["stats"]["matched"]))
skills = market.search(kind="skill", limit=5000)
check("B4 a category only one kind has is not offered on the other",
      "Location & Maps" in mcps["categories"] and "Location & Maps" not in skills["categories"],
      skills["categories"])
cat = max(mcps["stats"]["category_counts"], key=mcps["stats"]["category_counts"].get)
one = market.search(kind="mcp", category=cat, limit=5000)
check("B5 filtering by a chip returns exactly that chip's count",
      one["stats"]["matched"] == mcps["stats"]["category_counts"][cat]
      and all(i["category"] == cat for i in one["items"]), (cat, one["stats"]["matched"]))
check("B6 the chips are in the curated ORDER, not alphabetically",
      mcps["categories"] == [a for a in market.search(limit=1)["taxonomy"]
                             if a in set(mcps["categories"])], mcps["categories"])

# ── C: paging ──────────────────────────────────────────────────────────────
full = market.search(limit=5000)
head = market.search(limit=2)
second = market.search(limit=2, offset=2)
check("C1 offset pages do not overlap",
      len(head["items"]) == 2 and len(second["items"]) == 2
      and not ({i["id"] for i in head["items"]} & {i["id"] for i in second["items"]}),
      ([i["id"] for i in head["items"]], [i["id"] for i in second["items"]]))
check("C2 a page does not change the totals",
      head["stats"]["matched"] == full["stats"]["matched"] == len(full["items"]),
      (head["stats"]["matched"], full["stats"]["matched"]))
past = market.search(limit=2, offset=10 ** 6)
check("C3 an offset past the end is an empty page with the real total",
      past["items"] == [] and past["stats"]["matched"] == full["stats"]["matched"])

# ── D: the page carries the filter ─────────────────────────────────────────
check("D1 a catalogue chip row exists, separate from the sync selector",
      'id="mktSources"' in UI and 'aria-label="filter by catalogue"' in UI
      and 'el("mktSources")' in JS)
check("D2 the chips write `state.source` and reload",
      "state.source = c.getAttribute(\"data-source\")" in JS)
check("D3 the request carries the source and the offset",
      'qs.push("source="' in JS and '"offset=" + offset' in JS
      and 'qs.get("source")' in API and 'qs.get("offset")' in API)
check("D4 a partial page says so and offers Load more",
      "function sectionHtml(" in JS and "rows.length + \" of \" + total" in JS
      and 'id="mktMore"' in JS and "load({ append: true })" in JS)
check("D5 the sync selector is labelled as the sync target, not a filter",
      'id="mktSyncLbl"' in UI and ">sync from<" in UI and "\u21e3 import</button>" in UI)
check("D6 the cost of the selected catalogue is stated where it is read",
      'id="mktCost"' in UI and 'el("mktCost")' in JS and "s.cost" in JS)
check("D7 reload clears the source filter too",
      'state.source = "";' in JS.split("window.mktReload")[1][:200])
check("D8 the styles for the new blocks exist",
      ".mkt-sect-static {" in UI and ".mkt-more {" in UI and ".mkt-n {" in UI)
check("D9 the All chip counts the SCOPE, not the filtered page",
      "scopeTotal" in JS and "Object.values(c).reduce" in JS)

# ── E: one vocabulary ──────────────────────────────────────────────────────
tax = market.search(limit=1)["taxonomy"]
check("E1 the route publishes the curated vocabulary",
      isinstance(tax, list) and len(tax) == 14, len(tax or []))
check("E2 every reported category is a curated area",
      all(c in tax for c in full["categories"]), full["categories"])

print("\n---\nv1030: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
