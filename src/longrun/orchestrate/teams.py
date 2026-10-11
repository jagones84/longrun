"""Teams — a named group of agents (id ``TN``: T1, T2, …).

The object model gains one level above Agent:

    Team  TN   a named group with a symbol, a colour and an organigram
    Job   JN   a goal that orchestrates several agents
    Agent AX   a session; it may belong to SEVERAL teams (agent.teams = [TN, ...])
    Todo  AX.nY a plan step (graph node nY)

A team OWNS its membership: ``team["members"]`` is the single source of truth (a
list of agent ids like ``A3``). ``agents.py`` only READS it, so the two stores can
never drift. An agent in no team is an ad-hoc session.

Storage: one JSON file (``LONGRUN_TEAMS_FILE``, default ``data/teams.json``).
"""
import json
import os
import threading
import time

from longrun.util.fswrite import write_json
from longrun.util.paths import REPO_ROOT as REPO

_LOCK = threading.RLock()
TEAMS_FILE = os.environ.get("LONGRUN_TEAMS_FILE") or os.path.join(REPO, "data", "teams.json")

# A small, deterministic palette so a team always has a usable symbol + colour.
_PALETTE = [
    ("\U0001f680", "#3B82F6"),   # 🚀 blue
    ("\U0001f4e3", "#F97316"),   # 📣 orange
    ("\U0001f6a8", "#EF4444"),   # 🚨 red
    ("\U0001f9ea", "#F59E0B"),   # 🧪 amber
    ("\U0001f9e0", "#8B5CF6"),   # 🧠 violet
    ("\U0001f4b0", "#22C55E"),   # 💰 green
    ("\U0001f5fa\ufe0f", "#14B8A6"),  # 🗺️ teal
    ("\U0001f3ae", "#A855F7"),   # 🎮 purple
]


# JAG-343: model policy. A team may use at most `LOCAL_SLOTS` LOCAL model per machine
# (dgx / win / any provider with `local: true`); everyone else runs a cheap cloud model,
# and the LEADS / coordinator get the strongest cheap cloud. All three are overridable.
LEAD_MODEL = os.environ.get("LONGRUN_TEAM_LEAD_MODEL", "openrouter:z-ai/glm-5.3-flash")
MEMBER_MODEL = os.environ.get("LONGRUN_TEAM_MEMBER_MODEL",
                              "openrouter:deepseek/deepseek-v4-flash-0731")


def local_slots():
    try:
        return max(0, int(os.environ.get("LONGRUN_TEAM_LOCAL_SLOTS", "1")))
    except (TypeError, ValueError):
        return 1


def _providers():
    from longrun.model import providers
    return providers


def machine_of(ref):
    """The LOCAL machine a model ref runs on (``dgx``/``win``/…), or None for cloud.

    A `<provider>:<model>` ref is local when that provider has ``local: true``; a bare
    id / None resolves local-first, so it counts as the DEFAULT local machine (the
    agents in a seeded team carry no model and would otherwise all hit one GPU).
    """
    if not ref:
        return _default_machine()
    s = str(ref)
    if ":" in s:
        pid = s.split(":", 1)[0]
        try:
            p = _providers().get(pid)
        except Exception:  # noqa: BLE001 — a catalogue failure must not break the policy
            p = None
        return pid if (p and p.get("local")) else None
    return _default_machine()


def _default_machine():
    try:
        ref = _providers().default_ref()
        if ref and ":" in ref:
            pid = ref.split(":", 1)[0]
            p = _providers().get(pid)
            if p and p.get("local"):
                return pid
    except Exception:  # noqa: BLE001
        pass
    return "dgx"


