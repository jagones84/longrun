#!/usr/bin/env python3
"""Durable goal object (G-1): a `/goal` that outlives the turn that started it.

Longrun's `/goal` used to be a PER-REQUEST flag: the chat handler read
`mode=goal` and passed `goal_started=time.time()` into the loop, so the goal
existed only while that HTTP request was streaming (`core/httpapi.py:2074`,
`:2230`, `:2380`). Closing the tab, restarting the service, or wanting to pause
and come back later had no object to act on: there was nothing to pause, resume,
edit or delete. This module is that object.

One owner per fact:

* the OBJECTIVE (what to achieve, and whether it is active) lives here;
* the PLAN (steps and their evidence) stays in `plan.taskgraph`;
* completion is NOT a stored opinion — `progress()` reads the graph, so the bar
  can never say "done" while steps are still open, and a restart cannot
  resurrect a finished goal as active.

The record is small and human-readable, stored beside the other user state:

    {"session", "objective", "status", "created", "updated", "turns",
     "stopped"?, "note"?}

`status` is one of `active`, `paused`, `completed`. There is no `deleted`
status: deleting removes the record, so a deleted goal cannot be resumed by a
stale client.
"""
import os
import time

from longrun.util import paths
from longrun.util.fswrite import write_json

STATUSES = ("active", "paused", "completed")
MAX_OBJECTIVE = 8000


def _dir():
    """`<data>/goals` — one JSON file per session."""
    return os.path.join(paths.DATA_DIR, "goals")


def _safe(session_id):
    """A filesystem-safe session token (never a path escape)."""
    out = "".join(c for c in str(session_id or "") if c.isalnum() or c in "-_").strip("-.")
    return out[:96]


def path(session_id):
    """Absolute path of one session's goal record."""
    return os.path.join(_dir(), _safe(session_id) + ".json")


def load(session_id):
    """The goal record for `session_id`, or None (missing/corrupt = no goal)."""
    if not _safe(session_id):
        return None
    try:
        import json
        with open(path(session_id), "r", encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) and got.get("session") else None


def save(rec):
    """Persist one record (stamping `updated`) and return it."""
    rec["updated"] = round(time.time(), 3)
    os.makedirs(_dir(), exist_ok=True)
    write_json(path(rec.get("session")), rec)
    return rec


def _sync_graph(session_id, objective):
    """Mirror an EDITED/RESUMED objective onto the existing plan goal.

    The plan panel renders the graph's own `goal`, so letting the two disagree
    would show two different objectives for one task. Only an existing graph is
    touched: an empty plan is not a goal, and this module never authors steps.
    """
    if not objective:
        return
    try:
        from longrun.plan import taskgraph
        graph = taskgraph.load(session_id)
        if isinstance(graph, dict) and graph.get("goal") != objective:
            graph["goal"] = objective
            taskgraph.save(graph)
    except Exception:  # noqa: BLE001 — a goal edit must never fail on the graph
        pass


def can_start(session_id):
    """(ok, reason) — may a goal turn start for this session right now?"""
    rec = load(session_id)
    if not rec:
        return True, ""
    if rec.get("status") == "paused":
        return False, "the goal is paused: resume it before continuing"
    return True, ""


def start(session_id, objective=""):
    """Begin (or continue) the goal for this session and count the turn.

    A paused goal is NOT silently reactivated here — `can_start` refuses first,
    and a resume is an explicit operator action. Starting over a COMPLETED goal
    is a new goal: the objective is replaced and the counters restart — UNLESS the
    completion no longer holds (the plan reopened), in which case it is the SAME
    goal continuing and only the turn counter moves.
    """
    objective = str(objective or "").strip()[:MAX_OBJECTIVE]
    rec = load(session_id) or {}
    reopened = (rec.get("status") == "completed"
                and not progress(session_id).get("complete"))
    if rec.get("status") not in ("active", "paused") and not reopened:
        rec = {"session": session_id, "created": round(time.time(), 3), "turns": 0,
               "objective": objective, "status": "active"}
    else:
        if objective:
            rec["objective"] = objective
        rec["status"] = "active"
    rec["turns"] = int(rec.get("turns") or 0) + 1
    rec.pop("stopped", None)
    rec.pop("note", None)
    return save(rec)


