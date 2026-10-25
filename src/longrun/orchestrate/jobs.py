"""Jobs — higher-level goals (JN) that orchestrate one or many agents (AX).

A job has a goal, a coordinator agent, a set of member agents, optional ``deps`` (a
DAG: who runs before whom), optional ``blocked_by`` (inter-job dependencies) and a
mode:

  * ``coordinator`` (default): the coordinator decomposes the goal, every worker runs
    its slice, then the coordinator aggregates the team's results.
  * ``fanout``: every agent receives the same goal independently.

Execution reuses the normal per-session turn machinery (``server.chat_stream_gen``),
so each agent turn is a real, persisted turn with its own task list. Independent agents
of the same dependency wave run in parallel threads; the next wave waits for the
previous one — this is Longrun's "several agents working together", and it is safe
because turns serialise per session, never globally.

Storage: ``LONGRUN_JOBS_FILE`` (default ``data/jobs.json``).
"""
import os
import re
import threading
import time
import uuid

from longrun.util.dag import blockers_state as _dag_blockers_state
from longrun.util.dag import waves  # noqa: F401 — shared DAG helper (was local, JAG-533)
from longrun.util import paths
from longrun.util.fswrite import read_registry, retract_seq, write_json
from longrun.util.paths import REPO_ROOT as REPO

_LOCK = threading.RLock()
JOBS_FILE = os.environ.get("LONGRUN_JOBS_FILE") or os.path.join(
    paths.DATA_DIR, "jobs.json")

# v629: team-job policy (config/jobs.yaml). Missing file / bad value = shipped
# defaults, so an old checkout keeps working untouched.
JOBS_YAML = os.path.join(REPO, "config", "jobs.yaml")
# Settings > Harness writes there (gitignored overlay), so the shipped file and
# the operator's overrides stay separate — same pattern as decisions/trace_policy.
JOBS_OVERLAY = os.path.join(paths.DATA_DIR, "jobs.overlay.yaml")
_JOBS_DEFAULTS = {
    # How many ORG levels a team job may cover (1 = the assignee + direct
    # reports, i.e. the pre-v629 behaviour; deeper = the whole subtree, so a
    # subjob can nest as J8.1.1 under the lead that owns it).
    "subjob_depth": 3,
    # Hard ceiling on minted subjobs for one job (a runaway org must not
    # explode a single dispatch).
    "max_subjobs": 64,
}


def config():
    """The team-job policy: shipped `config/jobs.yaml` + the operator overlay."""
    out = dict(_JOBS_DEFAULTS)
    for path in (JOBS_YAML, JOBS_OVERLAY):
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                blk = (yaml.safe_load(f) or {}).get("jobs") or {}
            for k in out:
                if blk.get(k) is not None:
                    out[k] = int(blk[k])
        except Exception:  # noqa: BLE001 — a broken file must never block a job
            continue
    out["subjob_depth"] = max(1, min(int(out["subjob_depth"]), 6))
    out["max_subjobs"] = max(1, min(int(out["max_subjobs"]), 512))
    return out


def _load():
    return read_registry(JOBS_FILE, jobs={}, seq=0)


def _save(d):
    write_json(JOBS_FILE, d)


def _norm_jid(jid):
    """Normalise a job id for store lookup (v610).

    Records are keyed ``JN`` (``J17``) and subjobs ``JN.j`` (``J17.4``), but
    callers historically pass bare numbers (``17``) or lowercase (``j17``) —
    a lookup miss then reads as "job not found" while the deck (which passes
    the full id) shows it fine. Never raises; unknown shapes pass through.
    """
    s = str(jid or "").strip()
    if re.fullmatch(r"\d+(\.\d+)*", s):
        return "J" + s
    m = re.match(r"(?i)^j(\d+(\.\d+)*)$", s)
    if m:
        return "J" + m.group(1)
    return s


def _srv():
    from longrun.core import server
    return server


def handoff_state(receipt, target_len, subjob):
    """CCCC delivery facts, adapted: stored / delivered / replied (pure).

    `stored` = the handoff inject was persisted in the target session.
    `delivered` = the target session advanced past the receipt (`target_len`,
    its message count, exceeds the receipt's `after` boundary), so the handoff
    entered the context of a later turn. `replied` = the subjob finished with
    a result (done) or a reason (failed). Malformed input is `stored`, never
    a crash.
    """
    try:
        r = receipt or {}
        sj = subjob or {}
        if sj.get("status") in ("done", "failed") and (sj.get("result") or sj.get("error")):
            return "replied"
        after = r.get("after")
        if (isinstance(after, int) and isinstance(target_len, int)
                and target_len > after):
            return "delivered"
        return "stored"
    except Exception:  # noqa: BLE001 — classification never breaks the run
        return "stored"


def record_handoff(jid, sub_id, to_sid, text, kind):
    """Persist a handoff inject AND a delivery receipt (best-effort).

    The receipt {id, ts, to, kind, after} is appended to the subjob's
    `handoffs` list in the shared job store; `after` is the target session's
    message count at delivery, the boundary `handoff_state` measures against.
    Returns the receipt, or None when anything fails (the run continues).
    """
    try:
        srv = _srv()
        sess = srv.get_or_create_session(to_sid)
        before = len((sess or {}).get("messages", []))
        srv.persist_inject(sess, "handoff", text)
        rec = {"id": uuid.uuid4().hex[:10], "ts": round(time.time(), 3),
               "to": to_sid, "kind": str(kind or "handoff"), "after": before}
        def _fn(j):
            s = (j.get("subjobs") or {}).get(sub_id)
            if s is not None:
                s.setdefault("handoffs", []).append(rec)
        JOBS._update(jid, _fn)
        return rec
    except Exception:  # noqa: BLE001 — receipts never break the run
        return None


def handoff_status(jid, sub_id):
    """Live [(receipt, state)] for a subjob's handoffs (best-effort)."""
    try:
        job = JOBS.get(jid) or {}
        sub = ((job.get("subjobs") or {}).get(sub_id)) or {}
        out = []
        for r in sub.get("handoffs") or []:
            try:
                sess = _srv().get_or_create_session(r.get("to"))
                tlen = len((sess or {}).get("messages", []))
            except Exception:  # noqa: BLE001
                tlen = r.get("after") or 0
            out.append((r, handoff_state(r, tlen, sub)))
        return out
    except Exception:  # noqa: BLE001
        return []


