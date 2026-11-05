#!/usr/bin/env python3
"""v827 — every context budget is a CONFIG value, never a Python literal (2026-11-05).

Operator, verbatim: *"nonono please all in config files. all in config files i told
idiot! no hardocoding!!"* — and again later *"1) I TOLD NO HARDCODED NO HARDOCDED!"*
when the `limits:` block was still pending. Before this test the budgets that
decide how much text reaches the model were literals in the modules that used them
(`agent.py` 6000/200000/1500/600/4000/1200, `prompt.py` 2600/1200/120, `rules.py`
32 KB, `term.py` 200000/8/3600/2000, `tools.py` 65536, `sandbox.py` 2 MB,
`acceptance.py` 20/200) or a `LONGRUN_*` env var with a literal default
(`rllm.py` retries/backoff/timeouts, `server.py` body/feed/stream, `events.py`
retention, `sse.py` think flush, `skills.py`/`threads.py`/`stores.py`/`memory.py`/
`taskgraph.py`/`jobs.py`/`teams.py`/`heldout.py`).

The contract pinned here, for all THREE blocks (`context:`, `shell:`, `limits:`):

  * `config/tools.yaml` is the ONLY source of truth, and each block is COMPLETE
    (every resolver key has a row, and no row is unknown);
  * the value each module binds at import equals the config value (no drift);
  * the env var still wins (tests / one-off runs), a typo cannot switch a budget
    off (floor 1), and an unknown name fails loudly;
  * no consumer module still reads its own env var or hardcodes its number;
  * each block is wired into Settings ▸ Harness.

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

# -------------------------------------------------------- the `limits:` block
# Every value that used to be `int(os.environ.get("LONGRUN_…", <literal>))` in
# `src/` (router retries, timeouts, retention, skill caps, job retries…).
_yaml_lim = _yaml_raw.get("limits") or {}
check("A5j config/tools.yaml declares a `limits:` block", bool(_yaml_lim), sorted(_yaml_lim)[:3])
_missing_lim = sorted(k for k in CL.LIMITS_DEFAULTS if k not in _yaml_lim)
check("A5k every limits default has a config row", not _missing_lim, _missing_lim)
_unknown_lim = sorted(k for k in _yaml_lim if k not in CL.LIMITS_DEFAULTS)
check("A5l the resolver knows every limits key", not _unknown_lim, _unknown_lim)
_loaded_lim = registry.load_config().get("limits") or {}
check("A5m the loader carries the limits block (no whitelist drop)",
      not [k for k in _yaml_lim if k not in _loaded_lim],
      sorted(k for k in _yaml_lim if k not in _loaded_lim))
_lim_drift = {}
for _k, _dflt in CL.LIMITS_DEFAULTS.items():
    _got = _loaded_lim.get(_k)
    if _got is None:
        _lim_drift[_k] = (None, _dflt)
    elif isinstance(_dflt, bool):
        if CL.limitb(_k) != bool(_got):
            _lim_drift[_k] = (CL.limitb(_k), _got)
    elif isinstance(_dflt, float):
        if CL.limitf(_k) != float(_got):
            _lim_drift[_k] = (CL.limitf(_k), _got)
    elif CL.limit(_k) != int(_got):
        _lim_drift[_k] = (CL.limit(_k), _got)
check("A5n each limits value resolves to the loaded config value", not _lim_drift, _lim_drift)

# ---------------------------------------------------- the limits consumers bind
from longrun.model import rllm as RL  # noqa: E402
from longrun.model import context_engine as CE  # noqa: E402
from longrun.core import events as EV  # noqa: E402
from longrun.core import sse as SSE  # noqa: E402
from longrun.memory import stores as ST  # noqa: E402
from longrun.memory import threads as TH  # noqa: E402
from longrun.memory import memory as MEM  # noqa: E402
from longrun.memory import skills as SK  # noqa: E402
from longrun.plan import taskgraph as TG  # noqa: E402
from longrun.plan import heldout as HO  # noqa: E402

_lim_bound = {
    "router_retries": ("rllm", RL.ROUTER_RETRIES, "limit"),
    "model_load_timeout_secs": ("rllm", RL.MODEL_LOAD_TIMEOUT, "limit"),
    "context_reserve": ("rllm", RL.CONTEXT_RESERVE, "limit"),
    "summarizer_max_chars": ("rllm", RL.SUMMARIZER_MAX_CHARS, "limit"),
    "max_tokens": ("rllm", RL.MAX_TOKENS, "limit"),
    "repeat_min_period": ("rllm", RL._REPEAT_MIN_PERIOD, "limit"),
    "repeat_max_period": ("rllm", RL._REPEAT_MAX_PERIOD, "limit"),
    "repeat_limit": ("rllm", RL._REPEAT_LIMIT, "limit"),
    "router_backoff": ("rllm", RL.ROUTER_BACKOFF, "limitf"),
    "router_backoff_max": ("rllm", RL.ROUTER_BACKOFF_MAX, "limitf"),
    "router_idle_timeout_secs": ("rllm", RL.ROUTER_IDLE_TIMEOUT, "limitf"),
    "compact_force_ratio": ("rllm", RL.COMPACT_FORCE_RATIO, "limitf"),
    "connect_timeout_secs": ("rllm", RL.CONNECT_TIMEOUT, "limitf"),
    "context_budget": ("context_engine", CE.DEFAULT_BUDGET, "limit"),
    "context_keep_recent": ("context_engine", CE.DEFAULT_KEEP_RECENT, "limit"),
    "context_retrieval_k": ("context_engine", CE.RETRIEVAL_TOP_K, "limit"),
    "http_max_body_bytes": ("server", _srv.MAX_BODY_BYTES, "limit"),
    "feed_replay_max": ("server", _srv.FEED_REPLAY_MAX, "limit"),
    "chat_stream_idle_secs": ("server", _srv.CHAT_STREAM_IDLE, "limitf"),
    "feed_events_max": ("events", EV.MAX_FEED_EVENTS, "limit"),
    "events_keep": ("events", EV.EVENTS_KEEP, "limit"),
    "prune_batch": ("events", EV.PRUNE_BATCH, "limit"),
    "events_prune_secs": ("events", EV.PRUNE_INTERVAL_S, "limitf"),
    "think_flush_secs": ("sse", SSE.CHAT_THINK_FLUSH_S, "limitf"),
    "think_live_cap": ("sse", SSE.CHAT_THINK_LIVE_CAP, "limit"),
    "tool_event_max": ("stores", ST.TOOL_EVENT_MAX, "limit"),
    "thread_digest_max": ("threads", TH.MAX_DIGEST, "limit"),
    "thread_line_max": ("threads", TH.MAX_LINE, "limit"),
    "thread_groups_max": ("threads", TH.MAX_GROUPS, "limit"),
    "memory_core_max": ("memory", MEM.CORE_MAX, "limit"),
    "graph_orphan_days": ("taskgraph", TG.GRAPH_ORPHAN_DAYS, "limitf"),
}
_lim_bind_drift = {k: (src, val, getattr(CL, acc)(k))
                   for k, (src, val, acc) in _lim_bound.items()
                   if float(val) != float(getattr(CL, acc)(k))}
check("A5o every module binds its limits value (no drift)", not _lim_bind_drift, _lim_bind_drift)
check("A5p the lazily-read limits agree with the resolver",
      SK._max_zip() == CL.limit("skill_max_zip_bytes")
      and SK._max_unzip() == CL.limit("skill_max_unzip_bytes")
      and SK._max_files() == CL.limit("skill_max_files")
      and HO.require_enabled() == CL.limitb("require_heldout")
      and __import__("longrun.orchestrate.jobs", fromlist=["x"]).job_retries()
      == CL.limit("job_retries")
      and __import__("longrun.orchestrate.teams", fromlist=["x"]).local_slots()
      == CL.limit("team_local_slots"))
check("A5q the limits block is wired into Settings",
      (S.DEDICATED.get("tools.yaml") or {}).get("limits") == "Settings ▸ Harness")
# `limit_set` is how a module asks "did the operator pin this?" without reading
# the env var itself (`rllm.context_budget` is the one consumer).
check("A5r an untouched row is not reported as pinned", not CL.limit_set("context_budget"))
_old_budget = os.environ.get("LONGRUN_CONTEXT_BUDGET")
os.environ["LONGRUN_CONTEXT_BUDGET"] = "70000"
try:
    check("A5s a pinned budget wins over the model window (single reader)",
          CL.limit_set("context_budget") and RL.context_budget() == 70000,
          (CL.limit_set("context_budget"), RL.context_budget()))
finally:
    if _old_budget is None:
        os.environ.pop("LONGRUN_CONTEXT_BUDGET", None)
    else:
        os.environ["LONGRUN_CONTEXT_BUDGET"] = _old_budget

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
           ("src", "longrun", "agent", "acceptance.py"),
           # `limits:` consumers — none of them may read its own env var.
           ("src", "longrun", "model", "rllm.py"),
           ("src", "longrun", "model", "context_engine.py"),
           ("src", "longrun", "core", "server.py"), ("src", "longrun", "core", "events.py"),
           ("src", "longrun", "core", "sse.py"), ("src", "longrun", "core", "httpapi.py"),
           ("src", "longrun", "memory", "stores.py"), ("src", "longrun", "memory", "threads.py"),
           ("src", "longrun", "memory", "memory.py"), ("src", "longrun", "memory", "skills.py"),
           ("src", "longrun", "plan", "taskgraph.py"), ("src", "longrun", "plan", "heldout.py"),
           ("src", "longrun", "orchestrate", "jobs.py"),
           ("src", "longrun", "orchestrate", "teams.py"))
_leaks = {p[-1]: [e for e in (list(CL.ENV.values()) + list(CL.SHELL_ENV.values())
                              + list(CL.LIMITS_ENV.values()))
                  if e in _src(*p)] for p in _OWNERS}
_leaks = {k: v for k, v in _leaks.items() if v}
check("A15 only context_limits.py reads LONGRUN_* limit env vars", not _leaks, _leaks)

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

# ------------------------------------ no migrated `limits:` literal survives
_LIM_PATTERNS = (r"^MAX_LINE = \d", r"^MAX_DIGEST = \d", r"^MAX_GROUPS = \d",
                 r"^ROUTER_RETRIES = \d", r"^ROUTER_BACKOFF = \d",
                 r"^ROUTER_BACKOFF_MAX = \d", r"^MODEL_LOAD_TIMEOUT = \d",
                 r"^ROUTER_IDLE_TIMEOUT = \d", r"^CONTEXT_RESERVE = \d",
                 r"^COMPACT_FORCE_RATIO = \d", r"^SUMMARIZER_MAX_CHARS = \d",
                 r"^MAX_TOKENS = \d", r"^CONNECT_TIMEOUT = \d",
                 r"^DEFAULT_BUDGET = \d", r"^DEFAULT_KEEP_RECENT = \d",
                 r"^RETRIEVAL_TOP_K = \d", r"^MAX_BODY_BYTES = \d",
                 r"^FEED_REPLAY_MAX = \d", r"^CHAT_STREAM_IDLE = \d",
                 r"^MAX_FEED_EVENTS = \d", r"^EVENTS_KEEP = \d",
                 r"^PRUNE_INTERVAL_S = \d", r"^PRUNE_BATCH = \d",
                 r"^CHAT_THINK_FLUSH_S = \d", r"^CHAT_THINK_LIVE_CAP = \d",
                 r"^TOOL_EVENT_MAX = \d", r"^CORE_MAX = \d",
                 r"^GRAPH_ORPHAN_DAYS = \d", r"^REPEAT_GUARD = True")
_LIM_FILES = (("model", "rllm.py"), ("model", "context_engine.py"),
              ("core", "server.py"), ("core", "events.py"), ("core", "sse.py"),
              ("memory", "stores.py"), ("memory", "threads.py"), ("memory", "memory.py"),
              ("memory", "skills.py"), ("plan", "taskgraph.py"), ("plan", "heldout.py"),
              ("orchestrate", "jobs.py"), ("orchestrate", "teams.py"))
_lit_hits = {}
for _sub, _fname in _LIM_FILES:
    _hits = [p for p in _LIM_PATTERNS if re.search(p, _src("src", "longrun", _sub, _fname), re.M)]
    if _hits:
        _lit_hits[_fname] = _hits
check("A18 no migrated limits value is still a Python literal", not _lit_hits, _lit_hits)

print("%d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
