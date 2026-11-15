#!/usr/bin/env python3
"""v1022 — Manage: the installed record tracks the catalogue, and drift is reported.

  A  a newer catalogue entry marks the installed row `update_available`
  B  updating reinstalls through the verified path (digest checked again)
  C  audit reports a record whose owner lost the object — and repairs nothing
  D  a plugin entry installs through Matrix (no second installer) and refuses an empty bundle
  E  the Manage view renders update, drift and remove from those routes
"""
import hashlib
import io
import json
import os
import sys
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="sf-v1022-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_TMP, "data", "sessions")
# v1022 isolation: skills resolve from the REPO, so point them at the temp home —
# an install here must never create a skill in the operator's checkout.
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(_TMP, "skills")
os.environ["LONGRUN_SKILLS_LOCAL_DIR"] = os.path.join(_TMP, "skills", "local")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import market  # noqa: E402
from longrun.memory import skills  # noqa: E402

JS = open(os.path.join(REPO, "webui", "assets", "market.js"), encoding="utf-8").read()
results = []
_orig_fetch = market._fetch


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def zip_of(name, note):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("%s/SKILL.md" % name, "---\nname: %s\ndescription: %s\n---\n%s\n" % (name, note, note))
    return buf.getvalue()


def catalog(items):
    path = market._local_catalog_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"schema": market.SCHEMA, "items": items}, f)


def entry(name, version, data):
    return {"id": "skill/%s" % name, "kind": "skill", "name": name, "title": name,
            "version": version, "sha256": hashlib.sha256(data).hexdigest(),
            "source": {"type": "https", "url": "https://h.test/%s.zip" % name}}


v1 = zip_of("tool", "v1")
catalog([entry("tool", "1.0.0", v1)])
market._config()["allow_hosts"] = ["h.test"]
market._fetch = lambda url, cfg, limit: (v1, "")
try:
    first = market.install("skill/tool")
finally:
    market._fetch = _orig_fetch
check("A0 the first install lands", first.get("ok") is True, first)
check("A1 nothing is an update yet", market.installed()["installed"][0]["update_available"] is False)

# ── A: the catalogue moves ─────────────────────────────────────────────────
v2 = zip_of("tool", "v2 with a longer body")
catalog([entry("tool", "2.0.0", v2)])
row = market.installed()["installed"][0]
check("A2 a newer version marks the row update_available", row["update_available"] is True, row)

# ── B: update goes through the verified path ───────────────────────────────
market._fetch = lambda url, cfg, limit: (v2, "")
try:
    upd = market.install("skill/tool", overwrite=True)
finally:
    market._fetch = _orig_fetch
check("B1 the update installs", upd.get("ok") is True, upd)
row = market.installed()["installed"][0]
check("B2 the record now carries the new version and digest",
      row["version"] == "2.0.0" and row["sha256"] == hashlib.sha256(v2).hexdigest(), row)
check("B3 the row is no longer an update", row["update_available"] is False)
market._fetch = lambda url, cfg, limit: (b"tampered", "")
try:
    bad = market.install("skill/tool", overwrite=True)
finally:
    market._fetch = _orig_fetch
check("B4 an update with the wrong bytes is REFUSED and changes nothing",
      bad.get("ok") is False and market.installed()["installed"][0]["sha256"] == hashlib.sha256(v2).hexdigest())

# ── C: the record follows its owner (pruned on read, never "repaired") ─────
skills.remove("tool")
inst = market.installed()
check("C1 a record whose owner lost the object is pruned on read",
      inst["count"] == 0 and inst.get("pruned") == 1, inst)
check("C2 audit reports no drift: the record is gone, not repaired",
      market.audit()["drift"] == 0)
market._write_installed([{"id": "skill/tool", "kind": "skill", "name": "tool",
                          "target": "", "origin": "local"}])
check("C3 a forget removes the record", market.forget("skill/tool")["ok"] is True
      and market.installed()["count"] == 0)

# ── D: Matrix bundles go through Matrix, never a second installer ──────────
from longrun.core import matrix  # noqa: E402

catalog([{"id": "matrix/learned", "kind": "matrix", "name": "learned", "title": "Learned pack",
          "sha256": "e" * 64, "source": {"type": "https", "url": "https://h.test/p.zip"},
          "bundle": [{"kind": "tool", "name": "learned_x", "content": "#"}]}])
seen = {}
_orig_apply = matrix.apply_learning


def _fake_apply(bundle, repo_root=None):
    seen["bundle"] = bundle
    return {"ok": True, "installed": ["learned_x"], "failed": []}


matrix.apply_learning = _fake_apply
try:
    pres = market.install("matrix/learned")
finally:
    matrix.apply_learning = _orig_apply
check("D1 a Matrix bundle installs through matrix.apply_learning", pres.get("ok") is True, pres)
check("D2 the bundle reached Matrix unchanged", seen.get("bundle") and seen["bundle"][0]["name"] == "learned_x")
catalog([{"id": "matrix/empty", "kind": "matrix", "name": "empty", "title": "Empty",
          "sha256": "f" * 64, "source": {"type": "https", "url": "https://h.test/e.zip"}}])
check("D3 a Matrix entry with no bundle is refused by name",
      "no bundle" in market.install("matrix/empty")["error"])

# ── E: the Manage view is wired to those routes ────────────────────────────
check("E1 Manage asks the audit route", 'api("GET", "/api/market/audit")' in JS)
check("E2 an update-available row offers Update", 'class="ghost mkt-update"' in JS)
check("E3 Update reinstalls with overwrite (digest verified again)",
      "install(upd.getAttribute(\"data-id\"), true)" in JS)
check("E4 drift is shown as a banner, not swallowed", "disagree with their owner" in JS)
check("E5 remove is one control per row", 'class="ghost mkt-remove"' in JS)

print("\n---\nv1022: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
