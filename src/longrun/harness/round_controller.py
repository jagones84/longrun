#!/usr/bin/env python3
"""Round controller — the between-round decision is an object.

Source: arXiv:2611.22661, "The Between-Round Decision in Autonomous Research:
An LLM Controller That Reads the Whole Trajectory" (round 132). An autonomous
loop keeps a Champion (the best verified solution) and a log, and makes one
decision per round from the accumulated evidence.

  * **the Champion never regresses**: it changes only on a strict improvement
    of the verified metric (`between_round_decision_controller_2611.22661.md:80`).
  * **the lesson states facts only**, never an attribution to a mechanism, so a
    noisy measurement does not become a causal story later rounds inherit
    (`:90`).
  * **one decision object**: mode (explore/exploit/stop), base
    (baseline/Champion), a goal-level instruction of at most 40 words, 0–3
    checkable hard constraints, and a rationale citing the log (`:96`).
  * **code guardrails override the model**: no exploit before a Champion, the
    last 30% of rounds refine or stop, a fourth consecutive extension without
    progress becomes a new line, and a stop is refused after an improvement
    (`:98`).
  * **more evidence is better, monotonically**: no history 0.4299 / 83.71%,
    one round 0.4244 / 84.01%, full history 0.4172 / 84.63% (`:157`–`:161`).
  * **unproductive rounds cost nothing already won** (`:153`).
  * **the frontier is a direction, not a reachability claim**: local evidence
    overrides it (`:389`–`:391`).

  * `champion(rounds)` — fold the rounds and refuse a regression.
  * `decision(record)` — validate the four-part decision.
  * `lesson(entry)` — facts only, and a failure keeps its diagnosis.
  * `guardrails(decision, state)` — apply the code overrides.
  * `context_ladder(rows)` — does more accumulated evidence help?
  * `progress(rounds)` — did a non-improving round cost anything?
  * `frontier(decision)` — was a validated Champion abandoned for a number?
  * `advise(profile)` — map a harness profile onto the paper's failure modes.

Pure: round records in, findings out; nothing is executed.
"""
from __future__ import annotations

FORMAT = "longrun-round-controller/1"

MODES = ("explore", "exploit", "stop")
BASES = ("baseline", "champion")
CAUSAL = ("because", "caused", "due to", "led to", "as a result", "therefore")


def _text(value):
    return str(value).strip() if value is not None else ""


def _better(a, b, direction):
    if a is None or b is None:
        return False
    return a < b if direction == "lower" else a > b


def champion(rounds):
    """Fold the rounds into the Champion; a Champion never regresses."""
    direction = "lower"
    floor = None
    best = None
    findings = []
    history = []
    for r in rounds or ():
        direction = str(r.get("direction") or direction).lower()
        if floor is None and r.get("floor") is not None:
            floor = r["floor"]
        for cand in r.get("candidates") or ():
            metric = cand.get("metric")
            if metric is None:
                findings.append({"kind": "candidate-without-metric", "candidate": cand.get("id"),
                                 "why": "an unverified candidate cannot become a Champion"})
                continue
            if floor is not None and best is None and not _better(metric, floor, direction):
                continue
            if best is None or _better(metric, best["metric"], direction):
                best = {"id": cand.get("id"), "metric": metric,
                        "signature": cand.get("signature"), "round": r.get("round"),
                        "bottleneck": cand.get("bottleneck")}
                history.append(dict(best))
    if best is None and rounds:
        findings.append({"kind": "no-champion", "why": "no candidate strictly improved on the floor"})
    for prev, nxt in zip(history, history[1:]):
        if not _better(nxt["metric"], prev["metric"], direction):
            findings.append({"kind": "champion-regressed", "from": prev["metric"],
                             "to": nxt["metric"],
                             "why": "a Champion changes only on a strict improvement"})
    return {"format": FORMAT, "champion": best, "history": history,
            "floor": floor, "direction": direction, "findings": findings}


