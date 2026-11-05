"""Context limits — every budget on how much text reaches the model (2026-11-05).

Operator rule: *"all in config files ... no hardcoding"*. Before this module each
budget was a literal in the module that used it (`agent.py` 6000/200000/1500/600/
4000/1200, `prompt.py` 2600/1200/120, `rules.py` 32 KB, `term.py` 200000,
`tools.py` 65536, `sandbox.py` 2 MB, `acceptance.py` 20/200) or an env var with a
literal default, so changing one needed a code edit and nothing in Settings could
show it.

Now `config/tools.yaml` -> `context:` is the source of truth and this module is
the ONLY reader. Resolution order, identical to `runtime` (JAG-483):

    explicit override  ->  LONGRUN_* env var  ->  config/tools.yaml `context:`
    (+ data/tools.overlay.yaml)  ->  DEFAULTS below

`DEFAULTS` is a FALLBACK for a missing/broken config file, never a second source:
`v827_context_limits_config` fails if a DEFAULTS key has no `context:` row.

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
    "chat_tool_steps": 8,
    "chat_tool_iters": 64,
    "plan_tool_steps": 3,
    "subagent_wait_secs": 180,
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

#: Keys where 0 is a meaningful value ("show none"); everything else floors at 1
#: so a typo in the YAML cannot switch a budget off and flood the context.
_ZERO_OK = frozenset({"acceptance_missing_items", "acceptance_missing_chars"})


def cfg(override=None):
    """The effective `context:` block: DEFAULTS <- tools.yaml -> `override`."""
    from longrun.tools.registry import section_config
    try:
        return section_config("context", DEFAULTS, override)
    except Exception:  # noqa: BLE001 — a config read must never break a turn
        return dict(DEFAULTS)


def get(name, override=None):
    """One limit as an int, resolved config-first (see the module docstring).

    An unknown name raises `KeyError`: a typo must fail loudly at import, not
    silently return a different budget.
    """
    if name not in DEFAULTS:
        raise KeyError("unknown context limit: %r" % (name,))
    over = (override or {}).get(name)
    if over is not None:
        return _coerce(name, over)
    env = ENV.get(name)
    if env:
        raw = os.environ.get(env)
        if raw not in (None, ""):
            return _coerce(name, raw)
    try:
        got = (cfg() or {}).get(name)
    except Exception:  # noqa: BLE001
        got = None
    return _coerce(name, DEFAULTS[name] if got is None else got)


def _coerce(name, value):
    """A positive int (or >= 0 for the `_ZERO_OK` keys); bad input -> the default."""
    try:
        num = int(value)
    except (TypeError, ValueError):
        num = int(DEFAULTS[name])
    if name not in _ZERO_OK and num < 1:
        num = 1
    return num
