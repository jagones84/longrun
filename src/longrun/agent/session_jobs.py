#!/usr/bin/env python3
"""Session Jobs (SJ) — dependency-ordered subagents INSIDE one chat session.

An SJ is the in-session twin of the MULTI-SESSION job
(``longrun.orchestrate.jobs``): the session's agent declares ONE job (``SJ<n>``)
split into subjobs (``SJ<n>.<k>``), each handed to a subagent. A subjob may
declare ``deps`` on other subjobs of the same job, so the batch is DISPATCHED in
parallel but every subjob STARTS only when its dependencies finished, and then
receives their output as input (``## Input from dependencies``).

Deliberately SEGREGATED from the multi-session layer — different ids, different
store, different lifecycle — while REUSING the shared primitives instead of
duplicating them:

  * ids      ``SJ<n>`` / ``SJ<n>.<k>``          vs  ``J<n>`` / ``J<n>.<k>``
  * store    ``data/sessions/<sid>.sj.json``    (lives and dies with the session)
  * graph    ``longrun.util.dag``               (waves / ready / blockers_state)
  * workers  ``longrun.agent.subagent``         (spawn / collect, now durable)

Lifecycle: ``create`` → ``run`` (ready-queue scheduler, capped workers) →
``describe`` (model + REST introspection). ``delete(sid)`` is called by the
session-delete cascade in ``longrun.memory.stores._purge_session_artifacts``, so
an SJ never outlives the chat that created it.
"""
from __future__ import annotations

import os
import threading
import time

from longrun.util import dag
from longrun.util.paths import SESSIONS_DIR

STORE_SUFFIX = ".sj.json"
TERMINAL = ("done", "error", "blocked")
_LOCK = threading.RLock()

# Hard bounds: an SJ is a batch of SUBAGENTS, so the model cannot ask for an
# unbounded fan-out by accident (a typo in `calls` would otherwise spawn 500
# children). 0 disables the guard (operator decision in config, not here).
MAX_SUBJOBS = 32


def _safe(ident):
    return "".join(c for c in str(ident or "") if c.isalnum() or c in "-_.")[:120]


def path_for(sid):
    """The SJ ledger of one session (the cascade deletes exactly this file)."""
    return os.path.join(SESSIONS_DIR, _safe(sid) + STORE_SUFFIX)


def _empty(sid):
    return {"sid": sid, "seq": 0, "jobs": {}, "subjobs": {}}


def _load(sid):
    from longrun.util.fswrite import read_json
    doc = read_json(path_for(sid), None)
    if not isinstance(doc, dict):
        return _empty(sid)
    doc.setdefault("sid", sid)
    doc.setdefault("seq", 0)
    doc.setdefault("jobs", {})
    doc.setdefault("subjobs", {})
    return doc


def _save(sid, doc):
    from longrun.util.fswrite import write_json
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    write_json(path_for(sid), doc)


def _publish(kind, **data):
    try:
        from longrun.core.events import publish
        publish(kind, **data)
    except Exception:  # noqa: BLE001 — an event must never break the scheduler
        pass


# ------------------------------------------------------------------ create ----
def _normalise(specs):
    """(labels, specs) with a stable label per subjob (``s1``..``sN`` fallback)."""
    out = []
    labels = []
    for i, raw in enumerate(specs or []):
        s = raw if isinstance(raw, dict) else {}
        label = str(s.get("label") or s.get("name") or ("s%d" % (i + 1))).strip()
        out.append(dict(s, label=label))
        labels.append(label)
    return labels, out


