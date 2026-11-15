#!/usr/bin/env python3
"""v1021 — a connector is an MCP preset plus the key NAMES it needs.

  A  an empty catalogue means no connector, and the note is explicit about names
  B  a connector reports each key as set/missing — a NAME, never a value
  C  installing one lands the client DISABLED, exactly like a pasted server
  D  the install reports what is still missing before the operator enables it
  E  testing an unknown connector is refused by name
  F  the Settings panel is one view over the same two owners (catalogue + MCP file)
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-v1021-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_TMP, "data", "sessions")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import connectors, market  # noqa: E402
from longrun.interop import mcp_client  # noqa: E402

# v1021 isolation: `mcp_client` resolves its local JSON from the REPO (not from
# LONGRUN_CONFIG_DIR), so an install in this test would otherwise write a fake
# server into the OPERATOR's live config/mcp_clients.local.json — the same class
# of defect v507/v973 fixed for the memory store. Point the module's own paths at
# the temp home BEFORE any install.
_LOCAL_JSON = os.path.join(os.environ["LONGRUN_CONFIG_DIR"], "mcp_clients.local.json")
mcp_client.CONFIG_LOCAL_JSON_PATH = _LOCAL_JSON
mcp_client.CONFIG_LOCAL_PATH = os.path.join(os.environ["LONGRUN_CONFIG_DIR"], "mcp_clients.local.yaml")

UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def write_catalog(items):
    path = market._local_catalog_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"schema": market.SCHEMA, "items": items}, f)


# ── A: nothing to show, and the note says why ───────────────────────────────
res = connectors.available()
check("A1 an empty catalogue yields zero connectors", res["ok"] and res["connectors"] == [])
check("A2 the note states that only key NAMES are returned",
      "names only" in res.get("note", ""), res.get("note"))

# ── B: key state, names only ────────────────────────────────────────────────
write_catalog([
    {"id": "connector/db", "kind": "connector", "name": "db", "title": "Database",
     "description": "query the ops database", "category": "Developer Tools",
     "server": {"command": "npx", "args": ["-y", "db-mcp"],
                "env": {"DB_TOKEN": "${TEST_CONN_KEY}"}},
     "keys": ["TEST_CONN_KEY", "OTHER_CONN_KEY"]},
])
os.environ.pop("TEST_CONN_KEY", None)
os.environ.pop("OTHER_CONN_KEY", None)
row = connectors.available()["connectors"][0]
check("B1 the connector is listed with its declared keys",
      [k["name"] for k in row["keys"]] == ["TEST_CONN_KEY", "OTHER_CONN_KEY"], row["keys"])
check("B2 a key without a value reads set=false",
      all(k["set"] is False for k in row["keys"]) and row["missing"] == ["TEST_CONN_KEY", "OTHER_CONN_KEY"])
os.environ["TEST_CONN_KEY"] = "super-secret-value"
row = connectors.available()["connectors"][0]
check("B3 a key present in the environment reads set=true",
      row["keys"][0]["set"] is True and row["missing"] == ["OTHER_CONN_KEY"])
check("B4 the VALUE never leaves the keys owner",
      "super-secret-value" not in json.dumps(row), row)

# ── C: install lands the client DISABLED ────────────────────────────────────
res = connectors.install("connector/db")
check("C1 the connector installs", res.get("ok") is True, res.get("error") or res)
clients = mcp_client.load_doc().get("clients") or {}
check("C2 the client is in the MCP document", "db" in clients, list(clients))
check("C3 … and is DISABLED (opt-in, exactly like a pasted server)",
      clients.get("db", {}).get("enabled") is False, clients.get("db"))
check("C4 the write went to the local JSON, not the tracked file",
      os.path.isfile(_LOCAL_JSON), _LOCAL_JSON)
check("C5 the installed record exists for the marketplace's Manage view",
      any(r["id"] == "connector/db" for r in market.installed()["installed"]))

# ── D: what is still missing, said before enabling ──────────────────────────
check("D1 the install reports the remaining key by NAME",
      res.get("missing_keys") == ["OTHER_CONN_KEY"], res.get("missing_keys"))
check("D2 the note tells the operator the next step",
      "set" in res.get("note", "") and "test" in res.get("note", ""), res.get("note"))

# ── E: unknown ids are refused ──────────────────────────────────────────────
bad = connectors.install("connector/ghost")
check("E1 installing an unknown connector is refused by name",
      bad.get("ok") is False and "unknown item" in bad.get("error", ""), bad)
check("E2 testing an unknown connector is refused by name",
      "unknown connector" in connectors.test("connector/ghost").get("error", ""))

# ── F: the panel reads the same two owners ─────────────────────────────────
check("F1 the Settings panel exists as its own category",
      'data-cat="connectors"' in UI and '["connectors", "Connectors"]' in UI)
check("F2 it loads the real route", 'api("GET", "/api/connectors")' in UI)
check("F3 install and test go through their own routes",
      'api("POST", "/api/connectors/install"' in UI and 'api("POST", "/api/connectors/test"' in UI)
check("F4 the panel shows key state as a NAME with a tick/cross",
      'k.name + (k.set ? " ✓" : " ✗")' in UI)
check("F5 it never asks for or renders a key value",
      "key value" not in UI.split('data-cat="connectors"')[1].split("data-cat=")[0].lower())
check("F6 a connector that is not installable cannot be installed from the panel",
      "b.disabled = !c.installable;" in UI)

print("\n---\nv1021: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