def _load():
    try:
        with open(TEAMS_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:  # noqa: BLE001 - a missing/corrupt file is just an empty registry
        d = {}
    d.setdefault("teams", {})
    d.setdefault("seq", 0)
    return d


def _save(d):
    write_json(TEAMS_FILE, d)


class TeamRegistry:
    """Create, read, update and delete teams; own the membership."""

    def list(self):
        with _LOCK:
            d = _load()
        teams = sorted(d["teams"].values(), key=lambda t: t.get("n", 0))
        for t in teams:
            t.setdefault("members", [])
        return {"teams": teams, "seq": d["seq"], "count": len(teams)}

    def get(self, ref):
        """Find a team by id (``T1``) or by name (case-insensitive)."""
        ref = str(ref or "")
        with _LOCK:
            d = _load()
        return self._find(d, ref)

    @staticmethod
    def _find(d, ref):
        ref = str(ref or "")
        if ref in d["teams"]:
            return d["teams"][ref]
        low = ref.strip().lower()
        if low:
            for t in d["teams"].values():
                if str(t.get("name") or "").strip().lower() == low:
                    return t
        return None

    def create(self, name, symbol=None, color=None, description=None):
        """Create a team. The id is the next ``TN``; the symbol/colour default
        from a fixed palette so every team is visibly distinct."""
        nm = str(name or "").strip()[:80]
        if not nm:
            return {"ok": False, "error": "name required"}
        with _LOCK:
            d = _load()
            if any(str(t.get("name") or "").strip().lower() == nm.lower()
                   for t in d["teams"].values()):
                return {"ok": False, "error": "team name already in use: %s" % nm}
            d["seq"] += 1
            n = d["seq"]
            sym, col = _PALETTE[(n - 1) % len(_PALETTE)]
            t = {"id": "T%d" % n, "n": n, "name": nm,
                 "symbol": str(symbol or sym)[:8], "color": str(color or col)[:16],
                 "description": str(description or "")[:400],
                 "members": [], "created": round(time.time(), 3)}
            d["teams"][t["id"]] = t
            _save(d)
            return {"ok": True, "team": dict(t)}

    def update(self, ref, name=None, symbol=None, color=None, description=None):
        with _LOCK:
            d = _load()
            t = self._find(d, ref)
            if not t:
                return {"ok": False, "error": "team not found"}
            if name:
                nm = str(name)[:80].strip()
                if nm.lower() != str(t.get("name") or "").strip().lower() and any(
                        str(x.get("name") or "").strip().lower() == nm.lower()
                        for x in d["teams"].values() if x["id"] != t["id"]):
                    return {"ok": False, "error": "team name already in use: %s" % nm}
                t["name"] = nm
            if symbol is not None:
                t["symbol"] = str(symbol)[:8]
            if color is not None:
                t["color"] = str(color)[:16]
            if description is not None:
                t["description"] = str(description)[:400]
            _save(d)
            return {"ok": True, "team": dict(t)}

    def delete(self, ref):
        """Remove a team. Members are untouched — only the link disappears."""
        with _LOCK:
            d = _load()
            t = self._find(d, ref)
            if not t:
                return {"ok": False, "error": "team not found"}
            d["teams"].pop(t["id"], None)
            _save(d)
            return {"ok": True, "deleted": t["id"]}

    def add_member(self, ref, aid):
        """Add an agent id (``A3``) to a team (idempotent)."""
        aid = str(aid or "").strip()
        if not aid:
            return {"ok": False, "error": "agent id required"}
        with _LOCK:
            d = _load()
            t = self._find(d, ref)
            if not t:
                return {"ok": False, "error": "team not found"}
            t.setdefault("members", [])
            if aid not in t["members"]:
                t["members"].append(aid)
            _save(d)
            return {"ok": True, "team": dict(t)}

    def remove_member(self, ref, aid):
        aid = str(aid or "").strip()
        with _LOCK:
            d = _load()
            t = self._find(d, ref)
            if not t:
                return {"ok": False, "error": "team not found"}
            t["members"] = [m for m in t.get("members", []) if m != aid]
            _save(d)
            return {"ok": True, "team": dict(t)}

    def set_members(self, ref, aids):
        """Replace the whole membership (list of agent ids)."""
        with _LOCK:
            d = _load()
            t = self._find(d, ref)
            if not t:
                return {"ok": False, "error": "team not found"}
            seen, out = set(), []
            for a in (aids or []):
                a = str(a or "").strip()
                if a and a not in seen:
                    seen.add(a)
                    out.append(a)
            t["members"] = out
            _save(d)
            return {"ok": True, "team": dict(t)}

    def members_of(self, ref):
        t = self.get(ref)
        return list(t.get("members") or []) if t else []

    def teams_of(self, aid):
        """Every team id that contains this agent id (an agent may be in several)."""
        aid = str(aid or "").strip()
        if not aid:
            return []
        with _LOCK:
            d = _load()
        return [t["id"] for t in sorted(d["teams"].values(), key=lambda x: x.get("n", 0))
                if aid in (t.get("members") or [])]

    def local_conflict(self, aid, model):
        """JAG-343: the other agent that ALREADY holds a local model on the same
        machine within a team this agent belongs to, or None when the cap allows it.

        Used as a guard whenever an agent's model is set to a local one.
        """
        m = machine_of(model)
        if not m:
            return None
        from longrun.agent import agents as agents_mod
        recs = {a["id"]: a for a in agents_mod.REGISTRY.list()["agents"]}
        for tid in self.teams_of(aid):
            t = self.get(tid)
            for other in (t.get("members") or []):
                if other == aid:
                    continue
                o = recs.get(other)
                if o and machine_of(o.get("model")) == m:
                    return {"team": tid, "machine": m, "other": other,
                            "other_name": o.get("name") or other}
        return None

    def assign_models(self, ref, lead_model=None, member_model=None, local_slots_n=None):
        """JAG-343: apply the team model policy.

        - LEADS (an agent someone in the team reports to, or a team root) get the
          strongest cheap CLOUD model — never a local one;
        - at most `local_slots` LOCAL model per machine is kept among the NON-leads
          (the rest are moved to the cheap cloud model);
        - everyone else gets the cheap cloud model.
        """
        t = self.get(ref)
        if not t:
            return {"ok": False, "error": "team not found"}
        from longrun.agent import agents as agents_mod
        reg = agents_mod.REGISTRY
        recs = {a["id"]: a for a in reg.list()["agents"]}
        members = [recs[m] for m in (t.get("members") or []) if m in recs]
        if not members:
            return {"ok": True, "team": t["id"], "assigned": 0, "leads": [], "local_kept": []}
        lead_model = lead_model or LEAD_MODEL
        member_model = member_model or MEMBER_MODEL
        slots = local_slots() if local_slots_n is None else max(0, int(local_slots_n))
        leads = sorted({a["id"] for a in members
                        if (not a.get("reports_to"))
                        or any(x.get("reports_to") == a["id"] for x in members)})
        assigned, local_kept, used = 0, [], {}
        for a in sorted(members, key=lambda x: x.get("n", 0)):
            keep_local = False
            if a["id"] not in leads:
                m = machine_of(a.get("model"))
                if m and used.get(m, 0) < slots:
                    used[m] = used.get(m, 0) + 1
                    keep_local = True
            if keep_local:
                if a["id"] not in local_kept:
                    local_kept.append(a["id"])
                continue
            target = lead_model if a["id"] in leads else member_model
            if a.get("session"):
                reg.set_model(a["session"], target)
                assigned += 1
        return {"ok": True, "team": t["id"], "assigned": assigned,
                "leads": leads, "local_kept": local_kept,
                "lead_model": lead_model, "member_model": member_model}

    def drop_agent(self, aid):
        """Remove an agent id from EVERY team (called when an agent is released)."""
        aid = str(aid or "").strip()
        if not aid:
            return {"ok": False}
        with _LOCK:
            d = _load()
            changed = False
            for t in d["teams"].values():
                if aid in (t.get("members") or []):
                    t["members"] = [m for m in t["members"] if m != aid]
                    changed = True
            if changed:
                _save(d)
        return {"ok": True}


REGISTRY = TeamRegistry()