def pause(session_id, note=""):
    """Pause an ACTIVE goal (None when there is nothing active to pause)."""
    rec = load(session_id)
    if not rec or rec.get("status") != "active":
        return None
    rec["status"] = "paused"
    if note:
        rec["note"] = str(note)[:400]
    return save(rec)


def resume(session_id):
    """Reactivate a PAUSED goal — or a COMPLETED one whose plan reopened (None).

    A completed goal whose plan still has open steps is not really done; the bar
    shows it as `reopened` and the operator can put it back to work with the same
    button that resumes a paused one.
    """
    rec = load(session_id)
    if not rec:
        return None
    if rec.get("status") == "completed" and not progress(session_id).get("complete"):
        rec["status"] = "active"
        rec.pop("note", None)
        rec.pop("stopped", None)
        return save(rec)
    if rec.get("status") != "paused":
        return None
    rec["status"] = "active"
    rec.pop("note", None)
    rec.pop("stopped", None)
    rec = save(rec)
    _sync_graph(session_id, rec.get("objective"))
    return rec


def edit(session_id, objective):
    """Replace the objective of an existing goal (None when it does not exist)."""
    text = str(objective or "").strip()[:MAX_OBJECTIVE]
    rec = load(session_id)
    if not rec or not text:
        return None
    rec["objective"] = text
    rec = save(rec)
    _sync_graph(session_id, text)
    return rec


def complete(session_id, reason=""):
    """Mark an existing goal as completed (None when there is no goal)."""
    rec = load(session_id)
    if not rec:
        return None
    rec["status"] = "completed"
    rec["stopped"] = str(reason or "goal complete")[:400]
    return save(rec)


def delete(session_id):
    """Remove the record entirely (True when a record existed)."""
    existed = os.path.isfile(path(session_id))
    try:
        os.remove(path(session_id))
    except OSError:
        return False
    return existed


def progress(session_id):
    """Steps done/open from the PLAN — computed, never copied into the record.

    Only ACTIONABLE steps count (2026-11-02, operator report): a step that was
    cancelled or superseded is not work the goal is still accountable for, so it
    must not sit in the denominator nor be reported as "open". The bar used to read
    `13/19 steps · 6 open` for a plan where 4 steps had been deliberately
    superseded — the operator read that as "13 of 19 done, 6 to go" and could not
    tell the goal was actually finished except for the struck ones.

    `steps` = done + open (the actionable set), `struck` = cancelled + superseded
    (kept for display only), `total` = every node of the current plan, and
    `unproven` = steps marked `done` that carry NO evidence. A `done` node without
    evidence is not work the harness can count (see `taskgraph.goal_complete`), so
    `open == 0 and unproven > 0` is the state that used to be reported as
    "0/N steps still open" — a contradiction the operator would read as a bug.
    """
    out = {"steps": 0, "open": 0, "done": 0, "struck": 0, "unproven": 0,
           "total": 0, "complete": False}
    try:
        from longrun.plan import taskgraph
        graph = taskgraph.load(session_id)
        if isinstance(graph, dict):
            nodes = taskgraph.plan_nodes(graph)
            out["total"] = len(nodes)
            out["done"] = sum(1 for n in nodes if n.get("status") == "done")
            out["open"] = sum(1 for n in nodes
                              if n.get("status") in taskgraph.OPEN_STATUSES)
            out["struck"] = sum(1 for n in nodes
                                if n.get("status") in ("cancelled", "superseded"))
            out["unproven"] = sum(1 for n in nodes
                                  if n.get("status") == "done"
                                  and not taskgraph._has_evidence(n))
            out["steps"] = out["done"] + out["open"]
            out["complete"] = bool(taskgraph.goal_complete(graph))
    except Exception:  # noqa: BLE001 — progress is a read-out, never a blocker
        pass
    return out


