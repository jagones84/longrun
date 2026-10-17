"""Generic editor for the YAML config store (JAG-488).

The WebUI already has structured editors for routing, tool policy, providers,
subagents, MCP clients, the knowledge indexes and the compaction policy. Every
other file under ``config/`` (``decisions.yaml``, ``hooks.yaml``, ...) could
only be edited by hand on the host, so the SETTINGS panel was not a complete
view of the harness configuration.

This module makes the WHOLE top-level ``config/*.yaml`` store editable from the
WebUI: list -> read -> validate -> atomic write -> hot-reload.

Safety rules:
  * only top-level ``config/*.yaml`` / ``config/*.yml`` (no subdirectories, no
    ``..``, no symlink escape);
  * the submitted text MUST parse as YAML; a parse error is rejected before
    anything is written;
  * the previous version is copied to ``data/config-backups/`` first;
  * writes are atomic (temp file in the same directory + ``os.replace``).
"""

import os
import re
import shutil
import tempfile
import time

from longrun.util.paths import REPO_ROOT

CONFIG_DIR = os.path.join(REPO_ROOT, "config")
BACKUP_DIR = os.path.join(REPO_ROOT, "data", "config-backups")
MAX_BYTES = 1024 * 1024  # a config file is not a dataset
_NAME_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.ya?ml$")


def _path(name):
    """Resolve an allowed config file name to its absolute path (or raise)."""
    name = str(name or "").strip()
    if not _NAME_RX.match(name) or "/" in name or "\\" in name:
        raise ValueError("invalid config file name: %r" % (name,))
    path = os.path.join(CONFIG_DIR, name)
    real_dir = os.path.realpath(CONFIG_DIR)
    if os.path.dirname(os.path.realpath(path)) != real_dir:
        raise ValueError("refusing a path outside config/: %r" % (name,))
    return path


def list_files():
    """Every editable file in ``config/`` with size + mtime (newest last)."""
    out = []
    try:
        names = sorted(os.listdir(CONFIG_DIR))
    except OSError:
        return out
    for name in names:
        path = os.path.join(CONFIG_DIR, name)
        if not os.path.isfile(path):
            continue
        if not _NAME_RX.match(name):
            continue
        try:
            st = os.stat(path)
        except OSError:
            continue
        out.append({"name": name, "bytes": st.st_size,
                    "mtime": int(st.st_mtime)})
    return out


def read_file(name):
    """Read one config file. Returns ``{ok, name, text, mtime}``."""
    path = _path(name)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return {"ok": False, "error": "not found: %s" % name}
    except OSError as e:
        return {"ok": False, "error": "cannot read %s: %s" % (name, e)}
    return {"ok": True, "name": name, "text": text,
            "mtime": int(os.stat(path).st_mtime)}


def _backup(name, path):
    """Keep a timestamped copy of the previous version (best effort)."""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, os.path.join(BACKUP_DIR, "%s.%s.bak" % (name, stamp)))
    except OSError:
        pass


def _yaml_parse(text):
    """Parse ``text`` the way the loaders do. Raises ValueError on garbage."""
    try:
        import yaml
    except ImportError:  # the harness ships PyYAML; JSON is still valid YAML-ish
        import json
        try:
            return json.loads(text) if text.strip() else None
        except Exception as e:  # noqa: BLE001
            raise ValueError("invalid JSON: %s" % e)
    try:
        return yaml.safe_load(text)
    except Exception as e:  # noqa: BLE001
        raise ValueError("invalid YAML: %s" % e)


def write_file(name, text):
    """Validate + atomically write one config file, then hot-reload its module.

    Returns ``{ok, name, bytes, mtime, reloaded, backup}``; on a validation or
    IO error returns ``{ok: False, error}`` and leaves the file untouched.
    """
    path = _path(name)
    if not isinstance(text, str):
        return {"ok": False, "error": "text must be a string"}
    if len(text.encode("utf-8")) > MAX_BYTES:
        return {"ok": False, "error": "file too large (max %d bytes)" % MAX_BYTES}
    try:
        data = _yaml_parse(text)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    # A config file is a mapping (the loaders index it by key). An EMPTY file is
    # valid — it means "defaults" — but a scalar or a list is a typo.
    if data is not None and not isinstance(data, dict):
        return {"ok": False, "error": "the top level must be a mapping (key: value)"}
    existed = os.path.exists(path)
    if existed:
        _backup(name, path)
        # Keep the file's original newline style: `read_file` decodes CRLF to LF
        # (universal newlines), so a save would otherwise rewrite every line of a
        # Windows-authored file and produce a whole-file diff.
        try:
            with open(path, "rb") as f:
                if b"\r\n" in f.read(4096):
                    text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        except OSError:
            pass
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".%s." % name, dir=CONFIG_DIR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                if not text.endswith("\n"):
                    f.write("\n")
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    except OSError as e:
        return {"ok": False, "error": "cannot write %s: %s" % (name, e)}
    return {"ok": True, "name": name, "bytes": len(text.encode("utf-8")),
            "mtime": int(os.stat(path).st_mtime), "reloaded": _reload(name),
            "backup": existed}


def _reload(name):
    """Invalidate the in-memory cache of whichever module owns this file."""
    done = []
    base = name[:-5] if name.endswith(".yaml") else name[:-4]

    def attempt(label, fn):
        try:
            fn()
            done.append(label)
        except Exception as e:  # noqa: BLE001 — a reload failure must not undo a write
            done.append("%s: %s" % (label, e))

    if base.startswith("tools"):
        from longrun.tools import registry
        attempt("tools", lambda: registry.load_config(reload=True))
    if base.startswith("routing"):
        from longrun.model import routing
        attempt("routing", lambda: routing.load_config(reload=True))
    if base.startswith("compaction"):
        from longrun.model import compaction_config
        attempt("compaction", lambda: compaction_config.load(force=True))
    if base.startswith("hooks"):
        from longrun.tools import hooks
        attempt("hooks", lambda: hooks.load(reload=True))
    if base.startswith("providers"):
        from longrun.model import providers
        attempt("providers", providers.reload)
    if base.startswith("mcp_clients"):
        from longrun.interop import mcp_client
        attempt("mcp", mcp_client.reload)
    if base.startswith("subagents"):
        from longrun.agent import subagent
        attempt("subagents", lambda: subagent.load_cfg(reload=True))
    if base.startswith("decisions"):
        done.append("decisions (mtime-cached)")
    if base.startswith("index") or base.startswith("embedding"):
        done.append("index (read per call)")
    return done
