#!/usr/bin/env python3
"""Longrun subagent delegation — v0.3

Pattern (deepagents / hierarchical agents): the main agent loop can spawn child
agent runs (subagents) with an isolated context, let them execute, and collect
their result. This enables:

  - Parallel subtask execution
  - Delegation of specialized goals to a different model
  - Recursive decomposition of complex goals

Subagent runs share the same harness infrastructure (tools, sandbox, approvals)
but get their own plan/tasks context and a fresh transcript. The parent receives
a summary / trace when the child finishes.

Usage (from agent loop):
    {"action": "subagent", "goal": "...", "max_steps": 4, "model": "..."}
    {"action": "subagent_result", "id": "..."}
"""

import json
import os
import threading
import time
import uuid

from longrun.core import api_v02  # for the RunState / agent_run_v2 machinery
from longrun.model import structured as _structured  # M1: output contract
from longrun.agent import acceptance as _acceptance  # M8b1: acceptance predicates
from longrun.tools import approvals
from longrun.tools import registry
from longrun.tools import sandbox
from longrun.util import paths
from longrun.plan import taskgraph  # per-run task graph (child gets its own todo list)
from longrun.tools import tools as toolmod

# JAG-451: subagents are configured — NOT hardcoded. `config/subagents.yaml` holds
# the parallel cap + the named role briefs; the model lives in config/routing.yaml
# (roles.subagent). Both are surfaced/edited by Settings ▸ Subagents.
CFG_PATH = os.environ.get("LONGRUN_SUBAGENTS_CFG") or os.path.join(
    registry.REPO, "config", "subagents.yaml")
DEFAULT_CFG = {
    "version": "1",
    "max_parallel": 4,
    # M8: per-run spawn budget (DeerFlow `max_total_per_run`, default 6).
    # A parent doing spawn->collect->spawn in a loop could otherwise create
    # unbounded serial subagents (each a paid model run) while staying under
    # the parallel cap and the depth bound. 0 = no cap.
    "max_per_run": 6,
    "roles": {
        "researcher": ("Investigate a question against primary sources. Return a "
                       "compact, cited summary (max ~400 words). Do NOT modify files."),
        "coder": ("Implement a small, self-contained code change. Report the exact "
                  "files touched and the commands you ran. Do NOT touch unrelated files."),
        "reviewer": ("Audit the given code or output for correctness and risks. Return "
                     "a short, prioritised findings list with file/line references. "
                     "Do NOT modify files."),
    },
}


def load_cfg(reload=False):
    """The subagents config (max_parallel + roles). Never raises."""
    try:
        if reload or not hasattr(load_cfg, "_cache"):
            with open(CFG_PATH, encoding="utf-8") as f:
                text = f.read()
            try:
                import yaml
                data = yaml.safe_load(text)
            except Exception:  # noqa: BLE001
                data = json.loads(text)
            load_cfg._cache = data if isinstance(data, dict) else dict(DEFAULT_CFG)
    except Exception:  # noqa: BLE001 — a missing/broken file falls back to defaults
        load_cfg._cache = dict(DEFAULT_CFG)
    return load_cfg._cache


def save_cfg(cfg):
    """Persist the subagents config to yaml (best effort). Returns the path."""
    try:
        import yaml
        text = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True)
    except Exception:  # noqa: BLE001
        text = json.dumps(cfg, indent=2)
    os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    load_cfg._cache = cfg
    return CFG_PATH


def _role_spec(role):
    """The raw entry for a role: a bare brief (legacy) or `{brief, tools}` (I-1)."""
    roles = load_cfg().get("roles") or {}
    return roles.get(role or "")


def role_brief(role):
    """The standing instruction for a named subagent role ("" when unknown)."""
    spec = _role_spec(role)
    if isinstance(spec, dict):
        return str(spec.get("brief") or spec.get("text") or "").strip()
    return str(spec or "").strip()


def role_tools(role):
    """The tools a role may call, or None when the role is unrestricted (I-1).

    `roles.<name>.tools` lists exact tool names ("fs.read") or whole namespaces
    ("fs", which admits every `fs.*` tool). An ABSENT key means no restriction —
    today's behaviour — so adding the key is the only thing that changes it.
    """
    spec = _role_spec(role)
    if not isinstance(spec, dict) or "tools" not in spec:
        return None
    raw = spec.get("tools")
    if isinstance(raw, str):
        raw = [raw]
    out = [str(x).strip() for x in (raw or []) if str(x).strip()]
    return out or None


