"""RESEARCH configuration (JAG-403b / JAG-403d) — stdlib only.

The research LLM is configurable separately from the chat LLM. The picker offers,
IN ORDER:

  1. the web-grounded catalogue (Perplexity Sonar — a search-integrated model);
  2. your personal custom models (index overlay);
  3. **every model of every CONFIGURED provider** — so the research agent can use
     the same roster you already saved (OpenRouter models, the local router, …).

Resolution for a call (see ``research._default_llm``):
  * a catalogue entry with a ``base_url`` (Perplexity / OpenRouter pass-through)
    -> that endpoint with its env key;
  * ``local:<alias>`` -> the local llama.cpp router;
  * anything else -> the normal provider resolution (``rllm._chat_endpoint``).
"""
from longrun.memory import indexcfg as _base


# Web-grounded catalogue. These carry the endpoint + env key so they work even
# when the provider is not configured as a general provider.
MODELS = [
    {"id": "perplexity:sonar-pro", "provider": "perplexity",
     "label": "Perplexity Sonar Pro (web-grounded, recommended)",
     "env_key": "PERPLEXITY_API_KEY", "base_url": "https://api.perplexity.ai"},
    {"id": "perplexity:sonar", "provider": "perplexity",
     "label": "Perplexity Sonar (web-grounded, fast)",
     "env_key": "PERPLEXITY_API_KEY", "base_url": "https://api.perplexity.ai"},
    {"id": "openrouter:openai/gpt-4o-mini-search-preview", "provider": "openrouter",
     "label": "OpenRouter gpt-4o-mini-search-preview",
     "env_key": "OPENROUTER_API_KEY", "base_url": "https://openrouter.ai/api/v1"},
    {"id": "openrouter:perplexity/sonar-pro", "provider": "openrouter",
     "label": "OpenRouter Perplexity Sonar Pro",
     "env_key": "OPENROUTER_API_KEY", "base_url": "https://openrouter.ai/api/v1"},
    {"id": "local:default", "provider": "local",
     "label": "Local router (default model)", "env_key": "", "base_url": ""},
]

WEB_GROUNDED_GROUP = "web-grounded (search)"


def provider_models():
    """Every model of every CONFIGURED provider, as pickable research refs.

    This is what makes the research picker show the user's SAVED models, not just
    a hardcoded list. Never raises (a broken provider config yields []).
    """
    out = []
    try:
        from longrun.model import providers
        for p in providers.providers():
            pid = p.get("id")
            if not pid:
                continue
            pname = p.get("name") or pid
            for m in (p.get("models") or []):
                mid = m.get("id") if isinstance(m, dict) else m
                if not mid:
                    continue
                out.append({
                    "id": "%s:%s" % (pid, mid), "provider": pid,
                    "label": "%s · %s" % (mid, pname),
                    "group": pname, "local": bool(p.get("local")),
                })
    except Exception:  # noqa: BLE001
        pass
    return out


def all_models():
    """Catalogue + personal overlay + every configured provider model (deduped)."""
    out, seen = [], set()

    def _add(m):
        mid = m.get("id")
        if not mid or mid in seen:
            return
        seen.add(mid)
        out.append(m)

    for m in MODELS:
        _add({**m, "group": WEB_GROUNDED_GROUP})
    cfg = _base.load_config()
    for m in (cfg.get("custom_models") or []):
        if isinstance(m, dict) and m.get("id"):
            _add({**m, "custom": True, "group": m.get("provider") or "custom"})
    for m in provider_models():
        _add(m)
    return out


def find(model_id):
    for m in all_models():
        if m["id"] == model_id:
            return m
    return None


def active_model():
    cfg = _base.load_config()
    return (cfg.get("research_model") or cfg.get("research_active")
            or MODELS[0]["id"])


def set_active(model_id):
    """Persist the active research model. Idempotent. Always returns ok=True
    when the id is a string (custom / provider models are accepted)."""
    if not isinstance(model_id, str) or not model_id.strip():
        return {"ok": False, "error": "model id required"}
    _base.save_config({"research_model": model_id.strip()})
    return {"ok": True, "active": model_id.strip()}


def load_config():
    return _base.load_config()


def save_config(patch):
    return _base.save_config(patch or {})


def depth_budget(depth):
    """Per-depth budget: rounds + sources per round + max sources total."""
    depth = (depth or "shallow").lower()
    if depth == "shallow":
        return {"rounds": 1, "n_per_round": 5, "max_sources": 5}
    if depth == "medium":
        return {"rounds": 2, "n_per_round": 5, "max_sources": 12}
    if depth == "deep":
        return {"rounds": 3, "n_per_round": 6, "max_sources": 24}
    return {"rounds": 1, "n_per_round": 5, "max_sources": 5}


SEARCH_CHAIN = ["tavily", "brave", "duckduckgo"]


def search_providers():
    """Ordered web-search provider chain (config-overridable).

    Reads ``search_providers`` from the index config overlay; unknown or empty
    values fall back to SEARCH_CHAIN. Only known names survive, order kept.
    """
    try:
        cfg = _base.load_config() or {}
    except Exception:  # noqa: BLE001
        cfg = {}
    raw = cfg.get("search_providers")
    if not isinstance(raw, list) or not raw:
        return list(SEARCH_CHAIN)
    known = [str(x).strip().lower() for x in raw]
    out = [x for x in known if x in SEARCH_CHAIN]
    return out or list(SEARCH_CHAIN)


def resolve(model_id):
    """Return (catalogue-entry, model_name) for a web-grounded entry (with a
    ``base_url``), else (None, model_id) so the caller uses provider resolution.
    """
    m = find(model_id or active_model())
    if not m or not m.get("base_url"):
        return None, model_id
    return m, m["id"].split(":", 1)[1] if ":" in m["id"] else m["id"]