def decision(record):
    """Validate the decision object: mode, base, instruction, constraints, rationale."""
    d = record or {}
    mode = _text(d.get("mode")).lower()
    base = _text(d.get("base")).lower()
    instruction = _text(d.get("instruction"))
    constraints = d.get("hard_constraints") or []
    rationale = _text(d.get("rationale"))
    findings = []
    if mode not in MODES:
        findings.append({"kind": "unknown-mode", "mode": mode})
    if mode == "stop":
        if base:
            findings.append({"kind": "stop-with-base", "base": base,
                             "why": "a stop delivers the Champion; it chooses no base"})
    elif base not in BASES:
        findings.append({"kind": "unknown-base", "base": base})
    if mode == "exploit" and base == "baseline":
        findings.append({"kind": "exploit-on-baseline",
                         "why": "an exploit always refines a real Champion"})
    if not instruction and mode != "stop":
        findings.append({"kind": "instruction-missing"})
    words = instruction.split()
    if len(words) > 40:
        findings.append({"kind": "instruction-too-long", "words": len(words),
                         "why": "an instruction is a goal, not a plan; the limit is 40 words"})
    lowered = instruction.lower()
    if any(marker in lowered for marker in ("(1)", "step 1", "first,")) or lowered.count(";") >= 2:
        findings.append({"kind": "instruction-is-a-recipe",
                         "why": "concrete steps belong in constraints or in generation, not in the goal"})
    if len(constraints) > 3:
        findings.append({"kind": "too-many-constraints", "count": len(constraints),
                         "why": "hard constraints are the non-negotiable channel; at most three"})
    for idx, con in enumerate(constraints):
        if isinstance(con, dict):
            if not _text(con.get("text")) or not _text(con.get("check")):
                findings.append({"kind": "constraint-uncheckable", "index": idx,
                                 "why": "a constraint must be checkable post hoc"})
        elif not _text(con):
            findings.append({"kind": "constraint-uncheckable", "index": idx})
        else:
            findings.append({"kind": "constraint-uncheckable", "index": idx,
                             "why": "a bare string carries no check to verify after the round"})
    if mode != "stop" and not rationale:
        findings.append({"kind": "rationale-missing",
                         "why": "the rationale must cite the evidence the decision rests on"})
    return {"format": FORMAT, "mode": mode, "base": base,
            "instruction_words": len(words), "constraints": len(constraints),
            "findings": findings}


def lesson(entry):
    """A lesson states what was measured, never why it happened."""
    e = entry or {}
    text = _text(e.get("lesson")).lower()
    results = e.get("results") or []
    failures = [r for r in results if r.get("metric") is None]
    findings = []
    if not text:
        findings.append({"kind": "lesson-missing"})
    for word in CAUSAL:
        if word in text:
            findings.append({"kind": "lesson-attributed", "word": word,
                             "why": "one noisy measurement must not become a causal story"})
            break
    if results and e.get("best_metric") is None:
        findings.append({"kind": "lesson-without-measurement",
                         "why": "the log records the round's best metric"})
    if failures and not any(r.get("diagnosis") for r in failures):
        findings.append({"kind": "failed-candidates-dropped", "count": len(failures),
                         "why": "a failed candidate's diagnosis can steer later rounds"})
    return {"format": FORMAT, "findings": findings}


