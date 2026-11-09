#!/usr/bin/env python3
"""v921 — the routing config is handed out as a copy and saved atomically (DR-N).

Two defects, one owner:
  * `load_config()` returned the module cache ITSELF, so any caller that mutated
    what it received changed the live routing for every later turn — a writer
    with no save, no audit row, and no way to find it.
  * `save_config()` wrote `config/routing.yaml` in place, so an interrupted save
    (kill, crash, full disk) left a half file the next start cannot parse.

Now the cache is a deep copy in both directions and the write is tmp + os.replace.

Deterministic: a temp CONFIG_PATH, no model, no network, no server.
"""
import json
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="sf-v921-")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import routing  # noqa: E402
from longrun.util import fswrite  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


CFG_PATH = os.path.join(_tmp, "routing.yaml")
routing.CONFIG_PATH = CFG_PATH
routing._cache = None

BASE = {"roles": {"chat": {"pattern": "a", "fallbacks": []},
                  "agent": {"pattern": "b", "fallbacks": ["x"]}},
        "default_fallbacks": []}
routing.save_config(dict(BASE))

# ---- A: the returned dict is not the cache -----------------------------------
cfg = routing.load_config()
check("A1 a read returns a copy, not the cache itself",
      cfg is not routing._cache, type(cfg).__name__)
cfg["roles"]["chat"]["pattern"] = "HIJACKED"
cfg["default_fallbacks"].append("evil")
check("A2 a NESTED mutation does not reach the next read",
      routing.load_config()["roles"]["chat"]["pattern"] == "a",
      routing.load_config()["roles"]["chat"]["pattern"])
check("A3 a top-level mutation does not reach the next read",
      routing.load_config()["default_fallbacks"] == [],
      routing.load_config()["default_fallbacks"])
check("A4 the file on disk was never touched by a read",
      "HIJACKED" not in open(CFG_PATH, encoding="utf-8").read(), "")

# ---- B: save keeps a copy of what it was given --------------------------------
given = routing.load_config()
given["roles"]["agent"]["pattern"] = "c"
routing.save_config(given)
given["roles"]["agent"]["pattern"] = "MUTATED-AFTER-SAVE"
check("B1 the save persisted the value at save time",
      routing.load_config()["roles"]["agent"]["pattern"] == "c",
      routing.load_config()["roles"]["agent"]["pattern"])
check("B2 mutating the caller's dict after the save cannot change the cache",
      routing._cache["roles"]["agent"]["pattern"] == "c",
      routing._cache["roles"]["agent"]["pattern"])
check("B3 a reload reads the same value back from disk",
      routing.load_config(reload=True)["roles"]["agent"]["pattern"] == "c",
      routing.load_config(reload=True)["roles"]["agent"]["pattern"])

# ---- C: an interrupted save leaves the previous file intact -------------------
_before = open(CFG_PATH, encoding="utf-8").read()
_orig_replace = fswrite.os.replace


def _boom(src, dst):
    raise OSError("interrupted")


fswrite.os.replace = _boom
try:
    try:
        routing.save_config({"roles": {"chat": {"pattern": "NEW"}},
                             "default_fallbacks": ["x"]})
        _raised = False
    except OSError:
        _raised = True
finally:
    fswrite.os.replace = _orig_replace
_after = open(CFG_PATH, encoding="utf-8").read()
check("C1 the failure is surfaced, not swallowed", _raised is True, _raised)
check("C2 the previous file is byte-identical (no half-written YAML)",
      _after == _before, (_before[:40], _after[:40]))
check("C3 the file still parses as the old config",
      routing.load_config(reload=True)["roles"]["chat"]["pattern"] == "a",
      routing.load_config(reload=True)["roles"]["chat"]["pattern"])

# ---- D: no temp file is left behind in the config directory -------------------
_leftovers = [n for n in os.listdir(_tmp) if ".tmp" in n]
check("D1 no .tmp file is left next to the config", not _leftovers, _leftovers)

# ---- E: the comment-preserving save still works ------------------------------
with open(CFG_PATH, "w", encoding="utf-8") as f:
    f.write("# operator note: keep me\nroles:\n  chat:\n    pattern: a\n")
routing._cache = None
cfg = routing.load_config()
cfg["roles"]["chat"]["fallbacks"] = ["y"]
routing.save_config(cfg)
_saved = open(CFG_PATH, encoding="utf-8").read()
check("E1 a settings save still keeps the operator's comment",
      "# operator note: keep me" in _saved, _saved[:80])
check("E2 and still persists the new value",
      routing.load_config(reload=True)["roles"]["chat"]["fallbacks"] == ["y"],
      routing.load_config(reload=True)["roles"]["chat"]["fallbacks"])

# ---- F: the single write path is the atomic one -------------------------------
_src = open(os.path.join(REPO, "src", "longrun", "model", "routing.py"),
            encoding="utf-8").read()
check("F1 routing.py no longer opens the config for writing directly",
      'open(CONFIG_PATH, "w"' not in _src, "")
check("F2 it writes through fswrite.write_text",
      "write_text(CONFIG_PATH" in _src, "")

print("\n---\nv921: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
