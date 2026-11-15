#!/usr/bin/env python3
"""v1026 — an installed item knows WHICH catalogue it came from, everywhere.

The catalogue already carried `origin`; the RECORD dropped it, so after an install
the operator could not tell a ClawHub skill from a bundled one, or an MCP server
from a pasted client. This pins the provenance chain:

  A  one label vocabulary for every origin (`market.origin_label`)
  B  an install PERSISTS origin + category, and `installed()`/`audit()` expose them
  C  a record written before provenance is BACKFILLED from the catalogue; gone = Unknown
  D  `/api/skills` and `/api/mcp/clients` JOIN the record, guarded by the target path
  E  `/api/market/sources` says how old each sync is, and when it went stale
"""
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import zipfile
from types import SimpleNamespace

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-v1026-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_TMP, "data", "sessions")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_TMP, "skills")
os.environ["LONGRUN_SKILLS_LOCAL_DIR"] = os.path.join(_TMP, "skills", "local")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import market, market_sync  # noqa: E402
from longrun.interop import mcp_client  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# Isolated MCP config: an install must never touch the operator's local clients.
mcp_client.CONFIG_LOCAL_JSON_PATH = os.path.join(_TMP, "mcp.local.json")
mcp_client.CONFIG_LOCAL_PATH = os.path.join(_TMP, "mcp.local.yaml")

# The shipped allow-list is data; point the config at a temp file we control.
market.CONFIG_PATH = os.path.join(_TMP, "market.yaml")
with open(market.CONFIG_PATH, "w", encoding="utf-8") as f:
    f.write("catalogs: []\nallow_hosts:\n  - clawhub.ai\nstale_days: 7\n")
market._cache.update(sig=None, cfg=None)


def write_local(items):
    path = market._local_catalog_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"schema": market.SCHEMA, "items": items}, f)


def skill_zip(name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("%s/SKILL.md" % name,
                    "---\nname: %s\ndescription: d\n---\nBody\n" % name)
    return buf.getvalue()


ZIP = skill_zip("remote-skill")
write_local([
    {"id": "skill/remote-skill", "kind": "skill", "name": "remote-skill",
     "title": "Remote skill", "category": "Finance",
     "sha256": hashlib.sha256(ZIP).hexdigest(),
     "source": {"type": "https", "url": "https://clawhub.ai/api/v1/download?slug=remote-skill&version=1"}},
    {"id": "mcp/demo", "kind": "mcp", "name": "demo", "title": "Demo server",
     "category": "MCP servers",
     "server": {"command": "npx", "args": ["-y", "demo-mcp"]}},
])
# An imported group, written the way `market_sync.sync` writes it.
market_sync._write_imported({"clawhub": {
    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 9 * 86400)),
    "items": [{"id": "skill/remote-skill", "kind": "skill", "name": "remote-skill",
               "title": "Remote skill", "category": "Finance",
               "sha256": hashlib.sha256(ZIP).hexdigest(),
               "source": {"type": "https",
                          "url": "https://clawhub.ai/api/v1/download?slug=remote-skill&version=1"}}],
}})
market._fetch = lambda url, cfg, limit: (ZIP, "")

# ── A: one label vocabulary ────────────────────────────────────────────────
check("A1 bundled is 'Bundled'", market.origin_label("bundled") == "Bundled")
check("A2 an imported registry is named by its source",
      market.origin_label("imported:mcp-registry") == "MCP Registry"
      and market.origin_label("imported:clawhub") == "ClawHub")
check("A3 an operator catalogue URL becomes its host",
      market.origin_label("https://catalog.example.com/m.json") == "catalog.example.com")
check("A4 an empty/unknown origin is named, never blank",
      market.origin_label("") == "Unknown" and market.origin_label("unknown") == "Unknown")
check("A5 the catalogue's own origins keep their names",
      market.origin_label("local") == "Your catalogue" and market.origin_label("matrix") == "Bundled (Matrix)")

# ── B: an install PERSISTS provenance ─────────────────────────────────────
res = market.install("skill/security-review")           # bundled, from the shipped catalogue
check("B1 a bundled skill installs", res.get("ok") is True, res)
rec = {r["id"]: r for r in market.installed()["installed"]}.get("skill/security-review") or {}
check("B2 the record carries origin + category", rec.get("origin") == "bundled"
      and rec.get("category") == "Security & Quality", rec)
check("B3 installed() labels it", rec.get("origin_label") == "Bundled", rec.get("origin_label"))

res = market.install("skill/remote-skill")              # precedence: local wins over imported
check("B4 a skill from the local catalogue installs", res.get("ok") is True, res)
rec2 = {r["id"]: r for r in market.installed()["installed"]}.get("skill/remote-skill") or {}
check("B5 the FIRST catalogue to define the id owns its provenance",
      rec2.get("origin") == "local" and rec2.get("origin_label") == "Your catalogue", rec2)

