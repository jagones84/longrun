"""Cross-encoder re-ranking — the retrieval SECOND stage (one implementation).

Why this exists
---------------
Hybrid retrieval fuses a lexical list (BM25/FTS) with a semantic one (vectors) by
reciprocal rank. That fusion answers *"which candidates are plausible"*; it never
reads the query and a passage TOGETHER, so a chunk that merely shares words with
the question ranks like one that answers it. A cross-encoder scores the pair
`(query, passage)` and returns a calibrated relevance, so the passages that
actually answer the question rise to the top of what enters the model's context.

It only REORDERS (and optionally trims) what retrieval already found: it can
never invent a document the index missed.

Where it acts (two consumers, one implementation)
-------------------------------------------------
  * `memory.knowledge.search()`    — knowledge base + codebase index retrieval;
  * `model.context_engine.retrieve()` — memories recalled for prompt injection.
Both call `apply()`; neither re-implements ordering.

Configuration (`config/rerank.yaml`, Settings ▸ Models — never hardcoded here):
  enabled         off by default; a reranker costs one model call per retrieval
  model           `<provider>:<model>` of a RERANK model (providers.yaml `rerank: true`)
  candidates      how many fused hits are sent to the re-ranker
  top_n           how many passages survive
  min_score       relevance floor (0.0 = keep everything returned)
  timeout_secs    a slow re-ranker must not hold a turn hostage
  doc_chars       per-passage character cap (bounds the token bill)

Cost source: OpenRouter returns the EXACT USD cost of a call (`usage.cost`); a
provider that does not is recorded as unknown (never estimated).
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request

from longrun.util import paths
from longrun.util.dataio import load_yaml as _yaml_load

CFG_PATH = os.path.join(paths.REPO_ROOT, "config", "rerank.yaml")
# Programmatic changes (Settings ▸ Models) land in a sparse overlay, so the
# shipped file keeps its documentation comments — the house pattern used by
# hooks/decisions/trace/jobs/tools.
OVERLAY_PATH = os.path.join(paths.DATA_DIR, "rerank.overlay.yaml")

# Used ONLY when config/rerank.yaml is missing (a fresh clone still boots). The
# charged model is the cheapest one measured live on OpenRouter (2026-11-05,
# $0.02 per 1M tokens = $0.00000056 for a 3-document probe); `cohere/rerank-5-fast`
# measured the same $0.02 per 1M with better score separation but a higher token
# count per request, and `cohere/rerank-4-fast` bills $0.002 per SEARCH.
DEFAULTS = {
    "enabled": False,
    "model": "openrouter:voyageai/rerank-2.5-lite",
    "candidates": 30,
    "top_n": 8,
    "min_score": 0.0,
    "timeout_secs": 4,
    "doc_chars": 1200,
}

_lock = threading.RLock()
_cache = {"sig": None, "cfg": None}


def _coerce(raw):
    """Effective config: DEFAULTS <- the file (bad values fall back, never crash)."""
    out = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return out
    for key in ("enabled",):
        if key in raw:
            out[key] = bool(raw[key])
    for key in ("candidates", "top_n", "timeout_secs", "doc_chars"):
        if key in raw and raw[key] is not None:
            try:
                out[key] = int(raw[key])
            except (TypeError, ValueError):
                pass
    if raw.get("min_score") is not None:
        try:
            out["min_score"] = float(raw["min_score"])
        except (TypeError, ValueError):
            pass
    if raw.get("model"):
        out["model"] = str(raw["model"]).strip()
    out["candidates"] = max(2, min(out["candidates"], 200))
    out["top_n"] = max(1, min(out["top_n"], 100))
    out["timeout_secs"] = max(1, min(out["timeout_secs"], 60))
    out["doc_chars"] = max(100, min(out["doc_chars"], 20000))
    out["min_score"] = max(0.0, min(float(out["min_score"]), 1.0))
    return out


def _sig():
    sig = []
    for path in (CFG_PATH, OVERLAY_PATH):
        try:
            st = os.stat(path)
            sig.append((st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append(None)
    return tuple(sig)


def _read_yaml(path):
    try:
        with open(path, encoding="utf-8") as f:
            return _yaml_load(f.read()) or {}
    except Exception:  # noqa: BLE001 — an unreadable file means "no value"
        return {}


def cfg(reload=False):
    """Effective rerank config: DEFAULTS <- config/rerank.yaml <- overlay."""
    with _lock:
        sig = _sig()
        if not reload and _cache["cfg"] is not None and _cache["sig"] == sig:
            return dict(_cache["cfg"])
        base = _read_yaml(CFG_PATH) if sig[0] is not None else {}
        over = _read_yaml(OVERLAY_PATH) if sig[1] is not None else {}
        merged = dict(base) if isinstance(base, dict) else {}
        if isinstance(over, dict):
            merged.update(over)
        got = _coerce(merged)
        _cache.update(sig=sig, cfg=got)
        return dict(got)


def enabled():
    return bool(cfg().get("enabled"))


def _default_transport(url, headers, payload, timeout):
    """POST the rerank body; returns (status, decoded_json_or_text)."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]


