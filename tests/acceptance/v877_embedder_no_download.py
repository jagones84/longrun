#!/usr/bin/env python3
"""v877 — memory never DOWNLOADS model weights inside a turn.

Measured 2026-11-08 on this host: a cold HF cache made `_rebuild_index()` fetch
`all-MiniLM-L6-v2` from the Hub ("unauthenticated requests to the HF Hub"
warnings, still running after 90 s), so the FAST battery depended on the NETWORK
and on the model cache instead of the code. `_get_embedder()` must ask for LOCAL
files only; a missing model falls back (endpoint, then bag-of-words) as before.

A1 the loader passes local_files_only=True
A2 the model id is unchanged (a cached copy is still used)
A3 a loader that cannot load offline yields None and is never retried

Run: python3 tests/acceptance/v877_embedder_no_download.py
"""
import os
import sys
import tempfile
import types

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v877-")
os.environ.setdefault("LONGRUN_DATA_DIR", os.path.join(TMP, "data"))
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(TMP, "cfg"))
os.environ.setdefault("LONGRUN_DB", os.path.join(TMP, "events.db"))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import memory as mem   # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


seen = {}


class _Fake:
    def __init__(self, name, **kw):
        seen["name"] = name
        seen["kw"] = dict(kw)

    def encode(self, texts, **kw):
        return [[0.0] for _ in texts]


mod = types.ModuleType("sentence_transformers")
mod.SentenceTransformer = _Fake
sys.modules["sentence_transformers"] = mod

try:
    mem._EMBEDDER = None
    mem._EMBEDDER_READY = False
    emb = mem._get_embedder()
    check("A1 the loader asks for LOCAL files only (no Hub download)",
          (seen.get("kw") or {}).get("local_files_only") is True, seen.get("kw"))
    check("A2 the model id is unchanged",
          seen.get("name") == "all-MiniLM-L6-v2" and emb is not None, seen.get("name"))

    attempts = {"n": 0}

    class _Boom:
        def __init__(self, *a, **k):
            attempts["n"] += 1
            raise TypeError("offline mode unsupported")

    mod.SentenceTransformer = _Boom
    mem._EMBEDDER = None
    mem._EMBEDDER_READY = False
    first = mem._get_embedder()
    second = mem._get_embedder()
    check("A3 a loader that cannot load offline yields None and is not retried",
          first is None and second is None and attempts["n"] == 1,
          "attempts=%d" % attempts["n"])
finally:
    sys.modules.pop("sentence_transformers", None)

print("---")
okc = sum(results)
print("\nv877: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
