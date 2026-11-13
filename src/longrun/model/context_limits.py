"""Config limits — every budget and knob the code used to hardcode (2026-11-05).

Operator rule: *"all in config files ... no hardcoding"*. Before this module each
value was a literal in the module that used it (`agent.py` 6000/200000/1500/600/
4000/1200, `prompt.py` 2600/1200/120, `rules.py` 32 KB, `term.py` 200000/8/3600/
2000, `tools.py` 65536, `sandbox.py` 2 MB, `acceptance.py` 20/200, `rllm.py`
retries/backoff/timeouts/max-tokens/repeat guard, `context_engine.py` budget,
`server.py` body/feed/stream, `sse.py` think flush, `events.py` retention,
`skills.py`/`threads.py`/`stores.py`/`memory.py`/`taskgraph.py`/`jobs.py`/
`teams.py`/`heldout.py`), or an env var with a literal default.

Three config blocks in `config/tools.yaml` are the source of truth and this module
is the ONLY reader:

    `context:`  how much harness text reaches the model
    `limits:`   router/LLM I/O, model context, repeat guard, HTTP/SSE, retention,
                stores, skills, jobs/teams, graph — the values that used to be
                `int(os.environ.get(..., <literal>))`
    `shell:`    the persistent-terminal pool

Resolution order, identical to `runtime` (JAG-483):

    explicit override  ->  LONGRUN_* env var  ->  the config block
    (+ data/tools.overlay.yaml)  ->  the DEFAULTS below

`DEFAULTS`/`LIMITS_DEFAULTS`/`SHELL_DEFAULTS` are FALLBACKS for a missing or
broken config file, never a second source: `v827` fails if a DEFAULTS key has no
config row.

Consumers bind the value once at import (module constants), so an edit needs the
usual service restart — same contract as every other config block.
"""
import os

#: Fallback only. Every key here MUST also exist in `config/tools.yaml` `context:`.
DEFAULTS = {
    "tool_obs_limit": 6000,
    "render_max": 200000,
    "offload_head": 1500,
    "offload_tail": 600,
    "reference_max_chars": 4000,
    "reference_role_max_chars": 1200,
    "skills_prompt_max_chars": 2600,
    "memory_prompt_max_chars": 1200,
    "memory_item_chars": 120,
    "rules_prompt_max_bytes": 32768,
    "shell_capture_max": 200000,
    "fs_read_max_bytes": 65536,
    "sandbox_max_output_bytes": 2 * 1024 * 1024,
    "acceptance_max_predicates": 20,
    "acceptance_max_predicate_len": 200,
    "acceptance_missing_items": 6,
    "acceptance_missing_chars": 300,
    "chat_tool_steps": 12,
    "chat_tool_iters": 96,
    "plan_tool_steps": 3,
    "subagent_wait_secs": 600,
}

#: Env overrides kept for tests / one-off runs. A name absent here has no env
#: override: a limit that only exists to protect the context is not something a
#: shell variable should silently change.
ENV = {
    "tool_obs_limit": "LONGRUN_TOOL_OBS_LIMIT",
    "render_max": "LONGRUN_OFFLOAD_MAX",
    "rules_prompt_max_bytes": "LONGRUN_RULES_MAX",
    "shell_capture_max": "LONGRUN_SHELL_CAPTURE_MAX",
    "fs_read_max_bytes": "LONGRUN_FS_READ_MAX",
    "sandbox_max_output_bytes": "LONGRUN_SANDBOX_MAX_OUTPUT",
    "chat_tool_steps": "LONGRUN_CHAT_TOOL_STEPS",
    "chat_tool_iters": "LONGRUN_CHAT_TOOL_ITERS",
    "plan_tool_steps": "LONGRUN_PLAN_TOOL_STEPS",
    "subagent_wait_secs": "LONGRUN_SUBAGENT_WAIT",
}

