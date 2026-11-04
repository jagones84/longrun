"""Session scan — propose (never enable) automations from the operator's own work.

E-5 (2026-11-04). Nothing in the harness read the operator's own sessions to find
repeated work: `selfevolve` mines sequences of tool NAMES (`selfevolve.py:22-29`),
which says which tools were called and never WHAT keeps being asked for, so every
routine had to be invented by hand.

This is a PROPOSAL generator, not an actuator. Every candidate is created as a
routine with `enabled=False`, so the worst outcome of a bad suggestion is one row
the operator deletes. Nothing here ever enables a routine, and a duplicate of an
existing goal is never created twice.
"""
import json

from longrun.orchestrate import routines
from longrun.util import improve

# Bounds: the prompt is a sample, not the archive. 40 sessions x 3 operator
# messages x 160 chars keeps one scan in the same token class as a single turn.
SESSION_MAX = 40
MSG_PER_SESSION = 3
MSG_CHARS = 160
CANDIDATES_MAX = 2
GOAL_CHARS = 600
HARNESS_MARK = "[harness]"

SCAN_SYSTEM = (
    "You are the automation scout of an agent harness. You read a sample of the "
    "operator's own past requests and propose the SMALLEST number of recurring, "
    "boring, repetitive workflows that could run UNATTENDED on a schedule. "
    "Rules: propose at most %d; each must be something that is BORING and "
    "repeatable (a check, a sweep, a report, a tidy-up) — never a decision that "
    "needs taste, never a one-off; the goal is an instruction an agent can run "
    "alone, in English, at most 400 characters; cadence in seconds and at least "
    "%d. Prefer skipping over inventing. Answer with JSON ONLY: "
    '{"candidates":[{"goal":"...","every_seconds":86400,"why":"..."}]}'
    % (CANDIDATES_MAX, routines.MIN_EVERY)
)


def _operator_lines(sessions, limit=SESSION_MAX):
    """Up to `limit` samples of what the OPERATOR asked, as flat lines.

    Only a real human request counts: an `internal` message (persisted agentic
    history) and a `[harness] ` injection are the harness talking to itself.
    """
    out = []
    for sess in (sessions or [])[:limit]:
        msgs = [m for m in ((sess or {}).get("messages") or [])
                if isinstance(m, dict)]
        picked = []
        for m in msgs:
            if m.get("role") != "user" or m.get("internal"):
                continue
            text = " ".join(str(m.get("content") or "").split())
            if len(text) < 20 or text.startswith(HARNESS_MARK):
                continue
            picked.append(text[:MSG_CHARS])
        if picked:
            out.append((str((sess or {}).get("title") or "untitled")[:60],
                        picked[:MSG_PER_SESSION]))
    return out


def _prompt(lines):
    body = []
    for title, picked in lines:
        body.append("- session %r:" % title)
        body.extend("    * " + t for t in picked)
    return [{"role": "system", "content": SCAN_SYSTEM},
            {"role": "user", "content": "Operator requests:\n" + "\n".join(body)}]


def _candidates(answer):
    """Parse the model's JSON into candidate dicts. Never raises."""
    text = str(answer or "")
    data = None
    try:
        data = json.loads(text)
    except ValueError:
        from longrun.util import textkit
        for obj in textkit._iter_json_objects(text):
            if isinstance(obj, dict) and "candidates" in obj:
                data = obj
                break
            if isinstance(obj, list):
                data = {"candidates": obj}
                break
    if isinstance(data, dict):
        data = data.get("candidates")
    if not isinstance(data, list):
        return []
    return [c for c in data if isinstance(c, dict)]


