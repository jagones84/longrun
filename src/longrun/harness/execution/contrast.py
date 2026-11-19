#!/usr/bin/env python3
"""H2-2 — behavioural contrast between two execution records.

Probe gives "a behavioral contrast … rather than verify task correctness"
(`research/papers/harness2/harness2_2610.14224.txt:285-290`); Compose then ties
every decision to "a concrete observation rather than a presumed score gain"
(`:291-297`). This module is that observation, computed deterministically from two
`harness.record` artifacts — no model, no score, no answer key.

The verdict is deliberately conservative. The paper's own tables show a harness
can win while spending FEWER steps (`:443-478`), so a step delta never counts as
an improvement on its own:

  regressed      a new error class with no fix, or a lost deliverable with no fix
  improved       a fixed class, no new class/lost deliverable, successful tool evidence
  unchanged      no error delta, no deliverable delta, same tool mix
  mixed          everything else — the honest default
  incomparable   different goals or explicitly different models

Read-only comparison: two dicts in, one dict out. Workspace identities resolve
filesystem paths; no task is executed and no state is written.
"""
import re

from longrun.harness.record import artifact_identity

_MAX_SIG = 60
_NUM = re.compile(r"\d+")
_WS = re.compile(r"\s+")


def _steps_of(rec):
    """The step list of a record (tolerates a partial/empty record)."""
    got = rec.get("steps") if isinstance(rec, dict) else None
    return got if isinstance(got, list) else []


def _failed(rec):
    """Failed steps only."""
    return [s for s in _steps_of(rec) if isinstance(s, dict) and s.get("ok") is False]


def signature(error):
    """A stable error class: lowercased, digits folded, bounded.

    "exit 7 after 3 retries" and "exit 7 after 9 retries" are the SAME class —
    otherwise a retry counter reads as a new failure.
    """
    text = _WS.sub(" ", str(error or "").strip().lower())
    text = _NUM.sub("#", text).strip(" .,:;\t\n")
    return text[:_MAX_SIG]


def _classes(rec):
    """{signature: count} for the failed steps of a record."""
    out = {}
    for step in _failed(rec):
        sig = signature(step.get("error"))
        if not sig:
            # No diagnostic is still a failure. Keep the structured exit code
            # exact; unlike counters inside free text it identifies the outcome.
            tool = signature(step.get("tool")) or "unknown tool"
            code = step.get("exit_code")
            sig = "%s failed (exit %s)" % (tool, code if code is not None else "unknown")
        out[sig] = out.get(sig, 0) + 1
    return out


def _tool_counts(rec):
    """{tool: count} over every step."""
    out = {}
    for step in _steps_of(rec):
        if not isinstance(step, dict):
            continue
        name = str((step or {}).get("tool") or "")
        if name:
            out[name] = out.get(name, 0) + 1
    return out


def _deliverables(rec):
    """{path: sha256} for the record's deliverables."""
    out = {}
    for item in (rec.get("deliverables") or []):
        if isinstance(item, dict) and item.get("path"):
            out[artifact_identity(item["path"], rec.get("workspace"))] = item.get("sha256")
    return out


def _harness_changed(base, cand):
    """Component names whose harness digest differs (prompt, skills, hooks, ...)."""
    hb = base.get("harness") or {}
    hc = cand.get("harness") or {}
    changed = []
    for name in ("revision", "config", "overlay", "prompt", "skills", "hooks"):
        if hb.get(name) != hc.get(name):
            changed.append(name)
    return changed