def rerank(query, documents, model=None, top_n=None, timeout=None, transport=None):
    """Score `documents` against `query`. Never raises.

    Returns {"ok": True, "results": [{"index", "score"}...] sorted best-first,
             "model", "cost_usd", "tokens", "ms"} on success, or
    {"ok": False, "error": "..."} — the caller decides whether that is fatal
    (it never is: retrieval degrades to its own order).
    """
    docs = [str(d or "") for d in (documents or [])]
    if not query or not docs:
        return {"ok": False, "error": "empty query or documents"}
    conf = cfg()
    ref = str(model or conf["model"] or "")
    from longrun.model import providers
    hit = providers.rerank_endpoint(ref)
    if not hit:
        return {"ok": False, "error": "unknown or unavailable rerank model %r" % ref}
    url, headers, mid = hit
    payload = {"model": mid, "query": str(query), "documents": docs}
    if top_n:
        payload["top_n"] = int(top_n)
    t0 = time.time()
    try:
        status, doc = (transport or _default_transport)(
            url, headers, payload, float(timeout or conf["timeout_secs"]))
    except Exception as e:  # noqa: BLE001 — a re-ranker must never break retrieval
        return {"ok": False, "error": "transport: %s" % e, "model": ref}
    ms = int((time.time() - t0) * 1000)
    if status != 200 or not isinstance(doc, dict):
        body = doc if isinstance(doc, str) else json.dumps(doc)[:300]
        return {"ok": False, "error": "HTTP %s %s" % (status, body), "model": ref, "ms": ms}
    rows = doc.get("results")
    if not isinstance(rows, list):
        return {"ok": False, "error": "response carries no results", "model": ref, "ms": ms}
    out, seen = [], set()
    for r in rows:
        try:
            idx = int(r.get("index"))
        except (TypeError, ValueError, AttributeError):
            continue
        if idx < 0 or idx >= len(docs) or idx in seen:
            continue
        seen.add(idx)
        try:
            score = float(r.get("relevance_score"))
        except (TypeError, ValueError):
            score = 0.0
        out.append({"index": idx, "score": round(score, 6)})
    out.sort(key=lambda r: r["score"], reverse=True)
    usage = doc.get("usage") or {}
    cost = usage.get("cost")
    return {"ok": True, "results": out, "model": ref, "ms": ms,
            "cost_usd": (float(cost) if isinstance(cost, (int, float)) else None),
            "tokens": usage.get("total_tokens")}


def apply(query, items, text_of=None, top_n=None, transport=None):
    """Reorder `items` by relevance. FAIL-OPEN: any failure returns them untouched.

    `text_of(item)` supplies the passage text; it defaults to the item's own
    string value. Relevance is attached to each surviving item as `relevance`;
    the caller's own `score` field keeps meaning what it meant (rank fusion), so
    there is never a second meaning for the same key.

    Returns {"items": [...], "info": {...}} where `info.applied` says whether the
    order actually came from the cross-encoder.
    """
    conf = cfg()
    items = list(items or [])
    info = {"applied": False, "model": str(conf.get("model") or ""),
            "candidates": 0, "kept": len(items)}
    if not conf.get("enabled"):
        info["reason"] = "disabled"
        return {"items": items, "info": info}
    if len(items) < 2:
        info["reason"] = "fewer than two candidates"
        return {"items": items, "info": info}
    getter = text_of or (lambda it: it)
    cut = conf["candidates"]
    head, tail = items[:cut], items[cut:]
    docs = []
    for it in head:
        try:
            txt = str(getter(it) or "")
        except Exception:  # noqa: BLE001 — a bad item is just an empty passage
            txt = ""
        docs.append(txt[:conf["doc_chars"]] or "(empty)")
    res = rerank(query, docs, model=conf["model"],
                 top_n=int(top_n or conf["top_n"]), transport=transport)
    info["candidates"] = len(head)
    if not res.get("ok"):
        info["reason"] = res.get("error")
        return {"items": items, "info": info}
    floor = float(conf["min_score"] or 0.0)
    keep = [r for r in res["results"] if r["score"] >= floor]
    limit = max(1, int(top_n or conf["top_n"]))
    keep = keep[:limit]
    if not keep:
        info["reason"] = "no passage cleared min_score"
        return {"items": items, "info": info}
    out = []
    scores = []
    for r in keep:
        it = head[r["index"]]
        if isinstance(it, dict):
            it = dict(it)
            it["relevance"] = r["score"]
        out.append(it)
        scores.append(r["score"])
    # Candidates the re-ranker did not return are DROPPED (it saw them and ranked
    # them below the ones it returned); the un-scored tail beyond `candidates`
    # follows, so a huge candidate pool cannot vanish because of a small top_n.
    scores.extend([None] * len(tail))
    info.update(applied=True, kept=len(out), ms=res.get("ms"),
                cost_usd=res.get("cost_usd"), tokens=res.get("tokens"),
                scores=scores, reason=None)
    return {"items": out + tail, "info": info}


def describe():
    """Read-only status for the Models panel / diagnostics (never raises)."""
    conf = cfg()
    from longrun.model import providers
    hit = providers.rerank_endpoint(conf["model"]) if conf.get("model") else None
    return {"enabled": conf["enabled"], "model": conf["model"],
            "resolved": bool(hit),
            "url": (hit[0] if hit else None),
            "candidates": conf["candidates"], "top_n": conf["top_n"],
            "min_score": conf["min_score"], "config": CFG_PATH}
