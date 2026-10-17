#!/usr/bin/env python3
"""v488 — every config/*.yaml is editable from the WebUI (JAG-488).

The structured SETTINGS panels covered routing, tool policy, providers, subagents,
MCP clients, the knowledge indexes and the compaction policy. `decisions.yaml`
and `hooks.yaml` (and any future file) had no writer at all, so "change it from
the WebUI" was false for the whole config store.

`longrun.core.configfiles` is the generic editor: list -> read -> validate ->
atomic write -> hot-reload. This test drives it against a scratch directory and
source-locks the HTTP routes + the Settings panel.

Run: python3 tests/acceptance/v488_config_editor.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v488-")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import configfiles as cf  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A) the shipped store is fully listed -----------------------------------
SHIPPED = ["compaction.yaml", "decisions.yaml", "embedding.yaml", "hooks.yaml",
           "index.yaml", "mcp_clients.yaml", "providers.yaml", "routing.yaml",
           "subagents.yaml", "tools.yaml"]
check("A1 the editor points at <repo>/config",
      os.path.normpath(cf.CONFIG_DIR) == os.path.normpath(os.path.join(REPO, "config")),
      cf.CONFIG_DIR)
listed = {f["name"] for f in cf.list_files()}
missing = [n for n in SHIPPED if n not in listed]
check("A2 every shipped config file is listed", not missing, missing)
check("A3 the listing is YAML only", all(n.endswith((".yaml", ".yml")) for n in listed), listed)

# ---- B) isolate on a scratch directory --------------------------------------
cf.CONFIG_DIR = TMP
cf.BACKUP_DIR = os.path.join(TMP, "backups")
with open(os.path.join(TMP, "decisions.yaml"), "w", encoding="utf-8") as f:
    f.write("enabled: false\nmode: null\n")
with open(os.path.join(TMP, "notes.txt"), "w", encoding="utf-8") as f:
    f.write("not config\n")
os.makedirs(os.path.join(TMP, "subdir"), exist_ok=True)

check("B1 list_files ignores non-YAML files and subdirectories",
      [f["name"] for f in cf.list_files()] == ["decisions.yaml"],
      [f["name"] for f in cf.list_files()])
r = cf.read_file("decisions.yaml")
check("B2 read_file returns the real text", r.get("ok") and "enabled: false" in r["text"], r)

r = cf.write_file("decisions.yaml", "enabled: true\nmode: heuristic\n")
check("B3 a valid edit is written and reloaded",
      r.get("ok") and r.get("reloaded") == ["decisions (mtime-cached)"], r)
check("B4 the new content is on disk",
      open(os.path.join(TMP, "decisions.yaml"), encoding="utf-8").read().strip()
      == "enabled: true\nmode: heuristic")
check("B5 the previous version was backed up",
      r.get("backup") is True and os.path.isdir(cf.BACKUP_DIR)
      and len(os.listdir(cf.BACKUP_DIR)) == 1, os.listdir(cf.BACKUP_DIR))
with open(os.path.join(TMP, "crlf.yaml"), "wb") as f:
    f.write(b"a: 1\r\nb: 2\r\n")
r = cf.write_file("crlf.yaml", "a: 1\nb: 2\n")
raw = open(os.path.join(TMP, "crlf.yaml"), "rb").read()
check("B6 a CRLF file keeps its line endings on save",
      r.get("ok") and raw == b"a: 1\r\nb: 2\r\n", raw)

# ---- C) validation: a bad edit NEVER touches the file ------------------------
before = open(os.path.join(TMP, "decisions.yaml"), encoding="utf-8").read()
r = cf.write_file("decisions.yaml", "enabled: [unclosed\n")
check("C1 invalid YAML is rejected", not r.get("ok") and "invalid YAML" in r.get("error", ""), r)
check("C2 the file is untouched after a rejection",
      open(os.path.join(TMP, "decisions.yaml"), encoding="utf-8").read() == before)
r = cf.write_file("decisions.yaml", "- just\n- a list\n")
check("C3 a non-mapping top level is rejected",
      not r.get("ok") and "mapping" in r.get("error", ""), r)
check("C4 an empty file is valid (it means defaults)", cf.write_file("decisions.yaml", "")["ok"])
r = cf.write_file("empty.yaml", "a: 1\n")
check("C5 a new file can be created", r.get("ok") and os.path.isfile(os.path.join(TMP, "empty.yaml")), r)
check("C6 a missing file reads as not-found", cf.read_file("nope.yaml").get("ok") is False)

# ---- D) path traversal is impossible ----------------------------------------
for bad in ("../.env", "subdir/x.yaml", "/etc/passwd", "tools.YAML", "", ".hidden.yaml"):
    try:
        cf.read_file(bad)
        ok = False
    except ValueError:
        ok = True
    check("D1 rejects %r" % (bad or "<empty>"), ok)

# ---- E) the sandbox block has a writer too (JAG-488) ------------------------
from longrun.core import api_v02  # noqa: E402

state = {"cfg": {"sandbox": {"backend": "none", "image": "alpine:latest",
                             "timeout_secs": 900, "network": True,
                             "memory_mb": 256, "pids_limit": 128,
                             "cpus": "1.0", "workspace": "data/sandbox"},
                 "tools": {}}}
_orig = (api_v02.registry.load_config, api_v02.registry.save_config,
         api_v02.registry.catalog, api_v02.sandbox.probe,
         api_v02.sandbox.invalidate_probe)
api_v02.registry.load_config = lambda reload=False: state["cfg"]
api_v02.registry.save_config = lambda cfg: state.__setitem__("cfg", cfg)
api_v02.registry.catalog = lambda: []
api_v02.sandbox.probe = lambda force=False: {"requested": "auto", "backend": "docker",
                                             "isolated": True, "available": {}}
api_v02.sandbox.invalidate_probe = lambda: None
try:
    r = api_v02._update_policy({"sandbox": {"backend": "auto", "memory_mb": 512}})
    check("E1 the sandbox block is writable (backend + memory)",
          r.get("ok") and state["cfg"]["sandbox"]["backend"] == "auto"
          and state["cfg"]["sandbox"]["memory_mb"] == 512, r)
    r = api_v02._update_policy({"sandbox": {"backend": "podman"}})
    check("E2 an unknown backend is rejected",
          not r.get("ok") and "backend" in r.get("error", ""), r)
    r = api_v02._update_policy({"sandbox": {"memory_mb": 1}})
    check("E3 an out-of-range memory value is rejected",
          not r.get("ok") and "memory_mb" in r.get("error", ""), r)
    r = api_v02._update_policy({"sandbox": {"workspace": "/etc"}})
    check("E4 an absolute workspace is rejected",
          not r.get("ok") and "workspace" in r.get("error", ""), r)
    r = api_v02._update_policy({"sandbox": {"cpus": "0"}})
    check("E5 a non-positive cpu value is rejected",
          not r.get("ok") and "cpus" in r.get("error", ""), r)
finally:
    (api_v02.registry.load_config, api_v02.registry.save_config,
     api_v02.registry.catalog, api_v02.sandbox.probe,
     api_v02.sandbox.invalidate_probe) = _orig

# ---- F) the WebUI + the HTTP routes are wired -------------------------------
api_src = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
               encoding="utf-8").read()
ui_src = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("E1 GET /api/config/files is routed", '"/api/config/files"' in api_src)
check("E2 GET/POST /api/config/file is routed",
      api_src.count('"/api/config/file"') >= 2, api_src.count('"/api/config/file"'))
check("E3 POST validates before writing (configfiles.write_file)",
      "configfiles.write_file" in api_src)
check("E4 the Settings panel has a config category",
      '["config", "Config files"]' in ui_src)
check("E5 the panel has a file selector + editor + save",
      all(k in ui_src for k in ('id="cfgFileName"', 'id="cfgFileText"',
                                "function loadConfigFiles", "function saveConfigFile")))
check("E6 the panel loads when the category opens",
      'name === "config"' in ui_src and "loadConfigFiles()" in ui_src)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
