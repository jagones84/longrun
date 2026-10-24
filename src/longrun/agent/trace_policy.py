"""Single-trace safety rules over the run trace (M3a).

Local-Allow-Global-Deny splits policy in two: four single-trace safety
conjuncts (intent C1, provenance C3, consent C4, delegation C5) that a
per-trace monitor CAN enforce, and purpose (C2), a relational 2-safety
hyperproperty that NO per-trace monitor detects without false alarms
(Thm. 3) — cross-execution monitoring, explicitly out of scope here.

Mapping onto this harness:
  R1 delegation-revalidation (C5): a mutating action that cites a subagent
      id as justification needs that id to exist; a phantom id escalates
      auto to required. Deterministic, no NLP.
  R2 consent-cumulative (C4): executed mutating calls are counted from the
      run trace; past `consent_budget` (default 12, 0 = off) every auto
      escalates to required. Escalation only, never deny.
  R3 intent-fence (C1): the proposed subject, never named in the run goal
      or user messages, earns a harness note in the next turn — never a
      block (per-trace locus of blame does not exist, Thm. 3).

Pure + deterministic: the only I/O is load() of the yaml; no model, no
network. A missing/unparseable/disabled config fails open (returns None:
behaviour unchanged).
"""

import json
import os
import re

import yaml

from longrun.tools import registry
from longrun.util.paths import REPO_ROOT as REPO

_SUB_ID = re.compile(r"sub_[0-9a-f]{10}\b")
_TOKEN = re.compile(r"[a-z0-9]+")

DEFAULTS = {"enabled": True,
            "delegation_revalidation": True,
            "consent_budget": 12,
            "intent_fence": True}

_MISS = object()
_CACHE = {}