#: Keys where 0 is a meaningful value ("show none" / "disabled"); everything else
#: floors at 1 so a typo in the YAML cannot switch a budget off and flood context.
_ZERO_OK = frozenset({"acceptance_missing_items", "acceptance_missing_chars",
                      "think_live_cap", "job_retries", "team_local_slots",
                      "max_tokens"})   # 0 = omit the cap and let the router decide

#: The persistent-terminal pool (`config/tools.yaml` -> `shell:`). It is NOT a
#: context budget, but it follows the same contract (config-first, no literal in
#: `tools/term.py`) and it is resolved by this ONE chain instead of a second copy.
SHELL_DEFAULTS = {
    "max_shells": 8,             # oldest idle shell is reaped beyond this
    "idle_timeout_secs": 3600,   # a shell idle this long is reaped
    "backlog": 2000,             # events kept per shell (cursor catch-up)
}
SHELL_ENV = {
    "max_shells": "LONGRUN_SHELL_MAX",
    "idle_timeout_secs": "LONGRUN_SHELL_IDLE_SECS",
    "backlog": "LONGRUN_SHELL_BACKLOG",
}

#: `config/tools.yaml` -> `webhooks:` (2026-11-06). Same chain, one reader:
#: `core/webhooks.py` never holds a number of its own.
WEBHOOKS_DEFAULTS = {
    "max_hooks": 20,
    "max_body_kb": 256,
    "deliveries_keep": 50,
    "dedupe_window_secs": 600,
    "max_per_minute": 6,
    "payload_chars": 6000,
}
WEBHOOKS_ENV = {
    "max_body_kb": "LONGRUN_WEBHOOK_MAX_BODY_KB",
    "max_per_minute": "LONGRUN_WEBHOOK_MAX_PER_MINUTE",
}

