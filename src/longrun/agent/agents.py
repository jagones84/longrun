"""Agents — every Longrun session is a full-harness AGENT (id AX).

A session may be *designated* as an ORG AGENT: it then carries a name, a role and a
`reports_to` link (an org chart) and can take part in JOBS. Ad-hoc sessions stay
untouched. This registry is the single source of truth the GUI reads to badge org
agents and to guard their deletion.

Object model (see .agent/design-agents-jobs.md):
  * Agent  = a session, id ``AX``  (todos are ``AX.nY``)
  * Job    = a higher-level goal ``JN`` that orchestrates several agents (jobs.py)

Storage: one JSON file (``LONGRUN_AGENTS_FILE``, default ``data/agents.json``).
"""
import os
import threading
import time

from longrun.util import paths
from longrun.util.fswrite import read_registry, write_json
from longrun.util.paths import REPO_ROOT as REPO

_LOCK = threading.RLock()
AGENTS_FILE = os.environ.get("LONGRUN_AGENTS_FILE") or os.path.join(
    paths.DATA_DIR, "agents.json")


def _load():
    return read_registry(AGENTS_FILE, agents={}, seq=0)


def _save(d):
    write_json(AGENTS_FILE, d)


class AgentRegistry:
    """Designated org agents: create, read, tree and delete-guards."""

    def list(self):
        with _LOCK:
            d = _load()
        agents = sorted(d["agents"].values(), key=lambda a: a.get("n", 0))
        # JAG-431r4: index direct reports by manager so BOTH managers' tooltips and the
        # delete-confirmation sentence can read `reports` from THIS payload. Only
        # guards() used to compute it, so the WebUI's `ag.reports` was always undefined.
        by_mgr = {}
        for _aid, _rec in d["agents"].items():
            _m = _rec.get("reports_to")
            if _m:
                by_mgr.setdefault(_m, []).append(_aid)
        for a in agents:                       # JAG-339: expose team membership
            a["teams"] = self.teams_for(a.get("id"))
            a["reports"] = sorted(by_mgr.get(a.get("id"), []))
        return {"agents": agents, "seq": d["seq"], "count": len(agents)}

    @staticmethod
    def teams_for(aid):
        """JAG-339: the team ids an agent belongs to ([] on any failure)."""
        try:
            from longrun.orchestrate import teams as teams_mod
            return teams_mod.REGISTRY.teams_of(aid)
        except Exception:  # noqa: BLE001 — team lookup must never break the registry
            return []

    def agents_of_team(self, team_ref):
        """JAG-339: the agent records that belong to a team."""
        try:
            from longrun.orchestrate import teams as teams_mod
            ids = set(teams_mod.REGISTRY.members_of(team_ref))
        except Exception:  # noqa: BLE001
            return []
        return [a for a in self.list()["agents"] if a.get("id") in ids]

    def get(self, session_id):
        with _LOCK:
            return _load()["agents"].get(str(session_id))

    def is_agent(self, session_id):
        return self.get(session_id) is not None

    def resolve(self, ref):
        """Find an agent by session id OR by A-id; returns the record or None."""
        ref = str(ref or "")
        with _LOCK:
            d = _load()
        if ref in d["agents"]:
            return d["agents"][ref]
        for a in d["agents"].values():
            if a["id"] == ref:
                return a
        return None

    def by_id(self, aid):
        a = self.resolve(aid)
        return a if a and a.get("id") == aid else None

    @staticmethod
    def _find(d, ref):
        """Locate an agent record in a loaded store by session id or by A-id."""
        ref = str(ref or "")
        if ref in d["agents"]:
            return d["agents"][ref]
        for a in d["agents"].values():
            if a["id"] == ref:
                return a
        return None

    @staticmethod
    def _reaches(d, start, goal):
        """True when `goal` is an ancestor of `start` in the reports_to chain."""
        seen, cur = set(), start
        while cur and cur not in seen:
            if cur == goal:
                return True
            seen.add(cur)
            rec = next((x for x in d["agents"].values() if x["id"] == cur), None)
            cur = rec.get("reports_to") if rec else None
        return False

    def chain_of_command(self, ref):
        """The ordered chain from `ref` up to the root: [agent, its manager, ...].

        Empty when the agent is unknown. Terminates on a malformed cycle.
        """
        with _LOCK:
            d = _load()
        a = self._find(d, ref)
        if not a:
            return []
        chain, seen, cur = [], set(), a["id"]
        while cur and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            rec = next((x for x in d["agents"].values() if x["id"] == cur), None)
            cur = rec.get("reports_to") if rec else None
        return chain

    def team_of(self, ref):
        """The agent plus its DIRECT reports — the team a job assigned to it runs
        with. Stable, de-duplicated A-ids; [] when the agent is unknown."""
        a = self.resolve(ref)
        if not a:
            return []
        aid = a["id"]
        return [aid] + [x["id"] for x in self.list()["agents"]
                        if x.get("reports_to") == aid]

    def name_taken(self, name, exclude_sid=None):
        """True when `name` is already used by another agent OR a session title.

        The agent registry is the primary source; session titles are checked too
        (best effort) so a new agent cannot shadow an existing session by name.
        """
        nm = str(name or "").strip().lower()
        if not nm:
            return False
        ex = str(exclude_sid or "")
        with _LOCK:
            d = _load()
            for sid, a in d["agents"].items():
                if sid != ex and str(a.get("name") or "").strip().lower() == nm:
                    return True
        try:
            from longrun.core import server
            for s in server.list_sessions():
                if str(s.get("id")) != ex and str(s.get("title") or "").strip().lower() == nm:
                    return True
        except Exception:  # noqa: BLE001 — titles are a best-effort extra guard
            pass
        return False

    def charge(self, ref):
        """Consume one run from the agent's daily budget. False when exhausted.

        `daily_budget` 0/absent means unlimited; the counter resets on a new day.
        """
        with _LOCK:
            d = _load()
            a = d["agents"].get(str(ref)) or next(
                (x for x in d["agents"].values() if x["id"] == ref), None)
            if not a:
                return True
            today = time.strftime("%Y-%m-%d")
            if a.get("day") != today:
                a["day"] = today
                a["runs_today"] = 0
            try:
                limit = int(a.get("daily_budget") or 0)
            except (TypeError, ValueError):
                limit = 0
            if limit and int(a.get("runs_today") or 0) >= limit:
                _save(d)
                return False
            a["runs_today"] = int(a.get("runs_today") or 0) + 1
            _save(d)
            return True

    def designate(self, session_id, name=None, reports_to=None, role=None,
                  model=None, workspace=None, daily_budget=None):
        """Mark a session as an org agent (idempotent) and bind its metadata."""
        sid = str(session_id or "")
        if not sid:
            return {"ok": False, "error": "session required"}
        with _LOCK:
            d = _load()
            a = d["agents"].get(sid)
            if not a:
                d["seq"] += 1
                a = {"id": "A%d" % d["seq"], "n": d["seq"], "session": sid,
                     "created": round(time.time(), 3)}
                d["agents"][sid] = a
            if name:
                nm = str(name)[:80].strip()
                # JAG-294: names are unique across agents AND sessions. Reusing a
                # session's title as a new agent name is refused (the id exists).
                if nm.lower() != (a.get("name") or "").strip().lower() \
                        and self.name_taken(nm, exclude_sid=sid):
                    return {"ok": False, "error": "name already in use: %s" % nm}
                a["name"] = nm
            if role:
                a["role"] = str(role)[:80]
            if model is not None:
                # JAG-309: "" clears the choice (back to the router default);
                # None means "leave this field unchanged". An agent IS a session
                # and both must share ONE model, so a cleared choice here has to
                # be able to clear it too (server._set_session_model is the
                # single writer that keeps the two in lockstep).
                a["model"] = (str(model)[:120] or None)
            if workspace:
                a["workspace"] = str(workspace)
            if daily_budget is not None:
                try:
                    a["daily_budget"] = int(daily_budget)
                except (TypeError, ValueError):
                    pass
            if reports_to is not None:
                target = self._resolve(d, reports_to)
                # JAG-292: the org chart must stay a forest. Refuse a self-link or
                # a link that would close a cycle (A -> B -> A) so tree() and
                # getChainOfCommand can never loop.
                if target is not None and (target == a["id"] or self._reaches(d, target, a["id"])):
                    return {"ok": False, "error": "reports_to would create a cycle"}
                a["reports_to"] = target
            a.setdefault("name", a["id"])
            _save(d)
            _res = {"ok": True, "agent": dict(a)}
        # JAG-322: an agent's NAME and its session TITLE are the same identity seen
        # from two panels. Keep them in lockstep so renaming in the Orbit table
        # updates the main app immediately (the reverse is the /rename endpoint).
        if name:
            self.sync_title(sid, _res["agent"].get("name"))
        # JAG-2.8: publish so the WebUI hot-reloads the sessions rail on ANY
        # agent metadata change (reports_to, role, model, workspace, budget).
        try:
            from longrun.core import server
            server.publish("agent.updated", session=sid, agent=dict(_res["agent"]))
        except Exception:  # noqa: BLE001 — publish must never fail a designate
            pass
        return _res

    def sync_title(self, session_id, name):
        """JAG-322: mirror an agent's NAME onto its session TITLE (best effort).

        Loop-free: this only writes the session file, never the agent registry;
        it publishes `session.renamed` so the main app's session list refreshes
        live instead of staying stale until the next full load.
        """
        nm = str(name or "").strip()[:80]
        sid = str(session_id or "")
        if not sid or not nm:
            return False
        try:
            from longrun.core import server
            s = server.load_session(sid)
            if s is None or (s.get("title") or "") == nm:
                return False
            s["title"] = nm
            server.save_session(s)
            server.publish("session.renamed", session=sid, title=nm)
            return True
        except Exception:  # noqa: BLE001 — title sync must never fail a designate
            return False

    def set_name(self, session_id, name):
        """JAG-322: set an agent's NAME from the session side (session rename).

        Deliberately bypasses the uniqueness guard: a rename is explicit operator
        intent and must not be silently dropped, which would re-introduce the very
        desync this fixes. Unknown sessions are a no-op.
        """
        nm = str(name or "").strip()[:80]
        if not nm:
            return {"ok": False, "error": "name required"}
        with _LOCK:
            d = _load()
            a = self._find(d, session_id)
            if not a:
                return {"ok": False, "error": "not an agent"}
            a["name"] = nm
            _save(d)
            return {"ok": True, "agent": a}

    def set_model(self, session_id, ref):
        """JAG-343: set an agent's model AND its session's — they are ONE identity.

        Kept in lockstep with ``server._set_session_model`` so the Orbit table (the
        agent model, used by jobs) and the composer (the session model, used by chat)
        can never disagree. An empty ref clears the choice (router default).
        """
        sid = str(session_id or "")
        with _LOCK:
            d = _load()
            a = self._find(d, sid)
            if not a:
                return {"ok": False, "error": "not an agent"}
            a["model"] = (str(ref)[:120] or None)
            _save(d)
        try:
            from longrun.core import server as srv
            srv._set_session_model(sid, ref or "")
        except Exception:  # noqa: BLE001 — the sync must never fail the call
            pass
        return {"ok": True, "agent": a}

    @staticmethod
    def _resolve(d, ref):
        ref = str(ref or "").strip()
        if not ref:
            return None
        if ref in d["agents"]:
            return d["agents"][ref]["id"]
        for a in d["agents"].values():
            if a["id"] == ref:
                return ref
        return None

    def release(self, session_id):
        """Un-designate. Any direct reports are re-parented to nobody.

        JAG-314: also scrub the agent from jobs (members/coordinator) and delete
        its routines, so neither is left pointing at an agent that no longer
        exists. The session itself is untouched (that is session delete's job).
        """
        with _LOCK:
            d = _load()
            a = d["agents"].pop(str(session_id), None)
            if a:
                for other in d["agents"].values():
                    if other.get("reports_to") == a["id"]:
                        other["reports_to"] = None
                _save(d)
        released = a["id"] if a else None
        if released:
            try:
                from longrun.orchestrate import teams as teams_mod
                teams_mod.REGISTRY.drop_agent(released)   # JAG-339: leave its teams
            except Exception:  # noqa: BLE001
                pass
            try:
                from longrun.orchestrate import jobs as jobs_mod
                jobs_mod.JOBS.scrub_agent(released)
            except Exception:  # noqa: BLE001
                pass
            try:
                from longrun.orchestrate import routines as routines_mod
                routines_mod.REGISTRY.delete_for_agent(released)
            except Exception:  # noqa: BLE001
                pass
        # JAG-2.8: publish so the WebUI hot-reloads the sessions rail
        try:
            from longrun.core import server
            server.publish("agent.released", session=session_id, agent=released)
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "released": released}

    def tree(self):
        with _LOCK:
            d = _load()
        agents = sorted(d["agents"].values(), key=lambda a: a.get("n", 0))
        for a in agents:                       # JAG-339: teams travel with the tree
            a["teams"] = self.teams_for(a.get("id"))
        by_id = {a["id"]: a for a in agents}
        roots = []
        for a in agents:
            a["children"] = [c["id"] for c in agents if c.get("reports_to") == a["id"]]
            a["manager"] = a.get("reports_to") if a.get("reports_to") in by_id else None
            if not a.get("reports_to"):
                roots.append(a["id"])
        return {"agents": agents, "roots": roots}

    def guards(self, session_id):
        """Whether deleting this session is risky (used by the main GUI)."""
        a = self.get(session_id)
        if not a:
            return {"is_agent": False, "blocked": False}
        reports = [x["id"] for x in self.list()["agents"]
                   if x.get("reports_to") == a["id"]]
        try:
            from longrun.orchestrate import jobs as jobs_mod
            member = [j["id"] for j in jobs_mod.JOBS.list()["jobs"]
                      if a["id"] in (j.get("agents") or [])]
        except Exception:  # noqa: BLE001
            member = []
        return {"is_agent": True, "agent": a["id"], "name": a.get("name"),
                "reports": reports, "jobs": member, "blocked": bool(reports)}


REGISTRY = AgentRegistry()

