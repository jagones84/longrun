"""Sync an external marketplace into the local catalogue.

Two adapters, both read-only against a public API:

* ``mcp-registry`` — the official Model Context Protocol registry
  (`registry.modelcontextprotocol.io/v0/servers`). Its schema gives a server's
  stdio packages (`registryType`, `identifier`, `version`, `runtimeHint`,
  `environmentVariables`) and its `remotes` (`streamable-http`, optional headers),
  which is exactly the two shapes the longrun MCP client already speaks.
* ``clawhub`` — the skill marketplace OpenClaw publishes
  (`clawhub.ai/api/v1`). Its `/skills` listing plus a GET `/download?slug&version`
  ZIP is exactly what `memory.skills.install_zip` already consumes.

Compatibility is a RULE, not a per-item decision:

* a stdio package → an ``mcp`` entry with `command`/`args`/`env`;
* a remote whose headers are optional → an ``mcp`` entry;
* a remote that REQUIRES a credential → a ``connector`` entry with one key name
  derived from the item, so two connectors never share a `.env` name;
* anything with neither package nor remote → dropped, counted as skipped;
* every skill is downloaded ONCE at sync time and its digest pinned, so the
  install still verifies the bytes and fails closed if upstream moved.

Nothing here executes a server. A sync writes `data/market/imported.json`, which
the catalogue reads after the operator's own file and the bundled one.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from longrun.core import market, market_taxonomy
from longrun.util import fswrite, paths

MCP_REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"
CLAWHUB = "https://clawhub.ai/api/v1"
PAGE = 100
MAX_LIMIT = 20000
MAX_PAGES = 600
# 2026-11-21 (operator: *"non c'è modo di leggere descrizioni complete? sono tutte
# tagliate"*): the card clamps to two lines and the DETAIL dialog shows this text
# whole, so the copy must hold a real description, not a teaser. The published
# summaries measured on ClawHub run to ~800 chars; 1200 covers them. The cut is on
# a word boundary and says so, instead of ending mid-sentence.
DESC_MAX = 1200
_SLUG = re.compile(r"[^a-z0-9._-]+")
_HTTP = re.compile(r"^https?://", re.I)


def _page(url):
    """An origin PAGE only when it is a real http(s) URL — never a javascript: one."""
    u = str(url or "").strip()
    return u if _HTTP.match(u) else ""


def _clip(text, limit=DESC_MAX):
    """Collapse whitespace and cut on a word boundary, marking the cut with …"""
    s = " ".join(str(text or "").split())
    if len(s) <= limit:
        return s
    cut = s[:limit]
    sp = cut.rfind(" ")
    if sp >= limit // 2:
        cut = cut[:sp]
    return cut.rstrip(" ,;:.-") + "\u2026"

# One background import at a time; the page polls this dict.
_JOB = {"source": "", "running": False, "started": "", "finished": "",
        "pages": 0, "rows_seen": 0, "items": 0, "skipped": 0,
        "error": "", "path": "", "capped": False}
_JOB_LOCK = threading.Lock()
_IMPORTED_CACHE = {"sig": None, "doc": None}


def sources():
    """The adapters this build ships, with the host each one needs allowed."""
    return [
        {"id": "mcp-registry", "label": "MCP Registry (official)",
         "host": "registry.modelcontextprotocol.io",
         "kinds": ["mcp", "connector"],
         "cost": "Free and public to read \u2014 no account needed. A server may still "
                 "ask for its own key.",
         "note": "Every published MCP server; stdio packages and remotes."},
        {"id": "clawhub", "label": "ClawHub (OpenClaw skills)",
         "host": "clawhub.ai", "kinds": ["skill"],
         "cost": "Free to read and install; each skill carries its own license.",
         "note": "Skills published to ClawHub; each is pinned by digest at sync."},
    ]


def _slug(text, fallback="item", maxlen=48):
    s = _SLUG.sub("-", str(text or "").lower()).strip("-._")
    s = re.sub(r"-{2,}", "-", s)
    return (s or fallback)[:maxlen].strip("-._") or fallback


def _env_name(slug):
    """A per-item credential NAME — never shared between two connectors."""
    return (re.sub(r"[^A-Z0-9]+", "_", str(slug).upper()).strip("_") or "MCP")[:40] + "_TOKEN"


def _imported_path():
    return os.path.join(market._market_dir(), "imported.json")


def _read_imported():
    """The imported groups, memoised on (path, mtime, size).

    A full registry mirror is thousands of items (~tens of MB); re-parsing it on
    every `/api/market/catalog` call would make the page crawl. The file is only
    written by this module, so mtime+size is a safe invalidator.
    """
    path = _imported_path()
    try:
        st = os.stat(path)
        sig = (path, st.st_mtime, st.st_size)
    except OSError:
        sig = (path, None, None)
    if _IMPORTED_CACHE["sig"] == sig and _IMPORTED_CACHE["doc"] is not None:
        return _IMPORTED_CACHE["doc"]
    groups = {}
    if sig[1] is not None:
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            rows = doc.get("sources") if isinstance(doc, dict) else None
            groups = rows if isinstance(rows, dict) else {}
        except (OSError, ValueError):
            groups = {}
    _IMPORTED_CACHE.update(sig=sig, doc=groups)
    return groups


def _write_imported(groups):
    payload = {"schema": market.SCHEMA, "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "sources": groups}
    fswrite.write_json(_imported_path(), payload)
    _IMPORTED_CACHE.update(sig=None, doc=None)
    return _imported_path()


# ── MCP Registry ──────────────────────────────────────────────────────────────

def _map_package(pkg):
    """One stdio package → `(server, keys)`, or `(None, [])` when unrunnable."""
    transport = (pkg.get("transport") or {}).get("type") or "stdio"
    if transport != "stdio":
        return None, []
    ident = str(pkg.get("identifier") or "").strip()
    if not ident:
        return None, []
    ver = str(pkg.get("version") or "").strip()
    runtime = str(pkg.get("runtimeHint") or "").strip().lower()
    regtype = str(pkg.get("registryType") or "").strip().lower()
    extra = [str(a.get("value")) for a in (pkg.get("runtimeArguments") or [])
             if isinstance(a, dict) and a.get("value") is not None]
    if regtype == "npm" or runtime == "npx":
        args = list(extra)
        if not any(str(a).strip() == "-y" for a in args):
            args.append("-y")
        command, args = "npx", args + [ident + ("@" + ver if ver else "")]
    elif regtype == "pypi" or runtime == "uvx":
        command, args = "uvx", extra + [ident]
    elif regtype == "oci" or runtime == "docker":
        command, args = "docker", extra + ["run", "-i", "--rm", ident + (":" + ver if ver else "")]
    else:
        command, args = (runtime or "npx"), extra + [ident]
    server = {"command": command, "args": args}
    env, keys = {}, []
    for ev in (pkg.get("environmentVariables") or []):
        if not isinstance(ev, dict) or not ev.get("name"):
            continue
        name = str(ev["name"])
        env[name] = "${%s}" % name
        if ev.get("isRequired") or ev.get("isSecret"):
            keys.append(name)
    if env:
        server["env"] = env
    return server, keys


def _map_remote(remote, slug):
    """One remote → `(server, keys)`."""
    url = str(remote.get("url") or "").strip()
    if not url:
        return None, []
    server = {"type": "http", "url": url}
    headers, keys = {}, []
    for h in (remote.get("headers") or []):
        if not isinstance(h, dict):
            continue
        name = str(h.get("name") or ("Authorization" if h.get("value") else "")).strip()
        if not name:
            continue
        value = str(h.get("value") or "")
        if h.get("isRequired") or "{" in value:
            key = _env_name(slug)
            headers[name] = "Bearer ${%s}" % key
            keys.append(key)
        else:
            headers[name] = value
    if headers:
        server["headers"] = headers
    return server, keys


def _meta(row):
    """The registry's per-row official metadata (`status`, timestamps, isLatest)."""
    return (row.get("_meta") or {}).get("io.modelcontextprotocol.registry/official") or {}