def _clamp_every(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 0
    return max(routines.MIN_EVERY, n)


def scan_sessions(sessions=None, model=None, call=None, agent=None, limit=SESSION_MAX):
    """Read recent sessions and PROPOSE up to `CANDIDATES_MAX` disabled routines.

    Args:
        sessions: session dicts (default: the newest from the live store).
        model: model alias for the scout (default: the `subagent` role).
        call: injected model call `(messages) -> str` (tests; no model spent).
        agent: agent id that would own the proposed routines (default: the first
            designated agent).
        limit: how many sessions to sample.
    Returns:
        {"ok", "scanned", "sessions", "candidates", "created", "skipped", "reason"?}
    """
    from longrun.memory import stores
    out = {"ok": True, "scanned": 0, "sessions": 0, "candidates": [], "created": [],
           "skipped": []}
    if sessions is None:
        try:
            rows = stores.list_sessions()
            sessions = []
            for row in rows[:limit]:
                got = stores.load_session(str((row or {}).get("id") or ""))
                if got:
                    sessions.append(got)
        except Exception as e:  # noqa: BLE001 — a scan must not break the caller
            out.update({"ok": False, "reason": "sessions unreadable: %s" % e})
            return out
    out["scanned"] = len(sessions or [])
    lines = _operator_lines(sessions, limit)
    out["sessions"] = len(lines)
    if not lines:
        out["reason"] = "no operator messages to learn from"
        return out
    if call is None:
        def call(messages):
            answer, _used = improve.single_shot(messages, model=model,
                                                role="subagent", max_tokens=700)
            return answer
    try:
        answer = call(_prompt(lines))
        raw = _candidates(answer)
    except Exception as e:  # noqa: BLE001 — a bad answer is not a crash
        out.update({"ok": False, "reason": "scout failed: %s" % e})
        return out
    if not raw:
        # Keep the evidence: "the model declined" and "the parser broke" look
        # identical from the outside, and only one of them is worth a fix.
        out["reason"] = "the scout proposed nothing"
        out["answer_preview"] = str(answer or "")[:400]
        return out

    owner = str(agent or "").strip()
    try:
        from longrun.agent import agents as agents_mod
    except Exception:  # noqa: BLE001 — a missing roster must not break a scan
        agents_mod = None
    if not owner and agents_mod is not None:
        try:
            rows = agents_mod.REGISTRY.list().get("agents") or []
            owner = str((rows[0] or {}).get("id") or "") if rows else ""
        except Exception:  # noqa: BLE001
            owner = ""
    if not owner:
        out.update({"ok": False, "reason": "no agent to own a routine"})
        return out
    if agents_mod is not None:
        try:
            if agents_mod.REGISTRY.resolve(owner) is None:
                # Say it now: two failed creates would look like two bad ideas.
                out.update({"ok": False, "reason": "unknown agent: %s" % owner})
                return out
        except Exception:  # noqa: BLE001 — an unreadable roster is not a refusal
            pass

    existing = {str((r or {}).get("goal") or "").strip().lower()
                for r in (routines.REGISTRY.list().get("routines") or [])}
    # The cap applies to what the SCOUT offered, not to what survived dedupe: a
    # duplicate must not promote a lower-ranked candidate into a new routine.
    for cand in raw[:CANDIDATES_MAX]:
        goal = " ".join(str(cand.get("goal") or "").split())[:GOAL_CHARS]
        if len(goal) < 12:
            out["skipped"].append({"reason": "goal too short", "goal": goal})
            continue
        if goal.lower() in existing:
            out["skipped"].append({"reason": "already a routine", "goal": goal})
            continue
        rec = {"goal": goal,
               "every_seconds": _clamp_every(cand.get("every_seconds")),
               "why": " ".join(str(cand.get("why") or "").split())[:300]}
        out["candidates"].append(rec)
        if len(out["candidates"]) >= CANDIDATES_MAX:
            break
    for rec in out["candidates"]:
        made = routines.REGISTRY.create(owner, rec["goal"], rec["every_seconds"],
                                        enabled=False)
        if not made.get("ok"):
            out["skipped"].append({"reason": made.get("error") or "create failed",
                                   "goal": rec["goal"]})
            continue
        existing.add(rec["goal"].lower())
        row = dict(made["routine"])
        row["why"] = rec["why"]
        out["created"].append(row)
    try:
        improve.ledger_add("routine_proposal", origin="harness",
                           agent=owner, created=[r["id"] for r in out["created"]],
                           candidates=len(out["candidates"]),
                           skipped=len(out["skipped"]))
    except Exception:  # noqa: BLE001 — the audit row must not fail the scan
        pass
    if not out["created"]:
        out["reason"] = out.get("reason") or "nothing new to propose"
    return out
