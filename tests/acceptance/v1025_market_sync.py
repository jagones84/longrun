#!/usr/bin/env python3
"""v1025 — sync an EXTERNAL marketplace into the catalogue, without trusting it.

OpenClaw/ClawHub and the official MCP Registry publish machine-readable APIs, so the
whole marketplace can be pulled at once. Compatibility is a RULE, not one decision per
item, and this pins that rule plus the precedence that keeps curated entries first.

  A  the official registry maps a stdio package to a runnable server, with its env
  B  a remote that REQUIRES a credential becomes a connector with a per-item key NAME
  C  only the latest version of a server is kept; an unrunnable row is skipped, counted
  D  a sync writes imported.json and the catalogue reads it — after the bundled file
  E  a ClawHub skill is pinned by the digest of the bytes the sync downloaded
  F  an unknown source is refused by name; the UI offers the two that exist
"""
import hashlib
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-v1025-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_TMP, "data", "sessions")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_TMP, "skills")
os.environ["LONGRUN_SKILLS_LOCAL_DIR"] = os.path.join(_TMP, "skills", "local")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import market, market_sync  # noqa: E402

UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
JS = open(os.path.join(REPO, "webui", "assets", "market.js"), encoding="utf-8").read()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


REGISTRY = {"servers": [
    {"server": {"name": "io.example/stdio-one", "title": "Stdio One",
                "description": "A stdio server.", "version": "1.0.0",
                "packages": [{"registryType": "npm", "identifier": "stdio-one",
                              "version": "1.0.0", "runtimeHint": "npx",
                              "transport": {"type": "stdio"},
                              "runtimeArguments": [{"type": "positional", "value": "-y"}],
                              "environmentVariables": [
                                  {"name": "ONE_TOKEN", "isRequired": True, "isSecret": True},
                                  {"name": "ONE_OPTIONAL"}]}]},
     "_meta": {"io.modelcontextprotocol.registry/official": {"isLatest": True}}},
    {"server": {"name": "com.example/remote-needs-auth", "title": "Needs auth",
                "version": "2.0.0",
                "remotes": [{"type": "streamable-http", "url": "https://mcp.example.com/mcp",
                             "headers": [{"name": "Authorization", "isRequired": True}]}]},
     "_meta": {"io.modelcontextprotocol.registry/official": {"isLatest": True}}},
    {"server": {"name": "io.example/stdio-one", "title": "Stdio One (old)", "version": "0.9.0",
                "packages": [{"registryType": "npm", "identifier": "stdio-one",
                              "version": "0.9.0", "transport": {"type": "stdio"}}]},
     "_meta": {"io.modelcontextprotocol.registry/official": {"isLatest": False}}},
    {"server": {"name": "org.example/unrunnable", "title": "Nothing to run",
                "version": "1.0.0"},
     "_meta": {"io.modelcontextprotocol.registry/official": {"isLatest": True}}},
], "metadata": {"nextCursor": None}}


def fake_fetch_json(url, cfg):
    if "registry.modelcontextprotocol.io" in url:
        return REGISTRY, ""
    if "/skills?" in url:
        return {"items": [
            {"slug": "deploy-checklist", "displayName": "Deploy checklist",
             "summary": "A checklist before a deploy.", "ownerHandle": "someone",
             "latestVersion": {"version": "1.2.3"},
             "stats": {"downloads": 2000}},
        ]}, ""
    return None, "unexpected url"


_ZIP = b"PK\x03\x04 fake-zip-bytes"
market._fetch_json = fake_fetch_json
market._fetch = lambda url, cfg, limit: (_ZIP, "")

# ── A: stdio package mapping ───────────────────────────────────────────────
res = market_sync.sync("mcp-registry", limit=10)
check("A1 the sync succeeds and counts what it read", res.get("ok") is True and res["items"] == 2, res)
by = {i["id"]: i for i in market.search(limit=500)["items"]}
one = by.get("connector/io.example-stdio-one") or by.get("mcp/io.example-stdio-one")
check("A2 the package becomes a runnable npx server",
      one and one["server"]["command"] == "npx"
      and one["server"]["args"] == ["-y", "stdio-one@1.0.0"], one and one["server"])
