"""Local harness optimizer — reads session traces and proposes registry changes (S1).

An Agentron-style local optimizer (HarnessNet, arXiv:2610.15221 §3.1): a coding agent
constrained to a single agent's org scope that reads execution traces after every session
and produces ONE structured proposal targeting a tool-registry row.

The optimizer is ADDITIVE — it reads existing ledgers (runmetrics, jobcost, policy_hits)
and submits its proposal through the EXISTING approvals pipeline (`util/improve.py`):
the delta lands in the operator's inbox and, on approve, `improve.decide` applies exactly
those bytes to the sparse registry overlay (`registry.apply_delta`). The optimizer never
modifies the harness itself; `config/tools.yaml` is never touched.

Triggered by a post-session hook in `agent/agent.py` and the v2 API worker
(`core/api_v02.py`). Every hook is fail-safe: a failure here logs and continues, never
breaking the session.
"""
import ast
import json
import os
import re
import time
import warnings

from longrun.util import paths

OPTIMIZER_LOG = os.environ.get("LONGRUN_OPTIMIZER_LOG") or os.path.join(
    paths.DATA_DIR, "optimizer_runs.jsonl")

# Minimum session activity to trigger the optimizer: at least one tool call.
MIN_TOOL_CALLS = 1


def enabled():
    """Whether the post-turn proposer may run. ON by default, opt-out by env.

    Measured 2026-11-18: every chat turn with >=1 tool call ended with one
    `deepseek:deepseek-chat` call (18 in the last hour, 202 in the log), and a
    DETERMINISTIC test that drives `chat_once` therefore reached the network —
    `v693` failed with `connect(('3.173.21.63', 443))` and the battery had been
    spending money silently. One switch, read by the only call site
    (`agent.py:7500`); `tests/battery.sh` exports `LONGRUN_OPTIMIZER=0` so no
    test can spend a model call, and production is unchanged (unset = on).
    """
    return str(os.environ.get("LONGRUN_OPTIMIZER", "1")).strip().lower() \
        not in ("0", "false", "no", "off")

# RRSI (arXiv:2609.24972, abstract): recursive harness editing must condition the
# proposer on the evolution history ("encourages unexplored trajectories") and a
# pruner drops changes that are "no longer useful". The inbox is that history: the
# same delta re-proposed after a decision is noise, not exploration.
HISTORY_LIMIT = 8


def _evolution_history(limit=HISTORY_LIMIT):
    """Recent registry proposals with their decision, newest first.

    Read-only and fail-open: no history is better than no proposal. Only rows
    that actually carry a `delta` are useful here (a prose proposal has nothing
    to compare against).
    """
    try:
        from longrun.util import improve as _improve
        rows = [p for p in _improve.list_proposals() if p.get("scope") == "registry"]
    except Exception:  # noqa: BLE001 — the prompt must never break a run
        return []
    out = []
    for p in rows:
        d = p.get("delta")
        if not isinstance(d, dict) or not d:
            continue
        out.append({"id": p.get("id"), "status": str(p.get("status") or "pending"),
                    "delta": d, "reason": str(p.get("reason") or "")[:160],
                    "stale": str(p.get("stale") or "")})
        if len(out) >= limit:
            break
    # I-4: merge the DURABLE half — deltas the ledger still remembers after the
    # proposal JSON was cleared — so the pruner cannot be reset by `clear_decided`.
    seen = set()
    for h in out:
        k = _delta_key(h.get("delta"))
        if k:
            seen.add(k)
    for h in _durable_decided(limit):
        if h["key"] in seen:
            continue
        out.append(h)
        seen.add(h["key"])
        if len(out) >= limit:
            break
    return out


def _durable_decided(limit=HISTORY_LIMIT):
    """Registry deltas the LEDGER still remembers after `clear_decided` (I-4).

    `clear_decided` deletes the proposal JSON (its docstring says the ledger is
    the durable record) but the ledger row did not carry the delta IDENTITY, so
    the pruner's memory died with the file. `_submit` now stamps `delta_key` on
    each `optimizer.delta` row, so the refused deltas can be rebuilt from the
    record that is never deleted. Returns rows shaped like `_evolution_history`
    (id/status/key/reason, no `delta`).
    """
    try:
        from longrun.util import improve as _improve
        rows = _improve.ledger_tail(max(int(limit or 0) * 6, 60))
    except Exception:  # noqa: BLE001 — a read-only view must never break a run
        return []
    key_of = {}
    for r in rows:
        if isinstance(r, dict) and r.get("kind") == "optimizer.delta":
            k = str(r.get("delta_key") or "")
            if k:
                key_of.setdefault(str(r.get("proposal") or ""), k)
    if not key_of:
        return []
    out = []
    for r in rows:                          # newest first
        if not isinstance(r, dict) or r.get("kind") != "decide":
            continue
        if r.get("scope") != "registry":
            continue
        k = key_of.get(str(r.get("proposal") or ""))
        if not k:
            continue
        status = str(r.get("decision") or "denied")
        if status in ("approve", "approved"):
            status = "approved"
        elif status in ("deny", "denied"):
            status = "denied"
        out.append({"id": r.get("proposal"), "status": status, "key": k,
                    "reason": "recorded in the ledger (%s)" % status})
        if len(out) >= limit:
            break
    return out


def _delta_key(delta):
    """The IDENTITY of a delta: target/field/value/add/remove, no prose.

    `reason`/`confidence` are the model's explanation and may differ between two
    runs that propose the same change; including them would defeat the pruner.
    List order is not part of a list's identity (the validator treats a list as a
    set of entries).
    """
    d = delta if isinstance(delta, dict) else {}
    keep = {k: d.get(k) for k in ("target", "field", "value", "add", "remove")
            if k in d}
    for k in ("add", "remove"):
        if isinstance(keep.get(k), list):
            keep[k] = sorted(str(x) for x in keep[k])
    try:
        return json.dumps(keep, sort_keys=True)
    except (TypeError, ValueError):
        return ""


