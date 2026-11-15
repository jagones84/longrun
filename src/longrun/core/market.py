"""Marketplace catalogue for skills, MCP servers, plugins, connectors and Matrix modules.

The catalogue is DATA, never code: one JSON document per source, merged by item
`id`. A **skill**, **matrix** or **plugin** entry is installable only when its
artifacts are pinned; an install whose bytes do not hash to the declared `sha256`
is refused by name before anything is written. An **mcp** or **connector** entry
is installable when it carries a `server` block (it is a config preset, not an
artifact).

The five kinds are five different things, and the names say which:

  * **plugin** — a CONTAINER of members (`skill`, `mcp`, `connector`). It writes
    nothing itself: every member is delegated to the installer that owns it, and
    a failure undoes only what this call created.
  * **skill** — instructions (`SKILL.md`), installed by `memory.skills`.
  * **mcp** / **connector** — a config preset for an external server (a connector
    additionally names the keys it needs); it lands disabled.
  * **matrix** — an in-process Matrix artifact bundle (`core.matrix.apply_learning`),
    and the kind the modules that already ship in `src/Matrix/tools` are listed as.

Nothing here executes third-party code. An install delegates to the installer
that already owns the object — `memory.skills.install_zip` for a skill, the MCP
client document for a server/connector, `core.matrix.apply_learning` for a Matrix
bundle — so the marketplace adds a shelf, never a trust boundary.

`data/market/installed.json` is a RECORD of what was installed and verified; the
owning store stays authoritative. A record whose object no longer exists in its
owner (an MCP client deleted in Settings, a skill directory removed) is pruned on
the next read — measured 2026-11-15: deleting `filesystem` in Settings ▸ MCP left
the Marketplace advertising it as "installed". `audit()` still reports the drift a
probe cannot decide (plugin, unknown kind).
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request

import yaml

from longrun.util import paths, fswrite

SCHEMA = "longrun.market/1"
KINDS = ("plugin", "skill", "mcp", "connector", "matrix")
# What a plugin may contain. Anything else (command, rule, hook, code) is refused
# by name: those stores have no digest gate, so a bundle must not write them.
MEMBER_KINDS = ("skill", "mcp", "connector")
MAX_MEMBERS = 32
DEFAULTS = {
    "catalogs": [],
    "allow_hosts": [],
    "cache_ttl": 3600,
    "featured_limit": 6,
    "stale_days": 7,
    # 0 = import every published registry server; a number caps the mirror.
    "registry_max": 0,
    # Safety bound on a single registry pass (100 rows per page upstream).
    "max_sync_pages": 600,
    # How many online search results the page may show at once (max 100).
    "remote_search_limit": 50,
}
MAX_CATALOG_BYTES = 4 * 1024 * 1024
MAX_ITEM_BYTES = 32 * 1024 * 1024
TIMEOUT = 20
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

_cache = {"sig": None, "cfg": None}


# ── paths ─────────────────────────────────────────────────────────────────────

CONFIG_PATH = os.path.join(paths.REPO_ROOT, "config", "market.yaml")


def _config_path():
    """`<repo>/config/market.yaml` — beside every other operator config file."""
    return CONFIG_PATH


def _market_dir():
    d = os.path.join(paths.DATA_DIR, "market")
    os.makedirs(d, exist_ok=True)
    return d


def _local_catalog_path():
    return os.path.join(_market_dir(), "catalog.json")


def _bundled_catalog_path():
    """The catalogue that SHIPS with the code (tracked, beside this module)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_catalog.json")


def _repo_file(rel):
    """`<repo>/rel` when it really stays inside the repository, else None."""
    rel = str(rel or "").replace("\\", "/").lstrip("/")
    root = os.path.realpath(paths.REPO_ROOT)
    path = os.path.realpath(os.path.join(root, rel))
    if not rel or not (path == root or path.startswith(root + os.sep)):
        return None
    return path


def _read_doc_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None
    if isinstance(doc, list):
        doc = {"schema": SCHEMA, "items": doc}
    return doc if isinstance(doc, dict) else None


def _bundled_matrix():
    """The Matrix tool modules that ship with longrun, listed as PRESENT `matrix` rows.

    A `matrix` row is an in-process module: it is already hot-loaded, so the card
    reports it as present instead of offering an install that cannot happen. The
    `plugin` kind is the container (skills + MCP servers), never a module.
    """
    root = os.path.join(paths.REPO_ROOT, "src", "Matrix", "tools")
    out = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for fn in names:
        if not fn.endswith(".py") or fn == "__init__.py":
            continue
        desc = ""
        try:
            with open(os.path.join(root, fn), encoding="utf-8", errors="replace") as f:
                head = f.read(4000)
            m = re.search(r'^\s*(?:"""|\'\'\')\s*(.+)$', head, re.M)
            if m:
                desc = m.group(1).strip().rstrip('"\'')
        except OSError:
            pass
        stem = fn[:-3]
        out.append({"id": "matrix/" + stem, "kind": "matrix", "name": stem,
                    "title": stem.replace("_", " ").title(),
                    "description": desc or "Matrix tool shipped with longrun",
                    "category": "Matrix tools", "publisher": "longrun", "version": ""})
    return out