def merge_roles(current, incoming):
    """Assign the roles map WITHOUT destroying a role's tool scope (I-1).

    The writers (POST /api/subagents, the longrunAgent settings tool) used to
    coerce every value with `str()`, which flattened `{brief, tools}` into
    "{'brief': …}" and silently dropped the scope. One implementation, used by
    both writers, so a panel edit can never delete what it does not render.
    """
    out = {}
    for name, value in (incoming or {}).items():
        name = str(name)
        old = (current or {}).get(name)
        if isinstance(value, dict):
            out[name] = {str(k): v for k, v in value.items()}
        elif isinstance(old, dict):
            out[name] = dict(old, brief=str(value or ""))
        else:
            out[name] = str(value or "")
    return out


def _running_count():
    with _lock:
        return len(_running)


_lock = threading.RLock()
_running = {}     # subagent_id -> {state, parent_run_id, goal, result}
_DEPTH = {}       # run_id -> depth of nesting (matrioska); 0 = top level
# M8: successful spawns per parent run (the per-run budget). In-memory like
# `_running`; cleared by `purge_parent`. A `None` parent is never counted.
_SPAWN_COUNT = {}  # parent_run_id -> int
_SPAWN_COUNT_MAX_PARENTS = 4096

# JAG-533/SJ: a finished subagent used to live ONLY in the in-memory `_running`
# dict, so a harness restart lost every result — the parent's `collect()` then
# answered "not found" for work that had actually completed, and the session's
# Session Job (SJ) ledger could reference a result nobody could read any more.
# Every spawn writes a small durable record here; `collect`/`status` fall back
# to it. Deleted with the parent session (see `purge_parent`).
SUBAGENT_DIR = os.environ.get("LONGRUN_SUBAGENT_DIR") or os.path.join(
    paths.DATA_DIR, "subagents")
_MAX_SUMMARY = 8000


def _safe(ident):
    """A subagent/session id safe to use as a file name."""
    return "".join(c for c in str(ident or "") if c.isalnum() or c in "-_.")[:120]


def _rec_path(subagent_id):
    return os.path.join(SUBAGENT_DIR, _safe(subagent_id) + ".json")


def _persist(rec):
    """Atomically write one durable subagent record (never raises)."""
    try:
        from longrun.util.fswrite import write_json
        os.makedirs(SUBAGENT_DIR, exist_ok=True)
        write_json(_rec_path(rec.get("id")), rec)
    except Exception:  # noqa: BLE001 — persistence must never break a spawn
        pass


def load_record(subagent_id):
    """The durable record of one subagent, or None (survives a restart)."""
    try:
        from longrun.util.fswrite import read_json
        return read_json(_rec_path(subagent_id), None)
    except Exception:  # noqa: BLE001
        return None


def exists(subagent_id):
    """True when the id names a live or durable subagent (M3a R1).

    The single existence check: in-memory `_running` first, durable
    record fallback (post-restart) second. Never raises.
    """
    sid = _safe(subagent_id)
    if not sid:
        return False
    try:
        with _lock:
            if sid in _running:
                return True
    except Exception:  # noqa: BLE001
        pass
    return load_record(sid) is not None


def purge_parent(parent_run_id):
    """Delete every durable subagent record whose parent is `parent_run_id`.

    Called from the session-delete cascade so a session's subagents do not leak
    as orphans — like the transcript, its graph and its runs. Returns the names
    of the records removed.
    """
    if not parent_run_id:
        return []
    removed = []
    try:
        if not os.path.isdir(SUBAGENT_DIR):
            return []
        for fn in os.listdir(SUBAGENT_DIR):
            if not fn.endswith(".json"):
                continue
            p = os.path.join(SUBAGENT_DIR, fn)
            try:
                from longrun.util.fswrite import read_json
                rec = read_json(p, None) or {}
            except Exception:  # noqa: BLE001
                continue
            if rec.get("parent") == parent_run_id:
                try:
                    os.remove(p)
                    removed.append("subagent:" + fn[:-len(".json")])
                except OSError:
                    pass
    except Exception:  # noqa: BLE001 — cleanup must not break the delete
        pass
    # M8: the per-run spawn budget dies with the parent run.
    with _lock:
        _SPAWN_COUNT.pop(parent_run_id, None)
    return removed


