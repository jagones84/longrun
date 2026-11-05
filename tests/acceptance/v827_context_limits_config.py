#!/usr/bin/env python3
"""v827 — every context budget is a CONFIG value, never a Python literal (2026-11-05).

Operator, verbatim: *"nonono please all in config files. all in config files i told
idiot! no hardocoding!!"*. Before this test the budgets that decide how much text
reaches the model were literals in the modules that used them (`agent.py`
6000/200000/1500/600/4000/1200, `prompt.py` 2600/1200/120, `rules.py` 32 KB,
`term.py` 200000, `tools.py` 65536, `sandbox.py` 2 MB, `acceptance.py` 20/200) or a
LONGRUN_* env var with a literal default.

The contract pinned here:

  * `config/tools.yaml` -> `context:` is the ONLY source of truth, and it is
    COMPLETE (every resolver key has a row, and no row is unknown);
  * the value each module binds at import equals the config value (no drift);
  * the env var still wins (tests / one-off runs), a typo cannot switch a budget
    off (floor 1), and an unknown name fails loudly;
  * no consumer module still reads its own env var or hardcodes its number;
  * the block is wired into Settings (same panel as `runtime`).

Deterministic and offline: no server, no model, no network.
Run: python3 tests/acceptance/v827_context_limits_config.py
"""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v827-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
for _d in ("cfg", "sessions", "data"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

import yaml  # noqa: E402

from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}   # never spawn an MCP client in a test

# Import order matters: server.py imports agent.py (circular ImportError otherwise).
from longrun.core import server as _srv  # noqa: E402,F401
from longrun.model import context_limits as CL  # noqa: E402
from longrun.model import prompt as P  # noqa: E402
from longrun.agent import agent as A  # noqa: E402
from longrun.agent import acceptance as AC  # noqa: E402
from longrun.memory import rules as R  # noqa: E402
from longrun.tools import term as T  # noqa: E402
from longrun.tools import sandbox as SB  # noqa: E402
from longrun.tools import tools as TL  # noqa: E402
from longrun.core import settings as S  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# The shipped YAML block — read as a human edits it, not through the resolver.
with open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8") as _f:
    _yaml_raw = yaml.safe_load(_f) or {}
_yaml_ctx = _yaml_raw.get("context") or {}
_yaml_shell = _yaml_raw.get("shell") or {}

# ---------------------------------------------------------------- completeness
check("A1 config/tools.yaml declares a `context:` block", bool(_yaml_ctx), sorted(_yaml_ctx)[:3])
_missing_rows = sorted(k for k in CL.DEFAULTS if k not in _yaml_ctx)
check("A2 every resolver key has a config row (none left code-only)", not _missing_rows, _missing_rows)
_unknown_rows = sorted(k for k in _yaml_ctx if k not in CL.DEFAULTS)
check("A3 the resolver knows every configured key (no silent extra)", not _unknown_rows, _unknown_rows)

# ------------------------------------------------------------------ resolution
# `registry.load_config()` is the merged view (shipped YAML + the WebUI overlay)
# and the ONLY thing `section_config` reads. `_merge_into` keeps a WHITELIST of
# blocks: a block missing from it is silently dropped and the resolver falls back
# to DEFAULTS forever — measured live 2026-11-05, when editing the YAML to 6100
# still resolved to 6000. A4 therefore compares against the loaded view, not
# against the raw file.
_loaded = registry.load_config().get("context") or {}
_dropped = sorted(k for k in _yaml_ctx if k not in _loaded)
check("A4 the config loader carries the whole block (no whitelist drop)",
      not _dropped, _dropped)
_drift = {k: (CL.get(k), _loaded.get(k)) for k in CL.DEFAULTS
          if _loaded.get(k) is None or CL.get(k) != int(_loaded[k])}
check("A5 each limit resolves to the loaded config value", not _drift, _drift)