def _map_server(row):
    """One registry row → a catalogue entry, or None (counted as skipped)."""
    srv = row.get("server") if isinstance(row, dict) else None
    if not isinstance(srv, dict):
        return None
    name = str(srv.get("name") or "").strip()
    if not name:
        return None
    slug = _slug(name.replace("/", "-"))
    server, keys = None, []
    for pkg in (srv.get("packages") or []):
        if isinstance(pkg, dict):
            server, keys = _map_package(pkg)
            if server:
                break
    if server is None:
        for remote in (srv.get("remotes") or []):
            if isinstance(remote, dict):
                server, keys = _map_remote(remote, slug)
                if server:
                    break
    if server is None:
        return None
    kind = "connector" if keys else "mcp"
    meta = _meta(row)
    title = str(srv.get("title") or name)
    desc = str(srv.get("description") or "")
    repo = srv.get("repository") if isinstance(srv.get("repository"), dict) else {}
    item = {
        "id": ("connector/" if keys else "mcp/") + slug,
        "kind": kind,
        "name": slug,
        "title": title,
        "description": _clip(desc),
        # The publisher's own page, when the registry publishes one (the UI opens it
        # from the detail dialog). The MCP endpoint in `remotes` is NOT a page.
        "homepage": _page(srv.get("websiteUrl")) or _page(repo.get("url")),
        # `category` is the curated macro-area (config/market_taxonomy.yaml): the
        # registry publishes no taxonomy, and one bucket made every chip empty.
        "category": market_taxonomy.classify(" ".join((title, desc, name))),
        "upstream_category": "",
        "featured": False,
        "version": str(srv.get("version") or ""),
        "publisher": str(name.split("/")[0] if "/" in name else ""),
        "updated": str(meta.get("updatedAt") or "")[:10],
        "status": str(meta.get("status") or "active"),
        "server": server,
    }
    if keys:
        item["keys"] = keys
    return item