def _shrink(result):
    """The persisted slice of a run result: status/summary kept, trace counted."""
    result = result or {}
    return {
        "ok": result.get("status") == "done",
        "status": result.get("status"),
        # The termination is what tells a consumer WHY the run ended: "no_progress"
        # (the anti-spin guard) means there is no usable output, so a Session Job
        # must not treat the disk record as a satisfied dependency (SJ, 2026-10-22).
        "termination": result.get("termination"),
        "error": str(result.get("error") or "")[:500],
        "summary": str(result.get("summary") or "")[:_MAX_SUMMARY],
        "steps": len(result.get("trace") or []),
    }


def depth_of(run_id):
    """Depth of a run: 0 for top-level, +1 for each delegated level."""
    return _DEPTH.get(run_id, 0)


def depth_allowed(depth, max_depth=None):
    """True se si puo' ancora annidare (matrioska) sotto `depth` livelli."""
    from longrun.plan import keepgoing
    md = int(keepgoing.cfg()["subagent_max_depth"])
    if max_depth is not None:
        md = int(max_depth)
    return int(depth) < md


def spawn(goal, parent_run_id=None, max_steps=4, model=None, on_event=None, depth=0,
          role=None, output_schema=None, acceptance_criteria=None):
    """Spawn a subagent run and return its id.

    The subagent runs asynchronously in a background thread. Call
    `collect(subagent_id)` to get the result (blocks until done).

    JAG-451: `role` attaches a named brief (config/subagents.yaml) as the
    subagent's standing instruction. The subagent has its OWN isolated context —
    it sees ONLY this goal (+ the role brief), never the parent's transcript.

    M1: `output_schema` (a JSON Schema dict or JSON string) is coerced BEFORE
    anything is spawned — a malformed schema is rejected with an error dict and
    no thread/run is created. A valid schema appends the OUTPUT CONTRACT to the
    child goal; `collect` validates the result and runs exactly one repair turn.

    M8b1: `acceptance_criteria` (a list of predicate strings, see
    `agent/acceptance.py`) is normalized here and evaluated in `collect`
    against the child's trace. The verdict is attached, never fatal.

    Returns a dict with subagent_id (caller should store it).
    """
    # M1: reject a malformed contract before the run exists.
    schema, schema_error = None, None
    if output_schema is not None:
        schema, schema_error = _structured.coerce_schema(output_schema)
        if schema_error:
            return {"subagent_id": None, "run_id": None, "goal": goal,
                    "error": "output_schema invalid: %s" % schema_error}
        goal = "%s\n\n%s" % (goal, _structured.contract_block(schema))
    # M8b1: normalize the acceptance predicates (cap + truncate, pure).
    criteria = _acceptance.normalize(acceptance_criteria)
    # JAG-451: prepend the role brief so the subagent's instruction is self-contained.
    _brief = role_brief(role) if role else ""
    if _brief:
        goal = "[role: %s] %s\n\n%s" % (role, _brief, goal)
    fallbacks = []
    if not model:
        # JAG-259: honour an explicitly pinned "subagent" role model (Settings ->
        # Models) before the role pattern, so the WebUI setting actually applies.
        try:
            from longrun.model import routing
            model = routing.role_model("subagent") or routing.pick("subagent")
            # JAG-448: a real failover chain for cloud subagent models (literal
            # provider:model refs from config, never hardcoded).
            fallbacks = routing.model_chain("subagent")[1:]
        except Exception:  # noqa: BLE001 — routing must never block a spawn
            model = None
    if not depth_allowed(depth):
        return {"subagent_id": None, "run_id": None, "goal": goal,
                "error": "max subagent depth reached"}
    # JAG-451: enforce the configured parallel cap (0 = no cap).
    try:
        _cap = int(load_cfg().get("max_parallel") or 0)
    except (TypeError, ValueError):
        _cap = 0
    if _cap and _running_count() >= _cap:
        return {"subagent_id": None, "run_id": None, "goal": goal,
                "error": "max parallel subagents reached (%d)" % _cap}
    # M8: enforce the per-run spawn budget (0 = no cap). A None parent is
    # never counted. The count increments only on a spawn that passes every
    # gate below, so refusals never consume the budget. F1: the count is LIVE
    # (freed when the child ends in _run below), so the budget bounds
    # CONCURRENT children per parent session — not total spawns ever. A
    # looping parent is still caught by the no-progress + frequency guards.
    try:
        _run_cap = int(load_cfg().get("max_per_run", 6) or 0)
    except (TypeError, ValueError):
        _run_cap = 0
    if _run_cap and parent_run_id:
        with _lock:
            if _SPAWN_COUNT.get(parent_run_id, 0) >= _run_cap:
                return {"subagent_id": None, "run_id": None, "goal": goal,
                        "error": "max subagents per run reached (%d)" % _run_cap}
    sid = "sub_%s" % uuid.uuid4().hex[:10]
    st = api_v02.new_run("%s (subagent %s)" % (goal[:80], sid), model, max_steps)
    st.parent_run_id = parent_run_id
    # I-1: the role's tool scope rides on the RUN, so every call path (single,
    # batch, retry, subjob) reads the same value instead of re-reading config.
    st.role = role
    st.tool_allow = role_tools(role)
    _DEPTH[st.id] = int(depth)
    taskgraph.ensure(st.id, session_id=st.id, goal=goal)

    entry = {
        "id": sid,
        "state": st,
        "goal": goal,
        "max_steps": max_steps,
        "model": model,
        "role": role,
        "parent_run_id": parent_run_id,
        "output_schema": schema,
        "acceptance_criteria": criteria,
        "schema_retries": 0,
        "created": time.time(),
        "result": None,
        "done": threading.Event(),
    }

    with _lock:
        _running[sid] = entry
        # M8: count the successful spawn against the parent's budget.
        if parent_run_id and _run_cap:
            _SPAWN_COUNT[parent_run_id] = _SPAWN_COUNT.get(parent_run_id, 0) + 1
            if len(_SPAWN_COUNT) > _SPAWN_COUNT_MAX_PARENTS:
                _SPAWN_COUNT.clear()
                _SPAWN_COUNT[parent_run_id] = 1
    # JAG-533/SJ: the durable twin of `_running[sid]`, so the result survives the
    # process. Rewritten on completion with the terminal status + summary.
    _persist({
        "id": sid, "run_id": st.id, "goal": goal, "max_steps": max_steps,
        "model": model, "role": role, "parent": parent_run_id,
        "output_schema": schema,
        "acceptance_criteria": criteria,
        "status": "running", "created": round(entry["created"], 3),
    })

    def _run():
        try:
            from longrun.core.server import publish as _publish
            _publish("subagent.start", subagent_id=sid, parent=parent_run_id,
                     goal=goal, max_steps=max_steps, model=model)
        except Exception:
            pass
        # JAG-431r4b: a crash in the child run used to kill this thread SILENTLY —
        # `done` was never set, the parent blocked for the full SUBAGENT_WAIT and
        # reported a bogus "subagent timeout". Always complete the handshake.
        try:
            result = api_v02.agent_run_v2(
                goal, max_steps, model, on_event=on_event, run_id=st.id,
                fallbacks=fallbacks)
            entry["result"] = result
            status_txt = result.get("status")
            steps_n = len(result.get("trace", []))
        except Exception as e:  # noqa: BLE001 — the parent must see the failure
            entry["result"] = {"ok": False, "status": "error", "error": str(e),
                               "summary": "subagent crashed: %s" % e, "trace": []}
            status_txt, steps_n = "error", 0
        finally:
            # F1: the per-run budget counts LIVE subagents, not total spawns —
            # free the slot when the child ends even if nobody collects it.
            # Decrement BEFORE signalling done, so a woken collector (or a new
            # spawn right after) always sees the freed budget. Floor at zero:
            # purge_parent may have cleared the dict meanwhile.
            if parent_run_id and _run_cap:
                with _lock:
                    _left = _SPAWN_COUNT.get(parent_run_id, 1) - 1
                    if _left <= 0:
                        _SPAWN_COUNT.pop(parent_run_id, None)
                    else:
                        _SPAWN_COUNT[parent_run_id] = _left
            entry["done"].set()
        _persist({
            "id": sid, "run_id": st.id, "goal": goal, "max_steps": max_steps,
            "model": model, "role": role, "parent": parent_run_id,
            "status": status_txt or "error", "created": round(entry["created"], 3),
            "ended": round(time.time(), 3), **_shrink(entry.get("result")),
        })
        try:
            from longrun.core.server import publish as _publish
            _publish("subagent.done", subagent_id=sid, parent=parent_run_id,
                     goal=goal, status=status_txt, steps=steps_n)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True, name="subagent-%s" % sid).start()
    _publish_event(parent_run_id, "subagent.spawned",
                   subagent_id=sid, goal=goal, max_steps=max_steps, model=model)
    return {"subagent_id": sid, "run_id": st.id, "goal": goal}


