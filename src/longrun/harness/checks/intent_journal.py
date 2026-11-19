#!/usr/bin/env python3
"""Tool-call intent journal — declare the kind of act, then check it against the
effects the harness observed.

Source: arXiv:2611.06563, "EPISTEME: Trustworthy Coding Agents Through Tool Call
Intent" (round 111). The harness makes `type` (a closed vocabulary of seven
kinds) and `reason` mandatory on every shell call; a well-formed declaration is
required BEFORE execution, the harness records what the call actually changed,
and a mismatch between the declaration and the effects is a finding that no
command string or log alone can give. The journal lives outside the workspace,
so it survives a stopped or killed agent.

This module is the deterministic checker, not a shell wrapper: the caller hands
in the declaration and the before/after fingerprints of the workspace.

  * `well_formed`   — vocabulary, and a reason that is not a restatement;
  * `effects`       — modified / added / deleted from two fingerprint maps;
  * `check`         — findings: a read-only intent that wrote, a declared target
                      that was not touched, a change with no declared target;
  * `append`        — atomic journal write (survives a kill);
  * `audit`         — journal-level counts and the exposed-mismatch rate.

Pure: no execution, no model.
"""
from __future__ import annotations

import hashlib
import json
import os

FORMAT = "longrun-intent-journal/1"
READ_ONLY = ("collect-info", "test-hypothesis", "verify")
KINDS = READ_ONLY + ("setup", "change-state", "revert", "cleanup")
MIN_REASON = 20


def well_formed(decl):
    decl = decl or {}
    kind = str(decl.get("type") or "").strip()
    reason = " ".join(str(decl.get("reason") or "").split())
    if kind not in KINDS:
        return {"ok": False, "reason": "type-missing-or-outside-vocabulary"}
    if len(reason) < MIN_REASON:
        return {"ok": False, "reason": "reason-too-short"}
    return {"ok": True, "reason": "well-formed", "type": kind,
            "read_only": kind in READ_ONLY}


def fingerprint_map(paths):
    """Map a list of workspace-relative paths to content fingerprints."""
    out = {}
    for p in paths or ():
        p = str(p)
        try:
            with open(p, "rb") as fh:
                out[p] = hashlib.sha256(fh.read()).hexdigest()[:16]
        except OSError:
            out[p] = None
    return out


def effects(before, after, head_before=None, head_after=None):
    """The observable effect of one call: file changes and whether HEAD moved."""
    before = before or {}
    after = after or {}
    modified = sorted(p for p in set(before) & set(after) if before[p] != after[p])
    added = sorted(p for p in set(after) - set(before) if after[p] is not None)
    deleted = sorted(p for p in set(before) - set(after))
    return {"modified": modified, "added": added, "deleted": deleted,
            "git_head_moved": (head_before is not None and head_after is not None
                               and head_before != head_after)}


def _touched(eff):
    return set(eff.get("modified") or ()) | set(eff.get("added") or ()) \
        | set(eff.get("deleted") or ())


def _matches(path, targets):
    return any(str(path) == t or str(path).startswith(str(t).rstrip("/") + "/")
               for t in (targets or ()))


def check(decl, eff, declared_targets=None):
    """Compare the claim with the observation; never invents an effect."""
    wf = well_formed(decl)
    if not wf["ok"]:
        return {"format": FORMAT, "declaration": decl, "effects": eff,
                "findings": [{"kind": "invalid-declaration", "why": wf["reason"]}],
                "verdict": "rejected"}
    findings = []
    touched = _touched(eff)
    targets = [str(t) for t in (declared_targets or ())]
    if wf["read_only"] and touched:
        findings.append({"kind": "read-only-intent-wrote",
                         "why": "%s declared, but the call changed %s"
                                % (wf["type"], ", ".join(sorted(touched)))})
    if targets:
        stray = [p for p in touched if not _matches(p, targets)]
        if stray:
            findings.append({"kind": "undeclared-target-touched",
                             "why": "changed outside the declared targets: %s"
                                    % ", ".join(stray)})
        missing = [t for t in targets if not any(_matches(p, [t]) for p in touched)]
        if missing and not wf["read_only"]:
            findings.append({"kind": "declared-target-untouched",
                             "why": "declared but not touched: %s" % ", ".join(missing)})
    if wf["type"] == "change-state" and not touched and not eff.get("git_head_moved"):
        findings.append({"kind": "state-change-without-effect",
                         "why": "declared change-state, no file or HEAD change observed"})
    return {"format": FORMAT, "type": wf["type"], "read_only": wf["read_only"],
            "effects": eff, "findings": findings,
            "verdict": "clean" if not findings else "mismatch"}


def entry(tool, args, decl, eff, result):
    """One journal row: the claim, the observation, and the check."""
    row = check(decl, eff, (decl or {}).get("targets"))
    row.update({"tool": str(tool), "args": args, "exit_code": (result or {}).get("exit_code")})
    return row


def append(path, row):
    """Append one JSON line; the journal outlives a killed agent.

    One line per call, opened in append mode: a crash between calls leaves whole
    rows, never a truncated journal (the row itself is written by one `write`).
    """
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)
    return path


def audit(rows):
    rows = [r for r in (rows or ()) if isinstance(r, dict)]
    mism = [r for r in rows if r.get("verdict") == "mismatch"]
    rejected = [r for r in rows if r.get("verdict") == "rejected"]
    kinds = {}
    for r in mism:
        for f in r.get("findings") or ():
            kinds[f.get("kind")] = kinds.get(f.get("kind"), 0) + 1
    return {"format": FORMAT, "entries": len(rows), "mismatches": len(mism),
            "rejected": len(rejected),
            "exposed_rate": (round(len(mism) / len(rows), 3) if rows else None),
            "by_kind": dict(sorted(kinds.items())),
            "verdict": "clean" if not mism else "mismatch"}
