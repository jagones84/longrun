#!/usr/bin/env python3
"""The generate engine (K-2): the TEXT of one WebUI field, from its REAL context.

One completion, one surface, one returned string. It never writes: the operator
reviews the draft inside the field and saves (or sends it). That is what makes the
composer servable at all — a tool-running agent could not "draft a message".

Two things the operator asked for are decided here, and nowhere else:

* the CONTEXT. Each surface names a gatherer key; the gatherer reads the live state
  of that exact surface from the stores (the chat's recent turns, the plan, the goal,
  the workspace, the object the field belongs to). A generator that does not know
  where it is writing cannot know what a correct value is.
* the MODEL. A session-scoped surface runs on THAT SESSION's own model
  (`routing.turn_model`), so a chat prompt is written by the model that already holds
  the chat's context. Everything else runs on the `generate` role, one knob the
  operator can route in Settings ▸ Models.

Model policy lives in `_model_for`; prompt text lives in `longrun.gen.surfaces`. This
module owns neither.
"""
import json
import os

from longrun.gen import surfaces as S

MAX_CONTEXT_CHARS = 6000
_TIMEOUT = 120
_MAX_TOKENS = 1500


# ----------------------------------------------------------------- gatherers ---
#
# Each returns a JSON-able dict of REAL state. Everything is guarded: a gatherer
# that cannot read a store must degrade to "less context", never to an exception —
# the field's own current text is always sent anyway, so a thin context still
# produces a usable draft.
def _clip(text, n=400):
    return ("" if text is None else str(text))[:n]


def _tail(sid, n=8):
    """The last `n` transcript turns as `[{role, text}]` (compacted sessions included)."""
    try:
        from longrun.memory import stores
        sess = stores.load_session(sid) or {}
        out = []
        for m in (sess.get("messages") or [])[-n:]:
            if not isinstance(m, dict):
                continue
            txt = m.get("content")
            if not isinstance(txt, str) or not txt.strip():
                continue
            out.append({"role": str(m.get("role") or "?"), "text": _clip(txt, 500)})
        return out
    except Exception:  # noqa: BLE001
        return []


def _session_ctx(sid, own_workspace_only=False):
    """What most surfaces need: the workspace, the recent turns, the plan and the goal.

    `own_workspace_only` is for the composer (`chat.prompt`). That surface drafts a
    message for THIS conversation, so the folder is a fact about the chat ONLY when
    the session OWNS one; the global default is not. It used to be substituted here
    (`rules.resolve_workspace` falls back to `get_workspace()`), and because that
    default is the operator's setting it can be the harness's OWN repo: with an empty
    chat the workspace was then the only fact in the context, so the ✨ drafted
    "explore the repository at <harness repo>" in a conversation about something else
    (live, 2026-11-03). A chat with no folder and no turns now has a genuinely empty
    context, and the surface prompt asks the operator instead of inventing a project.
    """
    out = {"session": sid}
    try:
        from longrun.memory import stores, rules
        sess = stores.load_session(sid) or {}
        out["title"] = sess.get("title") or ""
        out["model"] = sess.get("model") or ""
        ws = None
        try:
            ws = (rules.check_dir(sess.get("workspace")) if own_workspace_only
                  else rules.resolve_workspace(sess))
        except Exception:  # noqa: BLE001
            ws = sess.get("workspace")
        if ws:
            out["workspace"] = ws
    except Exception:  # noqa: BLE001
        pass
    out["recent_turns"] = _tail(sid)
    try:
        from longrun.plan import taskgraph, goal as goal_mod
        g = taskgraph.load(sid) or {}
        nodes = taskgraph.plan_nodes(g)
        out["plan"] = [{"id": n.get("id"), "step": _clip(n.get("label"), 160),
                        "status": n.get("status")} for n in nodes[:40]]
        st = goal_mod.status(sid) or {}
        rec = st.get("goal") or {}
        if rec:
            out["goal"] = {"objective": _clip(rec.get("objective"), 400),
                           "status": st.get("effective_status")}
    except Exception:  # noqa: BLE001
        pass
    return out


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return _clip(f.read(), 2500)
    except OSError:
        return ""


def _rules(extra):
    """Both rules files, so a new paragraph never duplicates the other one."""
    out = {}
    try:
        from longrun.memory import rules
        out["global_rules"] = _read_text(rules.global_rules_path())
        out["project_rules"] = _read_text(rules.project_rules_path())
    except Exception:  # noqa: BLE001
        pass
    return out