def _history_block(history):
    """The bounded 'already tried' section of the prompt ("" when empty)."""
    if not history:
        return ""
    lines = ["Already proposed for this registry (newest first) — do NOT propose "
             "an identical delta again (approved = already applied, denied = "
             "refused, 'cannot apply' = the registry no longer accepts it); choose "
             "a DIFFERENT row, or skip:"]
    for h in history:
        if not h.get("delta"):                # durable rows carry only the identity
            continue
        d = h.get("delta") or {}
        bits = ["%s.%s" % (d.get("target"), d.get("field"))]
        if "value" in d:
            bits.append("value=%s" % json.dumps(d.get("value")))
        for k in ("add", "remove"):
            if d.get(k):
                bits.append("%s=%s" % (k, json.dumps(d.get(k))))
        status = str(h.get("status"))
        if h.get("stale"):
            status += " · cannot apply"
        lines.append("- [%s] %s — %s" % (status, " ".join(bits),
                                         h.get("reason") or "(no reason)"))
    return "\n".join(lines)[:3000]


def _read_trace(sid):
    """Read the session trace from runmetrics. Returns {} on any failure."""
    try:
        from longrun.model import runmetrics as _rm
        return _rm.get(sid) or {}
    except Exception:  # noqa: BLE001 — read-only, must never fail the session
        return {}


def _read_policy_hits():
    """Read the policy hits ledger. Returns {} on any failure."""
    try:
        from longrun.tools import registry as _reg
        return _reg.policy_report() or {}
    except Exception:  # noqa: BLE001
        return {}


def _hit_rows(policy_hits):
    """Split the firing ledger into the rules that are LIVE and the ones RETIRED.

    The ledger is HISTORY: a rule deleted from the policy keeps its counters for
    ever, and the keys are `<tool>:<kind>:<pattern>`. 2026-11-18 (round 75) the
    prompt printed the first five ledger keys as "Policy firings" — three of them
    rules the policy no longer has (measured: `shell:deny:grep[^\\n]*\\.env`) — and
    the model proposed removing one. The registry already decides which configured
    rules fired and which ledger keys it no longer owns (`retired_rules`), so this
    function only SPLITS that classification; it never re-derives it.
    """
    hits = (policy_hits or {}).get("firings") or {}
    retired = {str(k) for k in ((policy_hits or {}).get("retired_rules") or [])}
    live, gone = [], []
    for key, rec in hits.items():
        parts = str(key).split(":", 2)
        if len(parts) != 3:
            continue
        row = {"tool": parts[0], "kind": parts[1], "pattern": parts[2],
               "n": int((rec or {}).get("n") or 0)}
        _samples = [s for s in ((rec or {}).get("samples") or []) if str(s).strip()]
        if _samples:
            row["sample"] = str(_samples[-1])
        (gone if str(key) in retired else live).append(row)
    live.sort(key=lambda r: (-r["n"], r["tool"], r["pattern"]))
    gone.sort(key=lambda r: (-r["n"], r["tool"], r["pattern"]))
    return live, gone


def _read_job_cost(jid):
    """Read per-job cost aggregate. Returns {} on any failure."""
    if not jid:
        return {}
    try:
        from longrun.orchestrate import jobcost as _jc
        return _jc.aggregate(jid) or {}
    except Exception:  # noqa: BLE001
        return {}


def _read_feedback(sid):
    """Read per-agent feedback record (from S2 backward propagation). Returns {} on any failure."""
    try:
        from longrun.orchestrate import jobcost as _jc
        return _jc.feedback_for(None, sid) or {}
    except Exception:  # noqa: BLE001 — feedback is additive, never a read failure
        return {}


_BLOCK_MARK = "[harness] BLOCKED by harness policy"
_PAT_MARK = "matches hard-deny pattern '"
_PAT_END = "' — denied because"
_ACTION_RE = re.compile(r"Action '([^']+)' BLOCKED")
_TOOL_ACTION_RE = re.compile(r'"action"\s*:\s*"(?:tool|batch)"')
REFUSAL_SCAN_MAX = 400      # messages read from the tail of the transcript


def _read_refusals(sid):
    """What the agent did AFTER each hard-deny block (round 86).

    A count alone cannot say whether a guard cost the turn: the ledger knows the
    rule fired, not whether the work continued. The transcript carries both — the
    `[harness] BLOCKED by harness policy` message names the tool and the exact
    pattern, and the next assistant message is the next attempt. Returns
    `{"<tool>:deny:<pattern>": {"n", "continued", "repeated", "gave_up"}}`:
    `continued` = a tool/batch call ran next, `repeated` = the next message is
    another block, `gave_up` = the agent answered (or the turn ended) with no
    further call. Read-only; {} on any failure.
    """
    try:
        from longrun.memory import stores as _stores
        sess = _stores.load_session(str(sid or "")) or {}
    except Exception:  # noqa: BLE001 — no transcript is no evidence
        return {}
    msgs = [m for m in (sess.get("messages") or []) if isinstance(m, dict)]
    if not msgs:
        return {}
    start = max(0, len(msgs) - REFUSAL_SCAN_MAX)
    out = {}
    for i in range(start, len(msgs)):
        content = str(msgs[i].get("content") or "")
        if _BLOCK_MARK not in content:
            continue
        _a = _ACTION_RE.search(content)
        _p0 = content.find(_PAT_MARK)
        if not _a or _p0 < 0:
            continue
        _p1 = content.find(_PAT_END, _p0 + len(_PAT_MARK))
        if _p1 < 0:
            continue
        # The block renders the pattern with `%r` (registry.classify), so the text
        # between the quotes is a Python repr: `\\s`, `\\.`, `\\'`. The ledger key
        # is the RAW pattern; decoding the repr makes the two comparable. Measured
        # on the live transcript: without this every refusal key carried doubled
        # backslashes and matched no live-firing row.
        _body = content[_p0 + len(_PAT_MARK):_p1]
        try:
            with warnings.catch_warnings():
                # An unescaped body (`[\s…`) parses with a SyntaxWarning; the
                # value is still the text, and a service log is not the place.
                warnings.simplefilter("ignore")
                _pattern = ast.literal_eval("'" + _body + "'")
        except (ValueError, SyntaxError):
            _pattern = _body
        key = "%s:deny:%s" % (_a.group(1), _pattern)
        rec = out.setdefault(key, {"n": 0, "continued": 0, "repeated": 0,
                                   "gave_up": 0})
        rec["n"] += 1
        _j = None
        for j in range(i + 1, len(msgs)):
            if msgs[j].get("role") == "assistant":
                _j = j
                break
        if _j is None:
            rec["gave_up"] += 1
            continue
        if not _TOOL_ACTION_RE.search(str(msgs[_j].get("content") or "")):
            rec["gave_up"] += 1          # an answer, or a question to the operator
            continue
        after = msgs[_j + 1] if _j + 1 < len(msgs) else None
        if after is not None and _BLOCK_MARK in str(after.get("content") or ""):
            rec["repeated"] += 1
        else:
            rec["continued"] += 1
    return out


