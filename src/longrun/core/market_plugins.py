"""Adapters that read a COMMERCIAL plugin package and turn it into a Longrun `plugin` entry.

Three container standards are recognised, each read from the package's OWN manifest
(the names below are what the vendors ship, verified on this machine):

  * **trae** — `.trae-plugin/plugin.json`: `skills: "./skills/"` (a directory of
    `SKILL.md`) and `mcp: ".mcp.json"` (a `{"mcpServers": {...}}` document).
  * **claude** — `.claude-plugin/plugin.json`, plus a `.claude-plugin/marketplace.json`
    listing; same `skills/` layout and `.mcp.json`.
  * **openclaw** — `openclaw.plugin.json`: a CODE plugin (`dist/index.js` registering
    tools/hooks/channels/providers). It is refused BY NAME: code is not portable, and
    its Longrun home is the Matrix zone, not an install.

A bare directory with `SKILL.md` at its root is read as a one-member plugin.

Only two member kinds leave the converter — `skill` (a directory, zipped with a
digest) and `mcp` / `connector` (the server block, a connector when it names a
`${VAR}` credential). Everything else (commands, hooks, agents, binaries, apps,
extension code) is listed in `ignored` and never installed, so a package cannot
land half-installed.
"""
from __future__ import annotations

import io
import json
import os
import re
import time
import zipfile

from longrun.util import paths

MAX_FILES = 4000
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_PACKAGES = 400
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".DS_Store"}
_VAR = re.compile(r"\$\{([A-Z][A-Z0-9_]{1,63})\}")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


# ── roots (what the adapter is allowed to read) ───────────────────────────────

DEFAULT_ROOTS = ("~/.trae/plugins", "~/.claude/plugins", "~/.openclaw/extensions",
                 "~/.openclaw/plugin-skills")


