"""HTTP surface of the Orbit beta.

Reached only through the server's two guarded hooks. `serve_page` answers the
public shell (like `/console`); `handle` answers the auth-gated `/api/orbit/*`
routes. Every route is additive: the beta never shadows an existing app route.
"""
import os

from longrun.util.dataio import json_body as _body

from .attention import AttentionFeed
from .bay import ModelBay
from .decisions import DecisionQueue
from .orchestrator import Orchestrator
from .registry import SessionRegistry

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")

_BAY = ModelBay()
_REGISTRY = SessionRegistry()
_ORCH = Orchestrator()
_ATTN = AttentionFeed(_REGISTRY, lambda: _ORCH.jobs().get("jobs", []))


def dispatch_message(session: str, message: str, model: str | None = None) -> dict:
    """Start a chat turn through the shared Orbit orchestrator/job registry."""
    return _ORCH.dispatch([session], message, model=model, mode="chat")


def _retry_run(ref):
    """Re-dispatch a failed background run, addressed by its job key."""
    for j in _ORCH.jobs().get("jobs", []):
        if str(j.get("job")) == str(ref):
            return _ORCH.dispatch([j.get("session")], j.get("goal"),
                                  model=j.get("model"), mode=j.get("mode"))
    return {"ok": False, "error": "run not found"}


_QUEUE = DecisionQueue(_ATTN, _retry_run)

_PAGE_PATHS = ("/orbit", "/orbit/", "/orbit.html")


def _json(handler, code, obj):
    handler._send(code, obj)
    return True


def _ok(handler, res):
    """200 on success; an engine `{"ok": false, "error": ...}` becomes a 400.

    JAG-295-fix: the POST routes always answered 200, so a rejected dispatch or
    decision looked like success to any client/proxy keying on the status code.
    """
    code = 400 if (isinstance(res, dict) and res.get("ok") is False) else 200
    return _json(handler, code, res)


def _subjobs_of(agents_list, jobs_list, graphs):
    """JAG-324: every job's subjobs, enriched with the todos they embody.

    Object model the constellation draws: Job (JN) -> Subjob (JN.j, one per agent,
    with deps among subjobs) -> the subset of that agent's todos tagged `subjob`.
    """
    from longrun.orchestrate.jobs import latest_plan_nodes
    out = []
    by_id = {a.get("id"): a for a in agents_list}
    for j in jobs_list:
        for s in (j.get("subjobs") or {}).values():
            asid = (by_id.get(s.get("agent")) or {}).get("session")
            nodes = (graphs.get(asid) or {}).get("nodes", []) if asid else []
            # JAG-327: only the LATEST plan this subjob appeared in (a re-run reuses the
            # subjob id); the constellation then matches the run-scoped todo store.
            mine = latest_plan_nodes([n for n in nodes if n.get("subjob") == s.get("id")])
            out.append({
                "id": s.get("id"), "parent": j.get("id"), "agent": s.get("agent"),
                "deps": s.get("deps") or [], "status": s.get("status"),
                "assignment": s.get("assignment"),
                "todos": [n.get("id") for n in mine],
            })
    return out