def create(sid, goal, subjobs, mode="parallel"):
    """Declare one Session Job. Returns ``{ok, job}`` or ``{ok: False, error}``.

    Validation (refusing is the point — a malformed plan must not run):
      * at least one subjob, at most ``MAX_SUBJOBS``;
      * labels unique and non-empty;
      * every ``deps`` entry names a declared label (or subjob id);
      * the dependency graph is acyclic.
    """
    if not sid:
        return {"ok": False, "error": "session id required"}
    specs = [s for s in (subjobs or []) if isinstance(s, dict)]
    if not specs:
        return {"ok": False, "error": "an SJ needs at least one subjob"}
    if len(specs) > MAX_SUBJOBS:
        return {"ok": False, "error": "an SJ may hold at most %d subjobs" % MAX_SUBJOBS}
    labels, specs = _normalise(specs)
    if len(set(labels)) != len(labels):
        return {"ok": False, "error": "duplicate subjob labels: %s" % ", ".join(labels)}
    known = set(labels)
    for s in specs:
        for d in (s.get("deps") or []):
            if str(d) not in known:
                return {"ok": False,
                        "error": "subjob %r depends on unknown %r" % (s["label"], d)}
    dep_map = {s["label"]: [str(d) for d in (s.get("deps") or [])] for s in specs}
    if dag.has_cycle(labels, dep_map):
        return {"ok": False, "error": "the subjob dependencies form a cycle"}
    with _LOCK:
        doc = _load(sid)
        n = int(doc.get("seq") or 0) + 1
        doc["seq"] = n
        jid = "SJ%d" % n
        now = round(time.time(), 3)
        ids = {}
        for k, s in enumerate(specs, start=1):
            ids[s["label"]] = "%s.%d" % (jid, k)
        order = [ids[s["label"]] for s in specs]
        for s in specs:
            sub_id = ids[s["label"]]
            doc["subjobs"][sub_id] = {
                "id": sub_id, "job": jid, "label": s["label"],
                "goal": str(s.get("goal") or s.get("detail") or "").strip(),
                "role": (str(s.get("role")).strip() or None) if s.get("role") else None,
                "model": s.get("model") or None,
                "max_steps": _steps(s.get("max_steps")),
                "deps": [ids[str(d)] for d in (s.get("deps") or [])],
                "input_from": (str(s.get("input_from")).strip()
                               if s.get("input_from") else None),
                "status": "pending", "subagent_id": None, "result": None,
                "error": None, "created": now, "started": None, "ended": None,
            }
        doc["jobs"][jid] = {
            "id": jid, "n": n, "sid": sid, "goal": str(goal or "")[:500],
            "mode": str(mode or "parallel"), "status": "created",
            "order": order, "labels": ids, "created": now,
            "started": None, "ended": None,
        }
        _save(sid, doc)
        job = doc["jobs"][jid]
    _publish("sj.created", session=sid, job=jid, subjobs=order)
    return {"ok": True, "job": jid, "session": sid, "subjobs": order,
            "labels": {v: k for k, v in ids.items()}, "record": job}


def _steps(raw):
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 4
    return max(1, min(n, 32))


# -------------------------------------------------------------------- run ----
def _input_block(doc, spec):
    """The `## Input from dependencies` block for one subjob ("" when none)."""
    deps = spec.get("deps") or []
    if not deps:
        return ""
    labels = (doc.get("jobs", {}).get(spec.get("job"), {}) or {}).get("labels") or {}
    src = spec.get("input_from")
    if src is None:
        src = list(deps)
    elif isinstance(src, (list, tuple)):
        src = [str(x) for x in src]
    else:
        src = [str(src)]
    blocks, missing = [], []
    for x in src:
        sub_id = labels.get(x, x)
        dep = (doc.get("subjobs") or {}).get(sub_id)
        if dep and dep.get("status") == "done" and str(dep.get("result") or "").strip():
            blocks.append("### %s\n%s" % (x, str(dep["result"]).strip()))
        else:
            missing.append(x)
    if not blocks and not missing:
        return ""
    out = "\n\n## Input from dependencies\n"
    if blocks:
        out += "\n\n".join(blocks)
    if missing:
        out += ("\n\n(no usable output from: %s — proceed from the task alone)"
                % ", ".join(missing))
    return out