def _optimizer_model():
    """The model the optimizer runs on: `roles.optimizer`, then the `agent` role,
    then the harness default.

    2026-11-18 (round 77): `pick("agent")` alone ignores `roles.agent.model` — the
    exact-model pin the operator sets in `config/routing.yaml` — because `pick()`
    reads `pattern`/`fallbacks` only and returns None while the local roster is
    empty. Every other role consumer uses the same idiom (`role_model(role) or
    pick(role)`); the optimizer was the one that did not, so it fell through to
    `default_model()` and every run called the dead key (measured: HTTP 403, 95 of
    170 rows). A dedicated `optimizer` role keeps the proposer's model and cost out
    of the user-facing chat/agent routes.
    """
    try:
        from longrun.model import routing as _routing
        m = (_routing.role_model("optimizer") or _routing.role_model("agent")
             or _routing.pick("agent"))
        if m:
            return m
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.model.rllm import default_model
        return default_model()
    except Exception:  # noqa: BLE001
        return None


# The last `_call_model` failure, as a sanitized one-liner ("" = the last call did
# not fail). 2026-11-18 (round 76): `run()` reported "unparseable model reply" for
# EVERY provider failure, so 95 of 170 logged runs blamed the model's formatting
# for an infrastructure answer. Measured on the live key: HTTP 403, "Key limit
# exceeded (total limit) … $133.06 of $133.00 used; does not reset". The slot is
# transient — `run()` clears it before the call and reads it right after.
_LAST_CALL_ERROR = ""

_URL_RE = re.compile(r"https?://\S+")


def _error_line(exc=None, payload=None):
    """One sanitized line for a failed provider call: no URL, no token, ≤240 chars.

    A provider error body is written by a third party and can carry a key
    identifier in a link (the live 403 did), so URLs are stripped and the text is
    whitespace-collapsed before it reaches a log row.
    """
    msg, code = "", None
    if payload is not None:
        if isinstance(payload, dict):
            code = payload.get("code")
            msg = str(payload.get("message") or "")
        else:
            msg = str(payload)
    if exc is not None:
        code = getattr(exc, "code", None) or code
        if not msg:
            try:
                raw = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 — an unreadable body is just no body
                raw = ""
            if raw:
                try:
                    err = json.loads(raw).get("error")
                    msg = (err.get("message") if isinstance(err, dict) else err) or raw
                except Exception:  # noqa: BLE001
                    msg = raw
        if not msg:
            msg = str(exc)
    msg = _URL_RE.sub("<url>", " ".join(str(msg).split()))[:240]
    head = ("HTTP %s" % code) if code else "call failed"
    return head + ((": " + msg) if msg else "")


def _call_model(prompt, model=None):
    """One synchronous completion. Returns the raw reply text, or None on any failure.

    Resolves the endpoint through `providers.endpoint` so a cloud model carries its
    own auth header — `ROUTER_BASE` alone is not the whole address (it points at the
    local llama.cpp router, which is not where a routed `openrouter:` model lives).

    A failure sets `_LAST_CALL_ERROR` (round 76): an HTTP error, a 200 carrying an
    `error` object and a missing model are three different states, and the caller
    must be able to name the one that happened.
    """
    global _LAST_CALL_ERROR
    _LAST_CALL_ERROR = ""
    try:
        import urllib.request as _req
        from longrun.model import providers as _prov
        model = model or _optimizer_model()
        if not model:
            _LAST_CALL_ERROR = "no model configured"
            return None
        url, headers, resolved = _prov.endpoint(model)
        body = json.dumps({
            "model": resolved,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
            "temperature": 0.3,
            "stream": False,
        }).encode("utf-8")
        req = _req.Request(url, data=body, headers=headers)
        resp = _req.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode("utf-8"))
        if data.get("error"):
            _LAST_CALL_ERROR = _error_line(payload=data.get("error"))
            return None
        choices = data.get("choices") or []
        if not choices:
            return ""
        ch = choices[0] or {}
        text = ((ch.get("message") or {}).get("content")) or ""
        if not str(text).strip() and ch.get("finish_reason") == "length":
            # Measured 2026-11-18 (round 77) on a reasoning model with the REAL
            # prompt: 1024/1024 then 8192/8192 tokens spent reasoning, zero
            # content, `finish_reason=length`. "empty reply" would hide that.
            _LAST_CALL_ERROR = ("the reply was cut at the token limit "
                                "(finish_reason=length, no content)")
            return None
        return text
    except Exception as e:  # noqa: BLE001 — the model call is additive, never fails the session
        _LAST_CALL_ERROR = _error_line(exc=e)
        return None