def roots():
    """The directories an import may read: config `plugin_sources`, else the defaults."""
    env = os.environ.get("LONGRUN_PLUGIN_ROOTS")
    if env:
        return [p for p in env.split(os.pathsep) if p]
    out = [os.path.expanduser(p) for p in DEFAULT_ROOTS]
    try:
        import yaml
        with open(os.path.join(paths.REPO_ROOT, "config", "market.yaml"), encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        extra = doc.get("plugin_sources") if isinstance(doc, dict) else None
        if isinstance(extra, list):
            out = [os.path.expanduser(str(p)) for p in extra if str(p).strip()]
    except (OSError, ImportError, ValueError):
        pass
    out.append(paths.REPO_ROOT)
    return [p for p in out if p]


def allowed(path):
    """`(realpath, reason)` — a package must live under one of the configured roots."""
    real = os.path.realpath(os.path.expanduser(str(path or "")))
    if not real or not os.path.isdir(real):
        return "", "not a directory: %s" % (path or "")
    for root in roots():
        base = os.path.realpath(root)
        if real == base or real.startswith(base + os.sep):
            return real, ""
    return "", "outside the plugin roots (%s) — add it to `plugin_sources` in config/market.yaml" % (
        ", ".join(roots()))


# ── deterministic directory digest ────────────────────────────────────────────

def dir_zip(path):
    """A DETERMINISTIC zip of a skill directory, so its digest can be pinned.

    Sorted names and a fixed timestamp mean two reads of the same tree hash the
    same; symlinks are skipped (a package must not carry the machine out with it).
    """
    path = os.path.realpath(str(path or ""))
    if not os.path.isdir(path):
        raise ValueError("not a directory: %s" % path)
    if not os.path.isfile(os.path.join(path, "SKILL.md")):
        raise ValueError("no SKILL.md at %s" % path)
    buf = io.BytesIO()
    total, count = 0, 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(path):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
            for fn in sorted(files):
                full = os.path.join(root, fn)
                if os.path.islink(full) or not os.path.isfile(full):
                    continue
                size = os.path.getsize(full)
                if size > MAX_FILE_BYTES:
                    raise ValueError("file too large: %s (%d bytes)" % (full, size))
                total += size
                count += 1
                if total > MAX_TOTAL_BYTES or count > MAX_FILES:
                    raise ValueError("package too large (%d files, %d bytes)" % (count, total))
                info = zipfile.ZipInfo(os.path.relpath(full, path).replace(os.sep, "/"),
                                       date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                with open(full, "rb") as f:
                    z.writestr(info, f.read())
    return buf.getvalue()


# ── manifest readers ─────────────────────────────────────────────────────────

def _json(path):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _slug(text, fallback="plugin"):
    s = re.sub(r"[^a-z0-9._-]+", "-", str(text or "").lower()).strip("-._")
    return s[:64] if _SLUG.match(s or "") else fallback


def _server_members(document, where):
    """`{"mcpServers": {name: spec}}` -> members; a `${VAR}` anywhere makes it a connector."""
    servers = (document or {}).get("mcpServers") if isinstance(document, dict) else None
    if not isinstance(servers, dict):
        servers = (document or {}).get("servers") if isinstance(document, dict) else None
    out = []
    for name, spec in (servers or {}).items():
        if not isinstance(spec, dict) or not (spec.get("command") or spec.get("url")):
            continue
        blob = json.dumps(spec)
        keys = sorted(set(_VAR.findall(blob)))
        member = {"kind": "connector" if keys else "mcp", "name": _slug(name, "server"),
                  "title": str(name), "server": spec, "keys": keys,
                  "source": {"type": "manifest", "url": "", "path": where}}
        out.append(member)
    return out


def _skill_members(skill_dir):
    """Every child directory holding a SKILL.md is one skill member (or the root itself)."""
    out, ignored = [], []
    if not os.path.isdir(skill_dir):
        return out
    if os.path.isfile(os.path.join(skill_dir, "SKILL.md")):
        candidates = [(os.path.basename(skill_dir.rstrip(os.sep)) or "skill", skill_dir)]
    else:
        candidates = [(d, os.path.join(skill_dir, d)) for d in sorted(os.listdir(skill_dir))
                      if os.path.isfile(os.path.join(skill_dir, d, "SKILL.md"))]
    import hashlib
    for name, path in candidates:
        try:
            data = dir_zip(path)
        except ValueError as exc:
            ignored.append("skill %s: %s" % (name, exc))
            continue
        out.append({"kind": "skill", "name": _slug(name, "skill"), "title": name,
                    "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                    "source": {"type": "dir", "url": "", "path": os.path.realpath(path)}})
    return out


def detect(root):
    """Which container standard this directory is, or "" when it is none of them."""
    root = str(root or "")
    if os.path.isfile(os.path.join(root, ".trae-plugin", "plugin.json")):
        return "trae"
    if os.path.isfile(os.path.join(root, ".claude-plugin", "plugin.json")):
        return "claude"
    if os.path.isfile(os.path.join(root, "openclaw.plugin.json")):
        return "openclaw"
    if os.path.isfile(os.path.join(root, "SKILL.md")):
        return "skill"
    return ""


def _category(text):
    try:
        from longrun.core import market_taxonomy
        return market_taxonomy.classify(text)
    except Exception:  # noqa: BLE001 — a classifier miss must not block an import
        return "Other"


def _package_from_url(url):
    """Download a plugin ZIP from an allow-listed host into a private dir.

    `(root, base, reason)` — `base` is the temp directory the caller removes after
    the install. The download is bounded by the same size limit and https allow-list
    as any other catalogue fetch, and the archive may not escape its extraction root.
    """
    import shutil
    import tempfile
    from longrun.core import market as _market
    data, why = _market._fetch(str(url), _market._config(), MAX_TOTAL_BYTES)
    if data is None:
        return "", "", why
    dest = tempfile.mkdtemp(prefix="plugin-", dir=_market._market_dir())
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                name = info.filename
                target = os.path.realpath(os.path.join(dest, name))
                if name.startswith("/") or ".." in name.replace("\\", "/").split("/") \
                        or not (target == dest or target.startswith(dest + os.sep)):
                    raise ValueError("unsafe path in the archive: %s" % name)
            z.extractall(dest)
    except (zipfile.BadZipFile, ValueError, OSError) as exc:
        shutil.rmtree(dest, ignore_errors=True)
        return "", "", "bad archive: %s" % exc
    entries = [e for e in sorted(os.listdir(dest)) if not e.startswith(".")]
    if len(entries) == 1 and os.path.isdir(os.path.join(dest, entries[0])):
        return os.path.join(dest, entries[0]), dest, ""
    return dest, dest, ""


def convert(root, trusted=False):
    """Read one package and describe the Longrun entry it becomes. Writes nothing.

    `trusted` is for a directory this module created itself (a downloaded archive);
    a caller-supplied path must still live under the configured roots.

    Returns `{ok, format, item, ignored, notes}` or `{ok: False, error, ignored}`.
    """
    # The location gate comes FIRST: a path we may not read is refused for that
    # reason even when it happens to contain a manifest, so the caller is never
    # told "not a package" about a directory the adapter was never allowed to look at.
    if trusted:
        real = os.path.realpath(str(root or ""))
        why = "" if os.path.isdir(real) else "not a directory: %s" % root
    else:
        real, why = allowed(root)
    if why:
        return {"ok": False, "error": why, "ignored": []}
    fmt = detect(real)
    if not fmt:
        return {"ok": False, "error": "not a plugin package (no manifest and no SKILL.md)",
                "ignored": []}
    ignored, notes = [], []

    if fmt == "openclaw":
        manifest = _json(os.path.join(real, "openclaw.plugin.json")) or {}
        contracts = manifest.get("contracts") or {}
        what = ", ".join("%s %s" % (k, ", ".join(map(str, v)) if isinstance(v, list) else v)
                         for k, v in contracts.items()) or "code"
        # A code plugin is refused as CODE, but it is still a container: several of them
        # ship skills next to the JavaScript (a `skills` manifest key, or a SKILL.md at the
        # root). Those ARE portable, so they are imported and the code part is named as
        # ignored — refusing the whole package would throw away what the source gives.
        skill_dirs = []
        declared = manifest.get("skills")
        if isinstance(declared, str):
            declared = [declared]
        for rel in declared or []:
            rel = str(rel).strip()
            rel = rel[2:] if rel.startswith("./") else rel.lstrip("/")
            path = os.path.realpath(os.path.join(real, rel))
            if path == real or path.startswith(real + os.sep):
                skill_dirs.append(path)
        if os.path.isfile(os.path.join(real, "SKILL.md")):
            skill_dirs.append(real)
        members = []
        for path in skill_dirs:
            members += _skill_members(path)
        if not members:
            return {"ok": False,
                    "error": ("openclaw code plugin (%s): its runtime is JavaScript inside the "
                              "OpenClaw gateway — port it to a Matrix tool or ship an MCP server"
                              % what),
                    "ignored": ["code"]}
        ignored.append("code")
        notes.append("code (%s) has no portable member: only its skills are imported" % what)
        title = manifest.get("name") or manifest.get("id") or os.path.basename(real)
        description = manifest.get("description") or ""
        publisher = (manifest.get("author") or {}).get("name") if isinstance(
            manifest.get("author"), dict) else ""
        version = manifest.get("version") or ""
        category = _category(" ".join([str(title), str(description)]))

    elif fmt == "trae":
        manifest = _json(os.path.join(real, ".trae-plugin", "plugin.json")) or {}
        skills_dir = os.path.join(real, str(manifest.get("skills") or "./skills/"))
        members = _skill_members(skills_dir)
        mcp_ref = manifest.get("mcp")
        if isinstance(mcp_ref, str) and mcp_ref.strip():
            rel = mcp_ref.strip()
            rel = rel[2:] if rel.startswith("./") else rel.lstrip("/")
            doc_path = os.path.realpath(os.path.join(real, rel))
            document = _json(doc_path) if doc_path.startswith(real + os.sep) else None
            members += _server_members(document, real) if document else []
            if not document:
                notes.append("mcp document not readable: %s" % mcp_ref)
        elif isinstance(manifest.get("mcpServers"), dict):
            members += _server_members({"mcpServers": manifest["mcpServers"]}, real)
        for key, label in (("binaries", "binaries"), ("apps", "apps"), ("connector", "connector"),
                           ("i18n", "i18n")):
            if manifest.get(key):
                ignored.append(label)
        title = (manifest.get("interface") or {}).get("displayName") or manifest.get("name")
        description = manifest.get("description") or ""
        publisher = (manifest.get("author") or {}).get("name") if isinstance(
            manifest.get("author"), dict) else ""
        version = manifest.get("version") or ""
        category = _category(" ".join([str(title or ""), description] +
                                      [str(k) for k in (manifest.get("keywords") or [])]))
    elif fmt == "claude":
        manifest = _json(os.path.join(real, ".claude-plugin", "plugin.json")) or {}
        members = _skill_members(os.path.join(real, "skills"))
        mcp_doc = _json(os.path.join(real, ".mcp.json")) or _json(
            os.path.join(real, "mcp.json"))
        if mcp_doc:
            members += _server_members(mcp_doc, real)
        for extra in ("commands", "agents", "hooks"):
            if os.path.isdir(os.path.join(real, extra)) or os.path.isfile(
                    os.path.join(real, extra, "hooks.json")):
                ignored.append(extra)
        title = manifest.get("name") or os.path.basename(real)
        description = manifest.get("description") or ""
        publisher = manifest.get("author") or ""
        version = manifest.get("version") or ""
        category = _category(" ".join([str(title), description]))
    else:  # a bare SKILL.md directory
        manifest = {}
        members = _skill_members(real)
        title = os.path.basename(real)
        description = "A skill directory"
        publisher = version = ""
        category = _category(str(title))

    if not members:
        return {"ok": False, "ignored": ignored,
                "error": "no portable member: the package carries no SKILL.md and no mcpServers"}

    name = _slug(manifest.get("name") or title or os.path.basename(real))
    item = {"id": "plugin/" + name, "kind": "plugin", "name": name,
            "title": str(title or name), "description": str(description),
            "category": category, "featured": False, "version": str(version),
            "publisher": str(publisher or ""), "sha256": "", "bytes": None,
            "source": {"type": "dir", "url": "", "path": real},
            "members": members, "members_declared": len(members),
            "origin": "imported:" + fmt, "present": False, "installable": True}
    return {"ok": True, "format": fmt, "path": real, "item": item,
            "ignored": sorted(set(ignored)), "notes": notes}


_scan_cache = {"at": 0.0, "val": None}


def scan(max_age=30):
    """Every package under the configured roots, described but NOT installed.

    Memoised for `max_age` seconds: the roots include the repository, and the page
    asks for this every time the Plugins section opens.
    """
    now = time.time()
    if _scan_cache["val"] is not None and now - _scan_cache["at"] < max_age:
        return _scan_cache["val"]
    seen, out = set(), []
    for root in roots():
        if not os.path.isdir(root):
            continue
        base_depth = root.rstrip(os.sep).count(os.sep)
        for cur, dirs, files in os.walk(root):
            if cur.rstrip(os.sep).count(os.sep) - base_depth > 4 or len(out) >= MAX_PACKAGES:
                dirs[:] = []
                continue
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
            fmt = ""
            if ".trae-plugin" in dirs:
                fmt = "trae"
            elif ".claude-plugin" in dirs:
                fmt = "claude"
            elif "openclaw.plugin.json" in files:
                fmt = "openclaw"
            elif "SKILL.md" in files and cur.rstrip(os.sep).count(os.sep) - base_depth <= 2:
                fmt = "skill"
            if not fmt or cur in seen:
                continue
            seen.add(cur)
            conv = convert(cur)
            row = {"path": cur, "format": fmt}
            if conv.get("ok"):
                item = conv["item"]
                row.update(name=item["name"], title=item["title"], version=item["version"],
                           description=item["description"], category=item["category"],
                           members=[{"kind": m["kind"], "name": m["name"]}
                                    for m in item["members"]],
                           ignored=conv.get("ignored") or [],
                           notes=conv.get("notes") or [])
            else:
                row.update(error=conv.get("error") or "not convertible",
                           ignored=conv.get("ignored") or [])
            out.append(row)
    out.sort(key=lambda r: (r.get("format", ""), r.get("name") or r.get("path", "")))
    result = {"ok": True, "roots": roots(), "packages": out,
              "counts": {"found": len(out), "convertible": sum(1 for r in out if "error" not in r)}}
    _scan_cache.update(at=now, val=result)
    return result


def install_dir(root, overwrite=False):
    """Convert + install one LOCAL package. Delegates to the same bundle installer."""
    conv = convert(root)
    if not conv.get("ok"):
        return conv
    from longrun.core import market
    res = market.install_entry(conv["item"], overwrite=overwrite)
    res["format"] = conv["format"]
    res["path"] = conv["path"]
    res["ignored"] = conv.get("ignored") or []
    return res


def install(source, overwrite=False):
    """Install a plugin package from a local directory OR an https ZIP URL."""
    import shutil
    src = str(source or "").strip()
    if not src:
        return {"ok": False, "error": "no path or url", "ignored": []}
    if not src.startswith("https://"):
        return install_dir(src, overwrite=overwrite)
    root, base, why = _package_from_url(src)
    if why:
        return {"ok": False, "error": why, "ignored": []}
    try:
        conv = convert(root, trusted=True)
        if not conv.get("ok"):
            return conv
        from longrun.core import market
        res = market.install_entry(conv["item"], overwrite=overwrite)
        res["format"] = conv["format"]
        res["path"] = src
        res["ignored"] = conv.get("ignored") or []
        return res
    finally:
        shutil.rmtree(base, ignore_errors=True)
