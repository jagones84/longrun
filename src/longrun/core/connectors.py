"""Connectors — an MCP server preset plus the credential NAMES it needs.

A connector is not a second protocol: it is a catalogue entry of kind
`connector` whose `server` block is already in the `mcpServers` shape the MCP
client consumes, plus `keys` (names only, never values). Installing one is the
MCP install path — the client lands DISABLED, exactly like a pasted one — and
the connector view adds the one thing a paste cannot: whether each required key
is set, and the ability to test the server before enabling it.

Key values are never returned here. `keys.keys_status()` reports NAME + set,
and that is all this module exposes.
"""
from __future__ import annotations

from longrun.core import market
from longrun.interop import mcp_client
from longrun.model import keys


def _set_keys(names=()):
    """Which of `names` currently have a VALUE.

    The question is asked of the one keys owner (`keys.read_secret`), per declared
    name — `keys.keys_status()` only DISCOVERS names from providers and MCP
    headers, so a connector's own variable would be invisible to it. Only the
    boolean is kept; the value never leaves this call.
    """
    out = set()
    for name in names:
        try:
            if keys.read_secret(name):
                out.add(name)
        except Exception:  # noqa: BLE001 — a broken keys store must not break the panel
            continue
    return out


def available():
    """Every connector in the catalogue, with key state and client state."""
    items, errors, _ = market.catalog()
    declared = {i["name"]: i.get("keys") or [] for i in items if i["kind"] == "connector"}
    present = _set_keys({k for keys_ in declared.values() for k in keys_})
    clients = mcp_client.load_doc().get("clients") or {}
    rows = []
    for item in items:
        if item["kind"] != "connector":
            continue
        spec = clients.get(item["name"]) or {}
        missing = [k for k in item["keys"] if k not in present]
        rows.append({
            "id": item["id"], "name": item["name"], "title": item["title"],
            "description": item["description"], "category": item["category"],
            "publisher": item["publisher"], "version": item["version"],
            "keys": [{"name": k, "set": k in present} for k in item["keys"]],
            "missing": missing,
            "installed": bool(spec),
            "enabled": bool(spec.get("enabled")),
            "installable": bool(item["installable"]),
        })
    return {"ok": True, "connectors": rows, "errors": errors,
            "note": "key values live in the gitignored .env; this view returns names only"}


def install(item_id):
    """Install the connector's server, then report what is still missing."""
    res = market.install(item_id)
    if not res.get("ok"):
        return res
    item = market.search(kind="connector")["items"]
    item = next((i for i in item if i["id"] == item_id), {})
    present = _set_keys(item.get("keys") or [])
    missing = [k for k in (item.get("keys") or []) if k not in present]
    return {"ok": True, "id": item_id, "name": res.get("name"),
            "enabled": False, "missing_keys": missing,
            "note": ("set %s, then test and enable" % ", ".join(missing)) if missing
                    else "no key required — test, then enable"}


def test(item_id):
    """Validate the installed server WITHOUT enabling or persisting anything."""
    items = market.search(kind="connector")["items"]
    item = next((i for i in items if i["id"] == item_id), None)
    if item is None:
        return {"ok": False, "error": "unknown connector: %s" % item_id}
    return mcp_client.test_client({"name": item["name"]})
