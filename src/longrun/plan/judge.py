"""One INDEPENDENT model call that must return a JSON verdict.

The pattern behind TWO judges in this codebase — the L3 goal judge
(`plan/goal.py::_check_judge`) and the per-turn completeness verifier
(`plan/turn_verify.py`) — is the same: a SECOND model, never the one that did the
work, reads a bounded prompt and answers strict JSON. Keeping the call here means
both judges share ONE mechanism (resolve the model, one `_router_stream`, a
tolerant JSON parse) and can never drift apart.

Offline-safe: no model reachable → `None`, which both callers read as "no verdict"
— a judge that cannot answer is silent, never a RED finding.
"""
import json as _json


def ask_json(prompt, model=None, timeout=None):
    """Ask `model` to answer `prompt` with a JSON object; return the parsed dict.

    Returns `None` when the model call fails (no model / transport error), and a
    dict otherwise: the parsed object, or `{"_raw": <text>}` when the reply holds
    no JSON object. The caller decides what a missing verdict means.
    """
    try:
        from longrun.core import server as srv
    except Exception:  # noqa: BLE001
        return None
    ref = (str(model).strip() or None) if model else None
    try:
        kwargs = {"timeout": timeout} if timeout else {}
        text, _think = srv._router_stream([{"role": "user", "content": prompt}],
                                          ref, lambda *a: None, **kwargs)
    except Exception:  # noqa: BLE001 — no model → no verdict
        return None
    text = text or ""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {"_raw": text[:400]}
    try:
        got = _json.loads(text[start:end + 1])
    except Exception:  # noqa: BLE001
        return {"_raw": text[:400]}
    return got if isinstance(got, dict) else {"_raw": text[:400]}