def _extract_json(text):
    """Extract the first JSON object/array from a model reply. Returns (obj, ok)."""
    if not text:
        return None, False
    s = str(text).strip()
    if s.startswith("```"):
        s = s[3:]
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()
    try:
        return json.loads(s), True
    except ValueError:
        pass
    # Fall back to the outermost {...} or [...] block inside prose.
    for op, cl in (("{", "}"), ("[", "]")):
        i = s.find(op)
        j = s.rfind(cl)
        while i != -1 and j > i:
            try:
                return json.loads(s[i:j + 1]), True
            except ValueError:
                j = s.rfind(cl, 0, j)
    return None, False


_LITERAL_RE = re.compile(r"[A-Za-z0-9_./:@-]{3,}")
# Round 83: a literal written with regex escapes (`127\.0\.0\.1`, `\.env`) was cut at
# the backslash — the tokenizer saw `127`, `0`, `0`, `1` — so no candidate ever
# contained the address and the witness for that rule was never built. Measured: the
# optimizer proposed removing the `127.0.0.1` control-API guard, `_uncovered_removal`
# returned None, and the delta reached the inbox although no other live rule matches
# `curl 127.0.0.1/api/settings`. The escaped punctuation is unescaped BEFORE tokenizing.
_ESCAPED_PUNCT_RE = re.compile(r"\\([./:@_-])")


def _removal_witness(pattern, remaining):
    """A string the removed rule matches and NO remaining rule matches (None = none).

    Round 78: the proposer called `localhost` and `127.0.0.1` "duplicates" — twice,
    with the two rules' own `why` in the prompt — because resemblance is not
    coverage. This does not read the model's claim: it builds candidate inputs from
    the removed pattern's own literals (each one, the first two, all of them joined)
    and asks the COMPILED regexes. A witness proves the removal stops guarding an
    input; `None` means only that no witness was found, so the check can refute a
    removal and never approve one.
    """
    try:
        rx = re.compile(pattern)
        others = [re.compile(p) for p in remaining if p]
    except re.error:  # noqa: SIM105 — an uncompilable pattern is left to the validator
        return None
    lits = []
    for m in _LITERAL_RE.finditer(_ESCAPED_PUNCT_RE.sub(r"\1", pattern)):
        # `(?:curl|wget)` yields `:curl` — the `?:` prefix is regex syntax, not
        # part of any input (measured: the joined candidate started with `:curl`
        # and matched nothing, so a real non-duplicate found no witness).
        s = m.group(0).strip(":-")
        if len(s) >= 3 and s not in lits:
            lits.append(s)
    cands = list(lits)
    if len(lits) > 1:
        # A readable join first: a space between words, but none where the pattern
        # itself has no gap (`localhost` then `/api/jobs`), so the witness reads
        # like a command instead of a concatenation.
        smart = lits[0]
        for part in lits[1:]:
            smart += part if (part.startswith("/") or smart.endswith("/")) \
                else (" " + part)
        cands.append(smart)
        # Then the mechanical joins: `localhost` and `/api/` must be ADJACENT for
        # the measured rule, so the no-separator form is tried as well.
        cands.append("".join(lits))
        cands.append("".join(lits[:2]))
        cands.append(" ".join(lits[:2]))
        cands.append(" ".join(lits))
    for cand in cands:
        try:
            if not rx.search(cand):
                continue
            if not any(o.search(cand) for o in others):
                return cand
        except re.error:  # noqa: SIM105 — a candidate that cannot be tested is skipped
            continue
    return None


def _uncovered_removal(delta):
    """The first `deny` rule the delta removes with an unguarded input (None = ok).

    The remaining list is computed exactly as `apply_delta` would (`live - remove +
    add`), so a delta that replaces a rule with a broader one is allowed: only a
    removal that leaves an input to no rule is refused.
    """
    if str((delta or {}).get("field") or "") != "deny":
        return None
    removed = [str(x) for x in ((delta or {}).get("remove") or []) if str(x).strip()]
    if not removed:
        return None
    target = str((delta or {}).get("target") or "")
    try:
        from longrun.tools import registry as _reg
        spec = _reg.tool_spec(target) or {}
    except Exception:  # noqa: BLE001 — no live list is no check, never a refusal
        return None
    if not spec:
        # An unknown row is the VALIDATOR's refusal (`target is not a known tool
        # row`), not this check's: an empty list here would invent a witness.
        return None
    live = [str(x) for x in (spec.get("deny") or [])]
    add = [str(x) for x in ((delta or {}).get("add") or []) if str(x).strip()]
    remaining = [p for p in live if p not in removed] + add
    for pat in removed:
        witness = _removal_witness(pat, remaining)
        if witness:
            return {"pattern": pat, "witness": witness}
    return None


def _redundant_add(delta):
    """An `add` that writes nothing (None = the add changes something).

    Round 85: `_uncovered_removal` proves a LOSS and `_unchanged_friction` proves a
    friction that survives — both about `remove`. Nothing measured the other
    direction: an `add` whose entry is ALREADY in the live list. `apply_delta`
    computes `live - remove + add` and skips an entry already present
    (`registry.py`: `if x not in new`), so approving such a delta writes no new
    guard while the inbox claims one. Three provable no-ops, all inside the delta:
    a pattern copied from the live list, the same pattern listed twice, and a
    pattern both removed and re-added. Exact strings only — the applier compares
    exact strings, and a broader or narrower rule is a real change.
    """
    if not isinstance(delta, dict):
        return None
    target = str(delta.get("target") or "")
    field = str(delta.get("field") or "")
    added = [str(x) for x in (delta.get("add") or []) if str(x).strip()]
    if not target or not added:
        return None
    try:
        from longrun.tools import registry as _reg
        if field not in _reg.REGISTRY_LIST_FIELDS:
            return None
        spec = _reg.tool_spec(target) or {}
        live = _reg._effective_list(target, field)
    except Exception:  # noqa: BLE001 — no live list is no check, never a refusal
        return None
    if not spec:
        # An unknown row is the VALIDATOR's refusal, not this check's.
        return None
    removed = [str(x) for x in (delta.get("remove") or []) if str(x).strip()]
    remaining = [p for p in live if p not in removed]
    seen = []
    for pat in added:
        if pat in removed:
            return {"pattern": pat, "why": "is removed and re-added by the same delta"}
        if pat in remaining:
            return {"pattern": pat, "why": "is already live on %s.%s" % (target, field)}
        if pat in seen:
            return {"pattern": pat, "why": "is listed twice in this delta"}
        seen.append(pat)
    return None


