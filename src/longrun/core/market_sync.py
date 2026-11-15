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

import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

from longrun.core import market
from longrun.util import fswrite, paths

MCP_REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"
CLAWHUB = "https://clawhub.ai/api/v1"
PAGE = 100
MAX_LIMIT = 500
DESC_MAX = 300
_SLUG = re.compile(r"[^a-z0-9._-]+")


def sources():
    """The adapters this build ships, with the host each one needs allowed."""
    return [
        {"id": "mcp-registry", "label": "MCP Registry (official)",
         "host": "registry.modelcontextprotocol.io",
         "kinds": ["mcp", "connector"],
         "note": "Every published MCP server; stdio packages and remotes."},
        {"id": "clawhub", "label": "ClawHub (OpenClaw skills)",
         "host": "clawhub.ai", "kinds": ["skill"],
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
    try:
        with open(_imported_path(), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return {}
    rows = doc.get("sources") if isinstance(doc, dict) else None
    return rows if isinstance(rows, dict) else {}


def _write_imported(groups):
    payload = {"schema": market.SCHEMA, "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "sources": groups}
    fswrite.write_json(_imported_path(), payload)
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
    item = {
        "id": ("connector/" if keys else "mcp/") + slug,
        "kind": kind,
        "name": slug,
        "title": str(srv.get("title") or name),
        "description": str(srv.get("description") or "")[:DESC_MAX],
        "category": "MCP Registry",
        "featured": False,
        "version": str(srv.get("version") or ""),
        "publisher": str(name.split("/")[0] if "/" in name else ""),
        "server": server,
    }
    if keys:
        item["keys"] = keys
    return item


def _is_latest(row):
    meta = (row.get("_meta") or {}).get("io.modelcontextprotocol.registry/official") or {}
    return bool(meta.get("isLatest", True))


def sync_mcp_registry(limit=200, query="", cfg=None):
    """Read the official registry (latest versions only) and map every entry."""
    cfg = cfg or market._config()
    limit = max(1, min(int(limit or 200), MAX_LIMIT))
    items, errors, seen = [], [], set()
    cursor, pages = "", 0
    while len(items) < limit and pages < max(1, (limit // PAGE) + 2):
        params = {"limit": min(PAGE, limit)}
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
        for row in rows:
            if not _is_latest(row):
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
            if len(items) >= limit:
                break
        cursor = str((doc.get("metadata") or {}).get("nextCursor") or "")
        pages += 1
        if not cursor:
            break
    return items, errors


# ── ClawHub ───────────────────────────────────────────────────────────────────

def _claw_item(row, cfg):
    """One ClawHub row → `(item, error)`; its ZIP is downloaded once to pin it.

    The download is the slow part (one GET per skill), so callers run these in
    parallel — a serial sync measured 65.7 s for 24 skills on 2026-11-15.
    """
    slug = _slug(row.get("slug"))
    latest = row.get("latestVersion") or {}
    version = str(latest.get("version") or "")
    if not row.get("slug") or not version:
        return None, "skipped (no slug/version)"
    dl = "%s/download?slug=%s&version=%s" % (CLAWHUB, row["slug"], version)
    data, why = market._fetch(dl, cfg, market.MAX_ITEM_BYTES)
    if data is None:
        return None, "%s: %s" % (row["slug"], why)
    return {
        "id": "skill/" + slug, "kind": "skill", "name": slug,
        "title": str(row.get("displayName") or row.get("slug")),
        "description": str(row.get("summary") or "")[:DESC_MAX],
        "category": "ClawHub",
        "featured": bool((row.get("stats") or {}).get("downloads", 0) > 1000),
        "version": version,
        "publisher": str(row.get("ownerHandle") or ""),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "source": {"type": "https", "url": dl},
    }, ""


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


def sync(source, limit=None, query="", cfg=None):
    """Fetch one source and REPLACE that source's group in imported.json."""
    fn = SOURCES.get(str(source or ""))
    if fn is None:
        return {"ok": False, "error": "unknown source: %s (try %s)"
                % (source, ", ".join(sorted(SOURCES)))}
    items, errors = fn(limit if limit is not None else (200 if source == "mcp-registry" else 25),
                       query, cfg)
    groups = _read_imported()
    groups[source] = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "items": items}
    path = _write_imported(groups)
    return {"ok": True, "source": source, "items": len(items),
            "errors": errors[:8], "error_count": len(errors), "path": path,
            "catalog": market.search(limit=1)["stats"]}
