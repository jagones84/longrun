"""RESEARCH plan + executor (JAG-403b) — stdlib only.

The executor is a thin orchestrator:

  1. build a plan (rounds, queries, max sources) from depth
  2. for each round:
       - web search for the round's query
       - fetch + summarise each URL
       - import into the notebook
  3. after the last round, ask the research LLM for a final summary and store
     it as a text source alongside the URLs.

Both web search and the research LLM are injected (``SEARCH``, ``LLM``) so
tests run deterministic and offline.
"""
import json
import os
import re
import time
import urllib.request

from longrun.memory import chunk as _chunk
from longrun.memory import knowledge as _kb

from longrun.research import researchcfg as _rc


# Indirections (overridden in tests / in the live wiring).
SEARCH = _kb.SEARCH                       # (query, n) -> ([{title,url,snippet}], engine)
fetch_text = _chunk.fetch_url             # url -> text (markdown-ish)


def _catalogue_headers(cfg):
    """Bearer headers for a web-grounded catalogue entry (Perplexity/OpenRouter)."""
    env_key = cfg.get("env_key") or ""
    key = ""
    if env_key:
        try:
            from longrun.model import keys as _keys
            key = _keys.read_secret(env_key) or os.environ.get(env_key, "")
        except Exception:  # noqa: BLE001
            key = os.environ.get(env_key, "")
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = "Bearer " + key
    return h


