"""API-key management: which env-var NAMES the harness needs, and setting them.

The repo-level `.env` (gitignored) is the canonical place to SET a key from the
WebUI; it is already in providers' default env_files, so a value written here is
picked up by providers and MCP `${VAR}` references. `keys_status()` never returns
a secret VALUE — only NAME + set/where; `reveal_key()` fetches one value on an
explicit request.

Extracted from ``server.py`` (JAG-371). Stdlib only.
"""
import os

from longrun.util.paths import REPO_ROOT as REPO

# JAG-161: the repo-level .env (gitignored) is the canonical place to SET a key
# from the WebUI. It is already in providers' default env_files, so a value
# written here is picked up by providers and MCP `${VAR}` references.
ENV_FILE = os.path.join(REPO, ".env")

# Env vars the Keys panel must offer even when a provider or MCP catalog is
# unavailable. Each value is a (where_label, description) tuple.
KNOWN_ENV_KEYS = {
    "OPENROUTER_API_KEY": ("provider:openrouter", "Default chat/model API key; recommended first key"),
    "DEEPSEEK_API_KEY": ("provider:deepseek", "DeepSeek model API key"),
    "OPENAI_API_KEY": ("provider:openai", "OpenAI model API key"),
    "ANTHROPIC_API_KEY": ("provider:anthropic", "Anthropic model API key"),
    "GEMINI_API_KEY": ("provider:google", "Google Gemini model API key"),
    "COHERE_API_KEY": ("provider:cohere", "Cohere embedding API key"),
    "VOYAGE_API_KEY": ("provider:voyage", "Voyage embedding API key"),
    "JINA_API_KEY": ("provider:jina", "Jina embedding API key"),
    "VLLM_API_KEY": ("provider:vllm", "Local vLLM server auth, if required"),
    "GITHUB_TOKEN": ("mcp:github", "GitHub API access — issues, PRs, repos, code search"),
    "TAVILY_API_KEY": ("tool:tavily", "Web search (AI-powered)"),
    "BRAVE_API_KEY": ("tool:brave", "Web search (privacy-focused)"),
    "PERPLEXITY_API_KEY": ("tool:perplexity", "Research provider with citations"),
    "LONGRUN_TOKEN": ("server:auth", "Protects Longrun API routes; browser token is managed above"),
}

def _env_file_upsert(name, value):
    """Write/update `NAME=VALUE` in the repo .env, preserving every other line.

    An empty `value` removes the line. The file is (re)created 0600 and is
    gitignored, so secrets never reach the repository.
    """
    lines = []
    if os.path.isfile(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    prefix = name + "="
    out, found = [], False
    for ln in lines:
        if ln.strip().startswith(prefix):
            found = True
            if value:
                out.append("%s=%s" % (name, value))
            continue
        out.append(ln)
    if value and not found:
        out.append("%s=%s" % (name, value))
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(out).strip("\n") + "\n")
    try:
        os.chmod(ENV_FILE, 0o600)
    except Exception:  # noqa: BLE001 — best effort on exotic filesystems
        pass


def set_key(name, value):
    """POST /api/keys — set (or clear) an env var, persisted to the repo .env.

    Returns the refreshed keys_status() so the UI re-renders in one round-trip.
    """
    import re as _re
    name = (name or "").strip()
    if not _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return {"error": "invalid variable name"}
    value = "" if value is None else str(value)
    try:
        _env_file_upsert(name, value)
    except Exception as e:  # noqa: BLE001
        return {"error": "cannot write %s: %s" % (ENV_FILE, e)}
    if value:
        os.environ[name] = value
    else:
        os.environ.pop(name, None)
    try:
        from longrun.model import providers
        providers.load_env(reload=True)
    except Exception:  # noqa: BLE001
        pass
    out = keys_status()
    out["ok"] = True
    out["env_file"] = ENV_FILE
    return out


def read_secret(name):
    """Return the secret value for ``name`` from os.environ or the repo .env.

    ONE file: the gitignored `.env` next to the repo (the same file Settings >
    Keys writes). There is no fallback into another harness' home directory — a
    key lives where the UI puts it.
    """
    name = (name or "").strip()
    if not name:
        return ""
    val = os.environ.get(name)
    if val and val.strip():
        return val.strip()
    try:
        from longrun.model import providers
        providers.load_env()
        val = os.environ.get(name)
        if val and val.strip():
            return val.strip()
    except Exception:  # noqa: BLE001
        pass
    if os.path.isfile(ENV_FILE):
        try:
            with open(ENV_FILE, encoding="utf-8", errors="replace") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln or ln.startswith("#"):
                        continue
                    if ln.startswith("export "):
                        ln = ln[7:].strip()
                    if "=" in ln:
                        k, v = ln.split("=", 1)
                        if k.strip() == name:
                            v = v.strip().strip('"').strip("'")
                            if v:
                                return v
        except Exception:  # noqa: BLE001
            pass
    return ""


def reveal_key(name):
    """POST /api/keys/reveal — return ONE stored value, on demand.

    The bulk `keys_status()` deliberately never returns values; the UI calls this
    only when the operator clicks the eye / copy on a specific row, so a secret
    is fetched explicitly and never listed.
    """
    import re as _re
    name = (name or "").strip()
    if not _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return {"error": "invalid variable name"}
    val = read_secret(name)
    return {"name": name, "value": val or "", "set": bool(val)}


def keys_status():
    """JAG-113: which env-var NAMES the harness needs and whether they are set.

    Aggregates provider `api_key_env` and MCP client `${VAR}` headers. Returns the
    NAME + set/where only — never a secret VALUE (values live in a gitignored .env).
    """
    import re as _re
    rows = {}

    def _bump(env, where):
        _, description = KNOWN_ENV_KEYS.get(
            env, ("", "Custom environment variable"))
        r = rows.setdefault(env, {
            "env": env, "where": [], "set": False,
            "description": description,
        })
        r["where"].append(where)

    try:
        from longrun.model import providers
        for p in providers.providers():
            if p.get("api_key_env"):
                _bump(p["api_key_env"], "provider:%s" % p.get("id"))
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.interop import mcp_client
        for name, spec in (mcp_client.load_doc().get("clients") or {}).items():
            for v in (spec.get("headers") or {}).values():
                for env in _re.findall(r"\$\{([A-Z0-9_]+)\}", str(v)):
                    _bump(env, "mcp:%s" % name)
    except Exception:  # noqa: BLE001
        pass
    try:
        # JAG-161: any NAME already present in the repo .env is a known key too,
        # so a value the user sets here shows up (and can be cleared) again.
        if os.path.isfile(ENV_FILE):
            with open(ENV_FILE, encoding="utf-8") as f:
                for ln in f:
                    ln = ln.strip()
                    if ln and not ln.startswith("#") and "=" in ln:
                        _bump(ln.split("=", 1)[0].strip(), "env:.env")
    except Exception:  # noqa: BLE001
        pass
    for env, (where, description) in KNOWN_ENV_KEYS.items():
        row = rows.setdefault(env, {
            "env": env, "where": [], "set": False,
            "description": description,
        })
        row["where"].append(where)
        row["description"] = description
    out = []
    for env in sorted(rows):
        r = rows[env]
        r["where"] = sorted(set(r["where"]))
        r["set"] = bool(os.environ.get(env))
        r.setdefault("description", "Custom environment variable")
        out.append(r)
    return {"keys": out, "env_files": [".env"],
            "env_file": ENV_FILE,
            "note": "Values are never in the repo: set them here and they are written "
                    "to the gitignored .env. Providers and MCP reference a key by NAME only."}