def _error_turn(text):
    """True when a turn's reply is the harness's EXPLICIT error record.

    `stores.ensure_reply_persisted` appends `⚠️ error: <reason>` when a turn
    produced no assistant message (provider 500, timeout, crashed stream). That
    is a FAILED turn, not a result: before this check a job marked the subjob
    `done` with the error text as its deliverable, and the job itself `done`
    with the error as the final answer.
    """
    try:
        from longrun.memory import stores
        prefix = stores.ERROR_PREFIX
    except Exception:  # noqa: BLE001
        prefix = "\u26a0\ufe0f error: "
    return str(text or "").strip().startswith(prefix)


def _error_reason(text):
    """The reason carried by an error turn (or '' when the text is not one)."""
    s = str(text or "").strip()
    if not _error_turn(s):
        return ""
    try:
        from longrun.memory import stores
        s = s[len(stores.ERROR_PREFIX):]
    except Exception:  # noqa: BLE001
        s = s.split("error:", 1)[-1]
    return s.strip()[:300]


def subjob_id(jid, n, parent_sub=None):
    """JAG-334: a subjob id, NESTED when it comes from inside another subjob.

    Top level:  JN.j        (e.g. J8.1)
    Nested:     JN.j.x[.y]  (e.g. J8.2.1 — a piece the agent that received J8.2
                itself hands out). The extra level mirrors the ORGANIGRAM depth of
                the agent session that receives it.
    """
    root = parent_sub or jid
    return "%s.%d" % (root, n)


def plan_subjobs(jid, agents, coord, plan, deps, parent_sub=None, tree=None):
    """JAG-322/324/v629: split a job into numbered SUBJOBS, one per agent.

    Paperclip-style, and a first-class level of the object model:

        Job JN ──▶ Subjob JN.j (one per agent, with deps among subjobs)
                     └─ embraces the subset of that agent's todos (nY)

    The coordinator master owns the job (J6); each assignment it hands out becomes
    a tracked subjob J6.1, J6.2, ... bound to ONE agent, with its own status,
    timings and DEPENDENCIES. A subjob depends on the subjobs of the agents it
    waits on (the job's agent-level `deps`), so the subjob DAG mirrors the wave
    order — higher-level than todos, same idea. The coordinator is not a subjob.

    JAG-334: `parent_sub` nests the ids one level (`J8.2.1`) when the work is handed
    out FROM inside another subjob, so the numbering follows the org depth.

    v629: `tree` = {agent_id: parent_agent_id} (the org subtree of the assignee).
    A direct report of an agent that already owns a subjob NESTS under it
    (J8.1.1, J8.1.2), so the ids mirror the ORGANIGRAM at any depth — the
    numbering is per-parent (never a global counter, which produced J8.1.5).
    """
    agents = list(agents)
    deps = deps or {}
    tree = tree or {}
    limit = config()["max_subjobs"]
    # Pass 1: assign a subjob id to each delegable agent. Parents must be minted
    # BEFORE their children (a child nests under its parent's id), so a member
    # whose parent has no id yet is deferred to the next round.
    order, aid_to_sub, counters = [], {}, {}
    pending = []
    for wave_i, wave in enumerate(waves(agents, deps)):
        for aid in wave:
            if aid != coord:
                pending.append((aid, wave_i))
    while pending and len(order) < limit:
        rest, progressed = [], False
        for aid, wave_i in pending:
            parent_aid = tree.get(aid)
            # Only defer when the parent is ANOTHER TEAM MEMBER that still needs
            # its own subjob id. The coordinator never gets one (it owns the
            # job), so its direct reports hang off the JOB id (J8.1, J8.2).
            if (parent_aid and parent_aid in agents and parent_aid != coord
                    and parent_aid not in aid_to_sub):
                rest.append((aid, wave_i))
                continue
            host = aid_to_sub.get(parent_aid) if parent_aid else parent_sub
            root = host or jid
            counters[root] = counters.get(root, 0) + 1
            sub_id = subjob_id(jid, counters[root], host)
            aid_to_sub[aid] = sub_id
            order.append((aid, sub_id))
            progressed = True
            if len(order) >= limit:
                break
        if not progressed:
            # A cycle in the org link (malformed registry): mint the rest flat.
            for aid, wave_i in rest:
                counters[jid] = counters.get(jid, 0) + 1
                sub_id = subjob_id(jid, counters[jid], parent_sub)
                aid_to_sub[aid] = sub_id
                order.append((aid, sub_id))
            break
        pending = rest
    # Pass 2: a subjob depends on the subjobs of the agents it waits on.
    out = {}
    for aid, sub_id in order:
        sdeps = [aid_to_sub[a] for a in (deps.get(aid) or []) if a in aid_to_sub]
        out[sub_id] = {
            "id": sub_id, "parent": jid,
            "parent_sub": aid_to_sub.get(tree.get(aid)) or parent_sub,
            "agent": aid,
            "deps": sdeps,
            "assignment": JobRegistry._assignment_for(plan, aid) if plan else "",
            "status": "pending", "started": None, "ended": None,
            "result": "", "error": "",
        }
    return out


def subjob_num(sub_id):
    """JAG-326: the numeric index of a subjob id, for NATURAL order.

    Subjobs are JN.1, JN.2, ... JN.10. Sorting the ids as STRINGS puts JN.10 before
    JN.2 (and JN.10 before JN.2 everywhere a list sorts them), so a job with 10+
    subjobs shows in the wrong order. Sort by this index instead.
    """
    try:
        return int(str(sub_id).rsplit(".", 1)[-1])
    except (TypeError, ValueError):
        return 0


def subjob_path(sub_id):
    """v629: the numeric PATH of a subjob id — J8.1.2 -> (1, 2), J8 -> ().

    This is the one ordering key for any depth: sorting by the tuple keeps a
    child IMMEDIATELY after its parent (J8.1, J8.1.1, J8.1.2, J8.2) instead of
    interleaving it with its uncles the way `subjob_num` (trailing number only)
    did once nesting exists.
    """
    parts = str(sub_id or "").split(".")[1:]
    out = []
    for p in parts:
        try:
            out.append(int(p))
        except (TypeError, ValueError):
            return tuple(out) or (0,)
    return tuple(out) or (0,)


def subjob_depth(sub_id):
    """v629: the org LEVEL of a subjob id (J8 -> 0, J8.1 -> 1, J8.1.2 -> 2)."""
    return max(0, str(sub_id or "").count("."))


def subjob_children(subs, sub_id):
    """v629: the DIRECT children of a subjob id, in NATURAL path order."""
    pref = str(sub_id or "") + "."
    kids = [k for k in (subs or {}) if str(k).startswith(pref)
            and "." not in str(k)[len(pref):]]
    return sorted(kids, key=subjob_path)