def run(sid, job_id=None, hook=None, spawn_fn=None, collect_fn=None,
        cap=None, timeout=None):
    """Run (or resume) one SJ: parallel, dependency-ordered.

    ``hook(kind, spec)`` is called with ``kind`` in ``{"start", "done"}`` so the
    caller (the chat loop) can emit its cards without this module knowing about
    the chat. ``spawn_fn``/``collect_fn`` default to the real subagent layer and
    are injectable so the scheduler is testable without a model.

    A subjob starts only when every dependency reached ``done``; a dependency
    that ended in ``error``/``blocked`` fails it as ``blocked`` with the reason
    (never an infinite wait). Returns the combined observation text plus the
    per-subjob records.
    """
    if not sid:
        return {"ok": False, "error": "session id required"}
    if spawn_fn is None or collect_fn is None:
        from longrun.agent import subagent as _sub
        spawn_fn = spawn_fn or _sub.spawn
        collect_fn = collect_fn or _sub.collect
    if cap is None:
        cap = _worker_cap()
    with _LOCK:
        doc = _load(sid)
        job = _pick(doc, job_id)
        if not job:
            return {"ok": False, "error": "no SJ to run in this session"}
        job_id = job["id"]
        job["status"] = "running"
        job["started"] = job.get("started") or round(time.time(), 3)
        _save(sid, doc)
    _publish("sj.running", session=sid, job=job_id)

    running = []      # subjob ids currently in flight, FIFO
    while True:
        with _LOCK:
            doc = _load(sid)
            subs = doc["subjobs"]
            # 1) fail every pending subjob whose dependency can never succeed
            for sub_id, s in subs.items():
                if s.get("job") != job_id or s.get("status") != "pending":
                    continue
                _done, failed = dag.blockers_state(
                    s.get("deps") or [],
                    {k: v.get("status") for k, v in subs.items()},
                    missing_ok=False)
                if failed:
                    s["status"] = "blocked"
                    s["error"] = "dependency failed: %s" % ", ".join(failed)
                    s["ended"] = round(time.time(), 3)
            pending = [i for i in job["order"]
                       if subs[i].get("status") == "pending"]
            done_ids = [i for i, s in subs.items() if s.get("status") == "done"]
            if not pending and not running:
                _save(sid, doc)
                break
            # 2) spawn every ready subjob while a worker is free
            for sub_id in dag.ready(pending, {i: subs[i].get("deps") or [] for i in job["order"]},
                                    done_ids):
                if len(running) >= max(1, int(cap or 1)):
                    break
                spec = subs[sub_id]
                goal = (spec.get("goal") or "").strip() or "(no goal)"
                goal += _input_block(doc, spec)
                spec["status"] = "running"
                spec["started"] = round(time.time(), 3)
                _save(sid, doc)
                if hook:
                    hook("start", dict(spec, goal_prompt=goal))
                try:
                    spawned = spawn_fn(goal, parent_run_id=sid,
                                       max_steps=spec.get("max_steps") or 4,
                                       model=spec.get("model"),
                                       depth=_depth(sid) + 1,
                                       role=spec.get("role")) or {}
                except Exception as e:  # noqa: BLE001 — one item must not sink the SJ
                    spawned = {"subagent_id": None, "error": "spawn raised: %s" % str(e)[:200]}
                sub_agent = spawned.get("subagent_id")
                if not sub_agent:
                    spec["status"] = "error"
                    spec["error"] = str(spawned.get("error") or "spawn failed")
                    spec["ended"] = round(time.time(), 3)
                    _save(sid, doc)
                    if hook:
                        hook("done", dict(spec))
                    _publish("sj.subjob.done", session=sid, job=job_id,
                             subjob=sub_id, status="error")
                    continue
                spec["subagent_id"] = sub_agent
                _save(sid, doc)
                running.append(sub_id)
                _publish("sj.subjob.start", session=sid, job=job_id, subjob=sub_id)
            if not running:
                # Recomputed from the FRESH statuses: the list captured before the
                # spawn loop is stale by now (items just errored), and using it here
                # would overwrite a terminal subjob with a bogus "blocked".
                still = [i for i in job["order"] if subs[i].get("status") == "pending"]
                if not still:
                    _save(sid, doc)
                    break
                # break a deadlock (should not happen: cycles are refused at create)
                forced = still[0]
                subs[forced]["status"] = "blocked"
                subs[forced]["error"] = "dependency never satisfied"
                subs[forced]["ended"] = round(time.time(), 3)
                _save(sid, doc)
                if hook:
                    hook("done", dict(subs[forced]))
                continue
        # 3) collect one finished subjob (FIFO) and record its result
        sub_id = running.pop(0)
        with _LOCK:
            doc = _load(sid)
            spec = doc["subjobs"][sub_id]
        try:
            res = collect_fn(spec.get("subagent_id"), timeout=timeout) or {}
        except Exception as e:  # noqa: BLE001 — one bad child must not sink the SJ
            res = {"ok": False, "error": str(e)[:300]}
        ok = bool(res.get("ok"))
        out = (str(res.get("summary") or "").strip()
               or str(res.get("error") or "no summary"))
        with _LOCK:
            doc = _load(sid)
            spec = doc["subjobs"][sub_id]
            spec["status"] = "done" if ok else "error"
            spec["result"] = out[:8000]
            spec["error"] = None if ok else str(res.get("error") or "failed")[:500]
            spec["ended"] = round(time.time(), 3)
            _save(sid, doc)
            snapshot = dict(spec)
        if hook:
            hook("done", snapshot)
        _publish("sj.subjob.done", session=sid, job=job_id, subjob=sub_id,
                 status=snapshot["status"])

    with _LOCK:
        doc = _load(sid)
        job = doc["jobs"].get(job_id) or {}
        order = job.get("order") or []
        stats = [doc["subjobs"][i].get("status") for i in order]
        if stats and all(s == "done" for s in stats):
            final = "done"
        elif any(s == "done" for s in stats):
            final = "partial"
        else:
            final = "error"
        job["status"] = final
        job["ended"] = round(time.time(), 3)
        _save(sid, doc)
        view = describe(sid, job_id)
    _publish("sj.done", session=sid, job=job_id, status=final)
    text = _render_text(view)
    return {"ok": final == "done", "job": job_id, "status": final,
            "subjobs": view.get("jobs", [{}])[0].get("subjobs", []) if view.get("jobs") else [],
            "text": text}


