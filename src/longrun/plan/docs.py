"""Plan and spec documents written to the project, with the existing plan gate.

`/plan` and `/spec` are REVIEWED ARTIFACTS, not chat prose and not the todo list:
the document is written under `<workspace>/.longrun/documents/`, the session is
locked with `stores.set_plan_mode` (mutating tools are refused by
`registry.classify`), and the operator approves or rejects from the plan bar.

The task graph (`/api/plan`, todos) is a DIFFERENT object and is never touched
here. The document is the intent/decision truth; the graph is execution state.

Layout (configurable in `config/documents.yaml`):

    <workspace>/.longrun/documents/plans/<slug>-<YYYY-MM-DD>.md
    <workspace>/.longrun/documents/specs/<slug>/spec.md
    <workspace>/.longrun/documents/specs/<slug>/tasks.md
    <workspace>/.longrun/documents/specs/<slug>/checklist.md

`paths.workspace_state_dir` leaves the `documents/` entry in place when it
adopts a legacy `<ws>/.longrun` (see util/paths.py), so a deliverable is never
moved into the data home.
"""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
import uuid

import yaml

from longrun.util import fswrite, paths

ROOT_DEFAULT = ".longrun/documents"
_COMPONENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_DEFAULTS = {"root": ROOT_DEFAULT, "plans": "plans", "specs": "specs",
             "max_bytes": 262144}
SPEC_FILES = ("spec.md", "tasks.md", "checklist.md")
_LOCK = threading.RLock()


# --------------------------------------------------------------------- config --

def _config_path():
    return os.path.join(paths.REPO_ROOT, "config", "documents.yaml")


