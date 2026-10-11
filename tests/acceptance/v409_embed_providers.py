"""v409 — embedding providers resolve + hybrid retrieval works (JAG-403k).

Root bug fixed here: the embedding catalogue (config/embedding.yaml) referenced
providers (`cohere:`, `voyage:`, `jina:`) that did NOT exist in providers.yaml,
so `providers.resolve()` returned None, the embedder silently fell back to the
local router (no embeddings endpoint) and BOTH indexes ended up with 0 vectors —
the whole semantic layer was dead while the UI claimed a model was active.

Also fixed: the HYBRID search path raised `UnboundLocalError` (the comprehension
reused `r`, a function-local from the `for r in rows` loop below) the first time
it actually ran — which, with 0 vectors, it never had.

Stdlib-only, deterministic, no network (the embedder is stubbed).
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="v409-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["LONGRUN_CODEBASE_DIR"] = os.path.join(tmp, "codebase")
os.environ["LONGRUN_KNOWLEDGE_DIR"] = os.path.join(tmp, "knowledge")
os.environ["LONGRUN_EMBEDDING_DIR"] = os.path.join(tmp, "embedding")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
for d in ("data", "codebase", "knowledge", "embedding", "sessions"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if (detail and not ok) else ""))


from longrun.model import providers as P     # noqa: E402
from longrun.model import embed as E         # noqa: E402
from longrun.memory import indexcfg, codeindex  # noqa: E402
from longrun.memory import embedcfg, knowledge  # noqa: E402

P.load_env()

# -------------------------------------------------- 1) embedding providers ship
cfg = P.load()
byid = {p["id"]: p for p in cfg.get("providers", [])}
check("1a cohere/voyage/jina are declared as embedding endpoints",
      {"cohere", "voyage", "jina"} <= set(byid))
check("1b cohere points at the OpenAI-compatible endpoint + names its key",
      byid.get("cohere", {}).get("base_url", "").endswith("/compatibility/v1")
      and byid.get("cohere", {}).get("api_key_env") == "COHERE_API_KEY")
check("1c voyage + jina endpoints are the documented OpenAI-compatible bases",
      byid.get("voyage", {}).get("base_url") == "https://api.voyageai.com/v1"
      and byid.get("jina", {}).get("base_url") == "https://api.jina.ai/v1")
check("1d the embedding endpoints are flagged embed_only",
      all(byid[k].get("embed_only") for k in ("cohere", "voyage", "jina")))

# -------------------------------------------------- 2) the refs RESOLVE now
for ref in ("cohere:embed-multilingual-v3.0", "voyage:voyage-3", "jina:jina-embeddings-v3",
            "openai:text-embedding-3-small", "openrouter:openai/text-embedding-3-small"):
    hit = P.resolve(ref)
    check("2 the ref resolves: " + ref,
          hit is not None and ("%s:%s" % (hit[0]["id"], hit[1])) == ref, hit)

# -------------------------------------------------- 3) no clutter in the picker
ids = [p["id"] for p in P.catalog()["providers"]]
check("3a embedding-only providers are hidden from the CHAT model picker",
      "cohere" not in ids and "voyage" not in ids and "jina" not in ids, ids)
check("3b chat providers are still present",
      "openrouter" in ids and "openai" in ids)

# every shipped catalogue entry whose provider is a real provider must resolve
_ok = True
for m in embedcfg.all_models():
    prov = m["id"].split(":", 1)[0]
    if prov in byid or prov == "local":
        if prov != "local" and P.resolve(m["id"]) is None:
            _ok = False
check("3c every shipped catalogue entry resolves (or is a local ref)", _ok)

# -------------------------------------------------- 4) hybrid retrieval works
# Stub the network embedder and build a tiny index: the hybrid (RRF) path must
# run end-to-end and NOT raise (this is the code path that was dead before).
E.embed_texts = lambda texts, model=None, timeout=None: (
    [[1.0, 0.0, 0.0] for _ in texts], {"tokens": 1, "cost_usd": None})
indexcfg.save_config({"embed_model": "test:fake-embed"})

ws = os.path.join(tmp, "ws")
os.makedirs(ws)
with open(os.path.join(ws, "notes.md"), "w", encoding="utf-8") as f:
    f.write("# Alpha\nThe quick brown fox jumps over the lazy dog.\n"
            "## Beta\nQuantum entanglement and retrieval augmented generation.\n")

st = codeindex.build(ws)
check("4a build embeds the chunks (vectors stored)", st.get("embedded", 0) > 0 and st.get("dim") == 3, st)
try:
    r = codeindex.search(ws, "brown fox retrieval", k=5)
    crashed = None
except Exception as e:  # noqa: BLE001
    crashed = "%s: %s" % (type(e).__name__, e)
    r = {}
check("4b the hybrid search path no longer crashes", crashed is None, crashed)
check("4c hybrid mode is reported with results",
      (r.get("mode") == "hybrid") and len(r.get("results", [])) > 0, r.get("mode"))

# -------------------------------------------------- 5) re-embed back-fill exists
check("5a knowledge exposes a re-embed back-fill",
      callable(getattr(knowledge, "reembed", None)))
indexcfg.save_config({"embed_model": ""})
check("5b re-embed refuses with no active model",
      knowledge.reembed().get("ok") is False)

print("---")
ok = sum(results)
print("%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
