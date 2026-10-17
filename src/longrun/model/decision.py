#!/usr/bin/env python3
"""Local decision-model hooks (JAG-426 · Domain 6).

The harness routed per ROLE and always waited for the frontier model. This adds a
pluggable decision layer in front of the loop so a cheap, LOCAL model (or a pure
heuristic) can take the high-frequency, low-latency decisions — the pattern NVIDIA
NeMo Switchyard names "plans route up to the frontier, execution routes down to
Lightning" (and that speculative-tool-call work applies to pruning next actions):

    route(ctx)              -> which model should take this step
    prune(ctx, candidates)  -> rank/drop candidate actions BEFORE the model call
    validate(ctx, action)   -> reject a futile/denied action BEFORE approval+exec
    predict_next_tools(ctx) -> (speculation; read-only prefetch, off by default)

Ship-with guarantees (config/decisions.yaml, default `mode: null`):
  * `NullDecision` is a no-op, so today's behaviour is byte-identical;
  * every hook FAILS OPEN — an exception must never block a legitimate action;
  * a real local model plugs in by implementing the same Protocol; nothing in the
    loop changes.

Pure module: no server import at load, no network, no model call in the heuristic.
"""
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol, runtime_checkable

CONFIG_PATH = None  # resolved lazily (needs registry.REPO)


@dataclass
class StepCtx:
    """Everything a decision needs about the current step (cheap to build)."""
    role: str = "agent"
    step: int = 0
    goal: str = ""
    plan_open: int = 0
    last_tool: str = ""
    session: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutingHint:
    model: str = ""
    reason: str = ""


@dataclass
class Verdict:
    ok: bool = True
    reason: str = ""


@runtime_checkable
class DecisionModel(Protocol):
    """The interface a local decision/world model implements to plug in."""
    name: str

    def route(self, ctx: StepCtx) -> RoutingHint:
        ...

    def prune(self, ctx: StepCtx, candidates: List[Any]) -> List[Any]:
        ...

    def validate(self, ctx: StepCtx, action: Dict[str, Any]) -> Verdict:
        ...

    def predict_next_tools(self, ctx: StepCtx, k: int) -> List[str]:
        ...


class NullDecision:
    """Default: no decision layer at all — exactly today's behaviour."""

    name = "null"

    def route(self, ctx):
        return RoutingHint()

    def prune(self, ctx, candidates):
        return list(candidates or [])

    def validate(self, ctx, action):
        return Verdict()

    def predict_next_tools(self, ctx, k):
        return []


class HeuristicDecision:
    """A pure-Python decision model: no model call, deterministic, testable.

    It reuses the primitives the harness already trusts — the tool registry's
    hard-deny list, the deterministic process-reward ranker (`plan.prm`) — so it
    can prune and validate at zero latency and zero cost.
    """

    name = "heuristic"

    def route(self, ctx):
        try:
            from longrun.model import routing
            # JAG-455: there is no `planner` role any more — a step never switches
            # to a different model just because a plan is open.
            role = ctx.role or "agent"
            m = routing.pick(role)
            return RoutingHint(model=m or "", reason="role=%s" % role)
        except Exception:  # noqa: BLE001
            return RoutingHint()

    def prune(self, ctx, candidates):
        cands = list(candidates or [])
        if len(cands) < 2:
            return cands
        try:
            from longrun.plan import prm
            return [t for t, _ in prm.rank(cands)]
        except Exception:  # noqa: BLE001 — pruning must never drop a candidate by accident
            return cands

    def validate(self, ctx, action):
        try:
            from longrun.tools import registry
            tool = str((action or {}).get("tool") or "")
            args = (action or {}).get("args") or {}
            if not tool:
                return Verdict()
            spec = registry.tool_spec(tool) or {}
            subject = registry._subject(tool, args)
            hit = registry._match(spec.get("deny") or [], subject)
            if hit:
                return Verdict(ok=False, reason="%s matches the hard-deny pattern %r" % (tool, hit))
        except Exception:  # noqa: BLE001 — fail OPEN
            return Verdict()
        return Verdict()

    def predict_next_tools(self, ctx, k):
        # Speculation stays OFF here: predicting without a real predictor would
        # just burn tokens. A LocalRouterDecision supplies this instead.
        return []