def _safe_search(pattern, text):
    try:
        return re.search(pattern, text) is not None
    except re.error:
        return False


def _unchanged_friction(delta, policy_hits):
    """A removal that leaves every recorded blocked input blocked is not a fix.

    Round 79 (2026-11-18): the loop could refute a removal by building a witness
    from the rule's own regex; it could not touch the model's other premise — "this
    guard blocked a legitimate call 35 times". The ledger now keeps the refused
    inputs (redacted), so when EVERY one of them still matches another live deny
    rule, deleting this rule changes nothing for the calls it actually blocked: the
    stated friction survives the removal. Returns the refuting record, or None when
    the removal does unblock something (or there is no recorded input to judge).
    """
    if str((delta or {}).get("field") or "") != "deny":
        return None
    removed = [str(x) for x in ((delta or {}).get("remove") or []) if str(x).strip()]
    if not removed:
        return None
    target = str((delta or {}).get("target") or "")
    try:
        from longrun.tools import registry as _reg
        spec = _reg.tool_spec(target) or {}
    except Exception:  # noqa: BLE001
        return None
    if not spec:
        return None
    live = [str(x) for x in (spec.get("deny") or [])]
    add = [str(x) for x in ((delta or {}).get("add") or []) if str(x).strip()]
    remaining = [p for p in live if p not in removed] + add
    firings = (policy_hits or {}).get("firings") or {}
    for pat in removed:
        rec = firings.get("%s:deny:%s" % (target, pat)) or {}
        samples = [str(s) for s in (rec.get("samples") or []) if str(s).strip()]
        if not samples:
            continue
        judged, last_still = 0, []
        for s in samples:
            if not _safe_search(pat, s):
                continue
            judged += 1
            last_still = [p for p in remaining if p and _safe_search(p, s)]
            if not last_still:
                return None        # the recorded call would become allowed: a real change
        if judged:
            return {"pattern": pat, "sample": samples[-1], "also": last_still}
    return None


def _policy_snapshot(policy_hits):
    """The LIVE values of the rows the evidence names, for the model to copy.

    2026-11-17: the prompt used to describe the delta shape without showing a
    single current value, so the model rewrote `shell.exec.deny` from memory and
    proposed a one-entry list — a click away from deleting seven hard-deny rules.
    A model may only `add`/`remove` entries it was shown (the validator refuses
    a `remove` that is not in the live list, and refuses a whole-list `value`).

    2026-11-18 (round 75): the fix above passed `firings` KEYS (`shell.exec:deny:
    …`) to `tool_spec`, which knows no such tool, so on real data the section read
    "(not available)" — measured on the live ledger. The tool name is the first
    segment of the key.

    2026-11-18 (round 78): the list showed each rule's regex and nothing about what
    it protects, so the proposer called two different guards "duplicates" and moved
    to delete the `localhost` one — which the config explains in a `why` it never
    saw. The registry already carries `deny_why` and `deny_proof` beside the
    pattern; they are printed here, one line each, after the exact list.
    """
    live, _gone = _hit_rows(policy_hits)
    names = []
    for row in live:
        if row["tool"] not in names:
            names.append(row["tool"])
    for key in (policy_hits or {}).get("never_fired") or []:
        tool = str(key).split(":", 1)[0]
        if tool and tool not in names:
            names.append(tool)
    if not names:
        names = ["shell.exec"]
    try:
        from longrun.tools import registry as _reg
    except Exception:  # noqa: BLE001 — no snapshot is better than no prompt
        return ""
    rows = []
    for name in names[:4]:
        try:
            spec = _reg.tool_spec(name) or {}
        except Exception:  # noqa: BLE001
            continue
        if not spec:
            continue
        rows.append("%s: approval=%s deny=%s always_ask=%s auto_approve=%s" % (
            name, spec.get("approval"),
            json.dumps(spec.get("deny") or []),
            json.dumps(spec.get("always_ask") or []),
            json.dumps(spec.get("auto_approve") or [])))
        why = spec.get("deny_why") or {}
        proof = spec.get("deny_proof") or {}
        for r in live:
            if r["tool"] != name or not r.get("sample"):
                continue
            rows.append("  fired %s x%d — blocked: %s" % (r["kind"], r["n"], r["sample"]))
        for pat in (spec.get("deny") or []):
            if pat in why:
                rows.append("  deny why: %s — %s" % (pat, str(why[pat])[:200]))
            if pat in proof:
                rows.append("  deny proof: %s — %s" % (pat, proof[pat]))
    return "\n".join(rows)[:9000]


