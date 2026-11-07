#!/usr/bin/env python3
"""v855 — the shipped tools config is parsed once per FILE VERSION, not per caller.

Measured on the DGX (2026-11-07, `.agent/trash/prof_catalog.py`): `registry.catalog()`
cost 16.7 ms, of which **13.6 ms was `shipped_tools()` -> `_load_raw()` re-reading and
re-parsing `config/tools.yaml``. `catalog()` runs on EVERY system-prompt render — twice
per render, because the `tools` section and the `longrun-agent` subtool list both ask
for it — so ~27 ms of a 42 ms prompt build was literally reparsing the same bytes,
on every session switch, every panel refresh and every turn.

The fix memoises the parse by the file's own identity `(path, mtime_ns, size)`, so an
edit can never be missed, and hands out a COPY so a caller's mutation cannot corrupt
the memo (copy 0.10 ms vs parse 13.7 ms).

What this pins:
  A) a second read of an UNCHANGED file is a memo hit (one parse, equal value);
  B) an EDITED file is re-parsed (the signature changed — no stale config, ever);
  C) a caller that mutates the returned dict cannot poison the next call;
  D) a DELETED file falls back to defaults instead of serving the last memo;
  E) the public surface still answers: `catalog()` and `load_config(reload=True)`.

Deterministic, no model, no network.

Run:  python3 tests/acceptance/v855_registry_config_parse_memo.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v855-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
sys.path.insert(0, os.path.join(REPO, "src"))

import yaml  # noqa: E402

from longrun.tools import registry  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- isolation: a temp config, no MCP / Matrix / promoted discovery ----
CFG = os.path.join(TMP, "tools.yaml")
registry.CONFIG_YAML = CFG
registry.CONFIG_JSON = os.path.join(TMP, "tools.json")     # does not exist
registry._raw_memo = None
registry._external_tools = lambda: {}
registry._matrix_tools = lambda: {}
registry._promoted_tools = lambda: {}

_parses = []
_real_load = yaml.safe_load


def _counting_load(stream, *a, **k):
    _parses.append(1)
    return _real_load(stream, *a, **k)


yaml.safe_load = _counting_load


def write_cfg(enabled):
    """Write the config and make sure its signature really changed."""
    with open(CFG, "w", encoding="utf-8") as f:
        f.write("tools:\n  demo.tool:\n    enabled: %s\n" % ("true" if enabled else "false"))
    st = os.stat(CFG)
    os.utime(CFG, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


# ---- A: an unchanged file is parsed ONCE ----
write_cfg(True)
first = registry.shipped_tools()
second = registry.shipped_tools()
check("A1 the value is what the file says",
      isinstance(first, dict) and (first.get("demo.tool") or {}).get("enabled") is True,
      str(first))
check("A2 one parse for two reads of an unchanged file", len(_parses) == 1,
      "parses=%d" % len(_parses))
check("A3 both reads answer the same value", first == second)

# ---- B: an EDITED file is re-parsed ----
write_cfg(False)
third = registry.shipped_tools()
check("B1 an edit is visible (no stale config)",
      (third.get("demo.tool") or {}).get("enabled") is False, str(third))
check("B2 the edit cost exactly one more parse", len(_parses) == 2,
      "parses=%d" % len(_parses))

# ---- C: a caller's mutation cannot poison the memo ----
victim = registry.shipped_tools()
victim["demo.tool"]["enabled"] = "MUTATED"
after = registry.shipped_tools()
check("C1 the next reader still sees the file's value",
      (after.get("demo.tool") or {}).get("enabled") is False, str(after))
check("C2 a mutation does not trigger a re-parse", len(_parses) == 2,
      "parses=%d" % len(_parses))

# ---- D: a DELETED file falls back to defaults, not to the memo ----
os.unlink(CFG)
gone = registry.shipped_tools()
check("D1 a deleted config falls back to defaults", gone == {}, str(gone))

# ---- E: the public surface still answers ----
write_cfg(True)
rows = registry.catalog()
check("E1 catalog() still returns rows", isinstance(rows, list) and len(rows) > 0,
      "rows=%d" % (len(rows) if isinstance(rows, list) else -1))
check("E2 every row keeps its contract",
      all(r.get("name") and "enabled" in r for r in rows))
reloaded = registry.load_config(reload=True)
check("E3 load_config(reload=True) reads the file again",
      (reloaded.get("tools") or {}).get("demo.tool", {}).get("enabled") is True,
      str((reloaded.get("tools") or {}).get("demo.tool")))

print("")
print("%d/%d GREEN" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