# --------------------------------------------------------------- verification --
#
# A GOAL is not the todo list. Closing every todo is the agent's CLAIM that it is
# done; the harness decides that claim INDEPENDENTLY, the way the current harness
# literature does it (VeriHarness 2026 turns the model into an agentic verifier
# with evidence tools; "harness theory" pins a contract and combines evidence from
# an authority that can OBSERVE the failure mode):
#
#   L1 acceptance  — the configured `verifier.command` really runs in the goal's
#                    workspace; its exit code is the authority (deterministic).
#   L2 artefacts   — every DONE step that cites a source path must have that path
#                    actually present in the workspace (the claim is checkable).
#   L3 judge       — optionally, a cheap model reads the OBJECTIVE and the
#                    artefacts/evidence (never the agent's reasoning) and lists
#                    what the objective asks for that it cannot find evidence of.
#
# L1+L2 run always (free). L3 is opt-in (`goal_verify.judge`). The verdict is
# stored on the record and re-computed on every read, so a completed goal whose
# plan later REOPENED can never keep claiming "done".

GOAL_VERIFY_DEFAULTS = {"judge": False, "judge_model": "", "acceptance": True}


def verify_config():
    """Effective `goal_verify` config from config/tools.yaml (plus defaults)."""
    try:
        from longrun.tools.registry import section_config
        return section_config("goal_verify", dict(GOAL_VERIFY_DEFAULTS))
    except Exception:  # noqa: BLE001 — a config hiccup must not block verification
        return dict(GOAL_VERIFY_DEFAULTS)


def _workspace_of(session_id):
    try:
        from longrun.memory import rules, stores
        sess = stores.load_session(session_id)
        return rules.resolve_workspace(sess)
    except Exception:  # noqa: BLE001
        return None


def _check_artifacts(session_id, ws):
    """L2: every source a DONE step cites must exist in the workspace.

    Returns (ok, missing[]). Paths that are absolute are checked as-is; relative
    paths are resolved against the workspace. Only `sources[].path` is judged —
    it is the part of an evidence entry that names a real artefact.
    """
    missing = []
    try:
        from longrun.plan import taskgraph
        graph = taskgraph.load(session_id) or {}
        nodes = taskgraph.plan_nodes(graph)
    except Exception:  # noqa: BLE001
        return True, missing
    for node in nodes:
        if node.get("status") != "done":
            continue
        for entry in (node.get("evidence") or []):
            if entry.get("superseded"):
                continue
            for src in (entry.get("sources") or []):
                raw = str((src or {}).get("path") or "").strip()
                if not raw:
                    continue
                cand = raw if os.path.isabs(raw) else os.path.join(ws or "", raw)
                if not os.path.exists(cand):
                    missing.append("%s cites %s (not found)" % (node.get("id"), raw))
    return (not missing), missing


def _check_acceptance(session_id, ws, cfg):
    """L1: run the configured verifier command in the goal's workspace."""
    if not cfg.get("acceptance", True) or not ws:
        return None
    try:
        from longrun.plan import verify as verify_mod
        c = verify_mod.cfg()
        cmd = str(c.get("command") or "").strip()
        if not (c.get("enabled") and cmd):
            return None
    except Exception:  # noqa: BLE001
        return None
    try:
        from longrun.tools import sandbox
        res = sandbox.run(cmd, run_id=session_id, workspace=ws,
                          timeout=int(c.get("timeout_secs") or 120))
        ok = res.get("exit_code") == 0
        return {"ok": bool(ok), "command": cmd, "exit_code": res.get("exit_code"),
                "output": (res.get("stdout") or "")[-1500:]}
    except Exception as exc:  # noqa: BLE001 — a broken check is "unknown", not "pass"
        return {"ok": None, "command": cmd, "error": str(exc)[:300]}