def _is_latest(row):
    return bool(_meta(row).get("isLatest", True))


def sync_mcp_registry(limit=200, query="", cfg=None, on_page=None):
    """Read the official registry (latest versions only) and map every entry.

    `limit=0` means "everything the config allows" (`registry_max`, 0 = all). The
    loop is bounded by the CURSOR and `max_sync_pages`, never by an assumed page
    size: the old `limit // PAGE + 2` bound silently stopped at ~264 servers while
    the registry kept paginating (measured 2026-11-15).
    """
    cfg = cfg or market._config()
    try:
        budget = int(limit or 0)
    except (TypeError, ValueError):
        budget = 0
    if budget <= 0:
        budget = int(cfg.get("registry_max") or 0) or MAX_LIMIT
    budget = max(1, min(budget, MAX_LIMIT))
    try:
        max_pages = max(1, int(cfg.get("max_sync_pages") or MAX_PAGES))
    except (TypeError, ValueError):
        max_pages = MAX_PAGES
    items, errors, seen = [], [], set()
    cursor, pages, rows_seen = "", 0, 0
    while len(items) < budget and pages < max_pages:
        params = {"limit": PAGE}
        if query:
            params["search"] = str(query)
        if cursor:
            params["cursor"] = cursor
        url = MCP_REGISTRY + "?" + "&".join("%s=%s" % (k, v) for k, v in params.items())
        doc, why = market._fetch_json(url, cfg)
        if doc is None:
            errors.append(why)
            break
        rows = doc.get("servers") or []
        if not isinstance(rows, list):
            errors.append("unexpected payload: `servers` is not a list")
            break
        rows_seen += len(rows)
        for row in rows:
            if not _is_latest(row):
                continue
            status = str(_meta(row).get("status") or "active")
            if status != "active":
                errors.append("skipped (status=%s): %s"
                              % (status, (row.get("server") or {}).get("name") or "?"))
                continue
            item = _map_server(row)
            if item is None:
                errors.append("skipped (no runnable package or remote): %s"
                              % ((row.get("server") or {}).get("name") or "?"))
                continue
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            items.append(item)
            if len(items) >= budget:
                break
        cursor = str((doc.get("metadata") or {}).get("nextCursor") or "")
        pages += 1
        if on_page:
            on_page(pages, rows_seen, len(items), len(errors))
        if not cursor:
            break
    return items, errors


# ── ClawHub ───────────────────────────────────────────────────────────────────

def _claw_row_meta(row):
    """`(slug, version, topic, published)` shared by the mirror and the preview."""
    latest = row.get("latestVersion") or {}
    version = str(latest.get("version") or "")
    topics = [str(t).strip() for t in (row.get("topics") or []) if str(t).strip()]
    # The UI is English-only: take the publisher's first ASCII topic, else nothing.
    topic = next((t.title() for t in topics if t.isascii()), "")
    stamp = row.get("updatedAt")
    updated = ""
    if isinstance(stamp, (int, float)) and stamp > 0:
        updated = time.strftime("%Y-%m-%d", time.gmtime(stamp / 1000.0))
    return _slug(row.get("slug")), version, topic, updated