def diff(base, cand):
    """The contrast between two records.

    Args:
        base: the reference record (`harness.record.build` output).
        cand: the candidate harness's record, same goal.
    Returns:
        {steps, tools, errors, files, deliverables, budget, harness, verdict, reasons}
    """
    base, cand = (base if isinstance(base, dict) else {}), (cand if isinstance(cand, dict) else {})
    same_goal = bool(base.get("goal")) and base.get("goal") == cand.get("goal")
    models = [str(r.get("model") or "").strip() for r in (base, cand)]
    model_match = models[0] == models[1] if all(models) else None
    comparable = same_goal and model_match is not False
    mistakes_b, mistakes_c = _classes(base), _classes(cand)
    fixed = sorted(set(mistakes_b) - set(mistakes_c))
    introduced = sorted(set(mistakes_c) - set(mistakes_b))
    tools_b, tools_c = _tool_counts(base), _tool_counts(cand)
    deliv_b, deliv_c = _deliverables(base), _deliverables(cand)
    common = sorted(set(deliv_b) & set(deliv_c))
    rewrote = [p for p in common if deliv_b.get(p) != deliv_c.get(p)]
    files_b = {artifact_identity(p, base.get("workspace"))
               for p in (base.get("files_touched") or [])}
    files_c = {artifact_identity(p, cand.get("workspace"))
               for p in (cand.get("files_touched") or [])}
    steps_b, steps_c = len(_steps_of(base)), len(_steps_of(cand))
    successful_c = sum(1 for s in _steps_of(cand)
                       if isinstance(s, dict) and s.get("ok") is True
                       and str(s.get("tool") or "").strip())
    budget_b = base.get("budget") or {}
    budget_c = cand.get("budget") or {}
    tokens_b, tokens_c = budget_b.get("tokens"), budget_c.get("tokens")
    out = {
        "steps": {"base": steps_b, "cand": steps_c, "saved": steps_b - steps_c,
                  "successful_cand": successful_c},
        "tools": {"base": tools_b, "cand": tools_c, "same": tools_b == tools_c},
        "errors": {
            "base": sum(mistakes_b.values()), "cand": sum(mistakes_c.values()),
            "fixed": fixed, "introduced": introduced,
            "classes_base": mistakes_b, "classes_cand": mistakes_c,
        },
        "files": {
            "only_base": sorted(files_b - files_c),
            "only_cand": sorted(files_c - files_b),
            "common": len(files_b & files_c),
        },
        "deliverables": {
            "base": len(deliv_b), "cand": len(deliv_c),
            "only_base": sorted(set(deliv_b) - set(deliv_c)),
            "only_cand": sorted(set(deliv_c) - set(deliv_b)),
            "changed": rewrote,
        },
        "budget": {
            "steps": steps_c - steps_b,
            "seconds": round(float(budget_c.get("seconds") or 0)
                             - float(budget_b.get("seconds") or 0), 3),
            "tokens": (tokens_c - tokens_b)
            if isinstance(tokens_b, int) and isinstance(tokens_c, int) else None,
        },
        "harness": {"changed": _harness_changed(base, cand)},
        "evidence": {"base": base.get("evidence") or {},
                     "cand": cand.get("evidence") or {}},
        "identity": {"goal_match": same_goal, "model_match": model_match},
        "comparable": comparable,
    }
    out["verdict"] = verdict(out) if comparable else "incomparable"
    out["reasons"] = reasons(out)
    return out


def verdict(d):
    """The four-way verdict from the contrast alone (no score, no model)."""
    errs, deliv, steps = d["errors"], d["deliverables"], d["steps"]
    lost = bool(deliv["only_base"])
    if (errs["introduced"] and not errs["fixed"]) or (lost and not errs["fixed"]):
        return "regressed"
    if (errs["fixed"] and not errs["introduced"] and not lost
            and steps.get("successful_cand", 0) > 0):
        return "improved"
    quiet = (not errs["fixed"] and not errs["introduced"] and not lost
             and not deliv["only_cand"] and not deliv["changed"]
             and d["tools"]["same"] and steps["saved"] == 0)
    return "unchanged" if quiet else "mixed"


def reasons(d):
    """Human-readable lines behind the verdict (each one a counted fact)."""
    out = []
    identity = d.get("identity") or {}
    if identity.get("goal_match") is False:
        out.append("different goal (or no goal recorded): the contrast is NOT evidence")
    if identity.get("model_match") is False:
        out.append("different models: the contrast is NOT matched-model evidence")
    elif identity.get("model_match") is None:
        out.append("model identity unknown: matched-model provenance is not established")
    for label in ("base", "cand"):
        provenance = (d.get("evidence") or {}).get(label) or {}
        if provenance.get("scope") == "session_aggregate":
            out.append("%s is a session aggregate; run binding is unverified, "
                       "deliverable digests are live workspace observations" % label)
    errs = d["errors"]
    if errs["fixed"]:
        out.append("fixed error class(es): " + ", ".join(errs["fixed"]))
    if errs["introduced"]:
        out.append("new error class(es): " + ", ".join(errs["introduced"]))
    if not errs["fixed"] and not errs["introduced"]:
        out.append("error count %d -> %d" % (errs["base"], errs["cand"]))
    deliv = d["deliverables"]
    if deliv["only_base"]:
        out.append("lost deliverable(s): " + ", ".join(deliv["only_base"]))
    if deliv["only_cand"]:
        out.append("new deliverable(s): " + ", ".join(deliv["only_cand"]))
    if deliv["changed"]:
        out.append("rewritten deliverable(s): " + ", ".join(deliv["changed"]))
    steps = d["steps"]
    if not steps.get("successful_cand"):
        out.append("no successful candidate tool execution: removal of errors is not a demonstrated fix")
    out.append("steps %d -> %d" % (steps["base"], steps["cand"]))
    if d["harness"]["changed"]:
        out.append("harness changed: " + ", ".join(d["harness"]["changed"]))
    return out


def evidence_text(d, max_chars=1200):
    """One bounded block for an editor/composer prompt or the operator log."""
    head = "verdict: %s" % d.get("verdict", "?")
    lines = [head] + ["- " + r for r in (d.get("reasons") or [])]
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max(0, max_chars - 20)].rstrip() + "\n… [truncated]"
    return text
