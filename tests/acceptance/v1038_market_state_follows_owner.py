#!/usr/bin/env python3
"""v1038 — the Marketplace "installed" state follows its owner.

Measured 2026-11-15: `filesystem` was installed from the Marketplace, then deleted
in Settings ▸ MCP, and the Marketplace still labelled it INSTALLED. The RECORD
(`data/market/installed.json`) was written at install time and never reconciled
with the owning store (the MCP client document / the skills tree).

One read now decides: a record whose object is GONE from its owner is pruned
atomically, so every panel agrees; a record whose owner cannot be read is KEPT
(never erase history on a failed probe).

  A1 a deleted MCP client's record is pruned on read
  A2 a removed skill directory's record is pruned on read
  A3 the pruned file is what the next read sees (not just a filtered view)
  A4 installed_map() follows the same truth
  A5 audit() reports no drift for a reconciled record
  A6 a present-but-DISABLED client stays installed
  A7 an unreadable client document prunes nothing
  A8 a skill record with no target is never pruned on a guess
  A9 remove_client() forgets the record immediately, without waiting for a read

Deterministic: temp data dir, no network, no child process.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1038-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "SESSIONS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key.lower())
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import market  # noqa: E402
from longrun.interop import mcp_client  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


installed_path = market._installed_path()
os.makedirs(os.path.dirname(installed_path), exist_ok=True)
skill_dir = os.path.join(TMP, "skills", "live-skill")
os.makedirs(skill_dir, exist_ok=True)
open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8").write("# live\n")


def write_records(rows):
    with open(installed_path, "w", encoding="utf-8") as f:
        json.dump(rows, f)


def read_ids():
    with open(installed_path, encoding="utf-8") as f:
        return sorted(r.get("id") for r in json.load(f))


rows = [
    {"id": "mcp/live1", "kind": "mcp", "name": "live1", "target": "cfg"},
    {"id": "mcp/gone1", "kind": "mcp", "name": "gone1", "target": "cfg"},
    {"id": "skill/live2", "kind": "skill", "name": "live2", "target": skill_dir},
    {"id": "skill/gone2", "kind": "skill", "name": "gone2",
     "target": os.path.join(TMP, "skills", "deleted-skill")},
    {"id": "matrix/x", "kind": "matrix", "name": "x", "target": ""},
    # A record written when `plugin` still meant a Matrix bundle: no members, so
    # it can never be probed — and it must never be pruned on a guess.
    {"id": "plugin/legacy", "kind": "plugin", "name": "legacy", "target": ""},
]
write_records(rows)

real_load = mcp_client.load_doc
mcp_client.load_doc = lambda: {"clients": {"live1": {"url": "http://x"}, "gone-disabled": {}}}

try:
    out = market.installed()
    ids = sorted(r["id"] for r in out["installed"])
    check("A1 a deleted MCP client's record is pruned on read",
          "mcp/gone1" not in ids and "mcp/live1" in ids, ids)
    check("A2 a removed skill directory's record is pruned on read",
          "skill/gone2" not in ids and "skill/live2" in ids, ids)
    check("A3 the pruned file is what the next read sees",
          "mcp/gone1" not in read_ids() and "skill/gone2" not in read_ids(),
          read_ids())
    check("A3b the count reports what was pruned", out.get("pruned") == 2, out.get("pruned"))

    mapped = market.installed_map()
    check("A4 installed_map() follows the same truth",
          "live1" in mapped and "gone1" not in mapped and "gone2" not in mapped,
          sorted(mapped))

    report = market.audit()
    check("A5 audit() reports no drift for a reconciled record",
          report.get("drift") == 0, report)

    # A6 — a disabled client is still installed (it exists, it is just off).
    mcp_client.load_doc = lambda: {"clients": {"live1": {"url": "http://x", "enabled": False}}}
    check("A6 a present-but-disabled client stays installed",
          "mcp/live1" in sorted(r["id"] for r in market.installed()["installed"]),
          sorted(r["id"] for r in market.installed()["installed"]))

    # A7 — an unreadable owner must not prune.
    write_records([{"id": "mcp/gone1", "kind": "mcp", "name": "gone1", "target": "cfg"}])

    def _boom():
        raise OSError("config unreadable")
    mcp_client.load_doc = _boom
    out7 = market.installed()
    check("A7 an unreadable client document prunes nothing",
          out7.get("pruned") == 0 and out7["count"] == 1, out7)

    # A8 — no target means "cannot decide", never "gone".
    write_records([{"id": "skill/no-target", "kind": "skill", "name": "nt", "target": ""}])
    out8 = market.installed()
    check("A8 a skill record with no target is never pruned on a guess",
          out8.get("pruned") == 0 and out8["count"] == 1, out8)

    # A9 — deleting the client forgets the record at once.
    write_records([{"id": "mcp/rm1", "kind": "mcp", "name": "rm1", "target": "cfg"}])
    mcp_client.load_doc = lambda: {"clients": {"rm1": {"url": "http://x"}}}
    saved = {}
    real_local = mcp_client._load_local_doc
    real_save = mcp_client._save_local_doc
    real_reload = mcp_client.reload
    mcp_client._load_local_doc = lambda: {"clients": {"rm1": {"url": "http://x"}}}
    mcp_client._save_local_doc = lambda doc: saved.update(doc=doc) or "gist"
    mcp_client.reload = lambda: {"ok": True}
    try:
        res = mcp_client.remove_client("rm1")
    finally:
        mcp_client._load_local_doc = real_local
        mcp_client._save_local_doc = real_save
        mcp_client.reload = real_reload
    check("A9 remove_client() forgets the record immediately",
          res.get("ok") is True and "mcp/rm1" not in read_ids()
          and "rm1" not in (saved.get("doc") or {}).get("clients", {}),
          (res, read_ids()))
finally:
    mcp_client.load_doc = real_load

print("---")
passed = sum(results)
print("\nv1038: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