def _repair_once(entry, errors, timeout):
    """One sibling repair run for a schema-violating result (M1).

    The repair is a NEW sibling run (same parent, same depth — not a child) whose
    goal is the retry message plus the original task; it carries NO schema, so it
    can never repair-recurse. Returns the repair's collect dict, or None when the
    repair itself could not complete (the original invalid result then stands —
    a run never fails for schema).
    """
    try:
        rep_goal = (_structured.retry_message(errors)
                    + "\n\nOriginal task (the OUTPUT CONTRACT above still applies):\n"
                    + str(entry.get("goal") or ""))
        st = entry.get("state")
        rep = spawn(rep_goal, parent_run_id=entry.get("parent_run_id"),
                    max_steps=entry.get("max_steps") or 4,
                    model=entry.get("model"),
                    depth=_DEPTH.get(st.id, 0) if st is not None else 0,
                    role=entry.get("role"))
        if not rep.get("subagent_id"):
            return None
        got = collect(rep.get("subagent_id"), timeout=timeout)
        return got if got and got.get("ok") else None
    except Exception:  # noqa: BLE001 — repair is best-effort
        return None


def collect(subagent_id, timeout=None):
    """Wait for a subagent to finish and return the result.

    If timeout is None, blocks indefinitely (the main agent loop has a
    max_steps counter, so this is bounded in practice).

    Returns: {"ok": bool, "result": ..., "trace": [...], "summary": str}
    """
    with _lock:
        entry = _running.get(subagent_id)
    if entry is None:
        # JAG-533/SJ: the run may have finished in a PREVIOUS process (a restart
        # dropped `_running`). Serve the durable record instead of "not found",
        # so a Session Job's dependency can still read its input after a restart.
        rec = load_record(subagent_id)
        if rec and rec.get("status") not in (None, "running"):
            _fschema = rec.get("output_schema")
            _fvalid, _ferrs = None, []
            if _fschema is not None:
                _, _ferrs = _structured.validate_text(
                    str(rec.get("summary") or ""), _fschema)
                _fvalid = not _ferrs
            # M8b1: from-disk has no trace, so execution-anchored predicates
            # evaluate as violated — file predicates still work. Same shape.
            _facc = _acceptance.check_predicates(
                rec.get("acceptance_criteria") or [], [])
            return {"ok": rec.get("status") == "done", "status": rec.get("status"),
                    "result": dict(rec), "trace": [],
                    "summary": str(rec.get("summary") or ""),
                    "steps": rec.get("steps") or 0,
                    "subagent_id": subagent_id, "from_disk": True,
                    "schema_valid": _fvalid, "schema_errors": _ferrs,
                    "schema_retries": 0,
                    "acceptance": _facc,
                    "acceptance_ok": _acceptance.all_hold(_facc)}
        return {"ok": False, "error": "subagent %r not found" % subagent_id,
                "schema_valid": None, "schema_errors": [], "schema_retries": 0}
    if not entry["done"].wait(timeout=timeout):
        return {"ok": False, "error": "subagent timeout", "subagent_id": subagent_id,
                "schema_valid": None, "schema_errors": [], "schema_retries": 0}
    # JAG-431r4b: pop the finished entry — _running/_DEPTH kept every completed
    # subagent forever (status() listed dead runs; both dicts grew unboundedly).
    with _lock:
        done_entry = _running.pop(subagent_id, None)
        if done_entry is not None:
            st = done_entry.get("state")
            if st is not None:
                _DEPTH.pop(st.id, None)
    result = entry["result"] or {}
    summary = result.get("summary", "")
    # M1: validate a schema-bound result; exactly one sibling repair turn.
    # No schema -> untouched shape plus null markers. A run never fails
    # for schema: the raw text stands with schema_valid False.
    schema = entry.get("output_schema")
    schema_valid, schema_errors, schema_retries = None, [], 0
    if schema is not None:
        _, schema_errors = _structured.validate_text(str(summary or ""), schema)
        schema_valid = not schema_errors
        if not schema_valid and not entry.get("schema_retries"):
            entry["schema_retries"] = 1
            schema_retries = 1
            rep = _repair_once(entry, schema_errors, timeout)
            if rep is not None:
                result = rep.get("result") or result
                summary = rep.get("summary", summary)
                _, schema_errors = _structured.validate_text(
                    str(summary or ""), schema)
                schema_valid = not schema_errors
    parent_run_id = entry.get("parent_run_id")
    # M8b1: acceptance verdict — evaluated in code against the child's trace,
    # attached like M1's schema verdict. Never fatal: a violated claim marks
    # the result UNVERIFIED, it never fails the run.
    criteria = entry.get("acceptance_criteria") or []
    acceptance = _acceptance.check_predicates(criteria, result.get("trace") or [])
    acceptance_ok = _acceptance.all_hold(acceptance)
    if parent_run_id and summary:
        try:
            graph = taskgraph.load(parent_run_id)
            child_run_id = entry.get("state").id if entry.get("state") else None
            if graph and child_run_id:
                for n in graph.get("nodes", []):
                    if n.get("child_run_id") == child_run_id:
                        taskgraph.update_node(
                            graph, n["id"],
                            evidence="[subagent] " + str(summary)[:400])
                        break
        except Exception:
            pass
    return {
        "ok": result.get("status") == "done",
        "status": result.get("status"),
        "result": result,
        "trace": result.get("trace", []),
        "summary": summary,
        "steps": len(result.get("trace", [])),
        "subagent_id": subagent_id,
        "schema_valid": schema_valid,
        "schema_errors": schema_errors,
        "schema_retries": schema_retries,
        "acceptance": acceptance,
        "acceptance_ok": acceptance_ok,
    }