res = market.install("mcp/demo")
check("B6 an MCP server installs into the isolated config", res.get("ok") is True, res)
rec3 = {r["id"]: r for r in market.installed()["installed"]}.get("mcp/demo") or {}
check("B7 its record names the kind and the origin", rec3.get("kind") == "mcp"
      and rec3.get("origin") == "local", rec3)
audit = {r["id"]: r for r in market.audit()["rows"]}
check("B8 audit rows carry the same origin + label",
      audit.get("skill/security-review", {}).get("origin") == "bundled"
      and audit["skill/security-review"].get("origin_label") == "Bundled", audit.get("skill/security-review"))
mmap = market.installed_map()
check("B9 installed_map() is keyed by NAME for the Settings panels",
      set(mmap) >= {"security-review", "remote-skill", "demo"}
      and mmap["demo"]["origin_label"] == "Your catalogue", sorted(mmap))

# ── C: read-time backfill ──────────────────────────────────────────────────
rows = market._read_installed()
for row in rows:                       # simulate records written before this change
    row.pop("origin", None)
    row.pop("category", None)
market._write_installed(rows)
back = {r["id"]: r for r in market.installed()["installed"]}
check("C1 a record without origin is backfilled from the live catalogue",
      back["skill/security-review"]["origin"] == "bundled"
      and back["skill/security-review"]["origin_label"] == "Bundled", back["skill/security-review"])
rows.append({"id": "mcp/vanished", "kind": "mcp", "name": "vanished", "installed": "2026-01-01T00:00:00Z"})
market._write_installed(rows)
ghost = {r["id"]: r for r in market.installed()["installed"]}["mcp/vanished"]
check("C2 an id in no catalogue is 'Unknown', never a guess",
      ghost["origin"] == "unknown" and ghost["origin_label"] == "Unknown", ghost)
rows = [r for r in market._read_installed() if r["id"] != "mcp/vanished"]
market._write_installed(rows)

# ── D: the owner panels JOIN the record ────────────────────────────────────
def route(path):
    seen = {}

    def _send(code, obj):
        seen.update(code=code, body=obj)

    fake = SimpleNamespace(server=SimpleNamespace(server_address=("127.0.0.1", 8790)), _send=_send)
    from longrun.core import api_v02
    api_v02.handle(fake, "GET", path, {}, None)
    return seen


got = route("/api/skills")
sk = {s["name"]: s for s in (got.get("body") or {}).get("skills", [])}
check("D1 /api/skills marks the marketplace skill with its catalogue",
      (sk.get("security-review") or {}).get("market", {}).get("origin_label") == "Bundled",
      (sk.get("security-review") or {}).get("market"))

rows = market._read_installed()
for row in rows:
    if row["id"] == "skill/security-review":
        row["target"] = os.path.join(_TMP, "somewhere-else")   # a same-name skill that is NOT this one
market._write_installed(rows)
got = route("/api/skills")
sk = {s["name"]: s for s in (got.get("body") or {}).get("skills", [])}
check("D2 the join is guarded by the target: a same-named skill stays unlabelled",
      "market" not in (sk.get("security-review") or {}), (sk.get("security-review") or {}).get("market"))

got = route("/api/mcp/clients")
cl = (got.get("body") or {}).get("clients") or {}
check("D3 /api/mcp/clients marks the installed server",
      (cl.get("demo") or {}).get("market", {}).get("origin_label") == "Your catalogue",
      (cl.get("demo") or {}).get("market"))

# ── E: how old is the copy? ────────────────────────────────────────────────
srcs = {s["id"]: s for s in market_sync.status()}
check("E1 a synced source reports its age and its size",
      srcs["clawhub"]["items"] == 1 and isinstance(srcs["clawhub"]["age_seconds"], int)
      and srcs["clawhub"]["age_seconds"] >= 8 * 86400, srcs["clawhub"])
check("E2 an old group is marked stale", srcs["clawhub"]["stale"] is True, srcs["clawhub"])
check("E3 a never-synced source says so instead of inventing an age",
      srcs["mcp-registry"]["at"] == "" and srcs["mcp-registry"]["age_seconds"] is None
      and srcs["mcp-registry"]["stale"] is False, srcs["mcp-registry"])
market_sync._write_imported({"clawhub": {
    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "items": [{"id": "skill/remote-skill", "kind": "skill", "name": "remote-skill",
               "title": "Remote skill", "sha256": hashlib.sha256(ZIP).hexdigest(),
               "source": {"type": "https",
                          "url": "https://clawhub.ai/api/v1/download?slug=remote-skill&version=1"}}],
}})
fresh = {s["id"]: s for s in market_sync.status()}["clawhub"]
check("E4 a fresh sync is not stale", fresh["stale"] is False and fresh["age_seconds"] < 120, fresh)

print("\n---\nv1026: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