def _constellation(team=None):
    """JAG-296: aggregate agents + jobs + every agent's task graph for the Orbit UI.

    One read-only call so the constellation window needs no N+2 round-trips. Jobs are
    objects (blocked_by edges); agents are 1:1 with sessions (reports_to edges); tasks
    live inside an agent's session graph (deps edges). JAG-324 adds the SUBJOB level
    between a job and the todos (subjob -> agent, subjob -> subjob deps, subjob ->
    todos). JAG-339 adds the TEAM level: a `team` query scopes agents + jobs to that
    team, and the payload always lists every team. Returns engines-safe plain data.
    """
    from longrun.agent import agents as _agents
    from longrun.orchestrate import jobs as _jobs
    from longrun.plan import taskgraph as _tg
    from longrun.orchestrate import teams as _teams
    ags = _agents.REGISTRY.list().get("agents", [])
    jbs = _jobs.JOBS.list().get("jobs", [])
    tms = _teams.REGISTRY.list().get("teams", [])
    if team and team != "ALL":
        # JAG-513: `__none__` is the "No team" bucket — the stray agents the AGENTS
        # table already groups separately. It is a real scope, not a team id.
        if team == "__none__":
            ags = [a for a in ags if not (a.get("teams") or [])]
        else:
            member_ids = set(_teams.REGISTRY.members_of(team))
            ags = [a for a in ags if a.get("id") in member_ids]
        keep = {a.get("id") for a in ags}
        jbs = [j for j in jbs if keep & set(j.get("agents") or [])]
    graphs = {}
    for a in ags:
        sid = a.get("session")
        if not sid:
            continue
        g = _tg.load(sid) or {}
        graphs[sid] = {"nodes": g.get("nodes", []), "run_id": g.get("run_id")}
    out_payload = {
        "team": team or "ALL",
        "teams": [{"id": t.get("id"), "name": t.get("name"), "symbol": t.get("symbol"),
                   "color": t.get("color"), "count": len(t.get("members") or [])}
                  for t in tms],
        "agents": [{"id": a.get("id"), "session": a.get("session"), "name": a.get("name"),
                    "role": a.get("role"), "reports_to": a.get("reports_to"),
                    "model": a.get("model"), "teams": a.get("teams") or []} for a in ags],
        "jobs": [{"id": j.get("id"), "status": j.get("status"),
                  "coordinator": j.get("coordinator"), "agents": j.get("agents") or [],
                  "blocked_by": j.get("blocked_by") or [], "goal": j.get("goal")}
                 for j in jbs],
        "subjobs": _subjobs_of(ags, jbs, graphs),
        "graphs": graphs,
    }
    try:
        from longrun.core import matrix as _mtx
        aug = _mtx.call_hook("orbit", "augment_orbit", out_payload, default=out_payload)
        if isinstance(aug, dict):
            return aug
    except Exception:  # noqa: BLE001
        pass
    return out_payload


def serve_page(handler, path):
    """Serve the Orbit shell (public). Return True when this module answered."""
    if path not in _PAGE_PATHS:
        return False
    try:
        with open(os.path.join(WEB, "orbit.html"), "r", encoding="utf-8") as fh:
            html = fh.read()
    except OSError:
        html = ("<!doctype html><meta charset=utf-8><title>Control</title>"
                "<h1>Control beta</h1><p>The UI file <code>web/orbit.html</code> "
                "is missing from the beta package.</p>")
    handler._send(200, html, ctype="text/html; charset=utf-8")
    return True


def handle(handler, method, path, qs, body):
    """Answer the Orbit API. Return True when this module answered."""
    if not path.startswith("/api/orbit"):
        return False
    if method == "GET":
        if path == "/api/orbit/models":
            return _json(handler, 200, _BAY.snapshot(force=qs.get("force") == "1"))
        if path == "/api/orbit/sessions":
            return _json(handler, 200, _REGISTRY.list())
        if path == "/api/orbit/jobs":
            return _json(handler, 200, _ORCH.jobs())
        if path == "/api/orbit/constellation":
            return _json(handler, 200, _constellation(qs.get("team")))
        if path == "/api/orbit/attention":
            sessions = _REGISTRY.list().get("sessions", [])
            snap = _ATTN.snapshot(sessions)
            snap["board"] = AttentionFeed.board(sessions, snap["items"])
            return _json(handler, 200, snap)
        if path == "/api/orbit/decisions":
            return _json(handler, 200, _QUEUE.queue())
        return _json(handler, 404, {"error": "unknown orbit route"})
    if method == "POST":
        data = _body(body)
        if path == "/api/orbit/sessions":
            return _ok(handler, _REGISTRY.create(
                title=data.get("title"), model=data.get("model"),
                workspace=data.get("workspace")))
        if path == "/api/orbit/dispatch":
            targets = data.get("targets")
            if not targets and data.get("session"):
                targets = [data["session"]]
            return _ok(handler, _ORCH.dispatch(
                targets, data.get("goal"), model=data.get("model"),
                mode=data.get("mode") or "goal"))
        if path == "/api/orbit/decisions":
            return _ok(handler, _QUEUE.resolve(
                data.get("id"), data.get("action"), by=data.get("by") or "orbit"))
        return _json(handler, 404, {"error": "unknown orbit route"})
    return _json(handler, 405, {"error": "method not allowed"})