check("A3 its environment carries ${VAR} references, not values",
      one and one["server"]["env"] == {"ONE_TOKEN": "${ONE_TOKEN}",
                                       "ONE_OPTIONAL": "${ONE_OPTIONAL}"}, one and one["server"].get("env"))
check("A4 a REQUIRED env var becomes a declared key, so the card can check it",
      one and one["kind"] == "connector" and one["keys"] == ["ONE_TOKEN"], one and one.get("keys"))

# ── B: remote with a required credential ───────────────────────────────────
auth = by.get("connector/com.example-remote-needs-auth")
check("B1 a remote that needs auth becomes a connector", auth is not None, sorted(by))
check("B2 its header references a PER-ITEM key, never a shared name",
      auth and auth["server"]["headers"]["Authorization"] == "Bearer ${COM_EXAMPLE_REMOTE_NEEDS_AUTH_TOKEN}"
      and auth["keys"] == ["COM_EXAMPLE_REMOTE_NEEDS_AUTH_TOKEN"], auth and auth["server"])
check("B3 the header and url are preserved as the MCP client expects",
      auth and auth["server"]["url"] == "https://mcp.example.com/mcp"
      and auth["server"]["type"] == "http")

# ── C: latest only, unrunnable skipped ─────────────────────────────────────
check("C1 the older version is not a second entry",
      "mcp/io.example-stdio-one" not in by and "connector/io.example-stdio-one" in by, sorted(by))
check("C2 an unrunnable row is skipped and COUNTED, not silently dropped",
      "mcp/unrunnable" not in by and res["error_count"] >= 1
      and any("unrunnable" in e for e in res["errors"]), res["errors"])

# ── D: precedence — imported sits after the shipped catalogue ──────────────
imported_path = market_sync._imported_path()
check("D1 the sync wrote imported.json", os.path.isfile(imported_path), imported_path)
with open(imported_path, encoding="utf-8") as f:
    doc = json.load(f)
check("D2 it is grouped by source, so a second sync does not erase the first",
      isinstance(doc.get("sources"), dict) and "mcp-registry" in doc["sources"])
by = {i["id"]: i for i in market.search(limit=500)["items"]}
check("D3 a curated entry keeps its place over an imported id",
      by["mcp/playwright"]["origin"] == "bundled", by["mcp/playwright"]["origin"])
check("D4 imported entries are browsable", by["connector/io.example-stdio-one"]["origin"] == "imported:mcp-registry")

# ── E: ClawHub skills are pinned by digest at sync time ────────────────────
res2 = market_sync.sync("clawhub", limit=5)
check("E1 the ClawHub sync succeeds", res2.get("ok") is True and res2["items"] == 1, res2)
skill = {i["id"]: i for i in market.search(limit=500)["items"]}["skill/deploy-checklist"]
check("E2 the skill is installable because the sync PINNED its bytes",
      skill["installable"] is True and skill["sha256"] == hashlib.sha256(_ZIP).hexdigest(), skill["sha256"])
check("E3 the source URL is the download endpoint the installer will GET",
      "/download?slug=deploy-checklist&version=1.2.3" in skill["source"]["url"], skill["source"])
check("E4 the publisher and version are carried for the Manage view",
      skill["publisher"] == "someone" and skill["version"] == "1.2.3")
check("E5 both sync groups survive (one file, two sources)",
      set(json.load(open(imported_path, encoding="utf-8"))["sources"]) == {"mcp-registry", "clawhub"})

# ── F: refusals and the UI ─────────────────────────────────────────────────
bad = market_sync.sync("nope")
check("F1 an unknown source is refused by name",
      bad.get("ok") is False and "unknown source" in bad.get("error", ""), bad)
check("F2 the two adapters are declared with the host each needs",
      {s["id"] for s in market_sync.sources()} == {"mcp-registry", "clawhub"}
      and all(s.get("host") for s in market_sync.sources()))
check("F3 the page offers a source and a sync control",
      'id="mktSource"' in UI and 'id="mktSync"' in UI and 'data-call="mktSync"' in UI)
check("F4 the page posts to the sync route and re-reads the catalogue",
      '"/api/market/sync"' in JS and "await load();" in JS.split("async function syncSource")[1][:900])
check("F5 the catalogue route reports which sources are allowed",
      '"/api/market/sources"' in open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
                                       encoding="utf-8").read())

print("\n---\nv1025: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