def load_config():
    """The live documents config, with defaults for every missing/bad key."""
    out = dict(_DEFAULTS)
    try:
        with open(_config_path(), encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        sec = doc.get("documents") if isinstance(doc, dict) else None
        if isinstance(sec, dict):
            for key in out:
                if sec.get(key) is not None:
                    out[key] = sec[key]
    except (OSError, yaml.YAMLError):
        pass
    out["root"] = str(out.get("root") or ROOT_DEFAULT).strip() or ROOT_DEFAULT
    for key in ("plans", "specs"):
        val = str(out.get(key) or _DEFAULTS[key]).strip().lower()
        out[key] = val if _COMPONENT.match(val) else _DEFAULTS[key]
    try:
        out["max_bytes"] = max(4096, min(int(out.get("max_bytes") or 0), 2 * 1024 * 1024))
    except (TypeError, ValueError):
        out["max_bytes"] = _DEFAULTS["max_bytes"]
    return out


# ------------------------------------------------------------------ workspace --

def _session(session):
    sid = str(session or "").strip()
    if not sid:
        return None, ""
    try:
        from longrun.memory import stores
        return stores.load_session(sid), sid
    except Exception:  # noqa: BLE001 \u2014 an unreadable session is "no session"
        return None, sid


def _workspace(session):
    sess, _sid = _session(session)
    ws = str((sess or {}).get("workspace") or "").strip()
    if not ws:
        try:
            from longrun.memory import rules
            ws = rules.get_workspace()
        except Exception:  # noqa: BLE001
            ws = ""
    return os.path.abspath(os.path.expanduser(ws)) if ws else ""


def _root(session):
    """The documents root, boundary-checked against the session workspace."""
    ws = _workspace(session)
    if not ws:
        raise ValueError("this session has no workspace")
    cfg = load_config()
    raw = os.path.expanduser(str(cfg["root"]))
    base = raw if os.path.isabs(raw) else os.path.join(ws, raw)
    base = os.path.abspath(base)
    if not fswrite.path_under(base, ws):
        raise ValueError("documents root must stay inside the workspace: %s" % cfg["root"])
    return base


def docs_root(session):
    return _root(session)


def plan_dir(session):
    return os.path.join(_root(session), load_config()["plans"])


def spec_dir(session):
    return os.path.join(_root(session), load_config()["specs"])


def config_view(session=""):
    """`GET /api/slash` sees this: absolute paths when a workspace exists."""
    cfg = load_config()
    out = {"root": cfg["root"], "plans": cfg["plans"], "specs": cfg["specs"],
           "rel_root": cfg["root"], "max_bytes": cfg["max_bytes"]}
    try:
        base = _root(session)
        out.update(root=base, plans=os.path.join(base, cfg["plans"]),
                   specs=os.path.join(base, cfg["specs"]),
                   workspace=_workspace(session))
    except Exception as exc:  # noqa: BLE001 \u2014 the menu still works without a session
        out["error"] = str(exc)
    return out


# ------------------------------------------------------------------- documents --

SLUG_MAX = 48


def slug(text, fallback="untitled"):
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    if len(s) > SLUG_MAX:
        # 2026-11-28 (operator): never split a word — back off to the last dash of
        # the budget, so a name reads `adotta-le-capacita-...`, never `...-le-co`.
        s = s[:SLUG_MAX]
        cut = s.rfind("-")
        if cut >= SLUG_MAX // 2:
            s = s[:cut]
    return s.strip("-") or fallback


def _title(md, fallback):
    m = re.match(r"\s*#\s+(.+?)\s*$", str(md or ""), re.M)
    return (m.group(1).strip()[:160] if m else str(fallback or "document")[:160])


# The section word the doc prompts put around the title (`# Plan — <title>` but
# `# <title> — Spec`); it is not part of the subject, so the name drops it either way.
_DOC_PREFIX = re.compile(r"^\s*(plan|spec|tasks|checklist)\s*[\u2014\u2013:-]\s*", re.I)
_DOC_SUFFIX = re.compile(r"\s*[\u2014\u2013:-]\s*(plan|spec|tasks|checklist)\s*$", re.I)


def _doc_name(title, fallback):
    """A file/folder name from the document's OWN title (the LLM's heading).

    2026-11-28 (operator): "il titolo piano lo da l LLM" — a plan/spec must name
    itself from the title the model writes, NOT from a 48-char slug of the raw
    request (which read as `...-le-co`). A missing heading falls back to the ask.
    """
    t = str(title or "").strip()
    t = _DOC_PREFIX.sub("", t)
    t = _DOC_SUFFIX.sub("", t)
    return slug(t, fallback=slug(fallback))


def _steps_from(md):
    """Numbered steps under a Steps/Tasks heading, else any numbered line (bounded)."""
    lines = str(md or "").splitlines()
    out, inside = [], False
    for line in lines:
        s = line.strip()
        if re.match(r"^#{1,3}\s+(steps|tasks|task list)\b", s, re.I):
            inside = True
            continue
        if inside and re.match(r"^#{1,3}\s+", s):
            break
        if inside:
            m = re.match(r"^(?:\d+[.)])\s+(.+)$", s)
            if m:
                out.append(m.group(1).strip()[:200])
    if not out:
        for line in lines:
            m = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
            if m:
                out.append(m.group(1).strip()[:200])
            if len(out) >= 20:
                break
    return [x for x in out if x][:20]


def _bounded_write(path, text):
    body = str(text or "")
    if not body.strip():
        raise ValueError("the generator returned an empty document")
    if len(body.encode("utf-8")) > load_config()["max_bytes"]:
        raise ValueError("document exceeds max_bytes (%d)" % load_config()["max_bytes"])
    fswrite.write_text(path, body)
    return path


def _unique_plan_path(folder, base):
    path = os.path.join(folder, base + ".md")
    if not os.path.exists(path):
        return path
    for i in range(2, 1000):
        path = os.path.join(folder, "%s-%d.md" % (base, i))
        if not os.path.exists(path):
            return path
    raise ValueError("too many plan files for this slug")


def _unique_folder(folder, name):
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        return path
    for i in range(2, 1000):
        path = os.path.join(folder, "%s-%d" % (name, i))
        if not os.path.exists(path):
            return path
    raise ValueError("too many spec folders for this slug")


def _sweep_tmp(folder):
    """Remove a `.tmp-*` set left by a hard kill (service restart mid-write).

    The three files are written into a temp folder and renamed only when all of
    them exist, so a killed writer leaves `.tmp-<uuid>` behind and never a
    half-spec under the real name. Nothing else writes this folder while `_LOCK`
    is held, so any `.tmp-*` seen here is stale garbage from a dead writer.
    """
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        if not name.startswith(".tmp-"):
            continue
        path = os.path.join(folder, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def _context(session, kind, extra=""):
    """A small, honest context block: the planner has no tools to inspect files.

    `extra` is the CALLER's own notes (the `docs` tool can pass what it read);
    it is bounded and labelled as unverified, never mixed with the facts below.
    """
    sess, sid = _session(session)
    ws = _workspace(session)
    lines = ["DOCUMENT KIND: %s" % kind,
             "WORKSPACE: %s" % (ws or "(none)"),
             "SESSION: %s" % (sid or "(none)")]
    if sess:
        lines.append("SESSION TITLE: %s" % str(sess.get("title") or "")[:160])
    if ws and os.path.isdir(ws):
        try:
            names = sorted(n for n in os.listdir(ws) if not n.startswith("."))[:40]
            lines.append("TOP-LEVEL ENTRIES: " + ", ".join(
                n + ("/" if os.path.isdir(os.path.join(ws, n)) else "") for n in names))
        except OSError:
            pass
    try:
        base = _root(session)
        cfg = load_config()
        for sub in (cfg["plans"], cfg["specs"]):
            d = os.path.join(base, sub)
            if os.path.isdir(d):
                rows = sorted(os.listdir(d))[-10:]
                lines.append("EXISTING %s: %s" % (sub.upper(), ", ".join(rows) or "(none)"))
    except Exception:  # noqa: BLE001
        pass
    lines.append("You have NOT inspected these files. Do not invent paths; mark every "
                 "unverified claim as ASSUMPTION.")
    text = "\n".join(lines)[:4096]
    notes = str(extra or "").strip()
    if notes:
        text += ("\n\nAGENT NOTES (supplied by the caller; unverified by the planner):\n"
                 + notes[:8192])
    return text


def _record(sid, doc, steps, origin="composer"):
    from longrun.memory import stores
    # ONE write: the proposal and its lock land together. The INTENT is derived
    # from the origin, never from prose: the composer's `/plan`/`/spec` and the
    # CLI ask for a DOCUMENT; the agent's `docs` tool is acting and asks to
    # implement (operator: "if the user asked only to plan or spec then no need
    # to proceed to implement").
    intent = "implement" if origin == "tool" else "document"
    stores.propose_plan(sid, steps, doc=doc, lock=True, origin=origin, intent=intent)
    return intent


def _policy():
    """The operator's document-auto policy, read from the ONE config.

    `mode=full` auto-approves the CONTENT of every document as it is created (the
    operator: "if approval in full the over msg box shall be approved
    automatically"). `auto_implement_documents` — the checkbox "auto-approve
    plans and specs" — is the SECOND check: it also authorises the
    implementation, and only for a request whose intent is `implement`.
    """
    try:
        from longrun.tools import registry as _reg
        ap = (_reg.load_config() or {}).get("approvals") or {}
    except Exception:  # noqa: BLE001 — a broken config never blocks a document
        return {"full": False, "auto_implement": False}
    full = str(ap.get("mode", "normal")).lower() in ("full", "auto", "yolo")
    return {"full": full, "auto_implement": bool(ap.get("auto_implement_documents"))}


def _decide_by_policy(sid, origin, intent):
    """Apply `approvals.mode` to the document just written. Returns the decision.

    One place, so the composer, the CLI, the `docs` tool and the RH inbox inherit
    the same rule with no surface-specific branch (operator: "i dont want to
    duplicate things … agents calls of commands are subject to the approval laws").
    """
    pol = _policy()
    if not pol["full"]:
        return {"ok": True, "auto": False, "implement": False}
    implement = bool(pol["auto_implement"] and intent == "implement")
    try:
        from longrun.memory import stores
        stores.approve_plan(sid, implement=implement, by="policy:approvals.mode=full")
    except Exception as exc:  # noqa: BLE001 — a policy failure must leave the doc proposed
        return {"ok": False, "auto": False, "implement": False, "error": str(exc)}
    return {"ok": True, "auto": True, "implement": implement,
            "by": "policy:approvals.mode=full"}


def _generate_plan_doc(goal, model=None, context=""):
    """The ONE planner entry for a plan document (tests stub exactly this)."""
    from longrun.agent import agent as _agent
    return _agent.generate_plan_doc(goal, model, context)


def _generate_spec_docs(goal, model=None, context=""):
    """The ONE planner entry for a spec set (tests stub exactly this)."""
    from longrun.agent import agent as _agent
    return _agent.generate_spec_docs(goal, model, context)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------------- one writer at a time --
# A document write is `load_session -> mutate -> save_session`; a chat turn writes
# the SAME session object. Two concurrent writers would let the later `save_session`
# drop the messages the other one appended (an autonomous run has nobody to notice),
# so every document mutation refuses to run while that session's turn is in flight,
# and a second generate for the same session is refused instead of paying for a
# second model call and overwriting the first record.
_INFLIGHT = set()
_INFLIGHT_LOCK = threading.Lock()


def _turn_active(sid):
    """The chat turn in flight for `sid` (stub point in tests). Never raises."""
    try:
        from longrun.core import events
        return bool(events.turn_active(sid))
    except Exception:  # noqa: BLE001 — the probe must never block a document
        return False


def _refuse_if_busy(sid, verb="write a document", owner=False):
    # `owner=True` is the TOOL path: the caller is the turn that owns this session
    # and the document fields are recorded as live (`stores.LIVE_DOC_FIELDS`), so
    # the turn's own final save re-applies them instead of dropping them.
    if owner:
        return
    if _turn_active(sid):
        raise ValueError(
            "a chat turn is running in this session — let it finish, then %s" % verb)


class _Generating:
    """One generation per session: the second caller is refused, not queued."""

    def __init__(self, sid):
        self.sid = sid

    def __enter__(self):
        with _INFLIGHT_LOCK:
            if self.sid in _INFLIGHT:
                raise ValueError(
                    "a document is already being generated for this session — wait for it")
            _INFLIGHT.add(self.sid)
        return self

    def __exit__(self, *exc):
        with _INFLIGHT_LOCK:
            _INFLIGHT.discard(self.sid)
        return False


# ---------------------------------------------------------------------- create --

def create_plan(session, prompt, model=None, extra_context="", owner=False,
                origin="composer"):
    """Generate one markdown plan, write it, propose it and lock the session.

    `origin` (`composer|tool|cli`) decides the INTENT: only the agent's tool acts
    on the document, so only `tool` can be auto-authorised to implement it.
    """
    sess, sid = _session(session)
    if not sess:
        raise ValueError("unknown session: %s" % (session or ""))
    ask = str(prompt or "").strip()
    if not ask:
        raise ValueError("prompt required")
    folder = plan_dir(sid)          # validate the destination BEFORE a model call
    _refuse_if_busy(sid, owner=owner)
    with _Generating(sid), _LOCK:
        md, used_model = _generate_plan_doc(ask, model, _context(sid, "plan", extra_context))
        os.makedirs(folder, exist_ok=True)
        # 2026-11-28 (operator): the plan NAMES itself from the title the LLM writes
        # (`# Plan — <title>`), never from a truncated slug of the request.
        title = _title(md, ask)
        base = "%s-%s" % (_doc_name(title, ask), time.strftime("%Y-%m-%d"))
        path = _unique_plan_path(folder, base)
        try:
            _bounded_write(path, md)
            steps = _steps_from(md) or ["review %s" % path]
            doc = {"kind": "plan", "title": title, "path": path,
                   "folder": os.path.dirname(path), "documents": [path],
                   "workspace": _workspace(sid), "created": _now(), "status": "proposed",
                   "model": used_model, "rel_path": _safe_rel(path, sid)}
            intent = _record(sid, doc, steps, origin=origin)
            pol = _decide_by_policy(sid, origin, intent)
        except Exception:
            try:
                os.remove(path)
            except OSError:
                pass
            raise
    live = status(sid)
    active = live.get("active") or {}
    return {"ok": True, "kind": "plan", "title": doc["title"], "path": path,
            "rel_path": doc["rel_path"], "lines": len(md.splitlines()),
            "excerpt": "\n".join(md.splitlines()[:40]),
            "steps": steps, "plan_mode": bool(live.get("plan_mode")),
            "status": active.get("status") or "proposed",
            "implement": bool(active.get("implement")),
            "auto": pol.get("auto"), "origin": origin,
            "model": used_model}


def create_spec(session, prompt, model=None, extra_context="", owner=False,
                origin="composer"):
    """Generate spec.md + tasks.md + checklist.md in ONE folder, atomically."""
    sess, sid = _session(session)
    if not sess:
        raise ValueError("unknown session: %s" % (session or ""))
    ask = str(prompt or "").strip()
    if not ask:
        raise ValueError("prompt required")
    folder = spec_dir(sid)          # validate the destination BEFORE any model call
    _refuse_if_busy(sid, owner=owner)
    with _Generating(sid), _LOCK:
        docs, used_model = _generate_spec_docs(ask, model, _context(sid, "spec", extra_context))
        if not isinstance(docs, dict):
            raise ValueError("the generator returned no documents")
        missing = [n for n in SPEC_FILES if not str((docs or {}).get(n) or "").strip()]
        if missing:
            raise ValueError("the generator did not return %s" % ", ".join(missing))
        os.makedirs(folder, exist_ok=True)
        _sweep_tmp(folder)
        # 2026-11-28 (operator): the spec folder NAMES itself from the LLM's title.
        title = _title(docs["spec.md"], ask)
        final = _unique_folder(folder, _doc_name(title, ask))
        tmp = os.path.join(folder, ".tmp-%s" % uuid.uuid4().hex)
        try:
            os.makedirs(tmp, exist_ok=False)
            for name in SPEC_FILES:
                _bounded_write(os.path.join(tmp, name), docs[name])
            os.replace(tmp, final)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        spec_md = os.path.join(final, "spec.md")
        steps = _steps_from(docs["tasks.md"]) or ["review %s" % spec_md]
        doc = {"kind": "spec", "title": title, "path": spec_md, "folder": final,
               "documents": [os.path.join(final, n) for n in SPEC_FILES],
               "workspace": _workspace(sid), "created": _now(), "status": "proposed",
               "model": used_model, "rel_path": _safe_rel(spec_md, sid)}
        try:
            intent = _record(sid, doc, steps, origin=origin)
            pol = _decide_by_policy(sid, origin, intent)
        except Exception:
            shutil.rmtree(final, ignore_errors=True)
            raise
    live = status(sid)
    active = live.get("active") or {}
    return {"ok": True, "kind": "spec", "title": title, "path": spec_md,
            "folder": final, "rel_path": doc["rel_path"],
            "documents": [{"name": n, "path": os.path.join(final, n),
                           "rel_path": _safe_rel(os.path.join(final, n), sid)}
                          for n in SPEC_FILES],
            "lines": sum(len(docs[n].splitlines()) for n in SPEC_FILES),
            "excerpt": "\n".join(docs["spec.md"].splitlines()[:40]),
            "steps": steps, "plan_mode": bool(live.get("plan_mode")),
            "status": active.get("status") or "proposed",
            "implement": bool(active.get("implement")),
            "auto": pol.get("auto"), "origin": origin,
            "model": used_model}


def _safe_rel(path, sid):
    ws = _workspace(sid)
    try:
        return os.path.relpath(path, ws) if ws else path
    except ValueError:
        return path


# --------------------------------------------------------------------- status --

def status(session):
    sess, sid = _session(session)
    if not sess:
        raise ValueError("unknown session: %s" % (session or ""))
    plan = sess.get("plan") or {}
    doc = plan.get("doc") if isinstance(plan.get("doc"), dict) else None
    out = {"ok": True, "session": sid, "plan_mode": bool(sess.get("plan_mode")),
           "status": plan.get("status") or "", "active": None,
           "docs": config_view(sid)}
    if doc:
        path = str(doc.get("path") or "")
        exists = bool(path and os.path.isfile(path))
        excerpt = ""
        if exists:
            try:
                with open(path, "rb") as f:
                    excerpt = f.read(8192).decode("utf-8", errors="replace")
            except OSError:
                exists = False
        active = dict(doc)
        active["status"] = plan.get("status") or active.get("status") or ""
        active["implement"] = bool(plan.get("implement"))
        active["origin"] = plan.get("origin") or ""
        active["intent"] = plan.get("intent") or ""
        active["decided_by"] = plan.get("decided_by") or ""
        active["decided_ts"] = plan.get("decided_ts")
        active["exists"] = exists
        active["stale"] = not exists
        active["excerpt"] = excerpt
        out["active"] = active
    return out


def _decide(session, status_value):
    from longrun.memory import stores
    sess, sid = _session(session)
    if not sess:
        raise ValueError("unknown session: %s" % (session or ""))
    plan = sess.get("plan") or {}
    doc = plan.get("doc")
    if isinstance(doc, dict):
        doc = dict(doc)
        doc["status"] = status_value
        doc["decided_at"] = _now()
        plan["doc"] = doc
        sess["plan"] = plan
        # The live value is what the running turn's final save re-applies; it must
        # carry the decision timestamp too, or that save would drop it.
        stores.live_fields_changed(sid, plan=plan)
        stores.save_session(sess)
    return status(sid)


def approve(session, implement=False):
    """Approve the document's CONTENT; `implement=True` also opens the write gate.

    The two decisions are separate on purpose: approving a spec is not
    authorising the agent to implement it (`stores.grant_implement` is the other).
    """
    from longrun.memory import stores
    _sess, sid = _session(session)
    if not _sess:
        raise ValueError("unknown session: %s" % (session or ""))
    _refuse_if_busy(sid, "approve the document")
    with _LOCK:
        stores.approve_plan(sid, implement=bool(implement), by="operator")
        return _decide(sid, "approved")


def implement(session):
    """Authorise the implementation of an ALREADY approved document (the ▶ act)."""
    from longrun.memory import stores
    _sess, sid = _session(session)
    if not _sess:
        raise ValueError("unknown session: %s" % (session or ""))
    _refuse_if_busy(sid, "authorise the implementation")
    with _LOCK:
        stores.grant_implement(sid)
        return status(sid)


def reject(session, unlock=True):
    from longrun.memory import stores
    _sess, sid = _session(session)
    if not _sess:
        raise ValueError("unknown session: %s" % (session or ""))
    _refuse_if_busy(sid, "reject the document")
    with _LOCK:
        stores.reject_plan(sid)
        if unlock:
            stores.set_plan_mode(sid, False)
        return _decide(sid, "rejected")


def unlock(session):
    """Leave `/plan`/`/spec` mode for good: release the gate AND forget the record.

    The operator must never be stuck in a command's mode (live 2026-11-16: the bar
    stayed for ever after the decision). The FILE stays on disk; only the session's
    record of it goes away, so the next turn is a normal turn. One write.
    """
    from longrun.memory import stores
    sess, sid = _session(session)
    if not sess:
        raise ValueError("unknown session: %s" % (session or ""))
    _refuse_if_busy(sid, "unlock")
    with _LOCK:
        sess["plan_mode"] = False
        sess.pop("plan", None)
        # Final values as live: the next save by any writer (including a running
        # turn's stale copy) must keep the mode off and the record gone.
        stores.live_fields_changed(sid, plan=None, plan_mode=False)
        stores.save_session(sess)
        return status(sid)
