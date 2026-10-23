"""HTTP surface for the Agents & Jobs model (JAG-287).

Routed from `api_v02.handle` (one delegation line), so it adds no new hook to the
server. Routes:
  GET    /api/agents            list designated agents
  GET    /api/agents/tree       the org chart (reports_to)
  GET    /api/agents/<sid>/chain  chain of command (agent -> manager -> root)
  GET    /api/agents/<sid>      delete-guards for a session
  POST   /api/agents            designate a session as an agent
  DELETE /api/agents/<sid>      un-designate (release) — blocked if it has reports
  GET    /api/jobs              list jobs (JN)
  GET    /api/jobs/<id>         one job
  POST   /api/jobs              create a job (optional blocked_by: [JN])
  POST   /api/jobs/<id>/dispatch  run it (coordinator + workers, dependency waves)
  POST   /api/jobs/wake         release blocked jobs whose blockers are done
  DELETE /api/jobs/<id>         remove a job (refused while running)
  GET    /api/roles?session=    the session's ROLE.md (any session)
  POST   /api/roles             set {session, text} (empty text clears it)
  DELETE /api/roles?session=    remove the session's ROLE.md
  POST   /api/teams/<tid>/reset    team bulk: reset every member session (chat+tasks)
  POST   /api/teams/<tid>/compact  team bulk: compact every member session
"""
from longrun.agent import agents as agents_mod
from longrun.orchestrate import teams as teams_mod
from longrun.util.dataio import json_body as _body


def _json(handler, code, obj):
    handler._send(code, obj)
    return True


def _is(path, base):
    return path == base or path.startswith(base + "/")


def _aid_of(reg, ref):
    """Resolve a member reference (``A3`` or a session id) to an agent id."""
    ref = str(ref or "").strip()
    if not ref:
        return None
    if ref[:1].upper() == "A" and ref[1:].isdigit():
        return ref.upper()
    a = reg.resolve(ref)
    return a["id"] if a else None


def member_aid(reg, ref):
    """Resolve a TEAM-MEMBER reference to an agent id; designate a plain session.

    JAG-2.4: Control ▸ AGENTS lists EVERY session (the same roster as the Sessions
    page), so a membership request may name a chat that was never designated. Rather
    than dead-ending with "agent or session required", designate it on the spot (its
    session title becomes the agent name when that name is free) and use the new id.

    Returns ``(aid, error)`` — exactly one of them is None.
    """
    aid = _aid_of(reg, ref)
    if aid:
        return aid, None
    sid = str(ref or "").strip()
    if not sid:
        return None, "agent or session required"
    try:
        from longrun.core import server as _srv
        sess = _srv.load_session(sid) or {}
    except Exception:  # noqa: BLE001 — a session lookup must never 500 the route
        sess = {}
    if not sess:
        return None, "unknown session: %s" % sid
    made = reg.designate(sid, name=str(sess.get("title") or "").strip()[:80] or None)
    if not made.get("ok"):
        made = reg.designate(sid)   # a title collision must not block the assignment
    aid = (made.get("agent") or {}).get("id")
    if not aid:
        return None, made.get("error") or "could not designate the session"
    return aid, None


def _member_row(reg, aid):
    a = reg.by_id(aid) or {}
    return {"id": aid, "name": a.get("name") or aid, "session": a.get("session"),
            "role": a.get("role"), "reports_to": a.get("reports_to")}


def _team_payload(t, reg):
    """A team plus its members resolved to agent rows (JAG-339)."""
    out = dict(t)
    out["members"] = list(t.get("members") or [])
    out["member_rows"] = [_member_row(reg, m) for m in out["members"]]
    return out


def _team_bulk(tid, action, reg):
    """JAG-482: apply ONE action to EVERY session (= agent) of a team.

    `reset`   -> ``stores.clear_session``: wipe the transcript, the tool cards,
                 the harness injects and the task graph. The session, its agent
                 and its ROLE.md stay — nothing is deleted.
    `compact` -> ``httpapi.compact_session`` (the MANUAL policy, identical to the
                 single-session "compact now" action): summarise the old half of
                 the transcript so the context actually shrinks.

    The sessions are ACTUAL backend sessions; one session failing never aborts
    the batch, it is reported per session in ``results``.
    """
    if not teams_mod.REGISTRY.get(tid):
        return {"ok": False, "error": "team not found"}
    sids, seen = [], set()
    for a in reg.agents_of_team(tid):
        sid = a.get("session")
        if sid and sid not in seen:
            seen.add(sid)
            sids.append(sid)
    from longrun.core import httpapi as httpapi_mod
    from longrun.memory import stores as stores_mod
    results = []
    for sid in sids:
        try:
            if action == "compact":
                results.append({"session": sid,
                                "result": httpapi_mod.compact_session(sid, origin="manual")})
            else:
                stores_mod.clear_session(sid)
                results.append({"session": sid, "ok": True})
        except Exception as exc:  # noqa: BLE001 — one bad session must not abort the team
            results.append({"session": sid, "error": str(exc)})
    return {"ok": True, "team": tid, "action": action,
            "sessions": sids, "count": len(sids), "results": results}


