#!/usr/bin/env python3
"""v1033 — breadth without mirroring: live search, then import ONE row.

Mirroring ~10k ClawHub skills costs one download per skill (the digest is pinned by
downloading), so the page searches the source ONLINE and imports only what is asked
for. This pins the preview contract and the import path:

  A  a remote row is a PREVIEW: online, no digest, not in the catalogue
  B  import pins the digest, writes the group, then installs — the normal path
  C  the route is read-only; refusals are by name
  D  the page shows the online section and its Import button
"""
import hashlib
import io
import json
import os
import sys
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-v1033-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_TMP, "data", "sessions")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_TMP, "skills")
os.environ["LONGRUN_SKILLS_LOCAL_DIR"] = os.path.join(_TMP, "skills", "local")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import market, market_sync  # noqa: E402

JS = open(os.path.join(REPO, "webui", "assets", "market.js"), encoding="utf-8").read()
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
API = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def zip_skill(slug):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SKILL.md", "---\nname: %s\ndescription: Crawl pages with a browser.\n---\n\n"
                              "Use a headless browser and return the text.\n" % slug)
    return buf.getvalue()


ZIP = zip_skill("web-scraper")

CLAW = {"items": [
    {"slug": "web-scraper", "displayName": "Web Scraper",
     "summary": "Crawl pages with a headless browser.", "ownerHandle": "someone",
     "topics": ["Browser"], "latestVersion": {"version": "1.0.0", "license": "MIT"},
     "stats": {"downloads": 5000}},
    {"slug": "other-skill", "displayName": "Other skill",
     "summary": "Something else.", "ownerHandle": "someone",
     "topics": ["Misc"], "latestVersion": {"version": "2.0.0"},
     "stats": {"downloads": 10}},
]}

REGISTRY = {"servers": [
    {"server": {"name": "io.example/postgres-tools", "title": "Postgres tools",
                "description": "A database tool.", "version": "1.0.0",
                "remotes": [{"type": "streamable-http", "url": "https://db.example.com/mcp"}]},
     "_meta": {"io.modelcontextprotocol/registry/official": {"isLatest": True}}},
], "metadata": {"nextCursor": None}}


def fake_fetch_json(url, cfg):
    if "registry.modelcontextprotocol.io" in url:
        return REGISTRY, ""
    if "/skills?" in url:
        return CLAW, ""
    return None, "unexpected url"


market._fetch_json = fake_fetch_json
market._fetch = lambda url, cfg, limit: (ZIP, "")

# ── A: a preview, not an install ───────────────────────────────────────────
res = market_sync.search_remote("clawhub", "browser", limit=10)
check("A1 the live search returns rows", res.get("ok") is True and len(res["items"]) == 2,
      res.get("error") or len(res.get("items") or []))
prev = res["items"][0]
check("A2 a preview is marked online and pins NO digest",
      prev.get("online") is True and prev.get("sha256") == "", prev.get("sha256"))
check("A3 a preview is classified and keeps the publisher's topic",
      prev["category"] == "Browser & Web" and prev["upstream_category"] == "Browser",
      (prev["category"], prev["upstream_category"]))
check("A4 a preview names the URL the import will download",
      "/download?slug=web-scraper&version=1.0.0" in prev["source"]["url"])
reg = market_sync.search_remote("mcp-registry", "postgres", limit=5)
check("A5 the registry works the same way, read-only",
      reg.get("ok") is True and reg["items"] and reg["items"][0]["online"] is True)
check("A6 a preview does not enter the catalogue",
      not any(i["id"] == "skill/web-scraper" for i in market.search(limit=5000)["items"]))
early = market.install("skill/web-scraper")
check("A7 an unpinned row cannot be installed by id",
      early.get("ok") is False, early.get("error"))

# ── B: import one ──────────────────────────────────────────────────────────
got = market_sync.import_one("clawhub", "web-scraper")
check("B1 the import succeeds and names the id",
      got.get("ok") is True and got.get("id") == "skill/web-scraper", got.get("error"))
groups = json.load(open(market_sync._imported_path(), encoding="utf-8"))["sources"]
rows = {r["id"]: r for r in groups["clawhub"]["items"]}
check("B2 the row is written into that source's group, with its digest",
      rows.get("skill/web-scraper", {}).get("sha256") == hashlib.sha256(ZIP).hexdigest(),
      rows.get("skill/web-scraper", {}).get("sha256"))
check("B3 the catalogue now shows it as installable",
      {i["id"]: i for i in market.search(limit=5000)["items"]}["skill/web-scraper"]
      .get("installable") is True)
check("B4 the install went through the normal path and left a record",
      any(r["id"] == "skill/web-scraper" for r in market.installed()["installed"]),
      [r["id"] for r in market.installed()["installed"]])
check("B5 the skill's files are on disk",
      os.path.isfile(os.path.join(os.environ["LONGRUN_SKILLS_LOCAL_DIR"],
                                  "web-scraper", "SKILL.md")))
again = market_sync.import_one("clawhub", "web-scraper")
check("B6 importing the same row twice does not duplicate it",
      again.get("ok") is True
      and len([r for r in json.load(open(market_sync._imported_path(),
                                         encoding="utf-8"))["sources"]["clawhub"]["items"]
               if r["id"] == "skill/web-scraper"]) == 1)
missing = market_sync.import_one("clawhub", "nope")
check("B7 an unknown row is refused by name",
      missing.get("ok") is False and "not found upstream" in missing.get("error", ""),
      missing.get("error"))

# ── C: refusals ────────────────────────────────────────────────────────────
check("C1 a search without a query is refused",
      market_sync.search_remote("clawhub", "").get("ok") is False)
check("C2 an unknown source is refused by name",
      "unknown source" in market_sync.search_remote("nope", "x").get("error", ""))
check("C3 the remote route only READS (no write path in it)",
      '"/api/market/remote"' in API and "search_remote(" in API)
check("C4 the import route writes through import_one only",
      '"/api/market/import-remote"' in API and "import_one(" in API)

# ── D: the page ────────────────────────────────────────────────────────────
check("D1 the page renders an Online section after the local ones",
      'Online \\u00b7 ' in JS and "state.online" in JS and "onlineCard" in JS)
check("D2 the online card says it is not in the local catalogue",
      "not in the local catalogue yet" in JS)
check("D3 the Import button posts the source and the slug",
      'class="ghost mkt-import-remote"' in JS
      and '"/api/market/import-remote", { source, slug }' in JS)
check("D4 the live search runs only for a real query",
      "state.q.trim().length >= 2" in JS and "function remoteSearch(" in JS)
check("D5 the online section only shows for its own kind",
      "function onlineKindMatches(" in JS)
check("D6 the selector starts on ClawHub, which is the broad catalogue",
      'onlineSource: "clawhub"' in JS)
check("D7 the legend/kinds line still names what the four kinds are",
      'id="mktLegend"' in UI)

print("\n---\nv1033: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