def _agent(extra):
    """The agent this ROLE.md belongs to: identity, team, reporting line, current prompt."""
    sid = str((extra or {}).get("agent") or (extra or {}).get("session") or "")
    out = {}
    try:
        from longrun.agent import agents as agents_mod
        rec = agents_mod.REGISTRY.get(sid) or {}
        out["agent"] = {"id": sid, "name": rec.get("name"), "role": rec.get("role"),
                        "model": rec.get("model"),
                        "reports_to": rec.get("reports_to")}
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.orchestrate import roles as roles_mod
        cur = roles_mod.read(sid)
        if cur:
            out["current_prompt"] = _clip(cur, 2500)
    except Exception:  # noqa: BLE001
        pass
    out.update(_session_ctx(sid))
    return out


def _role_brief(v):
    """The brief of one configured role, whatever shape it was stored in.

    RH-18: a role is `{brief, tools}` OR a plain string (both are legal, the panel
    writes the object form). The old `(v or {}).get("brief")` raised on the string
    form and the whole `roles` map was then dropped by the caller's except — so a
    single string role silently removed EVERY neighbour from the context.
    """
    if isinstance(v, dict):
        return v.get("brief") or v.get("text") or ""
    return v if isinstance(v, str) else ""


def _subagent(extra):
    out = {"role": (extra or {}).get("role") or ""}
    try:
        from longrun.agent import subagent as sub
        cfg = sub.load_cfg() or {}
        roles = cfg.get("roles") or {}
        # RH-18: a NEW role must not duplicate an existing one, so the neighbours'
        # BRIEFS are context, not just their names. 12 roles x 500 chars stays inside
        # MAX_CONTEXT_CHARS even when a config grows.
        pairs = list(roles.items())[:12]
        out["existing_names"] = [str(k) for k, _ in pairs]
        out["roles"] = {str(k): _clip(_role_brief(v), 500) for k, v in pairs}
    except Exception:  # noqa: BLE001
        pass
    return out


def _compaction(extra):
    try:
        from longrun.core import settings
        return {"sections": [s for s in (settings.view() or {}).get("sections", [])
                             if s.get("id") == "compaction"]}
    except Exception:  # noqa: BLE001
        return {}


def _team(extra):
    """The team this description belongs to: its members and its existing description."""
    tid = str((extra or {}).get("team") or "")
    out = {"team": tid, "name": (extra or {}).get("name") or ""}
    try:
        from longrun.orchestrate import teams as teams_mod
        rec = teams_mod.REGISTRY.get(tid) or {}
        out["name"] = rec.get("name") or out["name"]
        out["existing_description"] = _clip(rec.get("description"), 400)
        out["existing"] = [t.get("name") for t in (teams_mod.REGISTRY.list() or {})
                           .get("teams", [])][:20]
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.agent import agents as agents_mod
        out["members"] = [{"name": a.get("name"), "role": a.get("role")}
                          for a in agents_mod.REGISTRY.agents_of_team(tid)][:20]
    except Exception:  # noqa: BLE001
        pass
    return out


def _kb(extra):
    out = {}
    try:
        from longrun.memory import knowledge
        out["notebooks"] = [n.get("name") for n in (knowledge.list_notebooks() or [])][:30]
    except Exception:  # noqa: BLE001
        pass
    return out


def _memory(extra):
    out = {}
    try:
        from longrun.memory import memory as mem
        recs = mem.query(limit=25) or []
        out["existing"] = [_clip(r.get("content"), 220) for r in recs][:25]
    except Exception:  # noqa: BLE001
        pass
    return out


def _blackboard(extra):
    out = {"topic": (extra or {}).get("topic") or ""}
    try:
        from longrun.agent import swarm
        entries = swarm.entries(topic=out["topic"], limit=5) if hasattr(swarm, "entries") else []
        out["recent"] = [_clip(e.get("content"), 240) for e in entries][:5]
    except Exception:  # noqa: BLE001
        pass
    return out


def _object_only(extra):
    """A routine/job goal: the object identity plus who will run it."""
    out = {k: (extra or {}).get(k) for k in ("routine", "job", "team", "name", "goal")
           if (extra or {}).get(k)}
    try:
        from longrun.agent import agents as agents_mod
        out["agents"] = [{"name": a.get("name"), "role": a.get("role")}
                         for a in (agents_mod.REGISTRY.list() or {}).get("agents", [])][:25]
    except Exception:  # noqa: BLE001
        pass
    return out