# ------------------------------------------------------------------ config ----

_DEFAULTS = {"enabled": False, "mode": "null",
             "speculative": {"enabled": False, "k": 2, "readonly_only": True}}

# JAG-426-fix: `pre_tool` runs on EVERY tool call, and it used to re-read + re-parse
# `config/decisions.yaml` on each one (twice). Memoise on (path, mtime, size) so the
# no-op layer costs nothing on the hot path while an edited config still applies.
_cfg_cache = {"key": None, "cfg": None}


def _path():
    global CONFIG_PATH
    if CONFIG_PATH:
        return CONFIG_PATH
    try:
        from longrun.tools import registry
        CONFIG_PATH = os.path.join(registry.REPO, "config", "decisions.yaml")
    except Exception:  # noqa: BLE001
        CONFIG_PATH = "config/decisions.yaml"
    return CONFIG_PATH


def _overlay_path():
    """JAG-491: the WebUI-structured form writes a gitignored overlay.

    The shipped file keeps its documentation; the overlay is merged on top
    (key-by-key, `speculative` merged too). An explicit LONGRUN_DECISIONS
    (tests) disables the overlay unless LONGRUN_DECISIONS_OVERLAY names one.
    """
    explicit = os.environ.get("LONGRUN_DECISIONS_OVERLAY")
    if explicit:
        return explicit
    if os.environ.get("LONGRUN_DECISIONS"):
        return ""
    try:
        from longrun.util.paths import DATA_DIR
        return os.path.join(DATA_DIR, "decisions.overlay.yaml")
    except Exception:  # noqa: BLE001
        return ""


def _stat_key(path):
    key = [path]
    for p in (path, _overlay_path()):
        try:
            st = os.stat(p) if p else None
            key.extend([st.st_mtime_ns, st.st_size] if st else [None, None])
        except OSError:
            key.extend([None, None])
    return tuple(key)


def _merge_file(cfg, path):
    """Merge one decisions document into `cfg` (best effort)."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        try:
            import yaml
            data = yaml.safe_load(raw)
        except Exception:  # noqa: BLE001
            import json
            data = json.loads(raw)
        if isinstance(data, dict):
            for k, v in data.items():
                if k != "speculative" or not isinstance(v, dict):
                    cfg[k] = v
                else:
                    cfg["speculative"].update(v)
    except OSError:
        pass
    return cfg


def load_config():
    # Absent file / bad stat -> a cacheable "missing" key, so a later appearance
    # of the file still invalidates the entry.
    path = _path()
    key = _stat_key(path)
    if _cfg_cache["key"] == key and _cfg_cache["cfg"] is not None:
        return dict(_cfg_cache["cfg"])
    cfg = {"speculative": dict(_DEFAULTS["speculative"])}
    cfg.update({k: v for k, v in _DEFAULTS.items() if k != "speculative"})
    _merge_file(cfg, path)
    overlay = _overlay_path()
    if overlay:
        _merge_file(cfg, overlay)
    _cfg_cache["key"] = key
    _cfg_cache["cfg"] = cfg
    return dict(cfg)


def get():
    """The active decision model. `null` unless explicitly enabled."""
    cfg = load_config()
    if not cfg.get("enabled"):
        return NullDecision()
    mode = str(cfg.get("mode") or "null").lower()
    if mode == "heuristic":
        return HeuristicDecision()
    # 'local' would return a LocalRouterDecision in a deployment that ships one.
    return NullDecision()


def speculative(cfg=None):
    """The speculative-execution settings (default: OFF)."""
    return (cfg or load_config()).get("speculative") or dict(_DEFAULTS["speculative"])


# ------------------------------------------------------------- loop hooks -----

def pre_tool(tool, args, ctx=None):
    """Guard a tool call BEFORE the approval round-trip. FAIL-OPEN by design."""
    try:
        d = get()
        v = d.validate(ctx or StepCtx(), {"tool": tool, "args": args or {}})
        return {"ok": bool(v.ok), "reason": v.reason, "model": d.name}
    except Exception:  # noqa: BLE001 — a decision must never block a valid action
        return {"ok": True, "reason": "", "model": "null"}