def _teams(handler, method, path, qs, body, reg):
    """JAG-339: the /api/teams surface (CRUD + multi-team membership)."""
    R = teams_mod.REGISTRY
    if method == "GET":
        if path == "/api/teams":
            d = R.list()
            d["teams"] = [_team_payload(t, reg) for t in d["teams"]]
            return _json(handler, 200, d)
        t = R.get(path[len("/api/teams/"):].split("/")[0])
        if not t:
            return _json(handler, 404, {"error": "team not found"})
        payload = _team_payload(t, reg)
        payload["agents"] = reg.agents_of_team(t["id"])
        return _json(handler, 200, payload)
    if method == "POST":
        data = _body(body)
        if path == "/api/teams":
            return _json(handler, 200, R.create(
                data.get("name"), symbol=data.get("symbol"), color=data.get("color"),
                description=data.get("description")))
        parts = path[len("/api/teams/"):].split("/")
        tid = parts[0]
        if len(parts) >= 2 and parts[1] == "members":
            # JAG-2.4: a plain session is designated on the spot (see member_aid).
            aid, err = member_aid(reg, data.get("agent") or data.get("session"))
            if err:
                return _json(handler, 400, {"ok": False, "error": err})
            if str(data.get("action") or "add").lower() == "remove":
                return _json(handler, 200, R.remove_member(tid, aid))
            return _json(handler, 200, R.add_member(tid, aid))
        if len(parts) >= 2 and parts[1] == "models":   # JAG-343: apply the model policy
            return _json(handler, 200, R.assign_models(
                tid, lead_model=data.get("lead_model"),
                member_model=data.get("member_model"),
                local_slots_n=data.get("local_slots")))
        if len(parts) >= 2 and parts[1] in ("reset", "compact"):
            # JAG-482: TEAM-WIDE bulk action over the team's member sessions.
            # "reset" wipes each session (chat + tasks), "compact" shrinks each
            # transcript — NEVER deletes a session or its agent.
            res = _team_bulk(tid, parts[1], reg)
            return _json(handler, 404 if res.get("error") else 200, res)
        return _json(handler, 200, R.update(
            tid, name=data.get("name"), symbol=data.get("symbol"),
            color=data.get("color"), description=data.get("description")))
    if method == "DELETE":
        return _json(handler, 200, R.delete(path[len("/api/teams/"):].split("/")[0]))
    return _json(handler, 404, {"error": "unknown teams route"})


