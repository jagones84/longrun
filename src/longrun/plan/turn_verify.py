"""Post-turn completeness verifier — the operator's "generic verifier".

Operator, 2026-11-20: *"non doveva esserci dopo ogni fine messaggio (che non
prosegue naturalmente con continuing involvement) una LLM call in versione
verificatore che il suo stesso ultimo messaggio non abbia lasciato lavoro
incompiuto? … non basterebbe vedere todo aperti perché potrebbe non esserci."*

After a turn that DID work and closes WITHOUT an explicit `finish`, an
INDEPENDENT model reads ONLY the operator's request, the agent's own final
message and the still-open plan steps — never the tool transcript, so the cost is
bounded and the judgement is not the worker marking its own homework. It returns
`{"complete": bool, "missing": [...]}`; on `complete=false` the harness gives the
agent at most `max_rounds` more round(s) to finish (no infinite loop).

This is a SEPARATE model call from the cheap SAME-model closure check
(`agent._closure_check_prompt`), which stays. It reuses the shared judge call
(`plan.judge.ask_json`) that the L3 goal judge also uses, so there is ONE
mechanism. Config: `turn_verify` in `config/tools.yaml` (Settings-editable).
"""

from longrun.plan import judge

TURN_VERIFY_DEFAULTS = {
    "enabled": True,
    "model": "openrouter:z-ai/glm-5.3-flash",
    "max_rounds": 2,
}


def config():
    """Effective `turn_verify` config (YAML section over the defaults)."""
    try:
        from longrun.tools.registry import section_config
        return section_config("turn_verify", dict(TURN_VERIFY_DEFAULTS))
    except Exception:  # noqa: BLE001 — a config hiccup must not break a turn
        return dict(TURN_VERIFY_DEFAULTS)


def _prompt(request_text, last_message, open_steps, gaps):
    return (
        "You are an INDEPENDENT verifier of ONE finished agent turn. You did NOT do "
        "the work and you see ONLY what follows — not the tool logs, not the agent's "
        "reasoning.\n\n"
        "THE USER'S REQUEST (the goal of the turn):\n%s\n\n"
        "THE AGENT'S FINAL MESSAGE (its own claim of what it did):\n%s\n\n"
        "PLAN STEPS STILL OPEN when it closed (verify it completed EVERY step it "
        "created; 'done' must be real, not a promise):\n%s\n\n"
        "MECHANICAL GAPS THE HARNESS ALREADY FOUND:\n%s\n\n"
        "Return STRICT JSON only: {\"complete\": true|false, \"missing\": [\"...\"]}. "
        "`complete` is true ONLY if the request is satisfied AND no step of the "
        "agent's own list was left unfinished (an open step that is not declared "
        "superseded is unfinished). Otherwise list, concretely, what is still "
        "missing. Be strict: a promise (\"I will…\") is NOT a completion, and a "
        "claim with no evidence in the message is not a completion — answer false "
        "and name what is missing."
        % (str(request_text or "")[:6000],
           str(last_message or "")[:4000],
           "\n".join("- %s" % s for s in (open_steps or []))[:2000] or "(none)",
           "\n".join(gaps or [])[:2000] or "(none)")
    )


def verify_turn(request_text, last_message, open_steps=None, gaps=None, cfg=None):
    """`{"ok": bool, "missing": [...]}`, or None when the verifier cannot answer.

    None means "no verdict" (disabled, no model, malformed reply) — the caller
    must then close on the model's own word, exactly as before.
    """
    cfg = cfg or config()
    if not cfg.get("enabled", True):
        return None
    model = str(cfg.get("model") or "").strip() or None
    got = judge.ask_json(_prompt(request_text, last_message, open_steps, gaps), model)
    if got is None or "_raw" in got:
        return None
    return {"ok": bool(got.get("complete")), "missing": got.get("missing") or []}