def _claw_page(owner, slug):
    """The ClawHub page of one skill (`<owner>/skills/<slug>`, verified HTTP 200)."""
    o, s = str(owner or "").strip(), str(slug or "").strip()
    if not o or not s:
        return ""
    return "https://clawhub.ai/%s/skills/%s" % (urllib.parse.quote(o, safe=""),
                                                urllib.parse.quote(s, safe=""))


def _claw_item(row, cfg):
    """One ClawHub row → `(item, error)`; its ZIP is downloaded once to pin it.

    The download is the slow part (one GET per skill), so callers run these in
    parallel — a serial sync measured 65.7 s for 24 skills on 2026-11-15.
    """
    slug, version, topic, updated = _claw_row_meta(row)
    if not row.get("slug") or not version:
        return None, "skipped (no slug/version)"
    dl = "%s/download?slug=%s&version=%s" % (CLAWHUB, row["slug"], version)
    data, why = market._fetch(dl, cfg, market.MAX_ITEM_BYTES)
    if data is None:
        return None, "%s: %s" % (row["slug"], why)
    title = str(row.get("displayName") or row.get("slug"))
    desc = str(row.get("description") or row.get("summary") or "")
    stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
    return {
        "id": "skill/" + slug, "kind": "skill", "name": slug,
        "title": title,
        "description": _clip(desc),
        # The skill's page on ClawHub (verified 200): <owner>/skills/<slug>. The
        # download URL in `source` is the artifact, not something to read.
        "homepage": _claw_page(row.get("ownerHandle"), slug),
        # `category` is the curated macro-area; the publisher's own topic is kept
        # beside it for the tooltip (the source is `origin`).
        "category": market_taxonomy.classify(" ".join((title, desc, topic)), topic),
        "upstream_category": topic,
        "featured": bool((stats.get("downloads") or 0) > 1000),
        "version": version,
        "publisher": str(row.get("ownerHandle") or ""),
        "updated": updated,
        "license": str((row.get("latestVersion") or {}).get("license") or ""),
        "downloads": stats.get("downloads") if isinstance(stats.get("downloads"), int) else None,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "source": {"type": "https", "url": dl},
    }, ""


def _claw_preview(row):
    """A search result: catalogue-shaped, NOT installable (no digest pinned yet)."""
    slug, version, topic, updated = _claw_row_meta(row)
    if not row.get("slug") or not version:
        return None
    title = str(row.get("displayName") or row.get("slug"))
    desc = str(row.get("description") or row.get("summary") or "")
    stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
    return {
        "id": "skill/" + slug, "kind": "skill", "name": slug,
        "title": title, "description": _clip(desc),
        "homepage": _claw_page(row.get("ownerHandle"), slug),
        "category": market_taxonomy.classify(" ".join((title, desc, topic)), topic),
        "upstream_category": topic,
        "featured": False, "version": version,
        "publisher": str(row.get("ownerHandle") or ""),
        "updated": updated,
        "license": str((row.get("latestVersion") or {}).get("license") or ""),
        "downloads": stats.get("downloads") if isinstance(stats.get("downloads"), int) else None,
        "sha256": "", "online": True,
        "source": {"type": "https",
                   "url": "%s/download?slug=%s&version=%s" % (CLAWHUB, row["slug"], version)},
    }


def sync_clawhub(limit=25, query="", cfg=None):
    """Read ClawHub and PIN each skill's digest by downloading it once."""
    cfg = cfg or market._config()
    limit = max(1, min(int(limit or 25), 100))
    params = {"limit": limit}
    if query:
        params["search"] = str(query)
    url = CLAWHUB + "/skills?" + "&".join("%s=%s" % (k, v) for k, v in params.items())
    doc, why = market._fetch_json(url, cfg)
    if doc is None:
        return [], [why]
    rows = doc.get("items") or []
    if not isinstance(rows, list):
        return [], ["unexpected payload: `items` is not a list"]
    rows = [r for r in rows if isinstance(r, dict)][:limit]
    workers = min(8, max(1, len(rows)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda r: _claw_item(r, cfg), rows))
    items, errors = [], []
    for item, err in results:
        if item:
            items.append(item)
        if err:
            errors.append(err)
    return items, errors


