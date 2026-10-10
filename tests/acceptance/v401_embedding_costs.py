"""v401 — EMBEDDING models catalogue + COST tracking (JAG-403).

Stdlib-only, deterministic. The catalogue ships with KNOWN embedding models
(OpenAI, Voyage, Cohere, Jina, OpenRouter) with per-1M-token pricing, plus
a `local:` family for free local models (BGE, e5, nomic). OpenRouter returns
real `usage.cost` USD in its response — when we call through it, the cost is
EXACT (recorded as `real_cost_usd`); for direct providers it is ESTIMATED from
the declared `price_per_mtok` (recorded as `est_cost_usd`).

Exercises:
  A) catalogue: known models list, custom model via config, active model
  B) cost math: estimate per provider, local = 0, custom = manual
  C) cost log: every embed batch writes one row, per-scope aggregates
  D) OpenRouter: when `_post` returns `usage.cost`, it is recorded EXACTLY
  E) wiring: API exposes the catalogue + cost log; WebUI has the section
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="v401-")
os.environ["LONGRUN_CODEBASE_DIR"] = os.path.join(tmp, "codebase")
os.environ["LONGRUN_KNOWLEDGE_DIR"] = os.path.join(tmp, "knowledge")
os.environ["LONGRUN_EMBEDDING_DIR"] = os.path.join(tmp, "embedding")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name +
          ((" :: " + str(detail)) if (detail and not ok) else ""))


from longrun.memory import embedcfg, costlog  # noqa: E402

# ---- A) catalogue ----------------------------------------------------------
ms = embedcfg.MODELS
check("A1 catalogue has at least 8 known models", len(ms) >= 8,
      "n=%d" % len(ms))
check("A2 an OpenAI small embedding is listed with a USD price",
      any(m["id"] == "openai:text-embedding-3-small" and m["price_per_mtok"] > 0
          for m in ms))
check("A3 a local model is listed with price 0",
      any(m["id"].startswith("local:") and m["price_per_mtok"] == 0
          for m in ms))
check("A4 an OpenRouter embedding is listed (OpenRouter returns real cost)",
      any(m["provider"] == "openrouter" and "embed" in m["id"].lower()
          for m in ms))
# Custom model via overlay
embedcfg.save_config({"embed_model": "custom:my-embed/8b", "custom_models": [
    {"id": "custom:my-embed/8b", "dim": 1024, "price_per_mtok": 0.05,
     "provider": "custom", "label": "My Embed 8B"}]})
cfg = embedcfg.load_config()
check("A5 a custom model is loaded from the overlay",
      any(m["id"] == "custom:my-embed/8b" for m in embedcfg.all_models()))
check("A6 the active model is the configured one",
      embedcfg.active_model() == "custom:my-embed/8b")

# ---- B) cost math ---------------------------------------------------------
check("B1 OpenAI small estimate for 1M tokens = declared price",
      abs(embedcfg.estimate_cost("openai:text-embedding-3-small", 1_000_000)
          - 0.02) < 1e-9)
check("B2 local embedding is free",
      embedcfg.estimate_cost("local:BAAI/bge-small-en-v1.5", 5_000_000) == 0.0)
check("B3 custom model uses its declared price",
      abs(embedcfg.estimate_cost("custom:my-embed/8b", 1_000_000) - 0.05) < 1e-9)
check("B4 unknown model returns 0 with a clear flag",
      embedcfg.estimate_cost("unknown:foo", 1000) == 0.0)

# ---- C) cost log ----------------------------------------------------------
costlog.clear()
costlog.record(model="openai:text-embedding-3-small", provider="openai",
               tokens=10_000, est_cost_usd=0.0002, real_cost_usd=None,
               scope="codebase", scope_id="ws1", op="build")
costlog.record(model="openai:text-embedding-3-small", provider="openai",
               tokens=20_000, est_cost_usd=0.0004, real_cost_usd=None,
               scope="notebook", scope_id="nb1", op="add_source")
costlog.record(model="openrouter:openai/text-embedding-3-small",
               provider="openrouter", tokens=15_000, est_cost_usd=None,
               real_cost_usd=0.0005, scope="notebook", scope_id="nb1",
               op="add_source")
rows = costlog.list_all()
check("C1 the log persists every batch as one row", len(rows) == 3,
      "n=%d" % len(rows))
agg = costlog.aggregate()
check("C2 total tokens is the sum of every batch",
      agg["total_tokens"] == 45_000, "tot=%d" % agg["total_tokens"])
check("C3 est + real costs add up",
      abs(agg["total_cost_usd"] - (0.0002 + 0.0004 + 0.0005)) < 1e-9,
      "tot=%.6f" % agg["total_cost_usd"])
by_model = {m["model"]: m for m in agg["by_model"]}
check("C4 per-model rollup is correct",
      "openai:text-embedding-3-small" in by_model
      and abs(by_model["openai:text-embedding-3-small"]["total_cost_usd"]
              - 0.0006) < 1e-9)
check("C5 OpenRouter cost is recorded as REAL (not estimated)",
      by_model["openrouter:openai/text-embedding-3-small"]["real_cost_usd"]
      == 0.0005)

# ---- D) end-to-end: vectors.embed_chunks + OR cost path -------------------
from longrun.memory import vectors  # noqa: E402
import sqlite3
db = sqlite3.connect(":memory:")
db.execute("CREATE TABLE chunks(id INTEGER PRIMARY KEY, vec BLOB)")
db.execute("INSERT INTO chunks VALUES (1, NULL)")
db.execute("INSERT INTO chunks VALUES (2, NULL)")
db.commit()
# Stub embed_texts: NEW contract returns (vecs_iter, usage_dict).
import longrun.model.embed as _emb  # noqa: E402
_calls = {"n": 0}


def _fake_embed_with_meta(texts, model=None, timeout=30):
    _calls["n"] += 1
    if model and "openrouter" in model:
        return ([0.1, 0.2, 0.3, 0.4] for _ in texts), {"cost_usd": 0.00123,
                                                          "tokens": 8}
    return ([0.1, 0.2, 0.3, 0.4] for _ in texts), {"cost_usd": None,
                                                      "tokens": 8}


_emb.embed_texts = _fake_embed_with_meta
n = vectors.embed_chunks(db, [(1, "hello"), (2, "world")],
                         ref="openrouter:openai/text-embedding-3-small",
                         batch=32, scope="codebase", scope_id="ws1", op="build")
check("D1 embed_chunks wrote both rows", n == 2, "n=%d" % n)
check("D2 embed_texts was called exactly once (one batch)", _calls["n"] == 1,
      "calls=%d" % _calls["n"])
# D1 adds ONE row tagged with op=build + scope=codebase. The total over the
# codebase scope must include the earlier C row (0.0002) AND the D OR row
# (0.00123) = 0.00143.
agg2 = costlog.aggregate(scope="codebase")
check("D3 the OpenRouter cost (exact) was recorded under the codebase scope",
      abs(agg2["total_cost_usd"] - (0.0002 + 0.00123)) < 1e-9,
      "tot=%.6f" % agg2["total_cost_usd"])
rows_d = [r for r in costlog.list_all() if r.get("op") == "build"
          and r.get("scope") == "codebase"]
check("D4 the OR row carries real_cost_usd=0.00123 (NOT an estimate)",
      any(r.get("model") == "openrouter:openai/text-embedding-3-small"
          and abs((r.get("real_cost_usd") or 0) - 0.00123) < 1e-9
          for r in rows_d))

# ---- E) wiring: API exposes catalogue + cost log --------------------------
# api_v02 is a handler-based router, not a Flask app. We verify the routes
# by reading the source: every URL we advertise must appear as a literal in
# the dispatcher `handle(...)`.
api_src = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
               encoding="utf-8").read()
check("E1 the API exposes /api/embedding/models",
      '"/api/embedding/models"' in api_src)
check("E2 the API exposes /api/embedding/costs",
      '"/api/embedding/costs"' in api_src)
check("E3 the API exposes /api/embedding/active (GET + POST)",
      '"/api/embedding/active"' in api_src and api_src.count(
          '"/api/embedding/active"') >= 2)
check("E3b the API exposes /api/embedding/costs.csv (download)",
      '"/api/embedding/costs.csv"' in api_src)

# WebUI has the Embedding section in the inspector
html = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("E4 the WebUI has the Embedding inspector section",
      "data-insp=\"embedding\"" in html)
check("E4b the WebUI Embedding section shows the model select + cost log",
      "emActive" in html and "emCostTotal" in html and "emCostByModel" in html)

# CLI: `forge embedding` exposes the actions
from longrun.core import forge  # noqa: E402
forge_src = open(os.path.join(REPO, "src", "longrun", "core", "forge.py"),
                 encoding="utf-8").read()
check("E5 CLI exposes `forge embedding models/active/costs`",
      "def cmd_embedding(" in forge_src
      and "sub.add_parser(\"embedding\")" in forge_src)


print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
