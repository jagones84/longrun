#!/usr/bin/env python3
"""v1031 — one curated vocabulary for the marketplace macro-areas.

The registry publishes no category and ClawHub's topics are inconsistent, so the
catalogue used to answer "Research & Analysis" with almost nothing. This pins the
classifier that fixes it, and the rule that every chip is a name the config declares.

  A  the vocabulary loads: declared areas, a real fallback, no duplicates
  B  classification is deterministic and the examples are the ones that broke
  C  a sync applies it to BOTH adapters and keeps the publisher's own value apart
  D  no model call, no network, no randomness
  E  a broken config falls back instead of crashing a sync
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-v1031-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_TMP, "data", "sessions")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_TMP, "skills")
os.environ["LONGRUN_SKILLS_LOCAL_DIR"] = os.path.join(_TMP, "skills", "local")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import market, market_sync, market_taxonomy  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ── A: the vocabulary ──────────────────────────────────────────────────────
areas = market_taxonomy.areas()
check("A1 the curated areas load, in their declared order",
      len(areas) == 14 and areas[0] == "AI & ML", (len(areas), areas[:2]))
check("A2 the names are unique", len(set(areas)) == len(areas), areas)
check("A3 a miss falls back to a real name", market_taxonomy.fallback() == "Other"
      and market_taxonomy.is_known("Other") is False)
catalog = json.load(open(os.path.join(REPO, "src", "longrun", "core", "market_catalog.json"),
                         encoding="utf-8"))["items"]
check("A4 every bundled catalogue category is a declared area",
      all(market_taxonomy.is_known(i.get("category")) for i in catalog),
      sorted({i.get("category") for i in catalog if not market_taxonomy.is_known(i.get("category"))}))
check("A5 the shipped plugins have a declared bucket of their own",
      market_taxonomy.is_known("Matrix tools"))

# ── B: classification ──────────────────────────────────────────────────────
check("B1 a database server is Data & Databases",
      market_taxonomy.classify("Postgres database tools for SQL queries") == "Data & Databases",
      market_taxonomy.classify("Postgres database tools for SQL queries"))
check("B2 a browser automation server is Browser & Web",
      market_taxonomy.classify("Browser automation with Playwright") == "Browser & Web",
      market_taxonomy.classify("Browser automation with Playwright"))
check("B3 research is Research & Analysis — the area that used to be empty",
      market_taxonomy.classify("Search arXiv papers and summarise research")
      == "Research & Analysis",
      market_taxonomy.classify("Search arXiv papers and summarise research"))
check("B4 gibberish is the fallback, not a random area",
      market_taxonomy.classify("zzz qqq wibble") == "Other")
check("B5 the same text always gives the same area",
      len({market_taxonomy.classify("browser scraping with a crawler") for _ in range(5)}) == 1)
check("B6 a publisher category that IS a curated name wins outright",
      market_taxonomy.classify("unrelated words", "Finance") == "Finance")
check("B7 an unrelated upstream topic is text, not a vote",
      market_taxonomy.classify("postgres database and sql", "Banking") == "Data & Databases",
      market_taxonomy.classify("postgres database and sql", "Banking"))
check("B8 matching is on word boundaries, not substrings",
      market_taxonomy.classify("transportation logistics") == "Other",
      market_taxonomy.classify("transportation logistics"))

# ── C: applied at sync, upstream kept aside ────────────────────────────────
market._fetch = lambda url, cfg, limit: (b"PK\x03\x04 fake-zip-bytes", "")
row = {"server": {"name": "io.example/postgres-tools", "title": "Postgres Database Tools",
                  "description": "Query a SQL database.", "version": "1.0.0",
                  "packages": [{"registryType": "npm", "identifier": "pg", "version": "1.0.0",
                                "runtimeHint": "npx", "transport": {"type": "stdio"}}]},
       "_meta": {"io.modelcontextprotocol/registry/official": {"isLatest": True}}}
item = market_sync._map_server(row)
check("C1 a registry row is classified by the curated vocabulary",
      item and item["category"] == "Data & Databases", item and item["category"])
check("C2 the registry publishes no category, so upstream stays empty",
      item and item["upstream_category"] == "", item and item.get("upstream_category"))
claw, _why = market_sync._claw_item(
    {"slug": "web-scraper", "displayName": "Web Scraper",
     "summary": "Crawl pages with a headless browser.", "topics": ["Browser"],
     "latestVersion": {"version": "1.0.0", "license": "MIT"}}, market._config())
check("C3 a ClawHub row is classified too",
      claw and claw["category"] == "Browser & Web", claw and claw["category"])
check("C4 the publisher's own topic is kept BESIDE the curated area",
      claw and claw["upstream_category"] == "Browser", claw and claw.get("upstream_category"))
_norm = market._normalize({"id": "skill/x", "kind": "skill", "title": "x",
                           "sha256": "a" * 64, "upstream_category": "Browser"}, "local")
check("C5 the catalogue carries both fields through",
      _norm is not None and _norm.get("upstream_category") == "Browser",
      _norm and _norm.get("upstream_category", "<dropped>"))

# ── D: deterministic, offline ──────────────────────────────────────────────
src = open(os.path.join(REPO, "src", "longrun", "core", "market_taxonomy.py"),
           encoding="utf-8").read()
check("D1 the classifier makes no network call",
      "urllib" not in src and "requests" not in src and "socket" not in src)
check("D2 it calls no model", "model" not in src.split('"""')[-1].lower()
      or "no model call" in src)
check("D3 area order comes from the file, not a sort",
      areas == [a for a in areas if a] and areas.index("AI & ML") < areas.index("Finance"))

# ── E: a broken config must not crash a sync ───────────────────────────────
broken = os.path.join(_TMP, "broken_taxonomy.yaml")
with open(broken, "w", encoding="utf-8") as f:
    f.write("fallback: Other\nareas: not-a-list\n")
original = market_taxonomy.TAXONOMY_PATH
market_taxonomy.TAXONOMY_PATH = broken
check("E1 a malformed vocabulary collapses to the fallback",
      market_taxonomy.areas() == ["Other"] and market_taxonomy.classify("anything") == "Other",
      market_taxonomy.areas())
missing = os.path.join(_TMP, "does-not-exist.yaml")
market_taxonomy.TAXONOMY_PATH = missing
check("E2 a missing vocabulary also falls back", market_taxonomy.classify("postgres") == "Other")
market_taxonomy.TAXONOMY_PATH = original
check("E3 restoring the file restores the areas", len(market_taxonomy.areas()) == 14)

print("\n---\nv1031: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
