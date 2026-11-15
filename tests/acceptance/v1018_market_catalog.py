#!/usr/bin/env python3
"""v1018 — the marketplace catalogue is data, and its install gate is a digest.

The catalogue must never be able to install something it cannot verify:
  A  the defaults are inert (no catalogue, no allowed host, nothing installable)
  B  a local catalogue is merged, deduped by id, and a malformed entry is dropped
  C  a skill entry with no sha256 is BROWSABLE and NOT installable
  D  an mcp entry is installable from its `server` block (a preset, not bytes)
  E  install refuses: unknown id, missing digest, a host outside allow_hosts
  F  a digest mismatch is refused by name and NOTHING is written
  G  installed.json records what was installed; audit reports drift
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-v1018-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_TMP, "data", "sessions")
# v1018 isolation: skills resolve from the REPO (`skills/`), not from the data home,
# so an install in this test would otherwise write a real skill into the operator's
# checkout — the same defect class v507/v973 fixed for the memory store.
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_TMP, "skills")
os.environ["LONGRUN_SKILLS_LOCAL_DIR"] = os.path.join(_TMP, "skills", "local")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import market  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def write_local(items):
    path = market._local_catalog_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"schema": market.SCHEMA, "items": items}, f)


# ── A: defaults are inert ────────────────────────────────────────────────────
cfg = market.config_view()
check("A1 no catalogue source and no allowed host by default",
      cfg["catalogs"] == [] and cfg["allow_hosts"] == [], cfg)
check("A2 an empty catalogue returns zero items, not an error",
      market.search()["items"] == [] and market.search()["errors"] == [])

# ── B: merge + dedupe + malformed drop ───────────────────────────────────────
write_local([
    {"id": "skill/one", "kind": "skill", "name": "one", "title": "One",
     "category": "Research", "sha256": "a" * 64, "source": {"type": "https", "url": "https://h.test/1.zip"}},
    {"id": "skill/one", "kind": "skill", "name": "one", "title": "One (duplicate)",
     "sha256": "b" * 64, "source": {"type": "https", "url": "https://h.test/1b.zip"}},
    {"id": "BROKEN ID", "kind": "skill", "name": "x"},           # bad slug -> dropped
    {"id": "skill/two", "kind": "telepathy", "name": "two"},      # unknown kind -> dropped
])
res = market.search()
ids = [i["id"] for i in res["items"]]
check("B1 duplicates collapse to ONE id and the first entry wins",
      ids.count("skill/one") == 1 and res["items"][0]["title"] == "One", ids)
check("B2 the duplicate is counted, not silently lost",
      res["items"][0].get("duplicates") == 1, res["items"][0].get("duplicates"))
check("B3 a malformed id and an unknown kind are dropped",
      "BROKEN ID" not in ids and "skill/two" not in ids, ids)
check("B4 categories are the distinct ones the entries declare",
      res["categories"] == ["Research"], res["categories"])

# ── C: no digest -> browsable, not installable ───────────────────────────────
write_local([
    {"id": "skill/nodigest", "kind": "skill", "name": "nodigest", "title": "No digest",
     "category": "Research", "source": {"type": "https", "url": "https://h.test/n.zip"}},
])
item = market.search()["items"][0]
check("C1 a skill with no sha256 is listed", item["id"] == "skill/nodigest")
check("C2 … and is NOT installable", item["installable"] is False)

# ── D: an mcp preset is installable from its server block ────────────────────
write_local([
    {"id": "mcp/files", "kind": "mcp", "name": "files", "title": "Filesystem",
     "category": "Developer Tools", "server": {"command": "npx", "args": ["-y", "pkg", "/tmp"]}},
    {"id": "mcp/empty", "kind": "mcp", "name": "empty", "title": "Empty", "server": {}},
])
by = {i["id"]: i for i in market.search()["items"]}
check("D1 a server with command/args is installable", by["mcp/files"]["installable"] is True)
check("D2 a server block with neither command nor url is not installable",
      by["mcp/empty"]["installable"] is False)

# ── E: install refusals, each named ─────────────────────────────────────────
check("E1 an unknown id is refused by name",
      market.install("nope")["error"].startswith("unknown item"))
write_local([
    {"id": "skill/nodigest", "kind": "skill", "name": "nodigest", "title": "No digest",
     "source": {"type": "https", "url": "https://h.test/n.zip"}},
    {"id": "skill/hosted", "kind": "skill", "name": "hosted", "title": "Hosted",
     "sha256": "c" * 64, "source": {"type": "https", "url": "https://evil.test/h.zip"}},
])
check("E2 an entry without sha256 is refused before any fetch",
      "no sha256" in market.install("skill/nodigest")["error"])
refused = market.install("skill/hosted")
check("E3 a host outside allow_hosts is refused",
      "allow_hosts" in refused["error"], refused.get("error"))

# ── F: a digest mismatch writes NOTHING ─────────────────────────────────────
from longrun.memory import skills  # noqa: E402

write_local([
    {"id": "skill/tampered", "kind": "skill", "name": "tampered", "title": "Tampered",
     "sha256": "d" * 64, "source": {"type": "https", "url": "https://h.test/t.zip"}},
])
market._config()["allow_hosts"] = ["h.test"]           # the only concession: the host
_orig_fetch = market._fetch
market._fetch = lambda url, cfg, limit: (b"not-the-hashed-bytes", "")
try:
    res = market.install("skill/tampered")
finally:
    market._fetch = _orig_fetch
check("F1 a digest mismatch is refused by name",
      res.get("ok") is False and "digest mismatch" in res.get("error", ""), res.get("error"))
check("F2 the mismatch names expected and actual digests",
      res.get("error", "").count("d" * 64) == 1 and "got" in res.get("error", ""))
check("F3 nothing was installed and no record was written",
      not os.path.isdir(os.path.join(skills._local_dir(), "tampered"))
      and market.installed()["count"] == 0)

# ── G: a good install records; audit reports drift ───────────────────────────
import hashlib  # noqa: E402
import io  # noqa: E402
import zipfile  # noqa: E402


def _skill_zip(name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("%s/SKILL.md" % name, "---\nname: %s\ndescription: d\n---\nBody\n" % name)
    return buf.getvalue()


good = _skill_zip("good")
write_local([
    {"id": "skill/good", "kind": "skill", "name": "good", "title": "Good",
     "sha256": hashlib.sha256(good).hexdigest(),
     "source": {"type": "https", "url": "https://h.test/good.zip"}},
])
market._config()["allow_hosts"] = ["h.test"]
market._fetch = lambda url, cfg, limit: (good, "")
try:
    res = market.install("skill/good")
finally:
    market._fetch = _orig_fetch
check("G1 a verified skill installs", res.get("ok") is True, res)
check("G2 the installed record carries id, digest and source",
      market.installed()["count"] == 1
      and market.installed()["installed"][0]["sha256"] == hashlib.sha256(good).hexdigest())
rows = market.audit()["rows"]
check("G3 audit reports the skill's owner", rows and rows[0]["owner"] == "memory.skills", rows)
check("G4 forgetting the record leaves the files alone",
      market.forget("skill/good")["ok"] is True and market.installed()["count"] == 0
      and os.path.isdir(os.path.join(skills._local_dir(), "good")))

print("\n---\nv1018: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
