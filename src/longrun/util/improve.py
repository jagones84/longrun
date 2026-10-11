#!/usr/bin/env python3
"""Self-improvement routing (JAG-128B).

Golden rule (frontier pattern): the agent writes FREELY only to memory;
the RULES (project/global) are written by the human -> the agent at most PROPOSES;
the harness CODE is out of scope.
"""
import time
import os
import re
import json

from longrun.util.fswrite import write_json
from longrun.util.paths import REPO_ROOT as REPO
PROPOSAL_DIR = os.path.join(REPO, "data", "proposals")

# scope -> write mode allowed to the agent
AGENT_WRITE = {
    "memory": "auto",       # data/memory/**  -> free write (silent)
    "skill": "propose",     # skills/**       -> proposal, threshold
    "project": "propose",   # <ws>/.longrun/RULES.md -> PROPOSAL only
    "global": "propose",    # ~/.config/longrun/RULES.md -> PROPOSAL only
    "code": "forbidden",    # longrun/*.py -> out of scope
}

_TOOLCALL_THRESHOLD = 5


def should_nudge(used_tools=0, errored=False, corrected=False):
    """True when the self-improvement nudge triggers (Hermes pattern)."""
    if corrected or errored:
        return True
    try:
        return int(used_tools) >= _TOOLCALL_THRESHOLD
    except (TypeError, ValueError):
        return False


def _path(pid):
    # JAG-231: `pid` comes from the client (approve/deny). A non-string crashed
    # (`pid + ".json"` -> TypeError, dropping the connection) and a
    # traversal-shaped id could escape the proposals store. Only a plain token
    # ever matches a real proposal id ("<epoch-ms>-<scope>").
    if not isinstance(pid, str) or not re.match(r"^[A-Za-z0-9_-]{1,80}$", pid):
        raise ValueError("invalid proposal id")
    return os.path.join(PROPOSAL_DIR, pid + ".json")


def propose(scope, content, reason="", target_path="", ws=None):
    """Register a PROPOSAL (writes nothing definitive).

    `ws` is the workspace the rule will be written to in case of approve:
    it is captured NOW (the workspace may change before the decision),
    so `decide` writes to the right project and not the "current" one.
    """
    if ws is None:
        try:
            from longrun.memory import rules
            ws = rules.get_workspace()
        except Exception:  # noqa: BLE001 — the ws must never break the proposal
            ws = ""
    os.makedirs(PROPOSAL_DIR, exist_ok=True)
    pid = "%d-%s" % (int(time.time() * 1000), scope)
    rec = {"id": pid, "ts": time.time(), "scope": scope,
           "content": str(content)[:8000], "reason": str(reason)[:500],
           "target_path": target_path, "status": "pending", "ws": ws}
    write_json(_path(pid), rec)
    return rec


def get_proposal(pid):
    try:
        with open(_path(pid), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def list_proposals():
    out = []
    try:
        for fn in sorted(os.listdir(PROPOSAL_DIR)):
            if fn.endswith(".json"):
                p = get_proposal(fn[:-5])
                if p:
                    out.append(p)
    except OSError:
        pass
    return out


def _save(rec):
    write_json(_path(rec["id"]), rec)
    return rec


def decide(pid, decision):
    """approve|deny. Only 'approve' on project/global writes (appends) the rules."""
    rec = get_proposal(pid)
    if not rec or rec.get("status") != "pending":
        return {"ok": False, "error": "proposal not found or not pending"}
    if decision == "deny":
        rec["status"] = "denied"
        return {"ok": True, **_save(rec)}
    if decision != "approve":
        return {"ok": False, "error": "decision must be approve|deny"}
    if rec.get("scope") == "skill":
        # JAG-128B deferred: applying a skill is not implemented. It is NOT
        # silently marked 'approved': the status stays 'pending' and we tell the truth.
        return {"ok": False, "error": "skill apply not implemented (JAG-128B deferred)"}
    if rec["scope"] in ("project", "global"):
        from longrun.memory import rules
        rules.append(rec["scope"], rec["content"], ws=rec.get("ws"))
    rec["status"] = "approved"
    return {"ok": True, **_save(rec)}