def _read_recent_traces(limit=6):
    """The most recent run records, newest first — CROSS-SESSION evidence (I-3).

    `run(sid)` reads ONE session, so a friction that only shows across many
    sessions is invisible. This reads the runmetrics store (`RUNS_DIR`, the same
    records `_read_trace` uses) and is fail-open: no store -> no context.
    Read-only.
    """
    try:
        from longrun.model import runmetrics as _rm
        d = _rm.RUNS_DIR
        names = [n for n in os.listdir(d) if n.endswith(".json")]
        names.sort(key=lambda n: os.path.getmtime(os.path.join(d, n)), reverse=True)
    except Exception:  # noqa: BLE001 — the context must never break a run
        return []
    out = []
    for n in names[:max(1, int(limit or 6))]:
        try:
            with open(os.path.join(d, n), encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _cross_summary(rows):
    """Outcome and exit-code counts across the recent runs (I-3). Bounded."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if not rows:
        return {}
    outcomes, code = {}, {}
    for r in rows:
        oc = str(r.get("outcome") or "unknown")
        outcomes[oc] = outcomes.get(oc, 0) + 1
        c = r.get("code")
        if c not in (None, 0):
            code[str(c)] = code.get(str(c), 0) + 1
    return {"sessions": len(rows), "outcomes": outcomes, "exit_codes": code}


def _build_analysis_prompt(trace, policy_hits, job_cost, feedback, history=None,
                           refusals=None, cross=None):
    """Build the optimizer's analysis prompt from session evidence.

    The prompt asks for ONE JSON object: either {"skip": true, ...} or a registry-row
    delta the existing approval pipeline can apply. It never asks for a code change.

    `cross` (I-3, 2026-11-23) is the cross-session summary from `_cross_summary`:
    a friction seen in ONE session is weaker evidence than the same friction seen
    across the last N runs. Absent -> the prompt is byte-identical to before.
    """
    parts = []

    tokens = trace.get("tokens", 0)
    steps = trace.get("steps", 0)
    outcome = trace.get("outcome", "unknown")
    model = trace.get("model", "unknown")
    parts.append(f"Session: {tokens} tokens, {steps} steps, outcome={outcome}, model={model}")

    code = trace.get("code")
    if code and code != 0:
        code_map = {1: "semantic error", 64: "usage error", 124: "timeout",
                    125: "sandbox", 126: "blocked", 127: "unknown tool", 130: "cancelled"}
        parts.append(f"Exit code: {code} ({code_map.get(code, 'unknown')})")

    if cross and cross.get("sessions"):
        _oc = ", ".join("%s=%d" % (k, v)
                        for k, v in sorted((cross.get("outcomes") or {}).items()))
        _ec = ", ".join("exit %s x%d" % (k, v)
                        for k, v in sorted((cross.get("exit_codes") or {}).items()))
        parts.append(
            "Across the last %d run record(s) (cross-session context — a friction "
            "seen here only ONE time is weaker evidence than the same one "
            "recurring): outcomes %s%s."
            % (cross["sessions"], _oc, ("; " + _ec) if _ec else ""))

    if policy_hits:
        live, gone = _hit_rows(policy_hits)
        never = [str(k) for k in ((policy_hits or {}).get("never_fired") or [])]
        unknown = policy_hits.get("unknown_args", {})
        if live:
            _lines = []
            for r in live[:12]:
                _ln = "  %s %s x%d: %s" % (r["tool"], r["kind"], r["n"], r["pattern"])
                if r.get("sample"):
                    _ln += "\n      blocked: " + r["sample"]
                # Round 86: the count says the rule fired; the transcript says what
                # the agent did next. A rule whose refusals were all followed by
                # another call did not stop the work.
                _ref = (refusals or {}).get(
                    "%s:%s:%s" % (r["tool"], r["kind"], r["pattern"])) or {}
                if _ref.get("n"):
                    _ln += ("\n      after %d refusal(s): %d continued with another "
                            "call, %d repeated the same call, %d gave up"
                            % (_ref["n"], _ref.get("continued", 0),
                               _ref.get("repeated", 0), _ref.get("gave_up", 0)))
                _lines.append(_ln)
            parts.append(
                "Rules that FIRED and are STILL in the live policy (load-bearing — each "
                "one blocked a real call, so removing one needs evidence from the "
                "trace):\n" + "\n".join(_lines))
        if gone:
            parts.append(
                "Ledger history of rules the live policy NO LONGER has (they are absent "
                "from the live list below, so they cannot be removed — never propose "
                "one of these in `remove`):\n" + "\n".join(
                    "  %s %s x%d: %s" % (r["tool"], r["kind"], r["n"], r["pattern"])
                    for r in gone[:6]))
        if never:
            _proof = (policy_hits or {}).get("never_fired_proof") or {}
            parts.append(
                "Configured rules that NEVER fired (context only — a guard that never "
                "fired may be doing its job; do not propose removing one without "
                "friction evidence):\n" + "\n".join(
                    "  " + k + ((" — proved by " + _proof[k]) if k in _proof else "")
                    for k in never[:8]))
        if unknown:
            # Round 81: this line dumped `first_ts`/`last_ts` — timestamps the model
            # cannot use — and never the call. The record now keeps the call, so the
            # line names it; an entry without one (recorded before the field existed)
            # prints exactly as before.
            _rows = []
            for _k, _rec in list(unknown.items())[:5]:
                _at = str(_k).split(":", 2)
                _s = [x for x in ((_rec or {}).get("samples") or []) if str(x).strip()]
                _rows.append("%s %r x%d%s" % (
                    _at[0], _at[2] if len(_at) > 2 else _k,
                    int((_rec or {}).get("n") or 0),
                    (" — e.g. call: " + str(_s[-1])) if _s else ""))
            parts.append("Unknown args (the call RAN; the argument was dropped):\n"
                         + "\n".join("  " + r for r in _rows))

    if job_cost:
        parts.append(f"Job cost: {job_cost.get('tokens', 0)} tokens, "
                     f"${job_cost.get('usd', 'unpriced')}, "
                     f"{job_cost.get('turns', 0)} turns")

    if feedback:
        fb_summary = feedback.get("summary", "")
        if fb_summary:
            parts.append(f"Downstream feedback: {fb_summary}")
        failed_agent = (feedback.get("details") or {}).get("failed_agent")
        if failed_agent:
            parts.append(f"A downstream agent that consumed this output failed: {failed_agent}")

    snap = _policy_snapshot(policy_hits)
    _hist = _history_block(history)
    prompt = (
        "You are a harness optimizer. Analyze this session trace and identify ONE "
        "concrete deficiency in the TOOL REGISTRY — a tool that failed, a gate that "
        "blocked a legitimate call, or a policy that created friction.\n\n"
        "Evidence:\n" + "\n".join(f"- {p}" for p in parts) + "\n\n"
        "Current live policy of the row(s) the evidence names (the exact values; a "
        "list is changed ONLY through add/remove, never rewritten from memory). Each "
        "`deny why` line says what that rule protects: a rule is NOT redundant "
        "because its text resembles another rule — two patterns on different "
        "literals cover different calls — so a `remove` of a rule that carries a "
        "`why` must say what still protects that case. A `fired … — blocked:` line "
        "is the call that rule actually refused: to claim friction, quote that input "
        "and say why it was legitimate; a count is not evidence, and a removal that "
        "leaves the recorded input blocked by another live rule does not fix it. An "
        "`after N refusal(s)` line is what the agent did next: `gave up` is friction, "
        "`continued with another call` means the guard did not stop the work:\n"
        + (snap or "(not available)") + "\n\n"
        + ((_hist + "\n\n") if _hist else "")
        + "Reply with ONE JSON object and NOTHING else. Either:\n"
        '  {"skip": true, "reason": "..."}   — when no registry deficiency is evident\n'
        "or a delta naming one editable registry field:\n"
        '  {"target": "<tool row, e.g. shell.exec or the namespace shell>",\n'
        '   "field": "<one of: enabled, approval, auto_approve, roots, deny, '
        'allow_hosts, always_ask>",\n'
        '   "value": <bool for enabled; "auto"|"required"|"denied" for approval>,\n'
        '   "add": ["<exact NEW list entries>"],\n'
        '   "remove": ["<exact EXISTING entries to delete, copied verbatim>"],\n'
        '   "reason": "...", "confidence": "low"|"medium"|"high"}\n'
        "For a list field use add/remove only; an entry you do not copy into `add` "
        "is kept, so adding a rule can never delete another one. An `add` whose "
        "entry is already in the live list writes nothing — the applier drops it — "
        "so it cannot fix the deficiency you describe.\n\n"
        "Only propose changes to the tool registry. Never propose changes to the "
        "agent loop, session management, or job dispatch."
    )
    return prompt


def _log_run(sid, proposal):
    """Append one optimizer run to the log. Never fails."""
    try:
        os.makedirs(os.path.dirname(OPTIMIZER_LOG), exist_ok=True)
        row = {"ts": round(time.time(), 3), "session": str(sid or ""),
               "proposal": proposal}
        with open(OPTIMIZER_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        pass


def _submit(delta, evidence, sid):
    """Register the delta as a `registry` proposal. Returns the proposal id or None.

    The proposal goes through the EXISTING approvals pipeline — no new gate: it
    appears in the operator's inbox and ledger, and `improve.decide(approve)`
    applies the delta via `registry.apply_delta` (overlay-only).
    """
    try:
        from longrun.util import improve as _improve
        # Round 77: a completing model (deepseek-chat) returned a valid delta with
        # NO `reason` key, which would have shown the operator a dangling "— " in
        # the inbox. The fallback says what is true instead of leaving a blank.
        why = str(delta.get("reason") or "").strip() or "the optimizer gave no reason"
        content = "%s.%s = %s — %s" % (
            delta.get("target"), delta.get("field"),
            json.dumps(delta.get("value")), why)
        # ITER-01 / R162: carry the failure mode and the reproduction verdict when
        # the evidence has them, so `improve.decide` can apply the reproduce-or-revert
        # rule (arXiv:2610.02616 §2.2). Absent keys change nothing.
        exp = {"session": sid, "evidence": evidence}
        ev = evidence if isinstance(evidence, dict) else {}
        for key in ("failure_mode", "outcome_change", "reproduces"):
            if ev.get(key) is not None:
                exp[key] = ev[key]
        rec = _improve.propose(
            "registry", content, reason=why[:500],
            origin="optimizer", delta=delta, experiment=exp)
        # I-4 (2026-11-23): stamp the delta IDENTITY on the durable ledger so the
        # pruner's memory survives `clear_decided` (which deletes the proposal
        # JSON). Without it a denied/reverted delta could be re-proposed after a
        # "clear decided" — the exact oscillation the pruner exists to stop.
        try:
            _improve.ledger_add("optimizer.delta", origin="optimizer",
                                proposal=rec.get("id"), delta_key=_delta_key(delta))
        except Exception:  # noqa: BLE001 — the durable stamp must not fail a submit
            pass
        return rec.get("id")
    except Exception:  # noqa: BLE001 — submitting is additive, never fails the session
        return None


def run(sid, jid=None):
    """Run the local optimizer on a session trace.

    Reads existing ledgers, asks the model (the `agent` role) for ONE registry delta,
    and submits it through the existing approvals pipeline. The delta is NOT applied
    here — a human approves it. Returns the proposal dict, or {"skip": True, ...}.
    """
    sid = str(sid or "").strip()
    if not sid:
        return {"skip": True, "reason": "no session id"}

    trace = _read_trace(sid)
    if not trace:
        return {"skip": True, "reason": "no trace"}

    steps = trace.get("steps", 0)
    if steps < MIN_TOOL_CALLS:
        return {"skip": True, "reason": "below minimum tool calls (%s < %s)" % (steps, MIN_TOOL_CALLS)}

    policy_hits = _read_policy_hits()
    job_cost = _read_job_cost(jid) if jid else {}
    feedback = _read_feedback(sid)
    refusal_rows = _read_refusals(sid)
    history = _evolution_history()
    # I-3: the ONE-session trace is joined by the cross-session context, so the
    # model can weigh a friction that recurs over the last N runs.
    cross = _cross_summary(_read_recent_traces())
    prompt = _build_analysis_prompt(trace, policy_hits, job_cost, feedback,
                                    history=history, refusals=refusal_rows,
                                    cross=cross)

    _live, _gone = _hit_rows(policy_hits)
    evidence = {
        "tokens": trace.get("tokens", 0),
        "steps": steps,
        "outcome": trace.get("outcome", "unknown"),
        "exit_code": trace.get("code"),
        "live_firings": len(_live),
        "retired_firings": len(_gone),
        "never_fired": len(policy_hits.get("never_fired") or []),
        "unknown_args": len(policy_hits.get("unknown_args", {})),
        "job_tokens": job_cost.get("tokens", 0),
        "has_feedback": bool(feedback),
        "cross_sessions": int(cross.get("sessions") or 0),
        "refusals": sum(int(r.get("n") or 0) for r in refusal_rows.values()),
        "refusals_gave_up": sum(int(r.get("gave_up") or 0)
                                for r in refusal_rows.values()),
    }

    global _LAST_CALL_ERROR
    _LAST_CALL_ERROR = ""
    reply = _call_model(prompt)
    call_error = _LAST_CALL_ERROR
    if reply is None:
        # 2026-11-18 (round 76): every provider failure used to be logged as
        # "unparseable model reply" — the model was blamed for an infrastructure
        # answer. The measured live case: HTTP 403, the key at its limit.
        result = {"skip": True, "session": sid, "prompt": prompt,
                  "evidence": evidence, "reply": "",
                  "reason": ("model call failed: " + call_error) if call_error
                            else "no reply from the model"}
        _log_run(sid, result)
        return result
    delta, parsed = _extract_json(reply)
    if not parsed:
        # 2026-11-18 (round 75): 95 of 170 logged runs ended here and the log kept
        # no reply, so a dead model (no endpoint) and a malformed reply were the
        # same row — undiagnosable. The reply is kept; an empty one is its own case.
        result = {"skip": True, "session": sid, "prompt": prompt,
                  "evidence": evidence, "reply": str(reply)[:1500],
                  "reason": "unparseable model reply" if str(reply).strip()
                            else "empty reply from the model"}
        _log_run(sid, result)
        return result

    # The registry owner is the ONE validator: a delta it would refuse is not a
    # proposal — the optimizer skips instead of writing an unusable entry.
    try:
        from longrun.tools import registry as _reg
        err = _reg.delta_error(delta)
    except Exception:  # noqa: BLE001
        err = "registry validator unavailable"
    if err:
        # Round 77: a model-reported skip is the model's own reasoning ("the fired
        # rules are load-bearing…"), and the operator's only chance to read it.
        # This branch used to drop the reply — the one skip whose text matters.
        result = {"skip": True, "reason": err, "session": sid,
                  "delta": delta, "prompt": prompt, "evidence": evidence,
                  "reply": str(reply)[:1500]}
        _log_run(sid, result)
        return result
    # Round 79: a removal offered as a friction fix that leaves every recorded
    # blocked input still blocked changes nothing the operator can feel.
    _fric = _unchanged_friction(delta, policy_hits)
    if _fric:
        result = {"skip": True, "session": sid, "delta": delta, "prompt": prompt,
                  "evidence": evidence, "reply": str(reply)[:1500],
                  "reason": "the removal does not unblock the recorded call: %r still "
                            "matches %r" % (_fric["sample"], _fric["also"][0])}
        _log_run(sid, result)
        return result
    # Round 78: a removal the harness can REFUTE is not a proposal. The model twice
    # called `localhost` and `127.0.0.1` duplicates; a witness string guards that
    # input with the removed rule and no remaining one. This gate runs before the
    # pruner: the defect is in the delta, not in its history.
    _unc = _uncovered_removal(delta)
    if _unc:
        result = {"skip": True, "session": sid, "delta": delta, "prompt": prompt,
                  "evidence": evidence, "reply": str(reply)[:1500],
                  "reason": "the removal is not covered: %r matches the removed rule "
                            "and NO other live deny rule" % _unc["witness"]}
        _log_run(sid, result)
        return result
    # Round 85: the other direction of round 78's witness — an `add` that is already
    # live is dropped by `apply_delta`, so approving it writes no new guard.
    _dup = _redundant_add(delta)
    if _dup:
        result = {"skip": True, "session": sid, "delta": delta, "prompt": prompt,
                  "evidence": evidence, "reply": str(reply)[:1500],
                  "reason": "the add writes nothing: %r %s" % (_dup["pattern"], _dup["why"])}
        _log_run(sid, result)
        return result
    # RRSI pruner ("no longer useful"): the same delta already decided or still
    # waiting adds a duplicate to the inbox and no information to the operator.
    _key = _delta_key(delta)
    _seen = None
    if _key:
        for h in history:
            if h.get("key") == _key:          # durable row (I-4)
                _seen = h
                break
            _d0 = h.get("delta")
            if isinstance(_d0, dict) and _d0 and _delta_key(_d0) == _key:
                _seen = h
                break
    if _seen:
        result = {"skip": True, "session": sid, "delta": delta,
                  "reason": "already proposed (%s): %s" % (
                      _seen["status"], _seen["reason"] or "no reason"),
                  "proposal_id": _seen.get("id"), "prompt": prompt,
                  "evidence": evidence}
        _log_run(sid, result)
        return result

    proposal_id = _submit(delta, evidence, sid)
    proposal = {"session": sid, "job": jid, "delta": delta,
                "proposal_id": proposal_id, "prompt": prompt, "evidence": evidence}
    _log_run(sid, proposal)
    return proposal
