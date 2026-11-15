"""Marketplace catalogue for skills, MCP servers, plugins and connectors.

The catalogue is DATA, never code: one JSON document per source, merged by item
`id`. A **skill** or **plugin** entry is installable only when it carries a
`sha256`; an install whose bytes do not hash to that value is refused by name
before anything is written. An **mcp** or **connector** entry is installable
when it carries a `server` block (it is a config preset, not an artifact).

Nothing here executes third-party code. An install delegates to the installer
that already owns the object — `memory.skills.install_zip` for a skill, the MCP
client document for a server/connector, `core.matrix.apply_learning` for a
Matrix plugin bundle — so the marketplace adds a shelf, never a trust boundary.

`data/market/installed.json` is a RECORD of what was installed and verified; the
owning store stays authoritative and `audit()` reports drift instead of repairing
it.
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
KINDS = ("skill", "mcp", "plugin", "connector")
DEFAULTS = {
    "catalogs": [],
    "allow_hosts": [],
    "cache_ttl": 3600,
    "featured_limit": 6,
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


def _bundled_plugins():
    """The Matrix tools that ship with longrun, listed as PRESENT plugins.

    A plugin here is a Matrix tool module: it is already hot-loaded, so the card
    reports it as installed instead of offering an install that cannot happen.
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
        out.append({"id": "plugin/" + stem, "kind": "plugin", "name": stem,
                    "title": stem.replace("_", " ").title(),
                    "description": desc or "Matrix plugin shipped with longrun",
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
    _cache.update(sig=sig, cfg=cfg)
    return cfg


def config_view():
    """The catalogue sources in force — names only, never a credential."""
    cfg = _config()
    return {"catalogs": list(cfg["catalogs"]), "allow_hosts": list(cfg["allow_hosts"]),
            "cache_ttl": cfg["cache_ttl"], "featured_limit": cfg["featured_limit"]}


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
    item = {
        "id": rid,
        "kind": kind,
        "name": name,
        "title": str(raw.get("title") or name),
        "description": str(raw.get("description") or ""),
        "category": str(raw.get("category") or "Uncategorised"),
        "featured": bool(raw.get("featured")),
        "version": str(raw.get("version") or ""),
        "publisher": str(raw.get("publisher") or ""),
        "sha256": sha,
        "bytes": raw.get("bytes") if isinstance(raw.get("bytes"), int) else None,
        "source": {"type": str(source.get("type") or ""),
                   "url": str(source.get("url") or ""),
                   "path": str(source.get("path") or "")},
        "server": server,
        "keys": [str(k) for k in (raw.get("keys") or []) if str(k).strip()],
        "bundle": raw.get("bundle") if isinstance(raw.get("bundle"), list) else None,
        "requires": raw.get("requires") if isinstance(raw.get("requires"), dict) else {},
        "origin": str(origin),
        "present": False,
    }
    if kind in ("skill", "plugin"):
        bundled = item["source"]["type"] == "bundled" and bool(item["source"]["path"])
        item["installable"] = bool(item["sha256"]) and (bool(item["source"]["url"]) or bundled)
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
    # The Matrix plugins that ship with longrun are listed as PRESENT: they are
    # already hot-loaded, so pretending they are installable would be a lie.
    for raw in _bundled_plugins():
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


def search(q="", kind=None, category=None, featured=False, limit=60):
    items, errors, stats = catalog()
    q = str(q or "").strip().lower()
    if kind:
        items = [i for i in items if i["kind"] == kind]
    if category:
        items = [i for i in items if i["category"].lower() == str(category).lower()]
    if featured:
        items = [i for i in items if i["featured"]]
    if q:
        items = [i for i in items
                 if q in i["id"].lower() or q in i["name"].lower()
                 or q in i["title"].lower() or q in i["description"].lower()]
    stats["matched"] = len(items)
    return {"ok": True, "items": items[:max(1, int(limit))], "categories": categories(),
            "errors": errors, "stats": stats, "config": config_view()}


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


def _record(item, target):
    rows = [r for r in _read_installed() if r.get("id") != item["id"]]
    rows.append({
        "id": item["id"], "kind": item["kind"], "name": item["name"],
        "version": item["version"], "sha256": item["sha256"],
        "publisher": item["publisher"], "source": item["source"].get("url") or "",
        "installed": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "enabled": item["kind"] not in ("mcp", "connector"),
        "target": target or "",
    })
    rows.sort(key=lambda r: (r.get("kind", ""), r.get("id", "")))
    _write_installed(rows)


def installed():
    items, _, _ = catalog()
    by_id = {i["id"]: i for i in items}
    rows = []
    for rec in _read_installed():
        live = by_id.get(rec["id"])
        row = dict(rec)
        row["in_catalog"] = bool(live)
        row["update_available"] = bool(
            live and (live["version"] != rec.get("version")
                      or (live["sha256"] and live["sha256"] != rec.get("sha256"))))
        rows.append(row)
    return {"ok": True, "installed": rows, "count": len(rows)}


def forget(item_id, remove_target=False):
    rows = _read_installed()
    rec = next((r for r in rows if r.get("id") == item_id), None)
    if rec is None:
        return {"ok": False, "error": "not installed: %s" % item_id}
    removed = False
    if remove_target and rec.get("target"):
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
    for rec in _read_installed():
        row = {"id": rec.get("id"), "kind": rec.get("kind"), "owner": "", "state": "ok",
               "detail": ""}
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
    if str(src.get("type") or "") == "bundled":
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


def _install_plugin(item):
    bundle = item.get("bundle")
    if not bundle:
        return {"ok": False, "error": "plugin item has no bundle"}
    from longrun.core import matrix
    res = matrix.apply_learning(bundle)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error") or "apply_learning refused the bundle"}
    return {"ok": True, "target": ",".join(res.get("installed") or [])}


def install(item_id, overwrite=False):
    """Install one catalogue item through its owning installer."""
    cfg = _config()
    items, _, _ = catalog()
    item = next((i for i in items if i["id"] == item_id), None)
    if item is None:
        return {"ok": False, "error": "unknown item: %s" % item_id}
    kind = item["kind"]
    if kind == "skill":
        res = _install_skill(item, cfg, overwrite)
    elif kind in ("mcp", "connector"):
        res = _install_server(item)
    elif kind == "plugin":
        res = _install_plugin(item)
    else:
        res = {"ok": False, "error": "unknown kind: %s" % kind}
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error") or "install failed", "id": item["id"]}
    _record(item, res.get("target"))
    return {"ok": True, "id": item["id"], "kind": kind, "name": item["name"],
            "target": res.get("target"), "sha256": item["sha256"],
            "enabled": res.get("enabled", True)}