def _check_judge(objective, ws, missing, cfg):
    """L3: an independent model judgement over the OBJECTIVE + artefacts only."""
    try:
        import json as _json
        from longrun.core import server as srv
        from longrun.model import routing
    except Exception:  # noqa: BLE001
        return None
    # A bounded inventory: the arbiter sees WHAT EXISTS, never the agent's story.
    files = []
    try:
        for root, _dirs, names in os.walk(ws or "."):
            for n in names[:200]:
                files.append(os.path.relpath(os.path.join(root, n), ws))
            if len(files) > 200:
                break
    except Exception:  # noqa: BLE001
        pass
    prompt = (
        "You are an INDEPENDENT verifier. You do NOT see the worker's reasoning or "
        "its claims-as-text; you judge ONLY from the objective and the artefacts.\n"
        "OBJECTIVE:\n%s\n\nARTEFACTS PRESENT IN THE WORKSPACE (paths):\n%s\n\n"
        "Deterministic checks already FAILED on:\n%s\n\n"
        "Return STRICT JSON only: {\"achieved\": true|false, \"missing\": [\"...\"]}. "
        "`achieved` is true ONLY if the objective is satisfied by what is actually "
        "present; otherwise list, concretely, what the objective asks for that you "
        "cannot find evidence of. Do not be charitable."
        % (str(objective or "")[:4000],
           "\n".join(files[:200])[:6000],
           "\n".join(missing) if missing else "(none)")
    )
    try:
        model = str(cfg.get("judge_model") or "").strip()
        if not model:
            try:
                chain = routing.model_chain("subagent")
                model = chain[0] if chain else ""
            except Exception:  # noqa: BLE001
                model = ""
        msgs = [{"role": "user", "content": prompt}]
        text, _think = srv._router_stream(msgs, model or None, lambda *a: None)
    except Exception:  # noqa: BLE001 — no model → no judge, not a failure
        return None
    try:
        start, end = text.find("{"), text.rfind("}")
        got = _json.loads(text[start:end + 1]) if start >= 0 and end > start else {}
    except Exception:  # noqa: BLE001
        return {"ok": None, "raw": str(text)[:400]}
    return {"ok": bool(got.get("achieved")), "missing": got.get("missing") or []}


def verify(session_id, model=None, persist=True, judge=None):
    """INDEPENDENT verification of a goal (see the module note above).

    Returns a verdict dict and (by default) stores it on the record as
    `verification`, so the UI and the next turn see the same truth.
    """
    rec = load(session_id)
    cfg = verify_config()
    if judge is not None:
        cfg["judge"] = bool(judge)
    if model:
        cfg["judge_model"] = model
    ws = _workspace_of(session_id)
    plan = progress(session_id)
    checks, missing = [], []

    if not plan["complete"]:
        if not plan["steps"]:
            missing.append("no plan exists for this goal — nothing was executed")
        elif plan["open"]:
            missing.append("the plan is not complete: %d/%d steps still open"
                           % (plan["open"], plan["steps"]))
        elif plan.get("unproven"):
            # `open == 0` but not complete: the steps say done and cite nothing. The
            # old message read "0/N steps still open", which contradicts itself and
            # hides the real gap (no evidence, so nothing can be checked).
            missing.append("the plan is not complete: %d/%d steps are marked done but "
                           "carry no evidence" % (plan["unproven"], plan["steps"]))
        else:
            missing.append("the plan is not complete: it has no evidence-backed done step")
    art_ok, art_missing = _check_artifacts(session_id, ws)
    if art_missing:
        checks.append({"layer": "artefacts", "ok": False, "missing": art_missing[:10]})
        missing.extend(art_missing[:10])
    else:
        checks.append({"layer": "artefacts", "ok": True})
    acc = _check_acceptance(session_id, ws, cfg)
    if acc is not None:
        checks.append({"layer": "acceptance", **{k: v for k, v in acc.items() if k != "output"}})
        if acc.get("ok") is False:
            missing.append("the acceptance check failed (exit %s): %s"
                           % (acc.get("exit_code"), acc.get("command")))
        elif acc.get("ok") is None:
            missing.append("the acceptance check could not run: %s" % acc.get("error"))
    if cfg.get("judge"):
        j = _check_judge((rec or {}).get("objective"), ws, missing, cfg)
        if j is not None:
            checks.append({"layer": "judge", "ok": j.get("ok"), "missing": j.get("missing")})
            if j.get("ok") is False:
                missing.extend([str(m) for m in (j.get("missing") or [])][:10])
    verdict = {
        "verified": not missing,
        "checks": checks,
        "missing": missing,
        "workspace": ws,
        "at": round(time.time(), 3),
    }
    if persist and rec:
        rec["verification"] = verdict
        save(rec)
    return verdict


