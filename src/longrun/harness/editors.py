#!/usr/bin/env python3
"""H2-4 — two scoped editors, propose-only.

Harness² splits the harness editor in two: an INVARIANT editor that owns how the
agent works (tool errors, mechanical repetition, triggered workflows, ignored
invariants) and a DOMAIN editor that owns the subject matter (rules, procedures
and constraints of the task family). The split is measured — removing it costs
2.9 WB / 3.7 JB (`research/papers/harness2/harness2_2610.14224.txt:628-643`), and
the editor prompts are Prompts 1–2 in Appendix H (`:1953-1979`).

This module is the PROPOSE stage only, and it is deliberately weaker than the
paper: Longrun's own policy keeps harness CODE out of the agent's reach
(`util/improve.py:21-27` — memory auto, skill/project/global propose, code
forbidden), so a candidate here becomes a proposal in the existing inbox and the
operator decides. There is no write path to a live harness file.

Evidence rules:
- the editors are conditioned on a contrast, so an absent, `unchanged` or
  `incomparable` contrast produces nothing (nothing to fix, or the two runs do not
  answer the same task);
- the prompt carries the record's step summary and the contrast, never a tool
  observation (a 40 KB shell output would drown the one fact that matters);
- a candidate that is not skill / guardrail / tool_guidance / script is rejected.
"""
import json
import re

from longrun.harness import contrast as contrast_mod

MAX_CONTENT = 8000
MAX_CANDIDATES = 4
MAX_LIBRARY_ROWS = 5
MAX_EVIDENCE = 1200
MAX_STEP_LINES = 40

# kind -> the proposal scope Longrun already knows (util/improve.AGENT_WRITE)
KINDS = {
    "skill": "skill",
    "guardrail": "project",
    "tool_guidance": "project",
    "script": "project",
}

SCOPE_TEXT = {
    "invariant": (
        "You own HOW the agent works: procedure, tool use and completion. You do "
        "not own subject matter. Match each failure to the cheapest effective "
        "component: a tool error gets one bounded fallback and a stop condition "
        "(never blind repetition); repeated mechanical work gets a script; a "
        "narrow multi-step procedure gets an on-demand skill whose trigger is "
        "named in always-on text; only repeated evidence that clear prose is "
        "skipped justifies a hard rule. Prefer the smallest edit that removes the "
        "observed failure."
    ),
    "domain": (
        "You own the SUBJECT MATTER of this task family: the rules, procedures and "
        "constraints a domain expert would add (an accountant, a lawyer, a data "
        "reviewer). Do not change how the agent loops or calls tools. Encode what "
        "the evidence actually establishes about this workspace, anchored as fact, "
        "and keep procedure general enough to be right for another task of the "
        "same kind."
    ),
}

SYSTEM = (
    "You adapt an autonomous agent's harness from execution evidence. You are "
    "given the task, the step summary of a reference run, a behavioural contrast "
    "between two runs, and the index of a harness improvement library. There is "
    "no score, rubric or answer key anywhere: judge only from the contrast.\n"
    "Return ONE JSON object and nothing else:\n"
    '{"candidates":[{"kind":"skill|guardrail|tool_guidance|script",'
    '"name":"<short-slug>","content":"<the file text>",'
    '"why":"<the concrete failure this removes>"}]}\n'
    "Rules: at most %d candidates; content is the literal file to propose, in "
    "English; every candidate must remove a failure visible in the contrast; "
    "never propose code that runs inside the tool loop." % MAX_CANDIDATES
)


def _steps_summary(record):
    """One line per step — tool, outcome, error class. Never the observation."""
    lines = []
    for step in (record.get("steps") or [])[:MAX_STEP_LINES]:
        if not isinstance(step, dict):
            continue
        mark = "ok" if step.get("ok", True) else "FAIL"
        err = str(step.get("error") or "")[:120]
        lines.append("%s %s%s" % (mark, step.get("tool") or "?", (" :: " + err) if err else ""))
    return "\n".join(lines) or "(no steps recorded)"


def _library_block(rows):
    """The bounded index the editor may reuse from (id + lesson + components)."""
    out = []
    for row in (rows or [])[:MAX_LIBRARY_ROWS]:
        if not isinstance(row, dict):
            continue
        out.append("- %s · %s · components: %s" % (
            row.get("id") or "?",
            str(row.get("lesson") or "")[:160],
            ", ".join(str(c) for c in (row.get("components") or [])) or "none"))
    return "\n".join(out) or "(empty library)"