#: `config/tools.yaml` -> `limits:`. Every value that used to be
#: `int(os.environ.get("LONGRUN_…", <literal>))` somewhere in `src/`.
#: Fallback only: `v827` fails if a key here has no config row.
LIMITS_DEFAULTS = {
    # --- router / LLM I/O (`model/rllm.py`) ---
    "router_retries": 5,
    "router_backoff": 0.75,
    "router_backoff_max": 8.0,
    "model_load_timeout_secs": 900,
    "router_idle_timeout_secs": 120.0,
    "connect_timeout_secs": 3.0,
    # --- model context + answer budget (`model/rllm.py`, `model/context_engine.py`) ---
    "max_tokens": 16384,
    "context_reserve": 4096,
    "compact_force_ratio": 0.5,
    "summarizer_max_chars": 60000,
    "context_budget": 262144,
    "context_keep_recent": 8,
    "context_retrieval_k": 3,
    # --- repetition guard (`model/rllm.py`) ---
    "repeat_guard_enabled": True,
    "repeat_min_period": 20,
    "repeat_max_period": 240,
    "repeat_limit": 4,
    # --- HTTP server + SSE (`core/server.py`, `core/sse.py`) ---
    "http_max_body_bytes": 8 * 1024 * 1024,
    "feed_replay_max": 300,
    "chat_stream_idle_secs": 900.0,
    "think_flush_secs": 0.08,
    "think_live_cap": 0,
    # --- retention / stores (`core/events.py`, `memory/stores.py`, `memory/threads.py`) ---
    "events_keep": 200000,
    "events_prune_secs": 900.0,
    "feed_events_max": 800,
    "prune_batch": 50000,
    "tool_event_max": 2000,
    "thread_digest_max": 1500,
    "thread_line_max": 240,
    "thread_groups_max": 2000,
    "memory_core_max": 4000,
    "memory_max_records": 300,
    "offload_keep_files": 200,
    "offload_keep_days": 30.0,
    # --- editing (`tools/tools.py`) ---
    "fs_edit_max_edits": 50,
    "fs_edit_stale_guard": True,
    # --- skills / graph / jobs / teams / held-out gate ---
    "skill_max_zip_bytes": 20 * 1024 * 1024,
    "skill_max_unzip_bytes": 60 * 1024 * 1024,
    "skill_max_files": 500,
    "graph_orphan_days": 14.0,
    "job_retries": 1,
    "team_local_slots": 1,
    "require_heldout": True,
    "tls_enabled": True,
}
LIMITS_ENV = {
    "router_retries": "LONGRUN_ROUTER_RETRIES",
    "router_backoff": "LONGRUN_ROUTER_BACKOFF",
    "router_backoff_max": "LONGRUN_ROUTER_BACKOFF_MAX",
    "model_load_timeout_secs": "LONGRUN_MODEL_LOAD_TIMEOUT",
    "router_idle_timeout_secs": "LONGRUN_ROUTER_IDLE_TIMEOUT",
    "connect_timeout_secs": "LONGRUN_CONNECT_TIMEOUT",
    "max_tokens": "LONGRUN_MAX_TOKENS",
    "context_reserve": "LONGRUN_CONTEXT_RESERVE",
    "compact_force_ratio": "LONGRUN_COMPACT_FORCE_RATIO",
    "summarizer_max_chars": "LONGRUN_SUMMARIZER_MAX_CHARS",
    "context_budget": "LONGRUN_CONTEXT_BUDGET",
    "context_keep_recent": "LONGRUN_CONTEXT_KEEP_RECENT",
    "context_retrieval_k": "LONGRUN_CONTEXT_RETRIEVAL_K",
    "repeat_guard_enabled": "LONGRUN_REPEAT_GUARD",
    "repeat_min_period": "LONGRUN_REPEAT_MIN_PERIOD",
    "repeat_max_period": "LONGRUN_REPEAT_MAX_PERIOD",
    "repeat_limit": "LONGRUN_REPEAT_LIMIT",
    "http_max_body_bytes": "LONGRUN_MAX_BODY",
    "feed_replay_max": "LONGRUN_FEED_REPLAY",
    "chat_stream_idle_secs": "LONGRUN_CHAT_STREAM_IDLE",
    "think_flush_secs": "LONGRUN_THINK_FLUSH_S",
    "think_live_cap": "LONGRUN_THINK_LIVE_CAP",
    "events_keep": "LONGRUN_EVENTS_KEEP",
    "events_prune_secs": "LONGRUN_EVENTS_PRUNE_S",
    "tool_event_max": "LONGRUN_TOOL_EVENT_MAX",
    "thread_digest_max": "LONGRUN_THREAD_DIGEST",
    "thread_groups_max": "LONGRUN_THREAD_GROUPS",
    "memory_core_max": "LONGRUN_CORE_MAX",
    "memory_max_records": "LONGRUN_MEMORY_MAX_RECORDS",
    "offload_keep_files": "LONGRUN_OFFLOAD_KEEP_FILES",
    "offload_keep_days": "LONGRUN_OFFLOAD_KEEP_DAYS",
    "skill_max_zip_bytes": "LONGRUN_SKILL_MAX_ZIP",
    "skill_max_unzip_bytes": "LONGRUN_SKILL_MAX_UNZIP",
    "skill_max_files": "LONGRUN_SKILL_MAX_FILES",
    "graph_orphan_days": "LONGRUN_GRAPH_ORPHAN_DAYS",
    "job_retries": "LONGRUN_JOB_RETRIES",
    "team_local_slots": "LONGRUN_TEAM_LOCAL_SLOTS",
    "require_heldout": "LONGRUN_REQUIRE_HELDOUT",
    "tls_enabled": "LONGRUN_TLS",
    "fs_edit_max_edits": "LONGRUN_FS_EDIT_MAX_EDITS",
    "fs_edit_stale_guard": "LONGRUN_FS_EDIT_STALE",
}