def _effective_status(rec, plan):
    """The TRUTHFUL status: a completed goal whose plan REOPENED is not done.

    Mirrors `verify`: "done" was a claim, and the plan/verification is the
    authority. Never written back here (a read must not mutate) — the caller
    decides; `status()` surfaces it so the bar cannot lie.
    """
    st = str((rec or {}).get("status") or "")
    if st == "completed" and not plan.get("complete"):
        return "reopened"
    return st


def settle(session_id):
    """Write the EFFECTIVE status back when it disagrees with the stored one.

    Called on an explicit action (a POST), never on a read: a goal stuck on
    `completed` while its plan has open steps is moved back to `active`, so the
    next pause/resume/continue acts on the real state instead of a stale claim.
    """
    rec = load(session_id)
    if not rec:
        return None
    eff = _effective_status(rec, progress(session_id))
    # "reopened" is a DISPLAY state; the persisted status is one of STATUSES, so a
    # reopened goal is written back as `active` (the real, valid state).
    target = "active" if eff == "reopened" else eff
    if target != str(rec.get("status") or ""):
        rec["status"] = target
        rec.pop("stopped", None)
        rec = save(rec)
    return rec


def _plan_changed_after(session_id, stamp):
    """Was the plan written AFTER `stamp`? (a verdict older than the plan is stale)

    Cheap and model-free: the graph file's mtime. The verdict is stored, so without
    this the panel could show a check that counted `6/19 steps open` against a plan
    that now has 4 open of 26 — numbers that are simply not about the same plan.
    """
    try:
        from longrun.plan import taskgraph
        p = taskgraph._path(session_id)
        return os.path.exists(p) and os.path.getmtime(p) > float(stamp) + 1
    except Exception:  # noqa: BLE001 — staleness is a hint, never a blocker
        return False


def status(session_id):
    """What the Active-goal bar renders: the record plus live plan progress.

    A completed goal whose plan has since REOPENED reports `reopened` (and a
    recorded verification that no longer holds reports `verified: false`), so the
    bar never shows "done" over open steps.

    A verdict OLDER than the plan is marked `stale` and says so: its counts belong to
    the plan of that moment, not to the one on screen (2026-11-02, operator report:
    "the number of steps is misleading"). Only a new `verify()` clears it.
    """
    rec = load(session_id)
    plan = progress(session_id)
    eff = _effective_status(rec, plan)
    ver = (rec or {}).get("verification") if rec else None
    # A stored "verified" is re-judged against the CURRENT plan: reopening work
    # invalidates a previous pass without needing a new model call.
    if ver and ver.get("verified") and not plan.get("complete"):
        ver = dict(ver, verified=False,
                   missing=(ver.get("missing") or [])
                   + ["the plan reopened: %d/%d steps open" % (plan["open"], plan["steps"])])
    if ver and ver.get("at") and _plan_changed_after(session_id, ver["at"]):
        ver = dict(ver, stale=True,
                   missing=(ver.get("missing") or [])
                   + ["the plan changed after this check — its counts are stale, re-verify"])
    return {"session": session_id, "goal": rec, "progress": plan,
            "effective_status": eff, "verification": ver}