def _pick(doc, job_id):
    jobs = doc.get("jobs") or {}
    if job_id and job_id in jobs:
        return jobs[job_id]
    open_jobs = [j for j in jobs.values()
                 if j.get("status") not in ("done", "error", "partial")]
    if open_jobs:
        return sorted(open_jobs, key=lambda j: j.get("n") or 0)[-1]
    if jobs:
        return sorted(jobs.values(), key=lambda j: j.get("n") or 0)[-1]
    return None


def _depth(sid):
    try:
        from longrun.agent import subagent as _sub
        return _sub.depth_of(sid)
    except Exception:  # noqa: BLE001
        return 0


def _worker_cap():
    """The configured parallel-subagent cap (config/subagents.yaml max_parallel)."""
    try:
        from longrun.agent import subagent as _sub
        n = int((_sub.load_cfg() or {}).get("max_parallel") or 0)
        return n if n > 0 else 1
    except Exception:  # noqa: BLE001
        return 4


# --------------------------------------------------------------- reporting ----
def describe(sid, job_id=None, max_result=600):
    """The SJ graph as a plain dict (the model view AND the REST payload)."""
    doc = _load(sid)
    jobs = doc.get("jobs") or {}
    chosen = [_pick(doc, job_id)] if job_id else sorted(
        jobs.values(), key=lambda j: j.get("n") or 0, reverse=True)
    out = []
    for job in chosen:
        if not job:
            continue
        subs = []
        for sub_id in job.get("order") or []:
            s = (doc.get("subjobs") or {}).get(sub_id) or {}
            subs.append({
                "id": sub_id, "label": s.get("label"),
                "status": s.get("status"), "deps": s.get("deps") or [],
                "subagent_id": s.get("subagent_id"),
                "result": (str(s.get("result"))[:max_result]
                           if s.get("result") else None),
                "error": s.get("error"),
            })
        out.append({"id": job.get("id"), "goal": job.get("goal"),
                    "status": job.get("status"), "created": job.get("created"),
                    "ended": job.get("ended"), "subjobs": subs})
    return {"ok": True, "session": sid, "jobs": out, "file": _rel(path_for(sid))}


def _rel(path):
    """The repo-relative path of the ledger (the WebUI opens these in the editor)."""
    try:
        from longrun.util.paths import REPO_ROOT
        return os.path.relpath(path, REPO_ROOT).replace("\\", "/")
    except Exception:  # noqa: BLE001
        return path


def _render_text(view):
    """The combined observation the chat loop injects as the next step."""
    lines = []
    for job in view.get("jobs") or []:
        lines.append("Session job %s (%s) — %d subjob(s)."
                     % (job.get("id"), job.get("status"),
                        len(job.get("subjobs") or [])))
        for s in job.get("subjobs") or []:
            deps = (" deps=%s" % ",".join(s.get("deps") or [])) if s.get("deps") else ""
            lines.append("\n### %s %s%s%s\n%s"
                         % (s.get("id"), s.get("label") or "", deps,
                            " [" + str(s.get("status")).upper() + "]",
                            s.get("result") or s.get("error") or "(no output)"))
    lines.append("\nContinue: use the results, call the next tool, or report.")
    return "\n".join(lines)


def delete(sid):
    """Delete one session's SJ ledger — part of the session-delete cascade."""
    if not sid:
        return []
    p = path_for(sid)
    try:
        if os.path.isfile(p):
            os.remove(p)
            return ["sj:" + os.path.basename(p)]
    except OSError:
        pass
    return []