def cfg(override=None):
    """The effective `context:` block: DEFAULTS <- tools.yaml -> `override`."""
    return _section("context", DEFAULTS, override)


def shell_cfg(override=None):
    """The effective `shell:` block: SHELL_DEFAULTS <- tools.yaml -> `override`."""
    return _section("shell", SHELL_DEFAULTS, override)


def limits_cfg(override=None):
    """The effective `limits:` block: LIMITS_DEFAULTS <- tools.yaml -> `override`."""
    return _section("limits", LIMITS_DEFAULTS, override)


def get(name, override=None):
    """One `context:` limit as an int (config-first, floor 1 unless 0 is allowed)."""
    return _as_int(_raw("context", DEFAULTS, ENV, name, override), DEFAULTS, name)


def shell(name, override=None):
    """One `shell:` limit as an int (`max_shells`/`idle_timeout_secs`/`backlog`)."""
    return _as_int(_raw("shell", SHELL_DEFAULTS, SHELL_ENV, name, override),
                   SHELL_DEFAULTS, name)


def limit(name, override=None):
    """One `limits:` value as an int (see `LIMITS_DEFAULTS`)."""
    return _as_int(_raw("limits", LIMITS_DEFAULTS, LIMITS_ENV, name, override),
                   LIMITS_DEFAULTS, name)


def webhook(name, override=None):
    """One `webhooks:` value as an int (see `WEBHOOKS_DEFAULTS`)."""
    return _as_int(_raw("webhooks", WEBHOOKS_DEFAULTS, WEBHOOKS_ENV, name, override),
                   WEBHOOKS_DEFAULTS, name)


def limitf(name, override=None):
    """One `limits:` value as a float (timeouts, ratios, backoff)."""
    raw = _raw("limits", LIMITS_DEFAULTS, LIMITS_ENV, name, override)
    try:
        num = float(raw)
    except (TypeError, ValueError):
        num = float(LIMITS_DEFAULTS[name])
    if name not in _ZERO_OK and num <= 0:
        num = float(LIMITS_DEFAULTS[name])
    return num


def limitb(name, override=None):
    """One `limits:` value as a bool (`true/false/1/0/yes/no/on/off`)."""
    raw = _raw("limits", LIMITS_DEFAULTS, LIMITS_ENV, name, override)
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("0", "false", "no", "off", ""):
        return False
    if text in ("1", "true", "yes", "on"):
        return True
    return bool(LIMITS_DEFAULTS[name])


def limit_set(name, override=None):
    """True when `limits: name` resolves to something OTHER than the shipped default.

    Used where the config value must act as an explicit override of a computed
    value (`context_budget`: a flat budget wins over the model's real window),
    so the module never reads the env var itself — one chain, one reader.
    """
    return limit(name, override) != int(LIMITS_DEFAULTS[name])


def _section(section, defaults, override=None):
    from longrun.tools.registry import section_config
    try:
        return section_config(section, defaults, override)
    except Exception:  # noqa: BLE001 — a config read must never break a turn
        return dict(defaults)


def _raw(section, defaults, envmap, name, override=None):
    """The ONE resolution chain: explicit override -> env -> config -> default."""
    if name not in defaults:
        raise KeyError("unknown %s limit: %r" % (section, name))
    over = (override or {}).get(name)
    if over is not None:
        return over
    env = envmap.get(name)
    if env:
        got_env = os.environ.get(env)
        if got_env not in (None, ""):
            return got_env
    try:
        got = (_section(section, defaults) or {}).get(name)
    except Exception:  # noqa: BLE001
        got = None
    return defaults[name] if got is None else got


def _as_int(value, defaults, name):
    """A positive int (or >= 0 for the `_ZERO_OK` keys); bad input -> the default."""
    try:
        num = int(value)
    except (TypeError, ValueError):
        num = int(defaults[name])
    if name not in _ZERO_OK and num < 1:
        num = 1
    return num
