#!/usr/bin/env python3
"""Team safety audit — a team without a named safety lead diffuses responsibility.

Source: arXiv:2611.17820, "Aligning AI Teams" (round 113). Four findings matter
here:

  * alignment training on a single agent does not transfer to a team, and the
    single-vs-team safety gap does not shrink with model capability;
  * natural interventions (agents critiquing each other, group chat) do NOT
    reliably restore the single-agent behaviour;
  * diffusion of responsibility explains much of the gap: team members are less
    likely to check for system-level safety failures and more likely to
    rationalize or deflect;
  * two interventions DO work: a DESIGNATED SAFETY LEAD agent, and a coordinator
    who publishes a system-level SAFETY SPECIFICATIONS document. The compound of
    both lands at the top of the reference band.

This module audits a team/job definition against those two intervention points.
It is deterministic and read-only: it names the missing object; it never edits the
org chart.

  * `audit(team)` -> findings + verdict `covered | incomplete | uncovered`;
  * `brief(team)` -> one line the coordinator can paste into its plan turn.
"""
from __future__ import annotations

FORMAT = "longrun-team-safety/1"
REQUIRED_DOC_SECTIONS = ("targets", "owners", "checks")


def _members(team):
    out = {}
    for m in team.get("members") or ():
        if isinstance(m, dict) and m.get("id"):
            out[str(m["id"])] = m
        elif isinstance(m, str):
            out[m] = {"id": m}
    return out


def _doc(team):
    doc = team.get("safety_doc") or team.get("safety_spec")
    return doc if isinstance(doc, dict) else {}


def audit(team):
    team = team or {}
    members = _members(team)
    coordinator = str(team.get("coordinator") or "")
    lead = str(team.get("safety_lead") or "")
    findings = []

    if not lead:
        findings.append({"kind": "missing-safety-lead",
                         "why": "no member is designated for system-level safety"})
    else:
        if lead not in members:
            findings.append({"kind": "lead-not-a-member",
                             "why": "%s is not in the team roster" % lead})
        if coordinator and lead == coordinator:
            findings.append({"kind": "lead-is-coordinator",
                             "why": "the safety lead must be separable from the coordinator"})

    doc = _doc(team)
    if not doc:
        findings.append({"kind": "missing-safety-doc",
                         "why": "the coordinator published no safety specifications document"})
    else:
        author = str(doc.get("author") or "")
        if author and coordinator and author != coordinator:
            findings.append({"kind": "doc-not-published-by-coordinator",
                             "why": "safety specs must come from the coordinator (%s), not %s"
                                    % (coordinator, author)})
        missing = [s for s in REQUIRED_DOC_SECTIONS if not doc.get(s)]
        if missing:
            findings.append({"kind": "incomplete-safety-doc",
                             "why": "missing sections: %s" % ", ".join(missing)})

    jobs = team.get("jobs") or []
    unscoped = [str(j.get("id") or j.get("name") or i)
                for i, j in enumerate(jobs)
                if isinstance(j, dict) and not str(j.get("safety") or "").strip()]
    if jobs and unscoped:
        findings.append({"kind": "job-without-safety-scope",
                         "why": "jobs carry no safety scope: %s" % ", ".join(unscoped)})

    kinds = {f["kind"] for f in findings}
    if not findings:
        verdict = "covered"
    elif kinds <= {"job-without-safety-scope", "incomplete-safety-doc"}:
        verdict = "incomplete"
    else:
        verdict = "uncovered"
    return {"format": FORMAT, "coordinator": coordinator, "safety_lead": lead,
            "findings": findings, "verdict": verdict}


def brief(team):
    """One line a coordinator can paste into its plan turn (no invention)."""
    res = audit(team)
    if res["verdict"] == "covered":
        return "team-safety: covered — designated lead + published safety specs."
    reasons = "; ".join(f["why"] for f in res["findings"])
    return "team-safety: %s — %s" % (res["verdict"], reasons)