def status(subagent_id=None):
    """List running / recent subagents, or one by id."""
    with _lock:
        if subagent_id:
            e = _running.get(subagent_id)
            if not e:
                # JAG-533/SJ: fall back to the durable record (post-restart).
                rec = load_record(subagent_id)
                if not rec:
                    return None
                return {
                    "id": rec.get("id"),
                    "goal": str(rec.get("goal") or "")[:120],
                    "state": rec.get("status") or "unknown",
                    "done": rec.get("status") not in (None, "running"),
                    "created": rec.get("created"),
                    "from_disk": True,
                }
            return {
                "id": e["id"],
                "goal": e["goal"][:120],
                "state": e["state"].status if e["state"] else "unknown",
                "done": e["done"].is_set(),
                "created": e["created"],
            }
        return [{
            "id": e["id"],
            "goal": e["goal"][:80],
            "state": e["state"].status if e["state"] else "unknown",
            "done": e["done"].is_set(),
            "created": e["created"],
        } for e in sorted(_running.values(), key=lambda x: x["created"], reverse=True)]


def _publish_event(run_id, kind, **data):
    try:
        from longrun.core.server import publish
        publish(kind, run_id=run_id, **data)
    except Exception:
        pass


def observation_formatter(result, max_chars=1200):
    """Format a subagent result as an agent observation string."""
    if result.get("ok"):
        return ("[subagent] status=%s summary=%s steps=%d trace_bytes=%d"
                % (result.get("status"), result.get("summary", "")[:160],
                   result.get("steps"), len(json.dumps(result.get("trace", [])))))
    return "[subagent] ERROR: %s" % result.get("error", "unknown")