def guardrails(dec, state):
    """The code overrides the model where the paper fixes a rule."""
    d = dec or {}
    mode = _text(d.get("mode")).lower()
    base = _text(d.get("base")).lower()
    s = state or {}
    findings = []
    effective = {"mode": mode, "base": base}
    if not s.get("has_champion") and mode == "exploit":
        effective = {"mode": "explore", "base": "baseline"}
        findings.append({"kind": "exploit-before-champion",
                         "why": "rounds start from the baseline until a Champion exists"})
    total = s.get("rounds_total")
    done = s.get("rounds_done")
    if total and done is not None:
        reserve = max(1, -(-int(total) * 3 // 10))  # ceil(0.3 * total)
        if int(total) - int(done) <= reserve and mode in ("explore",):
            effective = {"mode": "exploit", "base": "champion"}
            findings.append({"kind": "closing-phase-explore", "reserve": reserve,
                             "why": "the last 30% of rounds refine or stop"})
    if int(s.get("stall_count") or 0) >= 3 and effective.get("mode") == "explore" and effective.get("base") == "champion":
        effective = {"mode": "explore", "base": "baseline"}
        findings.append({"kind": "stall-forces-new-line",
                         "why": "a fourth consecutive extension without progress becomes a new line"})
    if mode == "stop" and s.get("improved_last_two"):
        effective = {"mode": "exploit", "base": "champion"}
        findings.append({"kind": "stop-after-improvement",
                         "why": "a stop is refused if the Champion improved in either of the last two rounds"})
    return {"format": FORMAT, "requested": {"mode": mode, "base": base},
            "effective": effective, "overridden": effective != {"mode": mode, "base": base},
            "findings": findings}


def context_ladder(rows):
    """Performance should improve monotonically as the controller reads more."""
    order = {"none": 0, "last": 1, "full": 2}
    usable = [r for r in (rows or ()) if str(r.get("reads")) in order and r.get("score") is not None]
    usable.sort(key=lambda r: order[str(r.get("reads"))])
    findings = []
    direction = str((rows or [{}])[0].get("direction") or "higher").lower()
    for prev, nxt in zip(usable, usable[1:]):
        if direction == "higher" and nxt["score"] < prev["score"]:
            findings.append({"kind": "context-does-not-help", "from": prev["reads"],
                             "to": nxt["reads"],
                             "why": "more accumulated evidence made the result worse"})
            break
        if direction == "lower" and nxt["score"] > prev["score"]:
            findings.append({"kind": "context-does-not-help", "from": prev["reads"],
                             "to": nxt["reads"],
                             "why": "more accumulated evidence made the result worse"})
            break
    if len(usable) >= 2 and not findings:
        findings.append({"kind": "context-helps", "best": usable[-1]["reads"]})
    if usable and usable[-1].get("reads") != "full":
        findings.append({"kind": "full-context-not-read", "best": usable[-1].get("reads")})
    return {"format": FORMAT, "ladder": usable, "findings": findings}


def progress(rounds):
    """A non-improving round costs nothing already won; a regression is a defect."""
    champ = champion(rounds)
    findings = []
    if champ["history"]:
        findings.append({"kind": "unproductive-rounds-free",
                         "why": "the Champion changes only on a verified improvement"})
    findings.extend(champ["findings"])
    return {"format": FORMAT, "champion": champ["champion"],
            "history": champ["history"], "findings": findings}


def frontier(dec):
    """Was a validated Champion abandoned for an unreached published number?"""
    d = dec or {}
    findings = []
    if d.get("abandoned_champion") and d.get("frontier_metric") is not None and not d.get("frontier_reproduced"):
        findings.append({"kind": "local-evidence-overridden",
                         "frontier_metric": d.get("frontier_metric"),
                         "why": "an unreached published number does not outrank a validated Champion"})
    if d.get("instruction") and str(d.get("instruction")).lower().startswith("reach"):
        findings.append({"kind": "frontier-used-as-target"})
    return {"format": FORMAT, "findings": findings}


def advise(profile):
    """Map a harness profile onto the paper's failure modes."""
    p = profile or {}
    have = {str(k) for k, v in p.items() if v}
    findings = []
    checks = (
        ("keeps_champion", "no-champion", "the loop has no best verified solution to carry forward"),
        ("factual_lessons", "causal-lessons", "a lesson attributes an outcome to a mechanism"),
        ("decision_object", "no-decision-object", "the between-round choice is not an auditable record"),
        ("code_guardrails", "guardrails-missing", "budget and stall rules live only in the prompt"),
        ("reads_full_history", "short-context", "the decision reads less than the full trajectory"),
        ("keeps_failures", "failures-dropped", "failed candidates leave no diagnosis for later rounds"),
    )
    for key, kind, why in checks:
        if key not in have:
            findings.append({"kind": kind, "why": why})
    return {"format": FORMAT, "findings": findings}