def _default_llm(prompt, model, timeout=30):
    """OpenAI-compatible chat call for the research summary.

    Resolution:
      1. a web-grounded catalogue entry with a ``base_url`` (Perplexity Sonar /
         OpenRouter pass-through) -> that endpoint + its env key;
      2. ``local:<alias>`` -> the local llama.cpp router;
      3. anything else -> the normal provider resolution, so **any model the user
         saved in their providers** (OpenRouter, a custom openai-compatible, …)
         works too.

    Returns ``{"summary": <content>, "queries": []}`` — the ``queries`` list is
    empty because follow-up expansion is done by ``make_plan`` (deterministic),
    not by the LLM. Never raises: any failure returns None.
    """
    ref = str(model or _rc.active_model())
    url, headers, mid = "", None, ref

    cfg, cmid = _rc.resolve(ref)          # only returns entries WITH a base_url
    if cfg and cfg.get("base_url"):
        url = cfg["base_url"].rstrip("/") + "/chat/completions"
        headers, mid = _catalogue_headers(cfg), cmid
    else:
        from longrun.model import rllm
        if ref.startswith("local:"):
            mid = ref.split(":", 1)[1] or "default"
            url = rllm.ROUTER_BASE.rstrip("/") + "/v1/chat/completions"
            headers = {"Content-Type": "application/json"}
        else:
            url, headers, mid = rllm._chat_endpoint(ref)

    body = json.dumps({
        "model": mid,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None
    choices = data.get("choices") or []
    if not choices:
        return None
    msg = (choices[0].get("message") or {}).get("content") or ""
    return {"summary": msg.strip(), "queries": []}


LLM = _default_llm


# ---------------------------------------------------------------------- plan --
def make_plan(query, depth="shallow", n=5, max_rounds=4):
    """Build a deterministic plan: queries per round, sources per round."""
    budget = _rc.depth_budget(depth)
    rounds = min(int(budget["rounds"] or 1), max(1, int(max_rounds or 1)))
    sources = max(1, min(int(n or 5), int(budget["n_per_round"] or 5)))
    queries = [str(query).strip()]
    if rounds > 1:
        # Expand the query for each subsequent round. The executor can also use
        # the LLM's ``queries`` field if present, but defaults are deterministic.
        for i in range(1, rounds):
            prefix = "expanded" if i == 1 else "deep-dive"
            queries.append("%s: %s" % (prefix, query))
    return {
        "query": query,
        "depth": depth,
        "rounds": rounds,
        "n_per_round": sources,
        "max_sources": int(budget["max_sources"] or sources),
        "queries": queries,
    }


# ------------------------------------------------------------------- executor --
def run(query, notebook="default", depth="shallow", n=5, max_rounds=4,
        on_event=None, llm_model=None):
    """Execute the research plan and import results into ``notebook``.

    ``on_event(event_dict)`` is invoked with one of:
      {"type":"round","i":..,"queries":[...]}
      {"type":"search","engine":..,"results":..}
      {"type":"import","url":..,"ok":..,"chunks":..}
      {"type":"summary","text":..}
      {"type":"done","rounds":..,"sources_added":..}
    """
    plan = make_plan(query, depth=depth, n=n, max_rounds=max_rounds)
    out = {"ok": False, "rounds": 0, "sources_added": 0, "sources": [],
           "notebook": notebook, "plan": plan, "log": []}

    def _emit(ev):
        out["log"].append(ev)
        if on_event:
            try:
                on_event(ev)
            except Exception:  # noqa: BLE001
                pass

    seen_urls = set()
    budget_left = plan["max_sources"]
    model = llm_model or _rc.active_model()
    summary_chunks = []

    # Lazy lookup so test/alternative implementations registered against the
    # ``executor`` module are honoured (avoids binding-time staleness).
    from longrun.research import executor as _executor  # noqa: PLC0415
    search_fn = getattr(_executor, "SEARCH", SEARCH)
    fetch_fn = getattr(_executor, "fetch_text", fetch_text)
    llm_fn = getattr(_executor, "LLM", LLM)

    for i, q in enumerate(plan["queries"], start=1):
        _emit({"type": "round", "i": i, "query": q})
        try:
            results, engine = search_fn(q, plan["n_per_round"])
        except Exception as e:  # noqa: BLE001
            _emit({"type": "search", "error": str(e)})
            results, engine = [], "error"
        _emit({"type": "search", "engine": engine, "n": len(results or [])})
        if not results:
            continue
        for cand in results:
            if budget_left <= 0:
                break
            url = (cand.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                text = fetch_fn(url)
            except Exception as e:  # noqa: BLE001
                _emit({"type": "import", "url": url, "ok": False, "error": str(e)})
                continue
            if not text or len(text.strip()) < 20:
                _emit({"type": "import", "url": url, "ok": False, "error": "empty body"})
                continue
            res = _kb.add_source_text(notebook, url, text, title=cand.get("title") or url)
            if res.get("ok"):
                budget_left -= 1
                out["sources"].append({
                    "url": url, "title": cand.get("title", url),
                    "snippet": cand.get("snippet", ""), "kind": "url",
                    "chunks": res.get("chunks", 0), "source_id": res.get("source_id"),
                })
                out["sources_added"] += 1
                _emit({"type": "import", "url": url, "ok": True,
                       "chunks": res.get("chunks", 0)})
                # collect a short excerpt for the final summary
                summary_chunks.append(text[:1200])
            else:
                _emit({"type": "import", "url": url, "ok": False,
                       "error": res.get("error", "")})
        out["rounds"] = i

    # final summary via the research LLM (v607: LOUD fallback chain, never a
    # silent stub — a dead summary model used to degrade to the bare
    # "Research summary about: …" with no trace of why the citations were gone).
    summary, warning = "", ""
    if summary_chunks:
        prompt = ("Summarise the following research notes in 6 short bullet points. "
                  "Every bullet carries inline [title](url) citations for its claims "
                  "and the summary ends with a link-only Sources section:\n\n")
        prompt += "\n\n---\n\n".join(summary_chunks)[:6000]
        try:
            r = llm_fn(prompt, model) if llm_fn else None
            if r and r.get("summary"):
                summary = r["summary"]
        except Exception:  # noqa: BLE001
            summary = ""
        if not summary and str(model) != "local:default":
            # The configured model is dead (no key, retired id, router down):
            # the local router is always there on a DGX checkout, so use it
            # before giving up — a cited summary beats a stub.
            try:
                r = llm_fn(prompt, "local:default") if llm_fn else None
                if r and r.get("summary"):
                    summary = r["summary"]
                    warning = ("research model %r failed; summary by local router"
                               % model)
            except Exception:  # noqa: BLE001
                pass
        if not summary:
            summary = "Research summary about: " + (query or "").strip()
            warning = (warning or
                       ("research model %r failed and no local router answered; "
                        "stored the uncited stub" % model))
    else:
        summary = "Research summary about: " + (query or "").strip()
        # v608: zero fetched sources is the "nothing embedded" case the
        # operator reported — say WHY (search dead? fetch empty?) instead of
        # silently storing a stub. NotebookLM-style contract: URLs land as
        # notebook sources automatically, no manual import step.
        errs = [e.get("error") for e in out["log"]
                if e.get("type") == "import" and e.get("error")]
        hint = ("search returned nothing or every fetch failed" if not errs
                else "fetch failed: " + "; ".join(sorted(set(errs)))[:300])
        warning = "research imported 0 sources — " + hint
    if warning:
        out["warning"] = warning
        _emit({"type": "warning", "text": warning})
    tres = _kb.add_text(notebook, "Research: " + (query or "").strip(), summary)
    if tres.get("ok"):
        out["sources"].append({"url": "", "title": tres.get("title", ""),
                               "kind": "text", "ref": tres.get("ref", ""),
                               "chunks": tres.get("chunks", 0),
                               "source_id": tres.get("source_id")})
    _emit({"type": "summary", "text": summary})
    out["ok"] = True
    _emit({"type": "done", "rounds": out["rounds"], "sources_added": out["sources_added"]})
    try:
        from longrun.core import matrix as _mtx
        aug = _mtx.call_hook("research", "augment_research", query, out, default=out)
        if isinstance(aug, dict):
            return aug
    except Exception:  # noqa: BLE001
        pass
    return out


# Public, JSON-friendly status used by the API + UI.
def status():
    return {
        "active": _rc.active_model(),
        "models": _rc.all_models(),
        "depths": ["shallow", "medium", "deep"],
    }