def build_prompt(scope, record, contrast, library_rows=()):
    """The editor prompt for one scope (pure, deterministic, bounded).

    Args:
        scope: "invariant" or "domain".
        record: the base execution record (`harness.record`).
        contrast: the `harness.contrast.diff` output.
        library_rows: index rows from `harness.library.relevant`.
    """
    if scope not in SCOPE_TEXT:
        raise ValueError("unknown editor scope: %r" % (scope,))
    evidence = contrast_mod.evidence_text(contrast or {}, MAX_EVIDENCE)
    return (
        "# YOUR DIMENSION: %s\n\n%s\n\n"
        "# THE TASK\n%s\n\n"
        "# THE REFERENCE RUN (step summary)\n%s\n\n"
        "# THE CONTRAST\n%s\n\n"
        "# THE LIBRARY (index only)\n%s\n\n"
        "# OUTPUT\n%s" % (
            "INV" if scope == "invariant" else "DOM",
            SCOPE_TEXT[scope],
            str(record.get("goal") or "(no goal recorded)")[:600],
            _steps_summary(record),
            evidence,
            _library_block(library_rows),
            SYSTEM,
        )
    )


def _parse(answer):
    """The candidates object out of a model answer (tolerant, never raises)."""
    text = str(answer or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        got = json.loads(text[start:end + 1])
    except ValueError:
        return []
    rows = got.get("candidates") if isinstance(got, dict) else None
    return rows if isinstance(rows, list) else []


def _name(value, fallback="candidate"):
    """A safe proposal name."""
    out = re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
    return (out or fallback)[:64]


def _validate(candidate):
    """(ok, reason) for one model candidate."""
    if not isinstance(candidate, dict):
        return False, "not an object"
    kind = str(candidate.get("kind") or "").strip().lower()
    if kind not in KINDS:
        return False, "kind %r is not proposable (code is forbidden)" % (kind,)
    content = str(candidate.get("content") or "").strip()
    if not content:
        return False, "empty content"
    if len(content) > MAX_CONTENT:
        return False, "content is %d bytes (max %d)" % (len(content), MAX_CONTENT)
    return True, ""


def propose(scope, record, contrast, library_rows=(), model=None, call=None,
            domain="general"):
    """Run one editor and register its candidates as proposals.

    Args:
        scope: "invariant" or "domain".
        record: the base execution record.
        contrast: the contrast between the base and candidate runs.
        library_rows: index rows the editor may reuse from.
        model: model alias for the one-shot call (ignored when `call` is given).
        call: `call(messages) -> (answer, think, used)`; injected in tests.
        domain: the library/family this cycle belongs to.
    Returns:
        {"scope", "proposals": [ids], "rejected": [{name, reason}], "skipped"?}
    """
    if not isinstance(contrast, dict) or not contrast:
        return {"scope": scope, "proposals": [], "rejected": [], "skipped": "no contrast"}
    if contrast.get("comparable") is False:
        return {"scope": scope, "proposals": [], "rejected": [], "skipped": "incomparable"}
    if contrast.get("verdict") == "unchanged":
        return {"scope": scope, "proposals": [], "rejected": [], "skipped": "no contrast"}
    prompt = build_prompt(scope, record or {}, contrast, library_rows)
    messages = [{"role": "user", "content": prompt}]
    used = model
    if call is None:
        from longrun.core import server
        answer, _think, used = server.stream_with_fallback(
            messages, model, "harness-editor", lambda *_a: None, timeout=240,
            max_tokens=4000)
    else:
        answer, _think, used = call(messages)
    ids, rejected = [], []
    for candidate in _parse(answer)[:MAX_CANDIDATES]:
        ok, reason = _validate(candidate)
        label = _name(candidate.get("name") if isinstance(candidate, dict) else "", "candidate")
        if not ok:
            rejected.append({"name": label, "reason": reason})
            continue
        from longrun.util import improve
        why = str(candidate.get("why") or "")[:400]
        rec = improve.propose(
            KINDS[str(candidate["kind"]).lower()],
            "%s\n" % str(candidate["content"]).strip(),
            reason="[%s/%s] %s" % (scope, label, why),
            origin="harness")
        if rec:
            ids.append(rec["id"])
        else:
            rejected.append({"name": label, "reason": "proposal store refused the write"})
    return {"scope": scope, "proposals": ids, "rejected": rejected,
            "model": used, "domain": domain}