SOURCES = {"mcp-registry": sync_mcp_registry, "clawhub": sync_clawhub}


def status(cfg=None):
    """Each adapter plus its LAST SYNC (`at`, `items`, `age_seconds`, `stale`).

    A sync is a point-in-time copy, so the page must be able to say how old it
    is: `stale_days` in `config/market.yaml` (0 = never stale).
    """
    cfg = cfg or market._config()
    groups = _read_imported()
    stale_days = int(cfg.get("stale_days") or 0)
    now = time.time()
    out = []
    for src in sources():
        group = groups.get(src["id"]) if isinstance(groups, dict) else None
        group = group if isinstance(group, dict) else {}
        rows = group.get("items")
        at = str(group.get("at") or "")
        age = None
        if at:
            try:
                stamp = datetime.datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ")
                age = max(0, int(now - stamp.replace(tzinfo=datetime.timezone.utc).timestamp()))
            except ValueError:
                age = None
        out.append(dict(src, at=at, items=len(rows) if isinstance(rows, list) else 0,
                        age_seconds=age,
                        stale=bool(stale_days and age is not None and age > stale_days * 86400)))
    return out


def sync(source, limit=None, query="", cfg=None):
    """Fetch one source and REPLACE that source's group in imported.json."""
    fn = SOURCES.get(str(source or ""))
    if fn is None:
        return {"ok": False, "error": "unknown source: %s (try %s)"
                % (source, ", ".join(sorted(SOURCES)))}
    items, errors = fn(limit if limit is not None else (200 if source == "mcp-registry" else 25),
                       query, cfg)
    if not items and errors:
        # Same rule as the background job: a total failure keeps the last good copy.
        return {"ok": False, "error": "import failed: %s" % errors[0], "source": source,
                "items": 0, "errors": errors[:8], "error_count": len(errors)}
    groups = dict(_read_imported())
    groups[source] = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "items": items}
    path = _write_imported(groups)
    return {"ok": True, "source": source, "items": len(items),
            "errors": errors[:8], "error_count": len(errors), "path": path,
            "catalog": market.search(limit=1)["stats"]}


# ── the background import (a full registry pass is minutes, not seconds) ─────

def job_status():
    with _JOB_LOCK:
        return dict(_JOB)