_bad_types = {k: v for k, v in (CL.cfg() or {}).items() if not isinstance(v, int)}
check("A5b the effective block is all ints", not _bad_types, _bad_types)

# ------------------------------------------------------- the shell-pool block
check("A5c config/tools.yaml declares a `shell:` block", bool(_yaml_shell), sorted(_yaml_shell))
_missing_shell = sorted(k for k in CL.SHELL_DEFAULTS if k not in _yaml_shell)
check("A5d every shell default has a config row", not _missing_shell, _missing_shell)
_unknown_shell = sorted(k for k in _yaml_shell if k not in CL.SHELL_DEFAULTS)
check("A5e the resolver knows every shell key", not _unknown_shell, _unknown_shell)
_loaded_shell = registry.load_config().get("shell") or {}
check("A5f the loader carries the shell block (no whitelist drop)",
      not [k for k in _yaml_shell if k not in _loaded_shell],
      sorted(k for k in _yaml_shell if k not in _loaded_shell))
_shell_drift = {k: (CL.shell(k), _loaded_shell.get(k)) for k in CL.SHELL_DEFAULTS
                if _loaded_shell.get(k) is None or CL.shell(k) != int(_loaded_shell[k])}
check("A5g each shell limit resolves to the loaded config value", not _shell_drift, _shell_drift)
check("A5h tools/term.py binds the shell limits",
      int(T.MAX_SHELLS) == CL.shell("max_shells")
      and int(T.IDLE_TIMEOUT) == CL.shell("idle_timeout_secs")
      and int(T.BACKLOG) == CL.shell("backlog"),
      (T.MAX_SHELLS, T.IDLE_TIMEOUT, T.BACKLOG))
check("A5i the shell block is wired into Settings",
      (S.DEDICATED.get("tools.yaml") or {}).get("shell") == "Settings ▸ Harness")

# ---------------------------------------------------------------- the consumers
BOUND = {
    "chat_tool_steps": ("agent", A.CHAT_TOOL_MAX_STEPS),
    "chat_tool_iters": ("agent", A.CHAT_TOOL_MAX_ITERS),
    "plan_tool_steps": ("agent", A.PLAN_ONLY_MAX_STEPS),
    "tool_obs_limit": ("agent", A.CHAT_TOOL_OBS_LIMIT),
    "subagent_wait_secs": ("agent", A.SUBAGENT_WAIT),
    "render_max": ("agent", A.CHAT_OBS_FULL),
    "offload_head": ("agent", A._OFFLOAD_HEAD),
    "offload_tail": ("agent", A._OFFLOAD_TAIL),
    "memory_prompt_max_chars": ("prompt", P._MEM_PROMPT_MAX),
    "memory_item_chars": ("prompt", P._MEM_ITEM_CHARS),
    "rules_prompt_max_bytes": ("rules", R.MAX_BYTES),
    "shell_capture_max": ("term", T.CAPTURE_MAX),
    "sandbox_max_output_bytes": ("sandbox", SB.MAX_OUTPUT_BYTES),
    "acceptance_max_predicates": ("acceptance", AC.MAX_PREDICATES),
    "acceptance_max_predicate_len": ("acceptance", AC.MAX_PREDICATE_LEN),
}
_consumer_drift = {k: (src, val, CL.get(k)) for k, (src, val) in BOUND.items()
                   if int(val) != CL.get(k)}
check("A6 every module binds the config value (no drift)", not _consumer_drift, _consumer_drift)

_source = _src("src", "longrun", "agent", "agent.py")
check("A7 the per-turn reference caps come from config",
      'ctx_limits.get("reference_max_chars")' in _source
      and 'ctx_limits.get("reference_role_max_chars")' in _source)
check("A8 the skills index cap comes from config",
      'ctx_limits.get("skills_prompt_max_chars")' in _src("src", "longrun", "model", "prompt.py"))
