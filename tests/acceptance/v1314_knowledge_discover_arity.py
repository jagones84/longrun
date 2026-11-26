#!/usr/bin/env python3
"""v1314 — knowledge.discover must unpack the REAL searcher arity.

`_web_search` has returned `(results, engine, notes)` since 2026-11-16 (v605
follow-up), but `knowledge.discover` unpacked two values, so **every** discover
call failed with "too many values to unpack" — reachable via the tool
(`knowledge action=discover`), the CLI (`forge.py knowledge discover`) and
`POST /api/knowledge/discover`. The bug survived because the acceptance stubs
returned a 2-tuple, which matched the broken caller instead of the real searcher.

This pin ties the caller to the real function, so the arity cannot silently drift
again.

Deterministic: no model, no network, no server. Run:
    python3 tests/acceptance/v1314_knowledge_discover_arity.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

_TMP = tempfile.mkdtemp(prefix="sf-v1314-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "KNOWLEDGE_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(_TMP, _k)
    os.makedirs(os.path.join(_TMP, _k), exist_ok=True)
os.environ["LONGRUN_DATA_HOME"] = _TMP

from longrun.memory import knowledge as kb  # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


# A · THE contract: the real searcher returns three values, and the caller unpacks three.
_r = kb._default_searcher("", 5)   # empty query short-circuits before any network
check("A1 the real searcher returns a 3-tuple (results, engine, notes)",
      isinstance(_r, tuple) and len(_r) == 3, "got %r" % (type(_r).__name__,))

kb.SEARCH = lambda q, n: ([{"title": "T", "url": "https://ex.com/a", "snippet": "s"}],
                          "stub", [])
_disc = kb.discover("anything")
check("A2 discover succeeds against the 3-tuple contract",
      _disc.get("ok") is True and len(_disc.get("candidates", [])) == 1, _disc)
check("A3 the engine is carried through", _disc.get("engine") == "stub", _disc)

# B · a 2-tuple (the old, wrong stub shape) is now the FAILING case, not the passing one.
kb.SEARCH = lambda q, n: ([{"title": "T", "url": "https://ex.com/a"}], "stub")
_bad = kb.discover("anything")
check("B1 a 2-tuple searcher is rejected, not silently mis-unpacked",
      _bad.get("ok") is False and "unpack" in (_bad.get("error") or ""), _bad)

print()
if FAILED:
    print("FAILED %d/%d: %s" % (len(FAILED), len(CHECKS), ", ".join(FAILED)))
    sys.exit(1)
print("OK %d/%d" % (len(CHECKS), len(CHECKS)))