def start(source, limit=None, query="", cfg=None):
    """Start ONE background import; the page polls `job_status()`.

    `limit=0` (the default for the registry here) means "the configured maximum",
    which is how the whole registry is mirrored. A second start while one runs is
    refused by name. The group is written only when the pass succeeds, so a failed
    run keeps the previous copy.
    """
    src = str(source or "")
    if src not in SOURCES:
        return {"ok": False, "error": "unknown source: %s (try %s)"
                % (src, ", ".join(sorted(SOURCES))), "job": job_status()}
    with _JOB_LOCK:
        if _JOB.get("running"):
            return {"ok": False, "error": "a sync is already running", "job": dict(_JOB)}
        _JOB.update(source=src, running=True,
                    started=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    finished="", pages=0, rows_seen=0, items=0, skipped=0,
                    error="", path="", capped=False)
    lim = 0 if (limit is None and src == "mcp-registry") else limit

    def _worker():
        def on_page(pages, rows, items, skipped):
            with _JOB_LOCK:
                _JOB.update(pages=pages, rows_seen=rows, items=items, skipped=skipped)
        try:
            fn = SOURCES[src]
            if src == "mcp-registry":
                items, errors = fn(lim if lim is not None else 0, query, cfg, on_page=on_page)
            else:
                items, errors = fn(lim if lim is not None else 25, query, cfg)
            if not items and errors:
                # A total failure (unreachable host, refused payload) must not
                # replace a good mirror with an empty one.
                with _JOB_LOCK:
                    _JOB.update(running=False, skipped=len(errors),
                                error="import failed: %s" % errors[0],
                                finished=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                return
            groups = dict(_read_imported())
            groups[src] = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                           "items": items}
            path = _write_imported(groups)
            # A pass that stopped at the item budget is PARTIAL: say so, never let
            # the page present a truncated mirror as the whole registry.
            eff = lim if lim else int((cfg or market._config()).get("registry_max") or 0) or MAX_LIMIT
            capped = bool(src == "mcp-registry" and len(items) >= min(int(eff), MAX_LIMIT))
            with _JOB_LOCK:
                _JOB.update(running=False, items=len(items), skipped=len(errors),
                            path=path, capped=capped,
                            finished=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        except Exception as e:  # noqa: BLE001 — the job must report, never kill the service
            with _JOB_LOCK:
                _JOB.update(running=False, error="%s: %s" % (type(e).__name__, e),
                            finished=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    threading.Thread(target=_worker, name="market-sync-%s" % src, daemon=True).start()
    return {"ok": True, "started": True, "source": src, "job": job_status()}


# ── live remote search: breadth without mirroring 10k skills ────────────────

def search_remote(source, query="", limit=50, cfg=None):
    """Search a source ONLINE. Rows are previews: no digest is pinned yet."""
    cfg = cfg or market._config()
    src = str(source or "")
    q = str(query or "").strip()
    if src not in SOURCES:
        return {"ok": False, "error": "unknown source: %s" % src, "items": []}
    if not q:
        return {"ok": False, "error": "a query is required", "items": []}
    lim = max(1, min(int(limit or 50), 100))
    if src == "clawhub":
        url = "%s/skills?limit=%d&search=%s" % (CLAWHUB, lim, urllib.parse.quote(q))
        doc, why = market._fetch_json(url, cfg)
        if doc is None:
            return {"ok": False, "error": why, "items": []}
        rows = [r for r in (doc.get("items") or []) if isinstance(r, dict)][:lim]
        items = [i for i in (_claw_preview(r) for r in rows) if i]
        return {"ok": True, "source": src, "query": q, "items": items, "errors": []}
    url = "%s?limit=%d&search=%s" % (MCP_REGISTRY, lim, urllib.parse.quote(q))
    doc, why = market._fetch_json(url, cfg)
    if doc is None:
        return {"ok": False, "error": why, "items": []}
    items, errors = [], []
    for row in (doc.get("servers") or [])[:lim]:
        if not _is_latest(row) or str(_meta(row).get("status") or "active") != "active":
            continue
        item = _map_server(row)
        if item:
            item["online"] = True
            items.append(item)
    return {"ok": True, "source": src, "query": q, "items": items, "errors": errors}


def _upsert(source, item, cfg):
    """Write ONE item into that source's group (used by import-one)."""
    groups = dict(_read_imported())
    group = groups.get(source) if isinstance(groups.get(source), dict) else {}
    rows = [r for r in (group.get("items") or [])
            if isinstance(r, dict) and r.get("id") != item["id"]]
    rows.append(item)
    groups[source] = {"at": group.get("at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "items": rows}
    return _write_imported(groups)


def import_one(source, slug, cfg=None):
    """Pin ONE remote row and install it — the same path as any other install."""
    cfg = cfg or market._config()
    src = str(source or "")
    slug = str(slug or "").strip()
    if src not in SOURCES or not slug:
        return {"ok": False, "error": "source and slug are required"}
    item = None
    if src == "clawhub":
        url = "%s/skills?limit=20&search=%s" % (CLAWHUB, urllib.parse.quote(slug))
        doc, why = market._fetch_json(url, cfg)
        if doc is None:
            return {"ok": False, "error": why}
        row = next((r for r in (doc.get("items") or [])
                    if isinstance(r, dict) and str(r.get("slug")) == slug), None)
        if row is None:
            return {"ok": False, "error": "not found upstream: %s" % slug}
        item, why = _claw_item(row, cfg)
        if item is None:
            return {"ok": False, "error": why}
    else:
        url = "%s?limit=20&search=%s" % (MCP_REGISTRY, urllib.parse.quote(slug))
        doc, why = market._fetch_json(url, cfg)
        if doc is None:
            return {"ok": False, "error": why}
        for row in (doc.get("servers") or []):
            srv = row.get("server") or {}
            if str(srv.get("name")) == slug and _is_latest(row):
                item = _map_server(row)
                break
        if item is None:
            return {"ok": False, "error": "not found upstream: %s" % slug}
    path = _upsert(src, item, cfg)
    res = market.install(item["id"])
    ok, already = bool(res.get("ok")), False
    if not ok and "already exists" in str(res.get("error") or ""):
        # Importing a row that is already installed is idempotent, not a failure.
        ok, already = True, True
    return {"ok": ok, "id": item["id"], "path": path, "already": already,
            "install": res}
