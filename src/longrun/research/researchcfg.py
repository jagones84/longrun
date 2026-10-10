"""RESEARCH configuration (JAG-403b) — stdlib only.

The research LLM is configurable separately from the chat LLM. Models are listed
with id+provider+label so the UI/CLI can show a dropdown. Depth controls how
many rounds + sources per round the executor uses.

Resolution order for a model id ``provider:model``:
  1. ``<provider>`` is ``perplexity`` -> Perplexity's OpenAI-compatible API
  2. ``<provider>`` is ``openrouter`` -> OpenRouter's chat completions
  3. ``<provider>`` is ``local`` / ``rllm`` -> the local llama.cpp router
  4. fall back to the active chat provider
"""
from longrun.memory import indexcfg as _base


# Catalogue of well-known research models. Custom models are layered via
# ``indexcfg.save_config({..., "custom_models": [...]})``.
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
     "label": "Local router (rllm)", "env_key": "", "base_url": ""},
]


def all_models():
    """Catalogue + custom overlay."""
    base = list(MODELS)
    cfg = _base.load_config()
    for m in (cfg.get("custom_models") or []):
        if isinstance(m, dict) and m.get("id"):
            base.append({**m, "custom": True})
    return base


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
    when the id is a string (custom models are accepted)."""
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


def resolve(model_id):
    """Return (cfg-dict, model_name) or (None, model_id) when not in the catalogue.

    The executor falls back to the local router if credentials are missing.
    """
    m = find(model_id or active_model())
    if not m:
        return None, model_id
    return m, m["id"].split(":", 1)[1] if ":" in m["id"] else m["id"]