#!/usr/bin/env python3
"""v824 — the retrieval re-ranker: one implementation, two consumers, no leakage.

Why: hybrid retrieval fuses a lexical and a semantic list by reciprocal rank, which
answers "these candidates are plausible" and never "this passage answers the
question". A cross-encoder scores (query, passage) TOGETHER. The stage only
REORDERS what retrieval already found.

What this pins:
  A  the config is a FILE with an overlay (never hardcoded), and bad values fall
     back instead of crashing;
  B  a re-ranker is a normal model entry (`rerank: true` in providers.yaml) that
     is NEVER offered as a chat model — not in the catalogue, not as the default,
     not in the research roster, and a chat ref cannot resolve as a re-ranker;
  C  `apply()` reorders, trims, honours the relevance floor, and FAILS OPEN on
     every failure (a broken re-ranker must never cost a turn);
  D  both consumers really call it (memory recall end-to-end, knowledge search by
     contract) and the response says when the order came from the cross-encoder;
  E  the operator surface is real: Settings ▸ Models renders it, the save goes to
     the overlay (the shipped file keeps its comments), and diagnostics names an
     unresolvable model.

Deterministic: temp dirs, injected transport, no network, no model, no server.
Run: python3 tests/acceptance/v824_rerank_stage.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="lr-rerank-v824-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
for _d in ("data", "cfg", "sessions"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import settings as settings_mod       # noqa: E402
from longrun.model import providers, rerank            # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def write_overlay(doc):
    import yaml
    path = os.path.join(os.environ["LONGRUN_DATA_DIR"], "rerank.overlay.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, sort_keys=False)
    rerank.cfg(reload=True)


def clear_overlay():
    path = os.path.join(os.environ["LONGRUN_DATA_DIR"], "rerank.overlay.yaml")
    if os.path.exists(path):
        os.remove(path)
    rerank.cfg(reload=True)


# ---- A: the config is a file (+ overlay), bad values fall back ------------
SHIPPED = rerank.cfg(reload=True)
check("A1 the shipped file is the source of the stage's settings",
      SHIPPED.get("model") == "openrouter:voyageai/rerank-2.5-lite"
      and SHIPPED.get("candidates") == 30 and SHIPPED.get("top_n") == 8, SHIPPED)
write_overlay({"enabled": True, "top_n": 2, "min_score": 0.5})
_ov = rerank.cfg()
check("A2 the overlay wins over the shipped file",
      _ov["top_n"] == 2 and _ov["min_score"] == 0.5 and _ov["enabled"] is True, _ov)
write_overlay({"enabled": True, "top_n": "abc", "candidates": 9999, "min_score": "x"})
_bad = rerank.cfg()
check("A3 bad values fall back to the default (never crash)",
      _bad["top_n"] == 8 and _bad["min_score"] == 0.0, _bad)
check("A4 out-of-range values are clamped", _bad["candidates"] == 200, _bad["candidates"])
clear_overlay()

# ---- B: a re-ranker is a model entry that is NOT a chat model -------------
_ors = providers.get("openrouter") or {}
_rer = [m["id"] for m in (_ors.get("models") or []) if providers.is_rerank_model(m)]
_chat = [m["id"] for m in providers.chat_models(_ors)]
check("B1 the re-rankers are declared in providers.yaml like any other model",
      "voyageai/rerank-2.5-lite" in _rer, _rer)
check("B2 they are excluded from the chat roster",
      not any("rerank" in str(m) for m in _chat), _chat[:6])
_cat = providers.catalog()
_cat_refs = [m.get("ref") for p in _cat["providers"] for m in (p.get("models") or [])]
check("B3 the catalogue never offers one to the picker",
      not any("rerank" in str(r) for r in _cat_refs))
check("B4 the default model is never a re-ranker",
      "rerank" not in str(_cat.get("default") or ""), _cat.get("default"))
from longrun.research import researchcfg  # noqa: E402
check("B5 the research roster excludes them too",
      not any("rerank" in str(m.get("id")) for m in researchcfg.provider_models()))

_url, _hdr, _mid = providers.rerank_endpoint("openrouter:voyageai/rerank-2.5-lite") or (None, None, None)
check("B6 the ref resolves to POST <base>/rerank with the model id",
      bool(_url) and _url.endswith("/rerank") and _mid == "voyageai/rerank-2.5-lite",
      (_url, _mid))
check("B7 a CHAT model cannot be used as a re-ranker",
      providers.rerank_endpoint("openrouter:z-ai/glm-5.3-flash") is None)

# ---- C: apply() reorders, trims, and FAILS OPEN --------------------------
DOCS = [{"content": "alpha passage about cats"}, {"content": "beta passage about dogs"},
        {"content": "gamma passage about the capital of France"}]
CALLS = []


def transport_factory(scores):
    def _t(url, headers, payload, timeout):
        CALLS.append({"url": url, "payload": payload, "timeout": timeout})
        rows = [{"index": i, "relevance_score": s} for i, s in enumerate(scores)]
        return 200, {"results": rows, "usage": {"cost": 0.000001, "total_tokens": 28}}
    return _t


def transport_fail(url, headers, payload, timeout):
    CALLS.append({"url": url, "fail": True})
    raise OSError("network down")


def transport_500(url, headers, payload, timeout):
    return 500, "boom"


write_overlay({"enabled": False})
_r = rerank.apply("capital of France", DOCS, text_of=lambda d: d["content"],
                  transport=transport_factory([0.1, 0.2, 0.9]))
check("C1 disabled: no call, order untouched, reason named",
      not CALLS and _r["items"] == DOCS and _r["info"]["applied"] is False
      and _r["info"]["reason"] == "disabled", _r["info"])

write_overlay({"enabled": True, "top_n": 2})
_r = rerank.apply("capital of France", DOCS, text_of=lambda d: d["content"],
                  transport=transport_factory([0.1, 0.2, 0.9]))
check("C2 enabled: the best passage comes first",
      [d["content"].split(" ")[0] for d in _r["items"]] == ["gamma", "beta"], _r["items"])
check("C3 top_n trims the survivors", len(_r["items"]) == 2, len(_r["items"]))
check("C4 the cross-encoder score rides as `relevance`, not over `score`",
      _r["items"][0].get("relevance") == 0.9 and "score" not in _r["items"][0],
      _r["items"][0])
check("C5 the report carries the model and the exact cost",
      _r["info"]["applied"] is True and _r["info"]["cost_usd"] == 0.000001
      and _r["info"]["model"].endswith("rerank-2.5-lite"), _r["info"])
check("C6 the request carries the query, the passages and top_n",
      CALLS[-1]["payload"]["query"] == "capital of France"
      and len(CALLS[-1]["payload"]["documents"]) == 3
      and CALLS[-1]["payload"]["top_n"] == 2, CALLS[-1]["payload"])

_r = rerank.apply("q", DOCS, text_of=lambda d: d["content"], transport=transport_fail)
check("C7 a transport error leaves the original order (fail-open)",
      _r["items"] == DOCS and _r["info"]["applied"] is False
      and "transport" in str(_r["info"]["reason"]), _r["info"])
_r = rerank.apply("q", DOCS, text_of=lambda d: d["content"], transport=transport_500)
check("C8 a non-200 answer also fails open", _r["items"] == DOCS
      and "HTTP 500" in str(_r["info"]["reason"]), _r["info"])

write_overlay({"enabled": True, "top_n": 5, "min_score": 0.95})
_r = rerank.apply("q", DOCS, text_of=lambda d: d["content"],
                  transport=transport_factory([0.1, 0.2, 0.9]))
check("C9 min_score can empty a weak result set instead of returning it",
      _r["items"] == DOCS and _r["info"]["applied"] is False, _r["info"])

write_overlay({"enabled": True, "top_n": 3, "candidates": 2})
CALLS.clear()
_r = rerank.apply("q", DOCS, text_of=lambda d: d["content"],
                  transport=transport_factory([0.5, 0.4, 0.3]))
check("C10 only `candidates` passages are sent (bounds the token bill)",
      len(CALLS[-1]["payload"]["documents"]) == 2, CALLS[-1]["payload"])
check("C11 the tail beyond the candidate cap follows, so nothing vanishes",
      len(_r["items"]) == 3 and _r["items"][-1]["content"].startswith("gamma"),
      [d["content"][:5] for d in _r["items"]])

# ---- D: both consumers really call the stage -----------------------------
# 1) memory recall, end to end with the transport and the model stubbed.
from longrun.model import context_engine  # noqa: E402
from longrun.memory import memory as memory_mod  # noqa: E402

write_overlay({"enabled": True, "top_n": 2})
_ORIG_SEARCH = memory_mod.search
_ORIG_RERANK = rerank.rerank
memory_mod.search = lambda q, kind, k, sem, ws: [
    (0.9, {"kind": "memory.store", "mid": "m1", "ts": 1, "content": "alpha about cats"}),
    (0.8, {"kind": "memory.store", "mid": "m2", "ts": 2, "content": "beta about dogs"}),
    (0.7, {"kind": "memory.store", "mid": "m3", "ts": 3, "content": "gamma capital France"}),
]
rerank.rerank = lambda q, docs, **kw: {
    "ok": True, "results": [{"index": 2, "score": 0.95}, {"index": 0, "score": 0.4},
                            {"index": 1, "score": 0.1}],
    "model": "stub", "ms": 1, "cost_usd": 0.0, "tokens": 10}
try:
    _hits = context_engine.retrieve("capital of France")
finally:
    memory_mod.search = _ORIG_SEARCH
    rerank.rerank = _ORIG_RERANK
check("D1 memory recall is reordered by the cross-encoder",
      [h["mid"] for h in _hits] == ["m3", "m1", "m2"] and _hits[0].get("relevance") == 0.95,
      [(h.get("mid"), h.get("relevance")) for h in _hits])

_KNOW = open(os.path.join(REPO, "src", "longrun", "memory", "knowledge.py"),
             encoding="utf-8").read()
check("D2 knowledge search uses the SAME stage and labels the mode",
      "_rerank.apply(" in _KNOW and 'out["mode"] + "+rerank"' in _KNOW
      and "out[\"rerank\"] = _rr[\"info\"]" in _KNOW)

# ---- E: the operator surface ---------------------------------------------
_sections = {s["file"]: s for s in settings_mod._sections()}
check("E1 Settings renders the stage in the MODELS panel",
      _sections.get("rerank.yaml", {}).get("panel") == "models", list(_sections))
check("E2 the form shows the values the harness actually uses",
      settings_mod._effective("rerank.yaml").get("top_n") == rerank.cfg().get("top_n"))
_ok = settings_mod.update({"file": "rerank.yaml",
                           "values": {"enabled": True, "top_n": 4, "model":
                                      "openrouter:cohere/rerank-5-fast"}})
_ov_path = os.path.join(os.environ["LONGRUN_DATA_DIR"], "rerank.overlay.yaml")
_shipped = open(os.path.join(REPO, "config", "rerank.yaml"), encoding="utf-8").read()
check("E3 a save reaches the overlay and the stage picks it up",
      _ok.get("ok") is True and rerank.cfg()["top_n"] == 4
      and rerank.cfg()["model"] == "openrouter:cohere/rerank-5-fast", _ok)
check("E4 the shipped file keeps its documentation comments",
      os.path.isfile(_ov_path) and "Measured on this account" in _shipped)

from longrun.core import diagnostics  # noqa: E402
write_overlay({"enabled": True, "model": "openrouter:z-ai/glm-5.3-flash"})
_iss = [i for i in diagnostics.validate_provider_config(
    providers.load(), os.environ, {}, None) if i.get("code") == "config.rerank_unresolved"]
check("E5 diagnostics names a re-ranker that cannot resolve (a chat model here)",
      len(_iss) == 1 and "Settings → Models" in _iss[0]["message"], _iss)
write_overlay({"enabled": False})

print("\n---")
print("v824: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
