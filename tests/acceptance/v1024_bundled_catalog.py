#!/usr/bin/env python3
"""v1024 — the catalogue SHIPS populated, and a bundled item is still digest-gated.

An empty shelf was the defect: a marketplace that requires the operator to author a
catalogue first is not a marketplace. This pins the shipped content and the rules
that keep it honest:

  A  the bundled catalogue exists, parses, and lists every kind
  B  the operator's own file still WINS over the shipped one
  C  a bundled skill installs OFFLINE and its bytes are verified against the digest
  D  a bundled file edited behind the catalogue's back is REFUSED
  E  the Matrix plugins ship in longrun and are listed as PRESENT, not installable
  F  the GitHub connector is a real remote server with a key NAME, and it lands disabled
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-v1024-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_TMP, "data", "sessions")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_TMP, "skills")
os.environ["LONGRUN_SKILLS_LOCAL_DIR"] = os.path.join(_TMP, "skills", "local")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import market  # noqa: E402
from longrun.interop import mcp_client  # noqa: E402
from longrun.memory import skills  # noqa: E402

_LOCAL_JSON = os.path.join(os.environ["LONGRUN_CONFIG_DIR"], "mcp_clients.local.json")
mcp_client.CONFIG_LOCAL_JSON_PATH = _LOCAL_JSON
mcp_client.CONFIG_LOCAL_PATH = os.path.join(os.environ["LONGRUN_CONFIG_DIR"], "mcp_clients.local.yaml")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def by_id():
    return {i["id"]: i for i in market.search()["items"]}


# ── A: the shelf is not empty ──────────────────────────────────────────────
bundled_path = market._bundled_catalog_path()
check("A1 the bundled catalogue ships beside the module", os.path.isfile(bundled_path), bundled_path)
with open(bundled_path, encoding="utf-8") as f:
    doc = json.load(f)
check("A2 it is a valid longrun.market document", doc.get("schema") == market.SCHEMA
      and isinstance(doc.get("items"), list))
items = by_id()
kinds = {i["kind"] for i in items.values()}
check("A3 every kind is represented (skills, mcp, connectors, plugins)",
      {"skill", "mcp", "connector", "plugin"} <= kinds, sorted(kinds))
check("A4 the page therefore has real content on a fresh install", len(items) >= 15, len(items))

# ── B: the operator's file wins ────────────────────────────────────────────
path = market._local_catalog_path()
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    json.dump({"schema": market.SCHEMA, "items": [
        {"id": "mcp/github", "kind": "mcp", "name": "github", "title": "My own github",
         "server": {"command": "npx", "args": ["-y", "mine"]}}]}, f)
check("B1 an operator entry overrides the shipped one without a code change",
      by_id()["mcp/github"]["title"] == "My own github", by_id()["mcp/github"]["title"])
os.remove(path)

# ── C/D: a bundled skill is digest-gated ───────────────────────────────────
item = by_id()["skill/security-review"]
check("C1 the bundled skill is installable offline", item["installable"] is True
      and item["source"]["type"] == "bundled" and item["source"]["path"].endswith("SKILL.md"), item["source"])
res = market.install("skill/security-review")
check("C2 it installs from the repository, with the digest verified", res.get("ok") is True, res.get("error"))
check("C3 it landed in the market category",
      os.path.isfile(os.path.join(os.environ["LONGRUN_SKILLS_DIR"], "market",
                                  "security-review", "SKILL.md")))
check("C4 the installed record carries the bundled digest",
      market.installed()["installed"][0]["sha256"] == item["sha256"])

# tamper: name a DIFFERENT bundled file than the digest was computed from
tampered = dict(item)
tampered["source"] = dict(item["source"])
tampered["source"]["path"] = "market/skills/pr-review/SKILL.md"   # different bytes
out = market._install_skill(tampered, market._config(), True)
check("D1 a bundled file whose bytes do not match is REFUSED by name",
      out.get("ok") is False and "digest mismatch" in out.get("error", ""), out.get("error"))
bad = dict(item)
bad["source"] = {"type": "bundled", "path": "../../etc/passwd"}
out2 = market._install_skill(bad, market._config(), False)
check("D2 a bundled path outside the repository is refused",
      out2.get("ok") is False and "outside the repository" in out2.get("error", ""), out2.get("error"))

# A market install lands in skills/market/, NOT skills/local/ — a remove must follow
# the RECORDED target, or the files stay behind while the record says "removed".
skill_dir = os.path.join(os.environ["LONGRUN_SKILLS_DIR"], "market", "security-review")
gone = market.forget("skill/security-review", remove_target=True)
check("D3 forgetting with files removes the MARKET directory it recorded",
      gone.get("ok") is True and gone.get("removed_files") is True
      and not os.path.isdir(skill_dir), (gone, os.path.isdir(skill_dir)))

# ── E: Matrix plugins are present, not installable ─────────────────────────
plugins = [i for i in items.values() if i["kind"] == "plugin" and i["origin"] == "matrix"]
check("E1 the Matrix tools are listed", len(plugins) >= 5, len(plugins))
check("E2 they are marked present (already hot-loaded), not installable",
      all(p["present"] and not p["installable"] for p in plugins))
check("E3 they carry a real description from the module docstring",
      any(len(p["description"]) > 20 for p in plugins))

# ── F: the GitHub connector is real ────────────────────────────────────────
gh = items["connector/github"]
srv = gh["server"]
check("F1 it is a remote HTTPS MCP server", srv.get("type") == "http"
      and srv.get("url", "").startswith("https://"), srv.get("url"))
check("F2 the credential is a NAME, never a value",
      "${GITHUB_PERSONAL_ACCESS_TOKEN}" in (srv.get("headers") or {}).get("Authorization", "")
      and gh["keys"] == ["GITHUB_PERSONAL_ACCESS_TOKEN"])
check("F3 the panel reports the key by NAME, with its set state, never the value",
      [k["name"] for k in next(c for c in __import__("longrun.core.connectors", fromlist=["x"])
                               .available()["connectors"] if c["id"] == "connector/github")["keys"]]
      == ["GITHUB_PERSONAL_ACCESS_TOKEN"])
inst = market.install("connector/github")
check("F4 installing it lands the client DISABLED", inst.get("ok") is True and inst.get("enabled") is False, inst)
clients = mcp_client.load_doc().get("clients") or {}
check("F5 the client keeps its url, header and disabled state",
      clients.get("github", {}).get("enabled") is False
      and "api.githubcopilot.com" in clients.get("github", {}).get("url", "")
      and "Authorization" in (clients.get("github", {}).get("headers") or {}), clients.get("github"))

print("\n---\nv1024: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
