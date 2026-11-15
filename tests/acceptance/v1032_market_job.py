#!/usr/bin/env python3
"""v1032 — the full registry mirror, and the background job the page polls.

The old import stopped after `limit // 100 + 2` pages, so asking for 200 servers
gave 194 while the registry kept paginating. This pins the cursor loop, the
single-flight job, the failed-pass rule, and the read path a page of 8k items needs.

  A  the loop follows the CURSOR, not an assumed page count
  B  one job at a time; status moves running → finished with real counts
  C  a failed pass keeps the previous copy of the file
  D  the imported file is parsed once, not on every catalogue read
  E  the page shows progress and pages the result
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-v1032-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_TMP, "data", "sessions")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_TMP, "skills")
os.environ["LONGRUN_SKILLS_LOCAL_DIR"] = os.path.join(_TMP, "skills", "local")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import market, market_sync  # noqa: E402

JS = open(os.path.join(REPO, "webui", "assets", "market.js"), encoding="utf-8").read()
API = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ── A: the cursor loop ─────────────────────────────────────────────────────
PAGES = 250
ROWS = 2


def row(i):
    return {"server": {"name": "io.example/srv-%d" % i, "title": "Server %d" % i,
                       "description": "A database tool.", "version": "1.0.0",
                       "packages": [{"registryType": "npm", "identifier": "srv-%d" % i,
                                     "version": "1.0.0", "runtimeHint": "npx",
                                     "transport": {"type": "stdio"}}]},
            "_meta": {"io.modelcontextprotocol/registry/official": {"isLatest": True}}}


def paged(url, cfg):
    cur = 0
    for part in url.split("?")[-1].split("&"):
        if part.startswith("cursor="):
            cur = int(part.split("=", 1)[1])
    base = cur * ROWS
    return {"servers": [row(base + k) for k in range(ROWS)],
            "metadata": {"nextCursor": str(cur + 1) if cur + 1 < PAGES else None}}, ""


market._fetch_json = paged
seen = []
all_items, _errs = market_sync.sync_mcp_registry(
    limit=0, cfg={"registry_max": 0, "max_sync_pages": 600},
    on_page=lambda p, r, i, s: seen.append((p, r, i, s)))
check("A1 every page is read until the cursor ends",
      len(all_items) == PAGES * ROWS and seen and seen[-1][0] == PAGES,
      (len(all_items), seen and seen[-1]))
check("A2 the old page-count bound would have stopped at 4 pages",
      seen and seen[-1][0] > 4, seen and seen[-1][0])
check("A3 rows_seen counts what the registry returned, not only what mapped",
      seen and seen[-1][1] == PAGES * ROWS, seen and seen[-1])
capped, _e = market_sync.sync_mcp_registry(limit=200, cfg={"max_sync_pages": 600})
check("A4 an explicit budget stops exactly at the budget",
      len(capped) == 200, len(capped))

# ── B: the background job ──────────────────────────────────────────────────
CLAW = {"items": [{"slug": "research-helper", "displayName": "Research helper",
                   "summary": "Search papers.", "ownerHandle": "someone",
                   "topics": ["Research"], "latestVersion": {"version": "1.0.0"},
                   "stats": {"downloads": 2000}}]}


def claw(url, cfg):
    return CLAW, ""


def fetch_bytes(url, cfg, limit):
    return b"PK\x03\x04 fake-zip-bytes", ""


market._fetch_json = claw
market._fetch = fetch_bytes


def wait(timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        job = market_sync.job_status()
        if not job.get("running"):
            return job
        time.sleep(0.05)
    return market_sync.job_status()


market_sync._JOB.update(source="clawhub", running=True)
busy = market_sync.start("clawhub", limit=1)
check("B1 a second start is refused while one runs",
      busy.get("ok") is False and "already running" in busy.get("error", ""), busy)
market_sync._JOB.update(source="", running=False)

started = market_sync.start("clawhub", limit=1)
check("B2 a start returns the running job, not the result",
      started.get("ok") is True and started.get("started") is True
      and started["job"]["running"] is True, started.get("job"))
job = wait()
check("B3 the job reaches `finished` with real counts",
      job.get("running") is False and job.get("finished") and job.get("items") == 1
      and not job.get("error"), job)
snapshot = market_sync.job_status()
snapshot["items"] = 999
check("B4 job_status() returns a copy, so a caller cannot rewrite the job",
      market_sync.job_status()["items"] == 1)
check("B5 the group was written with the imported item",
      "clawhub" in json.load(open(market_sync._imported_path(), encoding="utf-8"))["sources"])
check("B6 a skill pass is not a truncated mirror", job.get("capped") is False, job.get("capped"))
market._fetch_json = paged
market_sync.start("mcp-registry", limit=4)
cap = wait()
check("B7 a pass that stops at the item budget says so",
      cap.get("capped") is True and cap.get("items") == 4, cap)

# ── C: a failed pass keeps the previous copy ───────────────────────────────
good = open(market_sync._imported_path(), encoding="utf-8").read()
market._fetch_json = lambda url, cfg: (None, "boom")
market_sync.start("clawhub", limit=1)
bad = wait()
check("C1 the failure is reported on the job",
      bad.get("error") and "boom" in bad["error"], bad.get("error"))
check("C2 the previous catalogue survives a failed pass",
      open(market_sync._imported_path(), encoding="utf-8").read() == good)
check("C3 an unknown source is refused before any thread starts",
      market_sync.start("nope").get("ok") is False)

# ── D: the read path a full mirror needs ───────────────────────────────────
many = {"schema": market.SCHEMA, "generated": "2026-11-15T00:00:00Z", "sources": {
    "mcp-registry": {"at": "2026-11-15T00:00:00Z", "items": [
        {"id": "mcp/bulk-%d" % i, "kind": "mcp", "name": "bulk-%d" % i,
         "title": "Bulk %d" % i, "description": "A database tool.",
         "category": "Data & Databases", "version": "1.0.0",
         "server": {"command": "npx", "args": ["-y", "bulk-%d" % i]}}
        for i in range(8000)]}}}
with open(market_sync._imported_path(), "w", encoding="utf-8") as f:
    json.dump(many, f)
first = market_sync._read_imported()
second = market_sync._read_imported()
check("D1 the 8k file is parsed once and reused",
      first is second and len(first["mcp-registry"]["items"]) == 8000)
t0 = time.time()
page = market.search(kind="mcp", limit=50)
warm = time.time() - t0
check("D2 a page of an 8k catalogue answers quickly",
      page["stats"]["matched"] >= 8000 and warm < 2.0, "%.3fs" % warm)

# ── E: the page ────────────────────────────────────────────────────────────
check("E1 the page starts the job in the background and polls its status",
      "/api/market/sync/status" in JS and "background: 1" in JS)
check("E2 the page writes live progress into the sync row",
      '"importing " + Number(job.rows_seen' in JS and '" \\u00b7 page "' in JS)
check("E3 the page gives up after a bounded wait",
      "15 * 60 * 1000" in JS)
check("E4 the page pages the catalogue instead of one giant request",
      "const PAGE_SIZE = 300" in JS and '"offset=" + offset' in JS)
check("E5 the routes exist and the sync route can stay synchronous for the CLI",
      '"/api/market/sync/status"' in API and "background" in API)
check("E6 a capped import is reported to the operator, not hidden",
      "job.capped" in JS and "item budget reached" in JS)

print("\n---\nv1032: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