check("A9 the acceptance 'missing' list caps come from config",
      'ctx_limits.get("acceptance_missing_items")' in _source
      and 'ctx_limits.get("acceptance_missing_chars")' in _source)
check("A10 fs.read's default comes from config",
      'ctx_limits.get("fs_read_max_bytes")' in _src("src", "longrun", "tools", "tools.py"))
check("A11 the fs.read schema no longer advertises a literal default",
      '"default": 65536' not in _src("src", "longrun", "tools", "registry.py"))

# ------------------------------------------------------------- the chain rules
_env = "LONGRUN_TOOL_OBS_LIMIT"
_old = os.environ.get(_env)
os.environ[_env] = "7000"
try:
    check("A12 an env var still overrides the config", CL.get("tool_obs_limit") == 7000,
          CL.get("tool_obs_limit"))
finally:
    if _old is None:
        os.environ.pop(_env, None)
    else:
        os.environ[_env] = _old
check("A13 a YAML typo cannot switch a budget off (floor 1)",
      CL.get("tool_obs_limit", {"tool_obs_limit": 0}) == 1)
try:
    CL.get("no_such_limit")
    _raised = False
except KeyError:
    _raised = True
check("A14 an unknown limit name fails loudly", _raised)

# ------------------------------------------------- no consumer owns its env var
_OWNERS = (("src", "longrun", "agent", "agent.py"), ("src", "longrun", "model", "prompt.py"),
           ("src", "longrun", "memory", "rules.py"), ("src", "longrun", "tools", "term.py"),
           ("src", "longrun", "tools", "tools.py"), ("src", "longrun", "tools", "sandbox.py"),
           ("src", "longrun", "agent", "acceptance.py"))
_leaks = {p[-1]: [e for e in list(CL.ENV.values()) + list(CL.SHELL_ENV.values())
                  if e in _src(*p)] for p in _OWNERS}
_leaks = {k: v for k, v in _leaks.items() if v}
check("A15 only context_limits.py reads LONGRUN_* context env vars", not _leaks, _leaks)

# ------------------------------------------------------------------- Settings
check("A16 the block is wired into the Harness settings panel",
      (S.DEDICATED.get("tools.yaml") or {}).get("context") == "Settings ▸ Harness")

# --------------------------------------------------- no literal survives (scan)
_literals = {
    "agent.py": [r"LONGRUN_TOOL_OBS_LIMIT", r"LONGRUN_OFFLOAD_MAX",
                 r"LONGRUN_CHAT_TOOL_STEPS", r"LONGRUN_CHAT_TOOL_ITERS",
                 r"LONGRUN_PLAN_TOOL_STEPS", r"LONGRUN_SUBAGENT_WAIT",
                 r"_OFFLOAD_HEAD = \d+", r"_OFFLOAD_TAIL = \d+",
                 r"CHAT_TOOL_OBS_LIMIT = int\("],
    "prompt.py": [r"max_chars=2600", r"_MEM_PROMPT_MAX = \d+", r"_MEM_ITEM_CHARS = \d+"],
    "rules.py": [r"LONGRUN_RULES_MAX"],
    "term.py": [r"CAPTURE_MAX = \d", r"^MAX_SHELLS = \d", r"^IDLE_TIMEOUT = \d",
                r"^BACKLOG = \d"],
    "sandbox.py": [r"LONGRUN_SANDBOX_MAX_OUTPUT"],
}
_found = {}
for fname, pats in _literals.items():
    src = _src("src", "longrun", "agent", fname) if fname in ("agent.py", "acceptance.py") else None
    if src is None:
        for sub in ("model", "memory", "tools", "agent"):
            fp = os.path.join(REPO, "src", "longrun", sub, fname)
            if os.path.isfile(fp):
                src = _src("src", "longrun", sub, fname)
                break
    hits = [p for p in pats if src and re.search(p, src, re.M)]
    if hits:
        _found[fname] = hits
check("A17 no migrated literal or env read survives in the consumers", not _found, _found)

print("%d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