def _to_budget(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULTS["consent_budget"]
    return n if n >= 0 else DEFAULTS["consent_budget"]


def _base_path():
    explicit = os.environ.get("LONGRUN_TRACE_POLICY")
    if explicit:
        return explicit
    return os.path.join(REPO, "config", "trace_policy.yaml")


def _overlay_path():
    """WebUI-structured form writes a gitignored overlay (base keeps its docs).

    An explicit LONGRUN_TRACE_POLICY (tests) disables the overlay unless
    LONGRUN_TRACE_POLICY_OVERLAY names one (same split as decisions.py).
    """
    explicit = os.environ.get("LONGRUN_TRACE_POLICY_OVERLAY")
    if explicit:
        return explicit
    if os.environ.get("LONGRUN_TRACE_POLICY"):
        return ""
    try:
        from longrun.util.paths import DATA_DIR
        return os.path.join(DATA_DIR, "trace_policy.overlay.yaml")
    except Exception:  # noqa: BLE001
        return ""


def _stat_key(base, overlay):
    key = [base, overlay]
    for p in (base, overlay):
        try:
            st = os.stat(p) if p else None
            key.extend([st.st_mtime_ns, st.st_size] if st else [None, None])
        except OSError:
            key.extend([None, None])
    return tuple(key)


def _read_doc(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:  # noqa: BLE001 — a broken file fails open, never breaks runs
        return None
    return data if isinstance(data, dict) else None


def _apply(cfg, data):
    if isinstance(data.get("enabled"), bool):
        cfg["enabled"] = data["enabled"]
    if isinstance(data.get("delegation_revalidation"), bool):
        cfg["delegation_revalidation"] = data["delegation_revalidation"]
    if isinstance(data.get("intent_fence"), bool):
        cfg["intent_fence"] = data["intent_fence"]
    if "consent_budget" in data:
        cfg["consent_budget"] = _to_budget(data.get("consent_budget"))
    return cfg


def load(path=None):
    """Effective R1/R2/R3 config, or None when the rules are off.

    Base file merged with the WebUI overlay (overlay wins); a missing or
    unparseable base fails open to None. `enabled: false` stays IN the dict:
    `escalate` and the R3 hook treat it as off while the Settings form still
    displays the stored values. Cached on file stats.
    `LONGRUN_TRACE_POLICY[_OVERLAY]` override the paths (tests).
    """
    base = path or _base_path()
    overlay = "" if path else _overlay_path()
    key = _stat_key(base, overlay)
    hit = _CACHE.get(key, _MISS)
    if hit is not _MISS:
        return dict(hit) if isinstance(hit, dict) else None
    data = _read_doc(base)
    if data is None:
        _CACHE[key] = None
        return None
    cfg = _apply(dict(DEFAULTS), data)
    if overlay:
        odoc = _read_doc(overlay)
        if odoc is not None:
            cfg = _apply(cfg, odoc)
    _CACHE[key] = cfg
    return dict(cfg)


def count_required_executed(trace):
    """Mutating calls already executed in this run (proxy: the approval went
    through the `required` path and was approved). Auto-approved calls do
    NOT consume the consent budget."""
    n = 0
    for entry in trace or []:
        if not isinstance(entry, dict):
            continue
        meta = entry.get("tool_result") or {}
        if isinstance(meta, dict) and meta.get("approval_status") == "approved":
            n += 1
    return n


def unknown_subagent_ids(args, exists):
    """Subagent ids cited in `args` that name no live/durable subagent."""
    try:
        text = json.dumps(args or {}, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return []
    return sorted({t for t in _SUB_ID.findall(text) if not exists(t)})


def escalate(args, trace, cfg, subagent_exists):
    """R1+R2: (rule, reason) to upgrade auto to required, or (None, None).

    Pure given its inputs; the caller (`tool_action`) applies the upgrade
    through the existing `required` path, so no new approval flow exists.
    """
    if not cfg or cfg.get("enabled") is False:
        return None, None
    if cfg.get("delegation_revalidation"):
        try:
            unknown = unknown_subagent_ids(args, subagent_exists)
        except Exception:  # noqa: BLE001 — existence probe must not break the gate
            unknown = []
        if unknown:
            return ("delegation-revalidation",
                    "cites unknown subagent id %s — delegation must revalidate "
                    "(C5); the exact call needs approval" % unknown[0])
    budget = cfg.get("consent_budget", 0)
    try:
        budget = int(budget)
    except (TypeError, ValueError):
        budget = 0
    if budget > 0:
        spent = count_required_executed(trace)
        if spent >= budget:
            return ("consent-cumulative",
                    "cumulative consent budget exceeded (%d mutating calls "
                    "already executed, budget %d) (C4); the exact call needs "
                    "approval" % (spent, budget))
    return None, None


def intent_note(run_text, subject):
    """R3: harness note when `subject` was never named, else None.

    Token match (length >= 3, digits skipped), case-insensitive. The note
    text deliberately avoids the M2a taint markers so the fence can never
    suspend standing approvals by itself.
    """
    if not subject:
        return None
    tokens = [t for t in _TOKEN.findall(str(subject).lower())
              if len(t) >= 3 and not t.isdigit()]
    if not tokens:
        return None
    hay = str(run_text or "").lower()
    if any(t in hay for t in tokens):
        return None
    return ("[harness] off-intent note: %s was never named in this run's goal "
            "or user messages. Proceeding anyway — say so in your next thought "
            "if this is not what the operator wants." % subject)


def intent_note_for_action(act, action, goal, hist):
    """R3 entry point for the v2 loop: subject of the proposed action
    against goal + user messages. Returns a note or None."""
    subject = None
    try:
        if action == "tool":
            subject = registry._subject(act.get("tool"), act.get("args"))
        elif action == "batch":
            calls = (act or {}).get("calls") or []
            first = next((c for c in calls if isinstance(c, dict) and c.get("tool")), None)
            if first is not None:
                subject = registry._subject(first.get("tool"), first.get("args"))
    except Exception:  # noqa: BLE001 — subject probing must never break the loop
        return None
    texts = [goal]
    for msg in hist or []:
        if isinstance(msg, dict) and msg.get("role") == "user":
            texts.append(msg.get("content"))
        elif isinstance(msg, str):
            texts.append(msg)
    return intent_note("\n".join(str(t or "") for t in texts), subject)
