#!/usr/bin/env python3
"""Seed 3 diversified TEAMS (with real organigrams) from the agency-agents clone.

Reads the local clone of **agency-agents** (``strategy/runbooks.json`` + each agent
``.md`` frontmatter) and materialises, for every chosen runbook, ONE team whose
members are real Longrun agents arranged in an organigram:

    coordinator (root)
    ├── <group> lead ── specialists of that group …
    └── <group> lead ── specialists …

The groups come from the runbook's ``roster[].group``; ``reports_to`` builds the
organigram. The script is IDEMPOTENT: re-running reuses agents by name and just
re-asserts team membership.

Usage (on the DGX, from the repo root):
    python3 scripts/seed_teams.py                 # the default 3 teams
    python3 scripts/seed_teams.py startup-mvp     # a subset, by runbook slug
Env:
    LONGRUN_AGENCY_DIR   path to the agency-agents clone
                            (default ~/Repositories/agency-agents)
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

AGENCY = os.environ.get("LONGRUN_AGENCY_DIR") or os.path.expanduser(
    "~/Repositories/agency-agents")

# Per-slug symbol + colour (the runbooks carry none). Fallback: the palette default.
SYMBOLS = {
    "startup-mvp": ("\U0001f680", "#3B82F6"),         # 🚀
    "marketing-campaign": ("\U0001f4e3", "#F97316"),  # 📣
    "incident-response": ("\U0001f6a8", "#EF4444"),   # 🚨
    "enterprise-feature": ("\U0001f3e2", "#8B5CF6"),  # 🏢
}
DEFAULT_TEAMS = ["startup-mvp", "marketing-campaign", "incident-response"]

# Directories that are NOT agent sources.
_SKIP_DIRS = {"integrations", "scripts", "strategy", "examples", ".git", ".github"}


def _load_runbooks():
    with open(os.path.join(AGENCY, "strategy", "runbooks.json"), encoding="utf-8") as f:
        return json.load(f)


def _agent_index():
    """Map every agent slug (file stem) -> absolute .md path."""
    idx = {}
    for root, dirs, files in os.walk(AGENCY):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in files:
            if fn.endswith(".md"):
                idx.setdefault(fn[:-3], os.path.join(root, fn))
    return idx


def _frontmatter(path):
    """Parse the leading YAML-ish frontmatter — shared parser (JAG-483)."""
    from longrun.agent.agency import frontmatter
    return frontmatter(path)


def _pick_runbooks(slugs):
    wanted = slugs or DEFAULT_TEAMS
    by_slug = {r["slug"]: r for r in _load_runbooks().get("runbooks", [])}
    return [by_slug[s] for s in wanted if s in by_slug]


def _roster_slugs(runbook):
    """Ordered (group, [slugs]) list, preserving the runbook structure."""
    return [(g.get("group") or "Team", list(g.get("agents") or []))
            for g in runbook.get("roster", [])]


def seed(slugs=None, apply_models=False):
    from longrun.core import server  # noqa: E402
    from longrun.agent import agents  # noqa: E402
    from longrun.orchestrate import teams  # noqa: E402
    idx = _agent_index()
    by_name = {str(a.get("name") or "").strip().lower(): a
               for a in agents.REGISTRY.list()["agents"]}
    created = {"teams": [], "agents": 0}
    missing = set()

    def name_of(slug):
        fm = _frontmatter(idx.get(slug, ""))
        return (fm.get("name") or slug.replace("-", " ").title()), fm

    for rb in _pick_runbooks(slugs):
        tname = rb.get("title") or rb["slug"]
        sym, col = SYMBOLS.get(rb["slug"], (None, None))
        t = teams.REGISTRY.get(tname)
        if not t:
            t = teams.REGISTRY.create(tname, symbol=sym, color=col,
                                      description=rb.get("summary") or "")["team"]
        tid = t["id"]
        groups = _roster_slugs(rb)

        def ensure(slug, reports_to, role):
            """Create (or reuse) one agent and its team link. Returns its A-id."""
            if slug not in idx:
                missing.add(slug)
                return reports_to
            disp, fm = name_of(slug)
            role_txt = role or (fm.get("description") or "")[:80]
            a = by_name.get(disp.lower())
            if a:
                aid, sid = a["id"], a.get("session")
            else:
                sess = server.get_or_create_session(None, title=disp)
                sid = sess["id"]
                r = agents.REGISTRY.designate(sid, name=disp, role=role_txt,
                                              reports_to=reports_to)
                if not r.get("ok"):
                    return reports_to
                aid = r["agent"]["id"]
                by_name[disp.lower()] = r["agent"]
                created["agents"] += 1
            teams.REGISTRY.add_member(tid, aid)
            return aid

        root_slug = groups[0][1][0] if groups and groups[0][1] else None
        if not root_slug:
            continue
        root_aid = ensure(root_slug, None, "Coordinator")
        for gname, members in groups:
            lead_slug = members[0] if members else None
            if not lead_slug:
                continue
            lead_aid = root_aid if lead_slug == root_slug else ensure(
                lead_slug, root_aid, "%s lead" % gname)
            for slug in members[1:]:
                ensure(slug, lead_aid, gname)
        created["teams"].append({"id": tid, "name": tname})
        if apply_models:                       # JAG-343: leads cloud, cap local per machine
            teams.REGISTRY.assign_models(tid)

    # JAG-365: the seed used to carry ONLY the short label, so each agent's role
    # PROMPT (ROLE.md — the very file the Bridge prompt and the main app edit) stayed
    # VOID. Materialise it now from the clone's `.md` body. Non-destructive: only an
    # EMPTY role is filled, so a role the user wrote is never clobbered.
    from longrun.agent import agency
    role_report = agency.fill_roles()

    return {"ok": True, "teams": created["teams"], "agents_created": created["agents"],
            "missing": sorted(missing), "roles": role_report}


def main(argv):
    if not os.path.isdir(AGENCY):
        print("agency-agents not found at %s (set LONGRUN_AGENCY_DIR)" % AGENCY)
        return 2
    args = argv[1:] or []
    apply_models = "--models" in args
    slugs = [a for a in args if a != "--models"]
    res = seed(slugs or None, apply_models=apply_models)
    print("teams: " + ", ".join("%s %s" % (t["id"], t["name"]) for t in res["teams"]))
    print("agents created: %d" % res["agents_created"])
    if res["missing"]:
        print("missing slugs: %s" % ", ".join(res["missing"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
