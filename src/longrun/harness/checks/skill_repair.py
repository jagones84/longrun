#!/usr/bin/env python3
"""Skill repair — fault localization, typed mutations, regression screening.

Source: arXiv:2611.20856, "Synapse: Optimizing Natural-Language Agent Skills through
Program Repair" (round 118). A skill is not a program, but the procedure it
describes can be partly recovered as one; that partial view is the editable
surface. The paper's three questions and its three answers:

  L1 which instruction should change -> a typed mutation tied to a mapped source span;
  L2 which other instructions the fault involves -> control-flow and dependence
     closure over the view;
  L3 which passing tasks the edit may break -> tests selected through those
     relations, including previously passing ones.

Guarantees the host enforces, whatever the proposer returns (Section 4): an
accepted patch is well formed, leaves the source span of every untargeted
instruction unchanged, and is accepted only if it raises the pass count on a
separate validation suite.

This module is the deterministic host: it localizes, selects, applies, checks and
validates. Candidate mutations come from the caller.

Pure: skill + failures + candidates in, verdicts out.
"""
from __future__ import annotations

FORMAT = "longrun-skill-repair/1"
OPS = ("replace-span", "insert-before", "delete-span")


def _span_map(skill):
    return {s["id"]: s for s in (skill or {}).get("spans") or [] if isinstance(s, dict) and s.get("id")}


def _closure(spans, roots):
    """Control-flow and dependence closure: what an edit at ``roots`` can involve."""
    adj = {}
    for sid, span in spans.items():
        for other in (span.get("control") or []) + (span.get("depends_on") or []):
            adj.setdefault(sid, set()).add(other)
            adj.setdefault(other, set()).add(sid)
    seen, stack = set(), [r for r in roots if r in spans]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adj.get(node, set()) - seen)
    return seen


def localize(skill, failures):
    """The failing spans and their control/dependence neighbours."""
    spans = _span_map(skill)
    faults = sorted({f.get("span") for f in failures or [] if f.get("span") in spans})
    related = sorted(_closure(spans, faults) - set(faults))
    tests = sorted({f.get("test") for f in failures or [] if f.get("test")})
    return {"format": FORMAT, "faults": faults, "related": related, "failing_tests": tests}


def affected_tests(skill, span_ids):
    """Every test whose coverage touches the edited span or its related spans."""
    spans = _span_map(skill)
    reach = _closure(spans, set(span_ids or []))
    selected = []
    for test in (skill or {}).get("tests") or []:
        if set(test.get("covers") or []) & reach:
            selected.append({"id": test.get("id"), "was_passing": bool(test.get("passing"))})
    return selected


def apply(skill, mutation):
    """Write a typed mutation back to its mapped span; refuse anything unmapped."""
    mutation = mutation or {}
    spans = _span_map(skill)
    sid = mutation.get("span")
    if sid not in spans:
        return {"ok": False, "why": "the mutation does not target a mapped span", "skill": None}
    if mutation.get("op") not in OPS:
        return {"ok": False, "why": "untyped mutation", "skill": None}
    text = str(mutation.get("text") or "")
    if mutation["op"] != "delete-span" and not text.strip():
        return {"ok": False, "why": "an empty replacement is not a well-formed skill", "skill": None}
    new_spans = [dict(s) for s in skill.get("spans") or []]
    for span in new_spans:
        if span.get("id") != sid:
            continue
        if mutation["op"] == "replace-span":
            span["text"] = text
        elif mutation["op"] == "insert-before":
            span["text"] = text + "\n" + str(span.get("text") or "")
        else:
            span["text"] = ""
            span["deleted"] = True
    out = dict(skill)
    out["spans"] = new_spans
    return {"ok": True, "skill": out, "changed": [sid]}


def _untargeted_unchanged(before, after, target):
    old = {s["id"]: s.get("text") for s in before.get("spans") or []}
    new = {s["id"]: s.get("text") for s in after.get("spans") or []}
    return all(old[sid] == new.get(sid) for sid in old if sid != target)


def repair(record):
    """Screen and validate caller-supplied patches; at most one is accepted."""
    rec = record or {}
    skill = rec.get("skill") or {}
    loc = localize(skill, rec.get("failures") or [])
    selected = affected_tests(skill, loc["faults"] + loc["related"])
    selected_ids = [t["id"] for t in selected]

    verdicts = []
    accepted = None
    for cand in rec.get("candidates") or []:
        label = cand.get("label") or cand.get("span")
        applied = apply(skill, cand)
        if not applied["ok"]:
            verdicts.append({"label": label, "accepted": False, "why": applied["why"]})
            continue
        if not _untargeted_unchanged(skill, applied["skill"], cand.get("span")):
            verdicts.append({"label": label, "accepted": False,
                             "why": "an untargeted span changed"})
            continue
        screening = (rec.get("screening") or {}).get(label) or {}
        failing = [t for t in selected_ids if not screening.get(t, False)]
        if failing:
            verdicts.append({"label": label, "accepted": False,
                             "why": "selected tests still fail: %s" % ", ".join(failing),
                             "selected": selected_ids})
            continue
        validation = (rec.get("validation") or {}).get(label) or {}
        gained = int(validation.get("pass") or 0) - int(rec.get("incumbent_pass") or 0)
        if gained <= 0:
            verdicts.append({"label": label, "accepted": False,
                             "why": "the validation suite did not improve (%+d)" % gained,
                             "selected": selected_ids})
            continue
        verdicts.append({"label": label, "accepted": True, "gained": gained,
                         "selected": selected_ids, "skill": applied["skill"]})
        if accepted is None:
            accepted = label
    chosen = next((v for v in verdicts if v["label"] == accepted), None)
    return {"format": FORMAT, "localization": loc, "selected_tests": selected,
            "verdicts": [{k: v[k] for k in v if k != "skill"} for v in verdicts],
            "accepted": accepted, "skill": (chosen or {}).get("skill")}