def latest_plan_nodes(nodes):
    """JAG-327: the nodes of the HIGHEST plan number present (all when none is set).

    A re-run of a job reuses the SAME subjob ids (J6.1 is J6.1 again) but in a NEW
    plan; taking the latest plan a subjob appeared in scopes it to ITS run, without
    losing the mapping when a LATER, unrelated plan opens on the same session.
    """
    nodes = nodes or []
    if not nodes:
        return []
    top = max(n.get("plan", 1) for n in nodes)
    return [n for n in nodes if n.get("plan", 1) == top]


_AFTER_RE = re.compile(r"\(\s*after\s+([^)]*)\)", re.I)
_AGENT_RE = re.compile(r"\bA\d+\b")


def parse_plan_deps(plan):
    """JAG-330: the dependency DAG a coordinator DECLARED inside its plan.

    Paperclip-style: the master not only decomposes the goal, it states WHAT MUST
    HAPPEN IN ORDER. A bullet may end with ``(after AX, AY)``; we read those into
    ``{agent: [deps]}`` so the runner can ENFORCE the order — a dependent subjob does
    not start until the ones it waits on are done — instead of running every worker
    in parallel (the SEVERE case where coder 2 never waited for coder 1).
    """
    out = {}
    for line in str(plan or "").splitlines():
        s = line.strip()
        if not s:
            continue
        m = _AFTER_RE.search(s)
        if not m:
            continue
        own = _AGENT_RE.findall(s[:m.start()])
        if not own:
            continue
        deps = [d for d in _AGENT_RE.findall(m.group(1)) if d != own[0]]
        if deps:
            cur = out.setdefault(own[0], [])
            for d in deps:
                if d not in cur:
                    cur.append(d)
    return out


def merge_deps(job_deps, declared):
    """JAG-330: the user's job deps UNION the deps the coordinator declared."""
    out = {k: list(v) for k, v in (job_deps or {}).items()}
    for aid, ds in (declared or {}).items():
        cur = out.setdefault(aid, [])
        for d in ds:
            if d not in cur:
                cur.append(d)
    return out


_STATUS_RE = re.compile(r"^\s*STATUS\s*:\s*(DONE|OK|COMPLETE|BLOCKED|FAILED)\b[:\-]?\s*(.*)$",
                        re.I | re.M)


def parse_status(reply):
    """JAG-337: the terminal STATUS a worker declares (Paperclip-style).

    Returns (status, reason); status is "DONE"/"BLOCKED"/"FAILED" or None when the
    worker declared none. Workers are asked to end with `STATUS: DONE` (or
    `STATUS: BLOCKED: <why>`); a missing status is treated by the CALLER as DONE only
    when the worker left no open steps.
    """
    m = _STATUS_RE.search(str(reply or ""))
    if not m:
        return None, ""
    word = m.group(1).upper()
    if word in ("DONE", "OK", "COMPLETE"):
        status = "DONE"
    elif word == "FAILED":
        status = "FAILED"
    else:
        status = "BLOCKED"
    return status, m.group(2).strip()[:300]


def open_steps(sid):
    """JAG-337: labels of the OPEN steps in a session's CURRENT plan."""
    try:
        from longrun.plan import taskgraph as tg
        g = tg.load(sid) or {}
        return [n.get("label") or n.get("id") for n in tg.plan_nodes(g)
                if n.get("status") in tg.OPEN_STATUSES]
    except Exception:  # noqa: BLE001
        return []


def job_retries():
    """JAG-337: extra attempts per subjob (LONGRUN_JOB_RETRIES, default 1)."""
    try:
        return max(0, int(os.environ.get("LONGRUN_JOB_RETRIES", "1")))
    except (TypeError, ValueError):
        return 1