def handle(handler, method, path, qs, body):
    if not (_is(path, "/api/agents") or _is(path, "/api/jobs") or _is(path, "/api/routines")
            or _is(path, "/api/roles") or _is(path, "/api/teams")):
        return False
    reg = agents_mod.REGISTRY
    if _is(path, "/api/teams"):   # JAG-339: teams (a group of agents)
        return _teams(handler, method, path, qs, body, reg)
    if _is(path, "/api/routines"):   # JAG-287 D: scheduled heartbeats
        from longrun.orchestrate import routines as routines_mod
        rr = routines_mod.REGISTRY
        if method == "GET":
            if path == "/api/routines":
                return _json(handler, 200, rr.list())
            r = rr.get(path[len("/api/routines/"):].split("/")[0])
            return _json(handler, 200, r) if r else _json(handler, 404, {"error": "routine not found"})
        if method == "POST":
            if path == "/api/routines/tick":
                return _json(handler, 200, {"fired": rr.tick()})
            if path.endswith("/enable") or path.endswith("/disable"):
                rid = path[len("/api/routines/"):].split("/")[0]
                return _json(handler, 200, rr.set_enabled(rid, path.endswith("/enable")))
            if path.startswith("/api/routines/"):   # JAG-536: edit in place
                rid = path[len("/api/routines/"):].split("/")[0]
                data = _body(body)
                return _json(handler, 200, rr.update(
                    rid, agent=data.get("agent"), goal=data.get("goal"),
                    every_seconds=data.get("every_seconds"), enabled=data.get("enabled"),
                    model=data.get("model")))
            data = _body(body)
            return _json(handler, 200, rr.create(
                data.get("agent"), data.get("goal"), data.get("every_seconds"),
                enabled=data.get("enabled", True), model=data.get("model")))
        if method == "DELETE":
            return _json(handler, 200, rr.delete(path[len("/api/routines/"):].split("/")[0]))
        return _json(handler, 404, {"error": "unknown routines route"})
    if _is(path, "/api/roles"):   # JAG-294: per-session ROLE.md (any session)
        from longrun.orchestrate import roles as roles_mod
        if method == "GET":
            sid = qs.get("session")
            if not sid:
                return _json(handler, 400, {"error": "session required"})
            return _json(handler, 200, {"session": sid, "path": roles_mod.path_for(sid),
                                        "text": roles_mod.read(sid)})
        if method == "POST":
            data = _body(body)
            return _json(handler, 200, roles_mod.write(data.get("session"), data.get("text")))
        if method == "DELETE":
            return _json(handler, 200, roles_mod.delete(qs.get("session")))
        return _json(handler, 404, {"error": "unknown roles route"})
    if method == "GET":
        if path == "/api/agents":
            return _json(handler, 200, reg.list())
        if path == "/api/agents/tree":
            return _json(handler, 200, reg.tree())
        if path.startswith("/api/agents/") and path.endswith("/chain"):
            sid = path[len("/api/agents/"):-len("/chain")]
            return _json(handler, 200, {"agent": sid, "chain": reg.chain_of_command(sid)})
        if path.startswith("/api/agents/"):
            return _json(handler, 200, reg.guards(path[len("/api/agents/"):]))
        from longrun.orchestrate import jobs as jobs_mod
        if path == "/api/jobs":
            return _json(handler, 200, jobs_mod.JOBS.list())
        if path.startswith("/api/jobs/"):
            jid = path[len("/api/jobs/"):].split("/")[0]
            job = jobs_mod.JOBS.detail(jid)   # JAG-324: subjobs + their todos
            return _json(handler, 200, job) if job else _json(handler, 404, {"error": "job not found"})
    if method == "POST":
        data = _body(body)
        if path == "/api/agents":
            sid = data.get("session")
            # JAG-343: at most ONE local model per machine within a team. Refuse a
            # second local assignment (a team-wide action, `POST /api/teams/<id>/models`,
            # is the sanctioned way to set many at once).
            model_in = data.get("model")
            if model_in:
                aid_in = _aid_of(reg, sid)
                if aid_in:
                    clash = teams_mod.REGISTRY.local_conflict(aid_in, model_in)
                    if clash:
                        return _json(handler, 200, {
                            "ok": False,
                            "error": "team %s already uses a local model on %s (%s)"
                                     % (clash["team"], clash["machine"], clash["other_name"]),
                            "conflict": clash})
            res = reg.designate(
                sid, name=data.get("name"), reports_to=data.get("reports_to"),
                role=data.get("role"), model=data.get("model"),
                workspace=data.get("workspace"), daily_budget=data.get("daily_budget"))
            # JAG-309: an agent IS a session — keep its model identical to the
            # session's so the Orbit table (agent model, used by jobs) and the
            # composer (session model, used by chat) can never disagree. A chosen
            # model (even "" to clear) is pushed to the session; with no choice,
            # the agent inherits whatever the session already uses.
            if res.get("ok"):
                try:
                    from longrun.core import server as srv
                    if "model" in data:
                        srv._set_session_model(sid, data.get("model") or "")
                    else:
                        sess = srv.load_session(str(sid or ""))
                        if sess and sess.get("model"):
                            srv._set_session_model(sid, sess["model"])
                except Exception:  # noqa: BLE001 — model sync must never fail the call
                    pass
                # JAG-339: optional team membership at designate time.
                if isinstance(data.get("teams"), list):
                    aid = (res.get("agent") or {}).get("id")
                    for t in data["teams"] or []:
                        teams_mod.REGISTRY.add_member(t, aid)
            return _json(handler, 200, res)
        from longrun.orchestrate import jobs as jobs_mod
        if path == "/api/jobs":
            assignee, agents, coordinator = (data.get("assignee"), data.get("agents"),
                                             data.get("coordinator"))
            if assignee and not agents:
                # JAG-293: a job is "goal + who you give it to"; the team is the
                # assignee plus its direct reports in the org chart.
                agents = reg.team_of(assignee)
                coordinator = coordinator or assignee
            return _json(handler, 200, jobs_mod.JOBS.create(
                data.get("goal"), coordinator=coordinator,
                agents=agents, deps=data.get("deps"),
                mode=data.get("mode") or "coordinator",
                blocked_by=data.get("blocked_by")))
        if path == "/api/jobs/wake":   # JAG-292: sweep blocked jobs on demand
            return _json(handler, 200, jobs_mod.JOBS.wake())
        if path.startswith("/api/jobs/") and path.endswith("/dispatch"):
            jid = path[len("/api/jobs/"):-len("/dispatch")]
            return _json(handler, 200, jobs_mod.JOBS.dispatch(jid))
    if method == "DELETE" and path.startswith("/api/jobs/"):
        from longrun.orchestrate import jobs as jobs_mod
        jid = path[len("/api/jobs/"):].split("/")[0]
        return _json(handler, 200, jobs_mod.JOBS.delete(jid))
    if method == "DELETE" and path.startswith("/api/agents/"):
        sid = path[len("/api/agents/"):]
        g = reg.guards(sid)
        if g.get("blocked"):
            return _json(handler, 409, {"ok": False, "error": "agent has reports", "guards": g})
        return _json(handler, 200, reg.release(sid))
    return _json(handler, 404, {"error": "unknown agents/jobs route"})