_GATHER = {
    # The composer drafts a message for the CONVERSATION: the folder counts only when
    # the session owns one (never the global default — see `_session_ctx`).
    "chat.prompt": lambda e: _session_ctx((e or {}).get("session"),
                                          own_workspace_only=True),
    "goal.objective": lambda e: _session_ctx((e or {}).get("session")),
    "plan.input": lambda e: _session_ctx((e or {}).get("session")),
    "session.title": lambda e: _session_ctx((e or {}).get("session")),
    "memory.content": lambda e: dict(_session_ctx((e or {}).get("session")), **_memory(e)),
    "rules.global": _rules,
    "rules.project": _rules,
    "agent.role": _agent,
    "subagent.brief": _subagent,
    "subagent.new": _subagent,
    "compaction.instruction": _compaction,
    "team.description": _team,
    "kb.notebook": _kb,
    "blackboard.topic": _blackboard,
    "routine.goal": _object_only,
    "job.goal": _object_only,
}


def context_for(surface, extra=None):
    """The gathered context for one surface (public: the acceptance test pins it)."""
    fn = _GATHER.get(surface.ctx)
    if fn is None:
        return {}
    try:
        got = fn(extra or {}) or {}
    except Exception:  # noqa: BLE001 — a gatherer must never break a generation
        return {}
    return got if isinstance(got, dict) else {}


# -------------------------------------------------------------------- engine ---
def _model_for(surface, session):
    """The model that writes this surface — one rule, in one place.

    A session-scoped surface runs on the SESSION's own model (`routing.turn_model`),
    which is what makes a chat prompt contextually right. Anything else runs on the
    `generate` role, so the operator has ONE knob in Settings ▸ Models.
    """
    from longrun.model import routing
    if surface.session_scoped and session:
        m = routing.turn_model(session)
        if m:
            return m
    try:
        m = routing.role_model(S.DEFAULT_ROLE)
        if m:
            return m
    except Exception:  # noqa: BLE001
        pass
    try:
        from longrun.agent import architect as lra
        return lra.resolve_automation_model(active_session_id=session)
    except Exception:  # noqa: BLE001
        return None


def _user_message(surface, ctx, current, hint):
    parts = ["CONTEXT (the real state of this surface — do not contradict it):",
             json.dumps(ctx, ensure_ascii=False, default=str)[:MAX_CONTEXT_CHARS]]
    cur = (current or "").strip()
    parts.append("\nCURRENT CONTENT OF THE FIELD:\n" + (cur[:4000] if cur
                                                        else "(empty)"))
    if cur:
        parts.append("\nDo NOT duplicate what is already there; produce the text to "
                     "put in the field.")
    if (hint or "").strip():
        parts.append("\nOPERATOR HINT (obey it):\n" + _clip(hint, 600))
    return "\n".join(parts)


def _clean(text):
    """The reply as a field value: no fences, no wrapping quotes, no stray blank shell."""
    t = str(text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    t = t.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ('"', "'"):
        t = t[1:-1].strip()
    return t


def generate(surface, session=None, current="", hint="", extra=None, model=None):
    """Draft the text of ONE field. Returns `{ok, text, model, surface}`; never writes."""
    s = S.resolve(surface)
    if s is None:
        return {"ok": False, "error": "unknown surface %r" % (surface,)}
    if s.kind != S.GENERATE:
        return {"ok": False, "surface": s.id,
                "error": ("surface %r is an automate surface: it runs `longrunAgent` "
                          "through POST /api/longrun-agent/automate" % s.id)}
    sid = str(session or (extra or {}).get("session") or "")
    extra = dict(extra or {})
    if sid:
        extra.setdefault("session", sid)
    ctx = context_for(s, extra)
    msgs = [{"role": "system", "content": s.system},
            {"role": "user", "content": _user_message(s, ctx, current, hint)}]
    used = None
    try:
        from longrun.util import improve
        answer, used = improve.single_shot(
            msgs, model=model or _model_for(s, sid or None), role=s.role,
            timeout=_TIMEOUT, max_tokens=_MAX_TOKENS)
    except Exception as exc:  # noqa: BLE001 — a failed draft is reported, not raised
        return {"ok": False, "surface": s.id, "error": _clip(exc, 300)}
    text = _clean(answer)
    if not text:
        return {"ok": False, "surface": s.id, "error": "the model returned no text",
                "model": used}
    return {"ok": True, "surface": s.id, "text": text, "model": used,
            "context_keys": sorted(ctx)[:20]}