def _installed_path():
    return os.path.join(_market_dir(), "installed.json")


def _cache_dir():
    d = os.path.join(_market_dir(), "cache")
    os.makedirs(d, exist_ok=True)
    return d


# ── config ────────────────────────────────────────────────────────────────────

def _config():
    """`config/market.yaml` with defaults, memoised on (mtime, size)."""
    path = _config_path()
    try:
        st = os.stat(path)
        sig = (path, st.st_mtime, st.st_size)
    except OSError:
        sig = (path, None, None)
    if _cache["sig"] == sig and _cache["cfg"] is not None:
        return _cache["cfg"]
    cfg = dict(DEFAULTS)
    if sig[1] is not None:
        try:
            with open(path, encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
            if isinstance(doc, dict):
                for key in DEFAULTS:
                    if key in doc and doc[key] is not None:
                        cfg[key] = doc[key]
        except (OSError, yaml.YAMLError):
            pass  # a broken file must not take the panel down
    cfg["catalogs"] = [str(u) for u in (cfg.get("catalogs") or []) if str(u).strip()]
    cfg["allow_hosts"] = [str(h).strip().lower()
                          for h in (cfg.get("allow_hosts") or []) if str(h).strip()]
    try:
        cfg["cache_ttl"] = max(0, int(cfg.get("cache_ttl") or 0))
    except (TypeError, ValueError):
        cfg["cache_ttl"] = DEFAULTS["cache_ttl"]
    try:
        cfg["featured_limit"] = max(1, int(cfg.get("featured_limit") or 6))
    except (TypeError, ValueError):
        cfg["featured_limit"] = DEFAULTS["featured_limit"]
    try:
        cfg["stale_days"] = max(0, int(cfg.get("stale_days") or 0))
    except (TypeError, ValueError):
        cfg["stale_days"] = DEFAULTS["stale_days"]
    _cache.update(sig=sig, cfg=cfg)
    return cfg


def config_view():
    """The catalogue sources in force — names only, never a credential."""
    cfg = _config()
    return {"catalogs": list(cfg["catalogs"]), "allow_hosts": list(cfg["allow_hosts"]),
            "cache_ttl": cfg["cache_ttl"], "featured_limit": cfg["featured_limit"],
            "stale_days": cfg["stale_days"], "registry_max": cfg.get("registry_max", 0),
            "max_sync_pages": cfg.get("max_sync_pages", 600),
            "remote_search_limit": cfg.get("remote_search_limit", 50)}


def origin_label(origin):
    """The ONE human label for a catalogue origin (`local`, `bundled`, `imported:x`…).

    Provenance is one value everywhere: the Marketplace card, the Manage row, the
    Settings panels and the audit all call this, so a source is never named twice
    in two vocabularies.
    """
    o = str(origin or "").strip()
    fixed = {"local": "Your catalogue", "bundled": "Bundled",
             "matrix": "Bundled (Matrix)", "unknown": "Unknown", "": "Unknown"}
    if o in fixed:
        return fixed[o]
    if o.startswith("imported:"):
        src = o.split(":", 1)[1]
        named = {"mcp-registry": "MCP Registry", "clawhub": "ClawHub"}
        return named.get(src, src.replace("-", " ").title() or "Imported")
    if o.startswith("http://") or o.startswith("https://"):
        try:
            return urllib.parse.urlsplit(o).hostname or o
        except ValueError:
            return o
    return o


# ── fetch (https + allow-list only) ───────────────────────────────────────────

def _host_allowed(url, allow):
    try:
        parts = urllib.parse.urlsplit(str(url))
    except ValueError:
        return False, "unparseable url"
    if parts.scheme != "https":
        return False, "https required"
    host = (parts.hostname or "").lower()
    if not host:
        return False, "no host"
    for pattern in allow or []:
        if host == pattern or fnmatch.fnmatch(host, pattern):
            return True, ""
    return False, "host %r is not in market.allow_hosts" % host


def _fetch(url, cfg, limit):
    """Bytes from `url`, https and allow-listed, re-checked after a redirect."""
    ok, why = _host_allowed(url, cfg["allow_hosts"])
    if not ok:
        return None, why
    req = urllib.request.Request(str(url), headers={"User-Agent": "longrun-market/1"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 — https enforced above
            final = resp.geturl()
            ok, why = _host_allowed(final, cfg["allow_hosts"])
            if not ok:
                return None, "redirect refused: %s" % why
            data = resp.read(limit + 1)
    except Exception as e:  # noqa: BLE001 — every network failure is a named error here
        return None, "fetch failed: %s" % e
    if len(data) > limit:
        return None, "payload exceeds %d bytes" % limit
    return data, ""


def _fetch_json(url, cfg):
    """A catalogue document, cached on disk for `cache_ttl` seconds."""
    key = hashlib.sha256(str(url).encode("utf-8")).hexdigest()[:32]
    cache_path = os.path.join(_cache_dir(), key + ".json")
    ttl = cfg["cache_ttl"]
    if ttl:
        try:
            st = os.stat(cache_path)
            if (time.time() - st.st_mtime) <= ttl:
                with open(cache_path, encoding="utf-8") as f:
                    return json.load(f), ""
        except (OSError, ValueError):
            pass
    data, why = _fetch(url, cfg, MAX_CATALOG_BYTES)
    if data is None:
        return None, why
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        return None, "not JSON: %s" % e
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
    except OSError:
        pass
    return doc, ""


# ── entries ───────────────────────────────────────────────────────────────────

def _member(raw):
    """One plugin member, normalised like an item. `None` only when it is malformed.

    An UNKNOWN kind is kept, not dropped: `_bundle_plan` must be able to refuse it
    by name ("unsupported member kind: command") instead of silently installing a
    container with fewer members than the catalogue declared.
    """
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip().lower()
    name = str(raw.get("name") or "").strip()
    if not kind or not _SLUG.match(name):
        return None
    src = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    server = raw.get("server") if isinstance(raw.get("server"), dict) else None
    return {"kind": kind,
            "name": name,
            "title": str(raw.get("title") or name).strip(),
            "sha256": str(raw.get("sha256") or "").strip().lower(),
            "source": {"type": str(src.get("type") or ""),
                       "url": str(src.get("url") or ""),
                       "path": str(src.get("path") or "")},
            "server": server,
            "keys": [str(k) for k in (raw.get("keys") or []) if str(k).strip()]}


def _member_installable(member):
    """A member is installable by the SAME rule its own kind is; an unknown kind never is."""
    if member["kind"] not in MEMBER_KINDS:
        return False
    if member["kind"] == "skill":
        src = member["source"]
        if src["type"] == "dir":
            # An imported package: the directory is readable AND the digest is pinned.
            return (bool(member["sha256"]) and bool(src["path"]) and os.path.isdir(src["path"])
                    and os.path.isfile(os.path.join(src["path"], "SKILL.md")))
        bundled = src["type"] == "bundled" and bool(src["path"])
        return bool(member["sha256"]) and (bool(src["url"]) or bundled)
    srv = member.get("server") or {}
    return bool(srv.get("command") or srv.get("url"))


def _normalize(raw, origin):
    if not isinstance(raw, dict):
        return None
    rid = str(raw.get("id") or "").strip()
    kind = str(raw.get("kind") or "").strip().lower()
    if not _SLUG.match(rid.replace("/", ".")) or kind not in KINDS:
        return None
    name = str(raw.get("name") or rid.split("/")[-1]).strip()
    if not _SLUG.match(name):
        return None
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    server = raw.get("server") if isinstance(raw.get("server"), dict) else None
    sha = str(raw.get("sha256") or "").strip().lower()
    declared = raw.get("members") if isinstance(raw.get("members"), list) else []
    members = [m for m in (_member(r) for r in declared[:MAX_MEMBERS]) if m]
    item = {
        "id": rid,
        "kind": kind,
        "name": name,
        "title": str(raw.get("title") or name),
        "description": str(raw.get("description") or ""),
        "category": str(raw.get("category") or "Uncategorised"),
        # The publisher's own label, when it had one, kept for the tooltip only:
        # the chip/filter always uses `category` (the curated macro-area).
        "upstream_category": str(raw.get("upstream_category") or ""),
        "featured": bool(raw.get("featured")),
        "version": str(raw.get("version") or ""),
        "publisher": str(raw.get("publisher") or ""),
        # Optional upstream metadata a sync may carry (never invented here).
        "updated": str(raw.get("updated") or ""),
        "status": str(raw.get("status") or ""),
        "license": str(raw.get("license") or ""),
        "downloads": raw.get("downloads") if isinstance(raw.get("downloads"), int) else None,
        "sha256": sha,
        "bytes": raw.get("bytes") if isinstance(raw.get("bytes"), int) else None,
        "source": {"type": str(source.get("type") or ""),
                   "url": str(source.get("url") or ""),
                   "path": str(source.get("path") or "")},
        "server": server,
        "keys": [str(k) for k in (raw.get("keys") or []) if str(k).strip()],
        "bundle": raw.get("bundle") if isinstance(raw.get("bundle"), list) else None,
        # A plugin is a CONTAINER: `members` is what it will install, in order.
        "members": members,
        "members_declared": len(declared),
        "requires": raw.get("requires") if isinstance(raw.get("requires"), dict) else {},
        "origin": str(origin),
        "present": False,
    }
    bundled = item["source"]["type"] == "bundled" and bool(item["source"]["path"])
    local_dir = item["source"]["type"] == "dir" and bool(item["source"]["path"])
    pinned = bool(item["sha256"]) and (bool(item["source"]["url"]) or bundled or local_dir)
    if kind == "skill":
        item["installable"] = pinned
    elif kind == "matrix":
        # The code artifact is the digest-pinned one AND it must carry a bundle.
        item["installable"] = pinned and bool(item["bundle"])
    elif kind == "plugin":
        # Installable only when EVERY declared member is (a malformed or unpinned
        # member makes the whole container refuse, never install half of it).
        item["installable"] = bool(members) and all(
            _member_installable(m) for m in members)
    else:  # mcp / connector: a config preset, no artifact bytes to hash
        item["installable"] = bool(server) and bool(server.get("command") or server.get("url"))
    return item


def load_sources():
    """`(cfg, docs, errors)` — operator file, then the shipped catalogue, then URLs.

    Precedence is deliberate: the operator's `data/market/catalog.json` WINS over the
    bundled one (an override needs no code change), and a remote catalogue can only
    add ids the first two do not define.
    """
    cfg = _config()
    docs, errors = [], []
    local = _read_doc_file(_local_catalog_path())
    if local is not None:
        docs.append((local, "local"))
    bundled = _read_doc_file(_bundled_catalog_path())
    if bundled is not None:
        docs.append((bundled, "bundled"))
    # Imported marketplaces sit AFTER the bundled catalogue: a curated entry keeps
    # its place, and a sync can only add what nothing else defines. Lazy import —
    # market_sync imports this module.
    try:
        from longrun.core import market_sync as _sync
        groups = _sync._read_imported()
    except Exception:  # noqa: BLE001 — a broken sync store must not hide the shelf
        groups = {}
    for src, group in (groups or {}).items():
        rows = (group or {}).get("items") if isinstance(group, dict) else None
        if isinstance(rows, list):
            docs.append(({"schema": SCHEMA, "items": rows}, "imported:%s" % src))
    for url in cfg["catalogs"]:
        doc, why = _fetch_json(url, cfg)
        if doc is None:
            errors.append("%s: %s" % (url, why))
            continue
        if not isinstance(doc, dict):
            errors.append("%s: not a catalogue document" % url)
            continue
        docs.append((doc, url))
    return cfg, docs, errors


def catalog():
    """`(items, errors, stats)` — merged by id, local wins, first source wins."""
    cfg, docs, errors = load_sources()
    seen, items = {}, []
    for doc, origin in docs:
        rows = doc.get("items")
        if not isinstance(rows, list):
            errors.append("%s: `items` is not a list" % origin)
            continue
        for raw in rows:
            item = _normalize(raw, origin)
            if item is None:
                continue
            if item["id"] in seen:
                seen[item["id"]]["duplicates"] = int(seen[item["id"]].get("duplicates", 0)) + 1
                continue
            seen[item["id"]] = item
            items.append(item)
    # The Matrix modules that ship with longrun are listed as PRESENT `matrix`
    # rows: they are already hot-loaded, so pretending they are installable would
    # be a lie. No remote catalogue publishes them.
    for raw in _bundled_matrix():
        if raw["id"] in seen:
            continue
        item = _normalize(raw, "matrix")
        if item is None:
            continue
        item["present"] = True
        seen[item["id"]] = item
        items.append(item)
    stats = {"sources": len(docs), "items": len(items),
             "installable": sum(1 for i in items if i["installable"]),
             "present": sum(1 for i in items if i["present"])}
    return items, errors, stats


def categories(items=None):
    if items is None:
        items, _, _ = catalog()
    out = []
    for item in items:
        if item["category"] not in out:
            out.append(item["category"])
    return sorted(out)


def _taxonomy_order(names):
    """Chips in the curated order first, then any extra category alphabetically."""
    from longrun.core import market_taxonomy
    areas = market_taxonomy.areas()
    head = [a for a in areas if a in names]
    tail = sorted(n for n in names if n not in areas)
    return head + tail


def search(q="", kind=None, category=None, featured=False, limit=60,
           source=None, offset=0):
    """Filtered catalogue page.

    `source` matches an item's ORIGIN (`bundled`, `imported:mcp-registry`,
    `imported:clawhub`, `local`, a catalogue URL); a value ending in ":" is a
    prefix, so `imported:` covers every adapter. `categories` and
    `category_counts` are computed for the CURRENT kind/source/search scope and
    BEFORE the category filter, so a chip that would return nothing is not shown.
    """
    items, errors, stats = catalog()
    q = str(q or "").strip().lower()
    src = str(source or "").strip().lower()
    if kind:
        items = [i for i in items if i["kind"] == kind]
    if src:
        items = [i for i in items
                 if (i.get("origin", "").lower().startswith(src) if src.endswith(":")
                     else i.get("origin", "").lower() == src)]
    if featured:
        items = [i for i in items if i["featured"]]
    if q:
        items = [i for i in items
                 if q in i["id"].lower() or q in i["name"].lower()
                 or q in i["title"].lower() or q in i["description"].lower()]
    scoped = categories(items)
    counts = {}
    for i in items:
        counts[i["category"]] = counts.get(i["category"], 0) + 1
    if category:
        items = [i for i in items if i["category"].lower() == str(category).lower()]
    stats = dict(stats)
    stats["matched"] = len(items)
    stats["category_counts"] = counts
    stats["by_kind"] = {}
    for i in items:
        stats["by_kind"][i["kind"]] = stats["by_kind"].get(i["kind"], 0) + 1
    start = max(0, int(offset or 0))
    page = items[start:start + max(1, int(limit))]
    page = [dict(i, origin_label=origin_label(i.get("origin"))) for i in page]
    from longrun.core import market_taxonomy
    return {"ok": True, "items": page, "categories": _taxonomy_order(scoped),
            "errors": errors, "stats": stats, "config": config_view(),
            "taxonomy": market_taxonomy.areas()}


# ── installed record ──────────────────────────────────────────────────────────

def _read_installed():
    try:
        with open(_installed_path(), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return []
    return [r for r in doc if isinstance(r, dict) and r.get("id")] if isinstance(doc, list) else []


def _write_installed(rows):
    fswrite.write_json(_installed_path(), rows)


def _record(item, target, members=None):
    rows = [r for r in _read_installed() if r.get("id") != item["id"]]
    rec = {
        "id": item["id"], "kind": item["kind"], "name": item["name"],
        "version": item["version"], "sha256": item["sha256"],
        "publisher": item["publisher"], "source": item["source"].get("url") or "",
        # Provenance: WHICH catalogue the entry came from (see origin_label()).
        # It is recorded here, at install time, because the catalogue that named
        # the item can be re-synced or removed later.
        "origin": str(item.get("origin") or ""), "category": str(item.get("category") or ""),
        "installed": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "enabled": item["kind"] not in ("mcp", "connector"),
        "target": target or "",
    }
    if members:
        # A plugin's members ARE its installation: per-member target and whether
        # this install created it (an uninstall never removes a pre-existing one).
        rec["members"] = [{"kind": m.get("kind"), "name": m.get("name"),
                           "target": m.get("target") or "",
                           "created": bool(m.get("created")),
                           "enabled": bool(m.get("enabled", True))} for m in members]
    rows.append(rec)
    rows.sort(key=lambda r: (r.get("kind", ""), r.get("id", "")))
    _write_installed(rows)


def _owner_state(rec, clients, clients_readable):
    """`live` / `gone` / `unknown` for one record against its OWNING store.

    The record is written at install time; the owner is the live truth (the MCP
    client config, the skills tree). A `gone` answer means the object was deleted
    somewhere else and the Marketplace must stop advertising it. `unknown` is
    never pruned: a probe that cannot read the owner must not erase a record.
    """
    kind = str(rec.get("kind") or "")
    if kind == "skill":
        target = str(rec.get("target") or "")
        if not target:
            return "unknown"
        return "live" if os.path.isdir(target) else "gone"
    if kind in ("mcp", "connector"):
        if not clients_readable:
            return "unknown"
        return "live" if str(rec.get("name") or "") in clients else "gone"
    if kind == "plugin":
        members = rec.get("members") or []
        if not members:
            return "unknown"
        live = False
        for member in members:
            if str(member.get("kind") or "") != "skill" and not clients_readable:
                return "unknown"
            if _member_present(member, clients):
                live = True
        return "live" if live else "gone"
    return "unknown"  # matrix / unknown kind: no live probe, never a guess


def _live_clients():
    """`(clients, readable)` — the MCP client document, and whether it was read."""
    try:
        from longrun.interop import mcp_client
        return (mcp_client.load_doc().get("clients") or {}), True
    except Exception:  # noqa: BLE001 — an unreadable owner must not prune anything
        return {}, False


def installed():
    items, _, _ = catalog()
    by_id = {i["id"]: i for i in items}
    clients, readable = _live_clients()
    records = _read_installed()
    kept, dropped = [], 0
    for rec in records:
        if _owner_state(rec, clients, readable) == "gone":
            dropped += 1
            continue
        kept.append(rec)
    if dropped:
        # Prune once, atomically. ONE read reconciles every panel: a client deleted
        # in Settings ▸ MCP, a skill folder removed by hand, an uninstall from the
        # API — none of them may leave the badge behind.
        try:
            _write_installed(kept)
        except Exception:  # noqa: BLE001 — a failed prune must never break a read
            pass
    rows = []
    for rec in kept:
        live = by_id.get(rec["id"])
        row = dict(rec)
        # A record written before provenance was persisted is backfilled from the
        # live catalogue — the id still identifies the entry. Gone from every
        # catalogue and never recorded: "unknown", never a guess.
        row["origin"] = str(rec.get("origin") or (live or {}).get("origin") or "unknown")
        row["origin_label"] = origin_label(row["origin"])
        row["in_catalog"] = bool(live)
        row["update_available"] = bool(
            live and (live["version"] != rec.get("version")
                      or (live["sha256"] and live["sha256"] != rec.get("sha256"))))
        rows.append(row)
    return {"ok": True, "installed": rows, "count": len(rows), "pruned": dropped}


def installed_map():
    """`{name: {id, kind, origin, origin_label, installed, target}}` for the owners.

    The Settings panels list objects from THEIR store (skills on disk, MCP clients
    in the config). This is the one join to the marketplace RECORD, so a panel can
    say where an object came from without a second lookup or a copied field.
    """
    out = {}
    for rec in installed()["installed"]:
        name = str(rec.get("name") or "")
        if name:
            out[name] = {"id": rec.get("id"), "kind": rec.get("kind"),
                         "origin": rec.get("origin"), "origin_label": rec.get("origin_label"),
                         "installed": rec.get("installed"), "target": rec.get("target") or ""}
    return out


def forget(item_id, remove_target=False):
    rows = _read_installed()
    rec = next((r for r in rows if r.get("id") == item_id), None)
    if rec is None:
        return {"ok": False, "error": "not installed: %s" % item_id}
    removed = False
    if remove_target and rec.get("kind") == "plugin":
        # A plugin is uninstalled member by member, and only the members this
        # install created: a skill or server that was already there stays.
        _undo_members(rec.get("members") or [])
        removed = True
    elif remove_target and rec.get("target"):
        import shutil
        from longrun.memory import skills as _skills
        raw = str(rec["target"])
        target = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(paths.REPO_ROOT, raw))
        # `memory.skills` owns WHERE skills live (LONGRUN_SKILLS_DIR included), so the
        # guard asks it rather than assuming the repository root. Only a skill
        # DIRECTORY below that root — one that still holds a SKILL.md — may go.
        skills_root = os.path.realpath(_skills.SKILLS_DIR)
        if (target != skills_root and target.startswith(skills_root + os.sep)
                and os.path.isfile(os.path.join(target, "SKILL.md"))):
            shutil.rmtree(target, ignore_errors=True)
            removed = not os.path.exists(target)
        elif rec.get("kind") == "skill" and rec.get("name"):
            _skills.remove(rec["name"])
            removed = True
    _write_installed([r for r in rows if r.get("id") != item_id])
    return {"ok": True, "id": item_id, "removed_files": removed}


def audit():
    """Installed rows against their owner. Reports drift; never repairs it."""
    from longrun.interop import mcp_client
    clients = (mcp_client.load_doc().get("clients") or {})
    out = []
    for rec in installed()["installed"]:
        row = {"id": rec.get("id"), "kind": rec.get("kind"), "owner": "", "state": "ok",
               "detail": "", "origin": rec.get("origin") or "",
               "origin_label": rec.get("origin_label") or "Unknown"}
        kind = rec.get("kind")
        if kind == "skill":
            row["owner"] = "memory.skills"
            if not rec.get("target") or not os.path.isdir(str(rec["target"])):
                row.update(state="missing", detail="skill directory is gone")
        elif kind in ("mcp", "connector"):
            row["owner"] = "mcp_clients.local.json"
            if rec.get("name") not in clients:
                row.update(state="missing", detail="client is no longer configured")
            elif not clients[rec["name"]].get("enabled"):
                row.update(state="disabled", detail="client installed but not enabled")
        elif kind == "plugin":
            members = rec.get("members") or []
            if not members:
                # A record written before plugins became containers: it named a
                # Matrix bundle, whose owner cannot be probed from here.
                row["owner"] = "core.matrix"
                row.update(detail="legacy record without members — owner not probed")
            else:
                row["owner"] = "members"
                missing = [m.get("name") for m in members if not _member_present(m, clients)]
                if missing:
                    row.update(state="missing",
                               detail="missing member(s): %s" % ", ".join(str(n) for n in missing))
                else:
                    row.update(detail="%d members live" % len(members))
        elif kind == "matrix":
            row["owner"] = "core.matrix"
            row.update(detail="owner not probed")
        else:
            row.update(state="unknown", detail="unknown kind")
        out.append(row)
    drift = sum(1 for r in out if r["state"] in ("missing", "unknown"))
    return {"ok": True, "rows": out, "drift": drift}


# ── install ───────────────────────────────────────────────────────────────────

def _install_skill(item, cfg, overwrite):
    sha = item["sha256"]
    if not sha:
        return {"ok": False, "error": "item has no sha256 — not installable"}
    src = item["source"] or {}
    if str(src.get("type") or "") == "dir":
        # An imported package: the bytes come from a local skill directory, zipped
        # deterministically so the pinned digest still gates the install.
        from longrun.core import market_plugins
        try:
            data = market_plugins.dir_zip(src.get("path"))
        except ValueError as e:
            return {"ok": False, "error": "dir source: %s" % e}
    elif str(src.get("type") or "") == "bundled":
        # A bundled artifact lives INSIDE this repository, so the repository is the
        # trust boundary; the digest still proves the bytes are the ones the
        # catalogue names (a local edit to the file is caught here).
        rel = src.get("path") or ""
        path = _repo_file(rel)
        if path is None:
            return {"ok": False, "error": "bundled path is outside the repository: %s" % rel}
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            return {"ok": False, "error": "bundled file unreadable: %s (%s)" % (rel, e)}
    else:
        url = src.get("url")
        if not url:
            return {"ok": False, "error": "item has no source.url"}
        data, why = _fetch(url, cfg, MAX_ITEM_BYTES)
        if data is None:
            return {"ok": False, "error": why}
    got = hashlib.sha256(data).hexdigest()
    if got != sha:
        return {"ok": False,
                "error": "digest mismatch for %s: expected %s, got %s" % (item["id"], sha, got)}
    from longrun.memory import skills
    if overwrite:
        skills.remove(item["name"])
    if str(src.get("type") or "") == "bundled":
        res = skills.install_skill_file("market", item["name"],
                                        data.decode("utf-8", errors="replace"))
        if res.get("error"):
            return {"ok": False, "error": res["error"]}
        return {"ok": True, "target": res.get("path") or ""}
    res = skills.install_zip(data, name=item["name"], overwrite=bool(overwrite))
    if res.get("error"):
        return {"ok": False, "error": res["error"]}
    return {"ok": True, "target": res.get("path") or res.get("dir") or ""}


def _install_server(item):
    server = item.get("server") or {}
    if not (server.get("command") or server.get("url")):
        return {"ok": False, "error": "item has no server.command or server.url"}
    from longrun.interop import mcp_client
    converted = mcp_client._servers_to_clients({item["name"]: server})
    if not converted:
        return {"ok": False, "error": "server block was rejected by the MCP client schema"}
    for spec in converted.values():
        spec["enabled"] = False  # an installed server is opt-in, exactly like a pasted one
    doc = mcp_client.load_doc()
    doc.setdefault("clients", {}).update(converted)
    path = mcp_client._save_local_doc(doc)
    return {"ok": True, "target": path, "enabled": False}


def _install_matrix(item):
    """A Matrix artifact bundle: in-process code, written by `core.matrix` only."""
    bundle = item.get("bundle")
    if not bundle:
        return {"ok": False, "error": "matrix item has no bundle"}
    from longrun.core import matrix
    res = matrix.apply_learning(bundle)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error") or "apply_learning refused the bundle"}
    return {"ok": True, "target": ",".join(res.get("installed") or [])}


def _bundle_plan(item):
    """`(members, reason)` — what a plugin would install, validated BEFORE any write."""
    declared = int(item.get("members_declared") or 0)
    members = item.get("members") or []
    if not declared:
        return [], "plugin has no members"
    if declared > MAX_MEMBERS:
        return [], "plugin has more than %d members" % MAX_MEMBERS
    if len(members) != declared:
        return [], ("a member is malformed (kind must be one of %s and name a slug)"
                    % ", ".join(MEMBER_KINDS))
    for member in members:
        if member["kind"] not in MEMBER_KINDS:
            return [], "unsupported member kind: %s (%s)" % (member["kind"], member["name"])
        if not _member_installable(member):
            return [], ("member %s (%s) is not installable: a skill needs sha256 and a source, "
                        "a server needs command or url" % (member["name"], member["kind"]))
    seen = set()
    for member in members:
        key = (member["kind"], member["name"])
        if key in seen:
            return [], "duplicate member: %s (%s)" % (member["name"], member["kind"])
        seen.add(key)
    return members, ""


def _member_present(member, clients):
    """Is this member still in the store that owns it?"""
    if str(member.get("kind") or "") == "skill":
        target = str(member.get("target") or "")
        return bool(target) and os.path.isdir(target)
    return str(member.get("name") or "") in clients


def _remove_skill_member(member):
    """Remove a skill THIS install created — by its own target, under the skills root."""
    import shutil
    from longrun.memory import skills as _skills
    target = str(member.get("target") or "")
    if target:
        root = os.path.realpath(_skills.SKILLS_DIR)
        real = os.path.realpath(target)
        # Same guard as `forget`: only a skill DIRECTORY below the skills root —
        # one that still holds a SKILL.md — may go. `skills.remove` looks in the
        # local category only, and a bundled skill lands under its own category.
        if (real != root and real.startswith(root + os.sep)
                and os.path.isfile(os.path.join(real, "SKILL.md"))):
            shutil.rmtree(real, ignore_errors=True)
            if not os.path.exists(real):
                _skills.list_skills(reload=True)
                return
    _skills.remove(member.get("name"))


def _undo_members(members):
    """Remove ONLY what this install created. A pre-existing object is never touched."""
    for member in reversed(members or []):
        if not member.get("created"):
            continue
        try:
            if member.get("kind") == "skill":
                _remove_skill_member(member)
            elif member.get("kind") in ("mcp", "connector"):
                from longrun.interop import mcp_client
                mcp_client.remove_client(member["name"])
        except Exception:  # noqa: BLE001 — an undo failure must not mask the reason
            pass


def _install_bundle(item, cfg, overwrite):
    """A plugin writes nothing itself: every member goes to the installer that owns it."""
    members, why = _bundle_plan(item)
    if not members:
        return {"ok": False, "error": why}
    from longrun.memory import skills as _skills
    from longrun.interop import mcp_client
    existing = {s.get("name"): (s.get("abspath") or s.get("path") or "")
                for s in _skills.list_skills(reload=True)}
    try:
        clients_before = dict(mcp_client.load_doc().get("clients") or {})
    except Exception:  # noqa: BLE001 — an unreadable owner is not a pre-existing member
        clients_before = {}
    done, failed = [], ""
    for member in members:
        name = member["name"]
        if member["kind"] == "skill":
            # An already-installed member is SATISFIED, never re-written: the
            # skill installer refuses to clobber, and a bundle must not fail
            # because the operator already had one of its parts.
            if name in existing and not overwrite:
                res = {"ok": True, "target": existing[name]}
            else:
                res = _install_skill(dict(member, id="skill/" + name), cfg, overwrite)
            created = name not in existing
        else:
            if name in clients_before and not overwrite:
                res = {"ok": True, "target": "",
                       "enabled": bool((clients_before.get(name) or {}).get("enabled", False))}
            else:
                res = _install_server(dict(member, id=member["kind"] + "/" + name))
            created = name not in clients_before
        if not res.get("ok"):
            failed = "member %s (%s): %s" % (name, member["kind"],
                                             res.get("error") or "install failed")
            break
        done.append({"kind": member["kind"], "name": name,
                     "target": res.get("target") or "", "created": bool(created),
                     "enabled": res.get("enabled", True)})
    if failed:
        _undo_members(done)
        return {"ok": False, "error": failed}
    return {"ok": True, "target": "%d members" % len(done), "members": done}


def _install_one(item, cfg, overwrite):
    """`(ok, payload, members)` for one entry — the ONE dispatch every install uses."""
    kind = item["kind"]
    if kind == "skill":
        return _install_skill(item, cfg, overwrite)
    if kind in ("mcp", "connector"):
        return _install_server(item)
    if kind == "plugin":
        return _install_bundle(item, cfg, overwrite)
    if kind == "matrix":
        return _install_matrix(item)
    return {"ok": False, "error": "unknown kind: %s" % kind}


def _run_install(item, overwrite=False):
    cfg = _config()
    res = _install_one(item, cfg, overwrite)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error") or "install failed", "id": item["id"]}
    _record(item, res.get("target"), res.get("members"))
    return {"ok": True, "id": item["id"], "kind": item["kind"], "name": item["name"],
            "target": res.get("target"), "sha256": item.get("sha256") or "",
            "members": res.get("members") or [],
            "enabled": res.get("enabled", True)}


def install(item_id, overwrite=False):
    """Install one catalogue item through its owning installer."""
    items, _, _ = catalog()
    item = next((i for i in items if i["id"] == item_id), None)
    if item is None:
        return {"ok": False, "error": "unknown item: %s" % item_id}
    return _run_install(item, overwrite)


def install_entry(item, overwrite=False):
    """Install an entry that did NOT come from a catalogue (an imported plugin).

    The same dispatch, the same digest gate, the same record: an import is not a
    second install path, it is a second SOURCE of entries.
    """
    item = dict(item)
    item.setdefault("id", "plugin/" + str(item.get("name") or "imported"))
    item.setdefault("origin", "")
    item.setdefault("version", "")
    item.setdefault("publisher", "")
    item.setdefault("source", {"type": "", "url": "", "path": ""})
    item.setdefault("members", None)
    item.setdefault("members_declared", 0)
    return _run_install(item, overwrite)