class JobRegistry:
    """Create, inspect and run jobs (JN)."""

    def list(self):
        with _LOCK:
            d = _load()
        jobs = sorted(d["jobs"].values(), key=lambda j: j.get("n", 0), reverse=True)
        for j in jobs:                          # JAG-292: uniform contract for old jobs
            j.setdefault("blocked_by", [])
        out = {"jobs": jobs, "seq": d["seq"], "count": len(jobs)}
        try:
            from longrun.core import matrix as _mtx
            _mtx.call_hook("orchestrate", "on_job_change", out, "list", default=None)
        except Exception:  # noqa: BLE001
            pass
        return out

    def get(self, jid):
        with _LOCK:
            return _load()["jobs"].get(_norm_jid(jid))

    def delete(self, jid):
        """Remove a job from the store. Refused while it is running.

        JAG-314: scrub the id from every OTHER job's ``blocked_by`` too, else a
        dependent job is wedged forever pointing at a job that no longer exists
        (dispatch says "blocked by <gone>", wake() neither releases nor fails it).
        """
        jid = str(jid or "")
        if not jid.strip():
            return {"ok": False, "error": "job id required"}
        jid = _norm_jid(jid)
        with _LOCK:
            d = _load()
            job = d["jobs"].get(jid)
            if not job:
                return {"ok": False, "error": "job not found"}
            if job.get("status") == "running":
                return {"ok": False, "error": "job is running"}
            d["jobs"].pop(jid, None)
            dependents = self._scrub_blocker(d, jid)
            retract_seq(d, "jobs")
            _save(d)
        return {"ok": True, "deleted": jid, "unblocked": dependents}

    @staticmethod
    def _scrub_blocker(d, jid):
        """Drop a deleted job id from every other job's blocked_by (in place)."""
        unblocked = []
        for other in d["jobs"].values():
            bb = other.get("blocked_by") or []
            if jid in bb:
                other["blocked_by"] = [x for x in bb if x != jid]
                if not other["blocked_by"] and other.get("status") == "blocked":
                    other["status"] = "created"
                unblocked.append(other["id"])
        return unblocked

    def scrub_agent(self, aid):
        """JAG-314: an agent was released/deleted — drop it from every job.

        Removes the agent id from each job's ``agents`` list and re-points (or
        clears) ``coordinator`` so a dispatch does not silently skip a member.
        """
        aid = str(aid or "")
        with _LOCK:
            d = _load()
            changed = []
            for j in d["jobs"].values():
                if aid and aid in (j.get("agents") or []):
                    j["agents"] = [x for x in j["agents"] if x != aid]
                    if (j.get("coordinator") or "") == aid:
                        j["coordinator"] = (j["agents"][0] if j["agents"] else None)
                    changed.append(j["id"])
            if changed:
                _save(d)
            return changed

    def create(self, goal, coordinator=None, agents=None, deps=None, mode="coordinator",
               blocked_by=None):
        goal = (goal or "").strip()
        agents = [a for a in (agents or []) if a]
        if not goal:
            return {"ok": False, "error": "goal required"}
        if not agents:
            return {"ok": False, "error": "at least one agent required"}
        with _LOCK:
            d = _load()
            d["seq"] += 1
            jid = "J%d" % d["seq"]
            clean_deps = {k: [x for x in (v or []) if x in agents]
                          for k, v in (deps or {}).items()}
            # JAG-292: inter-job dependencies. A job may declare `blocked_by` — a
            # set of OTHER jobs (paperclip issue_blockers / ruflo Task.resolveExecutionOrder).
            # It stays "blocked" until every blocker is done, then wake() releases it.
            blockers = self._clean_blockers(d, jid, blocked_by)
            unresolved = [b for b in blockers
                          if (d["jobs"].get(b) or {}).get("status") != "done"]
            job = {"id": jid, "n": d["seq"], "goal": goal, "mode": mode,
                   "coordinator": coordinator or agents[0], "agents": agents,
                   "deps": clean_deps, "blocked_by": blockers,
                   "status": "blocked" if unresolved else "created",
                   "created": round(time.time(), 3), "runs": {}}
            d["jobs"][jid] = job
            _save(d)
        return {"ok": True, "job": job}

    @staticmethod
    def _clean_blockers(d, jid, blocked_by):
        """Keep only real, distinct blocker ids (never the job itself)."""
        out = []
        for ref in blocked_by or []:
            ref = str(ref or "").strip()
            if ref and ref != jid and ref in d["jobs"] and ref not in out:
                out.append(ref)
        return out

    @staticmethod
    def _blockers_state(job, d):
        """(all_done, failed) for a job's blocked_by set, read from a loaded store.

        JAG-348: a blocker in ANY terminal state other than `done` (`partial` or
        `error`) is a FAILED dependency. Before, only `error` counted, so a
        dependent of a job that ended `partial` — a NORMAL outcome (one worker
        failed) — was neither released nor failed: it stayed `blocked` FOREVER
        (open loop). Terminal-and-not-done must fail the dependent loudly.
        A blocker that no longer EXISTS is satisfied (JAG-314), never a wedge.
        JAG-533/SJ: the evaluation itself is the shared ``util.dag`` helper.
        """
        status = {k: (v or {}).get("status")
                  for k, v in (d.get("jobs") or {}).items()}
        return _dag_blockers_state(job.get("blocked_by") or [], status,
                                   missing_ok=True)

    def _update(self, jid, fn):
        with _LOCK:
            d = _load()
            job = d["jobs"].get(jid)
            if not job:
                return None
            fn(job)
            _save(d)
            return job

    def dispatch(self, jid):
        job = self.get(jid)
        if not job:
            return {"ok": False, "error": "job not found"}
        if job.get("status") == "running":
            return {"ok": False, "error": "job already running"}
        # JAG-292: a job whose blockers are not all done may not start (can_dispatch).
        if job.get("blocked_by"):
            with _LOCK:
                d = _load()
                done, _failed = self._blockers_state(d["jobs"].get(jid) or job, d)
            if not done:
                wait = ", ".join(b for b in job["blocked_by"]
                                 if (self.get(b) or {}).get("status") != "done")
                return {"ok": False, "error": "job blocked by %s" % wait}
        # JAG-322: a job left with NO agents (its members were scrubbed when they
        # were deleted) has literally no one to run — refuse with a reason instead
        # of starting a worker that walks an empty roster and marks the job `done`
        # (started == ended, no work). A job that still LISTS agents whose records
        # are gone is caught by `_run` (-> status error).
        if not (job.get("agents") or []):
            return {"ok": False,
                    "error": "no agents available for this job — its agent(s) were "
                             "deleted; re-assign the job before running it"}
        self._update(jid, lambda j: j.update(
            {"status": "running", "started": round(time.time(), 3), "error": "", "ended": None}))
        threading.Thread(target=self._run, args=(jid,), name="job-" + str(jid), daemon=True).start()
        return {"ok": True, "job": jid, "status": "running"}

    def _live_sessions(self, job):
        """{agent id -> session id} for the job's member agents that still exist.

        JAG-322: the roster is read fresh every time — an agent may have been
        released since the job was created (JAG-314 scrubs it from `agents`, but an
        explicitly-created job may still list a gone agent's id).
        """
        from longrun.agent import agents as agents_mod
        try:
            roster = {a["id"]: a for a in agents_mod.REGISTRY.list()["agents"]}
        except Exception:  # noqa: BLE001
            return {}
        out = {}
        for aid in (job.get("agents") or []):
            sid = (roster.get(aid) or {}).get("session")
            if sid:
                out[aid] = sid
        return out

    def subjob_todos(self, jid):
        """{subjob id -> [todo node ids]} for a job (JAG-324).

        A subjob embraces the subset of its agent's todos tagged with that subjob
        id while the subjob ran. Read-only view: the todo store is the source of
        truth (each node carries `jid` + `subjob`); this just pivots it.
        """
        job = self.get(jid) or {}
        subs = job.get("subjobs") or {}
        out = {sid: [] for sid in subs}
        try:
            from longrun.agent import agents as agents_mod
            from longrun.plan import taskgraph as tg
            roster = {a["id"]: a for a in agents_mod.REGISTRY.list()["agents"]}
            for sid, s in subs.items():
                asid = (roster.get(s.get("agent")) or {}).get("session")
                if not asid:
                    continue
                g = tg.load(asid) or {}
                # JAG-327: scope to the LATEST plan this subjob appeared in, so a
                # re-run's subjob embraces only ITS run's todos, not the previous one's.
                mine = latest_plan_nodes([n for n in (g.get("nodes") or [])
                                          if n.get("subjob") == sid])
                out[sid] = [n.get("id") for n in mine]
        except Exception:  # noqa: BLE001 — a read-only view must never raise
            pass
        return out

    def detail(self, jid):
        """A job enriched with its subjobs' todo membership (JAG-324).

        v629: every subjob also carries `depth` (its org level) and `children`
        (the subjobs nested directly under it), so the tree is readable at any
        depth without re-deriving it from the id string on the client.
        """
        job = self.get(jid)
        if not job:
            return None
        j = dict(job)
        todos = self.subjob_todos(jid)
        subs = job.get("subjobs") or {}
        j["subjobs"] = {sid: dict(s, todos=todos.get(sid, []),
                                  depth=subjob_depth(sid),
                                  children=subjob_children(subs, sid))
                        for sid, s in subs.items()}
        return j

    def reconcile(self):
        """Close jobs left 'running' by a previous process (a restart kills the
        in-process worker thread). Mirrors `reconcile_orphan_turns` for sessions."""
        n = 0
        with _LOCK:
            d = _load()
            for job in d["jobs"].values():
                if job.get("status") == "running":
                    job["status"] = "error"
                    job["error"] = "interrupted by restart"
                    job["ended"] = round(time.time(), 3)
                    n += 1
            if n:
                _save(d)
        if n:
            # JAG-348: an interrupted blocker now ends `error` (not `running`);
            # its dependents must be swept (failed) instead of waiting forever
            # for a job that will never finish.
            self.wake()
        return n

    def wake(self):
        """Level-triggered sweep over blocked jobs (never a busy poll).

        Called whenever ANY job ends. A ``blocked`` job whose blockers ALL finished
        is released (status -> created) and dispatched. A blocked job with a FAILED
        blocker can never resolve, so it is failed too (``dependency failed``) —
        mirroring paperclip's "cancelled blockers never unblock" without a deadlock.

        Returns ``{"released": [...], "failed": [...]}``.
        """
        released, failed = [], []
        with _LOCK:
            pending = [j["id"] for j in _load()["jobs"].values()
                       if j.get("status") == "blocked"]
        for jid in pending:
            with _LOCK:
                d = _load()
                job = d["jobs"].get(jid)
                if not job or job.get("status") != "blocked":
                    continue
                done, bad = self._blockers_state(job, d)
            if done:
                self._update(jid, lambda j: j.update({"status": "created", "error": ""}))
                res = self.dispatch(jid)
                released.append({"job": jid, "ok": bool(res.get("ok")),
                                 "error": res.get("error", "")})
            elif bad:
                reason = "dependency failed: %s" % ", ".join(bad)
                self._update(jid, lambda j, r=reason: j.update(
                    {"status": "error", "error": r, "ended": round(time.time(), 3)}))
                failed.append(jid)
        return {"released": released, "failed": failed}

    # ---- execution ----------------------------------------------------------
    def _sessions(self):
        from longrun.agent import agents as agents_mod
        return {a["id"]: a["session"] for a in agents_mod.REGISTRY.list()["agents"]}

    @staticmethod
    def _scope_graph(sid, jid, goal):
        """JAG-299: bind the agent's task graph to THIS job (JN).

        Two effects: (a) a FRESH plan per job, so a previous job's still-open todos
        stop leaking into the current one — they were gating/confusing the model
        (J2's library todos showing up while the agent worked J3's HTTP-caching
        goal, then a HUMAN-IN-THE-LOOP pivot demanding a choice); and (b) a `jid`
        tag on every node this job creates, so the UI can attribute a todo to its
        job instead of showing one undifferentiated list.
        """
        try:
            from longrun.plan import taskgraph as tg
            with tg.GRAPH_LOCK:
                g = tg.ensure(sid, session_id=sid, goal=goal)
                if g.get("jid") != jid:
                    tg.begin_plan(g)
                    g["jid"] = jid
                    tg.save(g)
        except Exception:  # noqa: BLE001 — graph bookkeeping must never break a run
            pass

    @staticmethod
    def _assignment_for(plan, aid):
        """The single plan line that names THIS agent (the whole plan when unnamed).

        JAG-303: the coordinator replies with one bullet per teammate
        ("- A5 (api-designer): ..."). Handing a worker the WHOLE list made it unsure
        which slice was its own and it tended to redo everyone's work; give it only
        its line, falling back to the full plan when the coordinator did not name it.

        JAG-344: pick the MOST SPECIFIC line for this agent. A plan can also carry
        an aggregate line that lists several ids ("critical path: A13 -> A14 -> A15");
        the old "first line containing the id" matched that line for EVERY agent, so
        all workers were handed the same assignment. Prefer a line whose FIRST agent
        id is this one and that names the FEWEST other agents.
        """
        text = str(plan or "").strip()
        best, best_score = "", None
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            ids = _AGENT_RE.findall(s)
            if aid not in ids:
                continue
            score = (0 if ids[0] == aid else 1, len(set(ids) - {aid}), len(s))
            if best_score is None or score < best_score:
                best, best_score = s, score
        return best or text

    @staticmethod
    def _best_reply(messages):
        """The most substantial assistant reply of a TURN (JAG-303).

        A turn can END with a short harness-prompted summary ("report the RESULT
        you already have") AFTER the real deliverable. Returning the LAST message
        therefore lost the work — a job goal asking for content got back a one-line
        description of it. The longest assistant message is the one carrying the
        deliverable. Shared with the `dispatch` path via `stores.turn_reply`.
        """
        from longrun.memory import stores
        return stores.turn_reply(messages, longest=True)

    @staticmethod
    def _close_open_todos(sid):
        """JAG-303: mark the current plan's open steps DONE once the team has run.

        The coordinator's decomposition todos ("Assign A4 to ...") are the job's
        assignments; when the worker wave has finished they ARE done. Left open,
        the FINAL synthesis turn was nagged by the harness ("you left N open") into
        a keepgoing loop instead of producing the deliverable.
        """
        try:
            from longrun.plan import taskgraph as tg
            with tg.GRAPH_LOCK:
                g = tg.load(sid)
                if not g:
                    return 0
                closed = 0
                for n in list(tg.plan_nodes(g)):
                    if n.get("status") not in tg.OPEN_STATUSES:
                        continue
                    try:
                        tg.complete_node(g, n["id"], evidence="job: team turn completed",
                                         source="job")
                        closed += 1
                    except Exception:  # noqa: BLE001 — a risky step needs observed proof
                        try:
                            tg.complete_node(g, n["id"], evidence="job: team turn completed",
                                             source="job", observed=True)
                            closed += 1
                        except Exception:  # noqa: BLE001
                            pass
                return closed
        except Exception:  # noqa: BLE001 — graph bookkeeping must never break a run
            return 0

    def _run_agent(self, sid, message, model=None, jid=None, sender=None, subjob=None,
                   plan_only=False):
        """Run one real turn on an agent's session; return its final prose reply.

        The session's ROLE.md rides in the system prompt (section `agent-role`),
        so every turn — coordinator, worker or routine — already carries the
        agent's role and behaviour rules. Nothing is prepended here (JAG-294).

        `jid` (JAG-299) scopes this job's work on the session's task graph so one
        job's todos never bleed into the next. `sender` / `subjob` (JAG-322) mark a
        DELEGATED turn: the worker's chat shows the delegation came from its
        coordinator for a specific subjob, not from the human operator.
        """
        srv = _srv()
        sess = srv.get_or_create_session(sid)
        if jid:
            self._scope_graph(sid, jid, message)
        before = len((srv.load_session(sid) or {}).get("messages", []))
        for _ in srv.chat_stream_gen(sess, message, model, None, autonomous=True, jid=jid,
                                     sender=sender, subjob=subjob, plan_only=plan_only):
            pass
        s = srv.load_session(sid) or {}
        # JAG-303: return THIS turn's substantial reply, not the trailing summary.
        # JAG-310: only THIS turn may answer. Scanning the WHOLE session returned
        # the last assistant message from a PREVIOUS run, so a job could be marked
        # `done` with a stale/duplicate "reply" — the coordinator looked like it
        # had answered a report it never answered. If this turn produced nothing,
        # return nothing and let the job fail loudly.
        return self._best_reply(s.get("messages", [])[before:])

    def _run(self, jid):
        from longrun.agent import agents as agents_mod
        try:
            job = self.get(jid)
            if not job:
                return
            roster = {a["id"]: a for a in agents_mod.REGISTRY.list()["agents"]}
            sessions = self._live_sessions(job)
            coord = job.get("coordinator")
            failed = []                    # JAG-337: subjobs that could not be finished
            if coord not in sessions:                 # JAG-322: coordinator was deleted
                coord = next(iter(sessions), None)
            if not sessions:
                raise RuntimeError(
                    "no agents available for this job — its agent(s) were deleted; "
                    "re-assign the job before running it")
            # JAG-327: a RUN owns a FRESH plan per participating agent. On a RE-RUN the
            # job id is unchanged, so `_scope_graph` (keyed on the job id) would NOT
            # open a new plan and a subjob id would then span TWO plans (J6.1 twice) —
            # `subjob_todos` would merge the runs. A FIRST run is bumped by
            # `_scope_graph` when the jid changes from None; here we cover the re-run.
            try:
                from longrun.plan import taskgraph as _tg
                for _sid in set(sessions.values()):
                    with _tg.GRAPH_LOCK:
                        _g = _tg.ensure(_sid, session_id=_sid, goal=job.get("goal"))
                        if _g.get("jid") == jid:
                            _tg.begin_plan(_g)
            except Exception:  # noqa: BLE001 — graph bookkeeping must never break a run
                pass
            plan = ""
            if job.get("mode") == "coordinator" and coord:
                team = ", ".join("%s (%s)" % (aid, roster.get(aid, {}).get("role")
                                              or roster.get(aid, {}).get("name") or "")
                                 for aid in job["agents"])
                plan = self._run_agent(sessions[coord],
                    "You are the COORDINATOR of a small team of agents.\nGoal: %s\nTeam: %s\n\n"
                    "Plan the work and decompose the goal into a short, concrete assignment for "
                    "EACH teammate, one bullet per agent id.\n"
                    "You MAY use your tools and skills to inspect the workspace and inform the "
                    "plan, and you SHOULD record your plan in your own task list (todos).\n"
                    "DEPENDENCIES (enforced): if a teammate must WAIT for another to finish "
                    "first, end its bullet with \"(after AX)\" naming the agent id(s) it depends "
                    "on — the dependent will NOT start until they are done. Add a dependency "
                    "ONLY when the order truly matters (e.g. coder 2 after coder 1).\n"
                    "End your reply with that bullet list (plain text).\n"
                    "This turn is for PLANNING ONLY: inspect the workspace if useful, "
                    "record your plan in your todos, then STOP. Do NOT write the "
                    "deliverable and do NOT execute the teammates' tasks yourself — the "
                    "workers do the work and you synthesise their results afterwards.\n"
                    "Rules: do NOT spawn subagents; do NOT do the teammates' work yourself."
                    % (job["goal"], team),
                    model=roster.get(coord, {}).get("model"), jid=jid, plan_only=True)
                if _error_turn(plan):
                    # A provider/turn failure is not a plan: without this the job
                    # ran its workers against an error string and could finish `done`.
                    raise RuntimeError("coordinator planning turn failed: %s"
                                       % (_error_reason(plan) or "provider error"))
                self._update(jid, lambda j: j["runs"].__setitem__(
                    coord, {"state": "done", "result": plan}))

            # JAG-330: the EFFECTIVE dependency DAG = the job's own deps UNION the ones the
            # coordinator DECLARED in its plan ("(after AX)"). This is what ORDERS the
            # subjobs; without it every subjob ran in parallel (SEVERE — coder 2 never
            # waited for coder 1). It is stored so the structure is visible and reusable.
            declared = parse_plan_deps(plan)
            deps = merge_deps(job.get("deps") or {}, declared)
            # JAG-322: the plan becomes numbered, attributable SUBJOBS (J6.1, J6.2...)
            # and the delegation is written into the coordinator's own chat.
            _coord_mode = job.get("mode") == "coordinator"
            coord_label = (("%s (%s)" % (coord, roster.get(coord, {}).get("name") or coord))
                           if (_coord_mode and coord) else None)
            # v629: the ORG tree of this job's team drives the subjob numbering.
            # Only links whose BOTH ends are on this job's team are used, so an
            # explicit `agents` list never invents a parent outside the job.
            _team = set(sessions.keys())
            try:
                from longrun.agent import agents as _agents_mod
                _root = coord or ((job.get("agents") or [None])[0])
                _sub = _agents_mod.REGISTRY.team_tree(
                    _root, depth=config()["subjob_depth"]) if _root else {}
            except Exception:  # noqa: BLE001 — a broken registry must not block
                _sub = {}
            _tree = {k: v for k, v in (_sub or {}).items()
                     if v and k in _team and v in _team}
            subs = plan_subjobs(jid, list(sessions.keys()),
                                (coord if _coord_mode else None), plan, deps,
                                tree=_tree)
            # v629: MERGE, never replace — a deeper org level mints children
            # under ids that already exist (J8.1.1), and a re-dispatch must not
            # drop the subjobs a previous pass recorded.
            def _merge_subs(j, _subs=subs, _decl=declared):
                j.setdefault("subjobs", {}).update(_subs)
                j["declared_deps"] = _decl
            self._update(jid, _merge_subs)
            self._announce_delegation(sessions.get(coord) if _coord_mode else None, jid, roster, subs)
            # JAG-333: give the MASTER a visible plan (one todo per delegated subjob).
            self._seed_coordinator_plan(
                sessions.get(coord) if _coord_mode else None, jid, subs, roster)

            for wave in waves(list(sessions.keys()), deps):
                threads = []
                for aid in wave:
                    if _coord_mode and aid == coord:
                        continue
                    sid = sessions.get(aid)
                    if not sid:
                        continue
                    sub = next((s for s in subs.values() if s["agent"] == aid), None)
                    mine = ((sub or {}).get("assignment")
                            or (self._assignment_for(plan, aid) if plan else ""))
                    msg = self._delegation_msg(jid, coord_label, sub, job["goal"], mine)
                    t = threading.Thread(
                        target=self._one,
                        args=(jid, aid, sid, msg, roster.get(aid, {}).get("model"),
                              (sub or {}).get("id"), coord_label),
                        daemon=True)
                    t.start()
                    threads.append(t)
                for t in threads:
                    t.join()

            if job.get("mode") == "coordinator" and coord:
                # JAG-303: the team has run — close the coordinator's decomposition
                # steps, so the synthesis turn is not nagged by its own open todos.
                self._close_open_todos(sessions[coord])
                cur = self.get(jid) or {}
                # JAG-337: the master must be TOLD which subjobs were NOT finished, so
                # the "ball" never comes back silently. Failed subjobs are excluded from
                # the team report and listed explicitly as OPEN work.
                failed = [(s.get("id"), s.get("agent"), s.get("error") or "")
                          for s in (cur.get("subjobs") or {}).values()
                          if s.get("status") == "failed"]
                res = "\n\n".join("%s: %s" % (aid, (cur.get("runs", {}).get(aid) or {}).get("result", ""))
                                  for aid in job["agents"] if aid != coord)
                warn = ""
                if failed:
                    warn = ("\n\n!! UNFINISHED SUBJOBS (the workers could NOT deliver these — "
                            "say so in your deliverable, do NOT pretend they are done):\n"
                            + "\n".join("  - %s (%s): %s" % (a, b, (c or "-")[:200]) for a, b, c in failed))
                final = self._run_agent(sessions[coord],
                    "Team results:\n%s%s\n\nProduce the COMPLETE final deliverable for this goal, "
                    "in full, as your reply:\n%s\n\nOutput the ACTUAL content (the endpoints, the "
                    "schema, the error payload, the examples) — not a description of it and not "
                    "the word 'done'. Rules: do NOT call tools; do NOT spawn subagents."
                    % (res, warn, job["goal"]), model=roster.get(coord, {}).get("model"), jid=jid)
                if not (final or "").strip():
                    # JAG-310: never mark a job `done` when its coordinator produced
                    # NO reply to the team report — that is "accepted without an
                    # answer". Fail loudly so it is visible and re-runnable.
                    raise RuntimeError("coordinator produced no final reply")
                if _error_turn(final):
                    raise RuntimeError("coordinator final turn failed: %s"
                                       % (_error_reason(final) or "provider error"))
                self._update(jid, lambda j: j["runs"].__setitem__(
                    coord, {"state": "done", "result": final}))
            self._update(jid, lambda j, _f=list(failed): j.update(
                {"status": "partial" if _f else "done", "failed_subjobs":
                 [a for a, _, _ in _f], "ended": round(time.time(), 3)}))
            self.wake()   # JAG-292: release jobs that were blocked on this one
        except Exception as _e:  # noqa: BLE001
            _err = str(_e)
            self._update(jid, lambda j, _err=_err: j.update(
                {"status": "error", "error": _err, "ended": round(time.time(), 3)}))
            self.wake()   # a failed blocker must still sweep its dependents

    @staticmethod
    def _delegation_msg(jid, coord_label, sub, goal, mine):
        """The message a worker receives for a delegated subjob (JAG-322/330/331).

        JAG-331: a subjob is WORK TO DO, not a paragraph to write. The old text ended
        with a plain-text-only instruction ("keep the reply short"), so a worker answered
        with a PLAN and "this turn exposes no callable tools" instead of executing
        (the SEVERE "deployment is pending" report). It now tells the worker to DO its
        assignment end to end with its tools and skills, then report the RESULT.
        """
        sub_id = (sub or {}).get("id") or "-"
        if coord_label:
            head = "Delegation from %s — subjob %s (job %s)." % (coord_label, sub_id, jid)
        else:
            head = "Subjob %s (job %s)." % (sub_id, jid)
        # JAG-330: the worker is told what it WAITS FOR (the scheduler already enforces
        # the order, so by the time this turn runs they are done — state it for clarity).
        dep_note = ""
        if (sub or {}).get("deps"):
            dep_note = "\nWaits for (already completed): %s." % ", ".join(sub["deps"])
        return ("%s\nGoal: %s%s\n\nYour assignment (yours only):\n%s\n\n"
                "DO this now, end to end. You HAVE tools: use them to inspect the "
                "workspace, read/write files and run shell commands, and consult skills "
                "with the `skills` tool when one helps (skills{action:'search'|'list'}). "
                "Do NOT merely describe the steps or say you cannot — carry them out, "
                "then report what you DID and the concrete result (output, files, "
                "commands, errors).\n"
                "End your report with a line `STATUS: DONE` (or `STATUS: BLOCKED: <why>` "
                "if you truly cannot finish).\n"
                "Rules: do NOT spawn subagents; do NOT do the other agents' parts."
                % (head, goal, dep_note, mine))

    @staticmethod
    def _announce_delegation(coord_sid, jid, roster, subs):
        """Write the delegation into the coordinator's chat (JAG-322).

        Without this the master's transcript showed only its own plan: no record
        that it handed a subjob to a specific agent, nor any timing. The worker
        side gets the matching "Delegation from ..." message, so BOTH chats carry
        the hand-off.
        """
        if not coord_sid or not subs:
            return
        srv = _srv()
        lines = []
        for s in sorted(subs.values(), key=lambda x: subjob_num(x.get("id"))):
            a = roster.get(s["agent"], {})
            # JAG-330: show the DECLARED order in the master's chat (who waits for whom).
            dep = (" [after %s]" % ", ".join(s.get("deps") or [])) if s.get("deps") else ""
            lines.append("%s → %s (%s) [session %s]: %s%s"
                         % (s["id"], s["agent"], a.get("name") or "",
                            a.get("session") or "?", (s["assignment"] or "").strip()[:160], dep))
        try:
            csess = srv.get_or_create_session(coord_sid)
            srv.persist_inject(
                csess, "delegation",
                "↳ Delegated %d subjob(s) of %s:\n%s\n"
                "Inspect any teammate's transcript with the `sessions` tool "
                "(sessions{action:'list'}, then sessions{action:'read', "
                "session:'<id>'}) to see why one is failing and help it."
                % (len(subs), jid, "\n".join(lines)))
        except Exception:  # noqa: BLE001 — the record must never break the run
            pass

    def _seed_coordinator_plan(self, coord_sid, jid, subs, roster):
        """JAG-333: the MASTER's task list = its own decomposition (the subjobs).

        Job turns are NEVER auto-planned (JAG-308), so historically the master ended up
        with NO plan and its panel looked empty. The harness seeds one todo node per
        subjob (tagged with the subjob id), so the master's persistent plan shows what
        it delegated and to whom — and the workers' subjobs map onto the same hierarchy.

        JAG-338: now that the coordinator MAY author its own plan, seeding is only a
        FALLBACK. If the master already wrote todos into this run's plan, keep them and
        do not duplicate the decomposition.
        """
        if not coord_sid or not subs:
            return
        try:
            from longrun.plan import taskgraph as tg
            with tg.GRAPH_LOCK:
                g = tg.ensure(coord_sid, session_id=coord_sid, goal=jid)
                if tg.plan_nodes(g):
                    return          # the master planned itself — do not duplicate it
                for s in sorted(subs.values(), key=lambda x: subjob_num(x.get("id"))):
                    a = roster.get(s.get("agent"), {})
                    label = "%s %s (%s): %s" % (
                        s["id"], s["agent"], a.get("name") or "",
                        (s.get("assignment") or "").strip()[:120] or "assigned")
                    _prev = g.get("subjob")
                    g["subjob"] = s["id"]
                    try:
                        tg.add_node(g, label, source="job")
                    finally:
                        g["subjob"] = _prev
                tg.save(g)
        except Exception:  # noqa: BLE001 — a convenience plan must never break the run
            pass

    def _sub_update(self, jid, sub_id, patch):
        """Patch one subjob in place (status/timing/result) — JAG-322."""
        def _fn(j):
            s = (j.get("subjobs") or {}).get(sub_id)
            if s is not None:
                s.update(patch)
        self._update(jid, _fn)

    def _coord_session(self, jid):
        """The coordinator agent's SESSION for a job (None when unresolved)."""
        try:
            from longrun.agent import agents as agents_mod
            aid = (self.get(jid) or {}).get("coordinator")
            if not aid:
                return None
            roster = {a["id"]: a for a in agents_mod.REGISTRY.list()["agents"]}
            return (roster.get(aid) or {}).get("session")
        except Exception:  # noqa: BLE001
            return None

    def _log_escalation(self, jid, aid, sid, sub_id, status, reason, retry):
        """JAG-337: record in BOTH chats that a subjob could not be finished.

        Paperclip rule: never sit silently on blocked work. The WORKER's chat gets the
        "returning it" note; the COORDINATOR's chat gets the "it came back to you" note.
        Without these the ball silently passed to the master with no trace.
        Both notes go through `record_handoff` (same words as before) so each
        carries a delivery receipt (stored/delivered/replied).
        """
        record_handoff(jid, sub_id, sid,
                       "\u21a9 returning subjob %s to the coordinator%s\n%s"
                       % (sub_id or "-", " (retrying)" if retry else "",
                          reason or "-"),
                       "escalation")
        csid = self._coord_session(jid)
        if not csid:
            return
        head = ("\u21a9 %s (%s) could not finish subjob %s%s" %
                (aid, status, sub_id or "-", " \u2014 retrying" if retry else " \u2014 BACK TO YOU"))
        record_handoff(jid, sub_id, csid, "%s\n%s" % (head, reason or "-"),
                       "escalation")

    def _one(self, jid, aid, sid, msg, model, sub_id=None, sender=None):
        """Run ONE worker's subjob with bounded RETRY + explicit ESCALATION (JAG-337).

        Paperclip rule: never sit silently on blocked work. A worker that does not finish
        (declares `STATUS: BLOCKED`/`FAILED`, or leaves OPEN steps) is RETRIED up to
        `LONGRUN_JOB_RETRIES` extra times; if it still cannot finish, the subjob is
        marked `failed` (NEVER `done`) and the handoff is RECORDED IN BOTH CHATS.
        """
        self._update(jid, lambda j: j["runs"].__setitem__(
            aid, {"state": "running", "started": round(time.time(), 3)}))
        if sub_id:
            self._sub_update(jid, sub_id,
                             {"status": "running", "started": round(time.time(), 3)})
        attempts = 1 + job_retries()
        cur, out, status, reason = msg, "", None, ""
        for attempt in range(1, attempts + 1):
            try:
                out = self._run_agent(sid, cur, model=model, jid=jid,
                                      sender=sender, subjob=sub_id)
            except Exception as _e:  # noqa: BLE001
                out, status, reason = "", "FAILED", str(_e)
            else:
                if _error_turn(out):
                    # The turn ended in the harness error record (provider 500,
                    # timeout): that is a FAILED subjob, never a deliverable.
                    status = "FAILED"
                    reason = "turn error: %s" % (_error_reason(out) or "provider error")
                else:
                    status, reason = parse_status(out)
                    steps = open_steps(sid)
                    if status is None:
                        status = "BLOCKED" if steps else "DONE"
                        if steps:
                            reason = "%d open step(s): %s" % (len(steps), "; ".join(steps[:5]))
            if status == "DONE":
                break
            if attempt < attempts:
                if sub_id:
                    self._sub_update(jid, sub_id, {"status": "retrying", "attempt": attempt,
                                                   "result": out, "error": reason})
                self._log_escalation(jid, aid, sid, sub_id, status, reason, retry=True)
                cur = ("Resume subjob %s \u2014 your previous attempt did NOT finish (%s).\n"
                       "Finish the work now with your tools and end with a line "
                       "`STATUS: DONE`, or `STATUS: BLOCKED: <why>` if it is truly impossible."
                       % (sub_id or "-", reason or "incomplete"))
        if status == "DONE":
            self._update(jid, lambda j: j["runs"].__setitem__(
                aid, {"state": "done", "result": out, "ended": round(time.time(), 3)}))
            if sub_id:
                self._sub_update(jid, sub_id, {"status": "done", "result": out,
                                               "ended": round(time.time(), 3)})
            return
        err = reason or "worker did not finish"
        self._update(jid, lambda j, _err=err: j["runs"].__setitem__(
            aid, {"state": "failed", "error": _err, "result": out,
                  "ended": round(time.time(), 3)}))
        if sub_id:
            self._sub_update(jid, sub_id, {"status": "failed", "error": err,
                                           "result": out, "ended": round(time.time(), 3)})
        self._log_escalation(jid, aid, sid, sub_id, status, err, retry=False)


JOBS = JobRegistry()

