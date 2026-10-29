#!/usr/bin/env python3
"""Self-improvement routing (JAG-128B).

Golden rule (frontier pattern): the agent writes FREELY only to memory;
the RULES (project/global) are written by the human -> the agent at most PROPOSES;
the harness CODE is out of scope.
"""
import time
import os
import re
import json
import uuid

from longrun.util.fswrite import write_json
from longrun.util.paths import REPO_ROOT as REPO, DATA_DIR
# JAG-447: derive from the env-overridable DATA_DIR, so tests run against a
# scratch dir and never pollute the live data/ (same convention as paths.py).
PROPOSAL_DIR = os.path.join(DATA_DIR, "proposals")
# Machine-mined skill DRAFTS (selfevolve stage 1/2). Modules patch DRAFT_DIR in
# tests; one owner for the location so a draft cannot be written in one place and
# looked for in another.
DRAFT_DIR = os.path.join(PROPOSAL_DIR, "skills")

# scope -> write mode allowed to the agent
AGENT_WRITE = {
    "memory": "auto",       # data/memory/**  -> free write (silent)
    "skill": "propose",     # skills/**       -> proposal, threshold
    "project": "propose",   # <data>/projects/<ws>/Project_rules.md -> PROPOSAL only
    "global": "propose",    # <config>/Global_rules.md (~/.longrun/config) -> PROPOSAL only
    "matrix": "propose",    # src/Matrix/** + matrix runtime -> PROPOSAL only (verified bundle)
    "code": "forbidden",    # longrun/*.py -> out of scope
}

# JAG-447: WHERE a self-improvement artifact came from — the segregation key.
# Every improvement product (proposal, mined skill, ledger entry) and every
# memory record carries one of these, so auto-generated knowledge is never
# mixed with what the user actually said.
ORIGINS = ("user", "agent", "reflect", "mining", "harness", "matrix")

_TOOLCALL_THRESHOLD = 5

# JAG-447: the significance gate. A turn must be *worth learning from* — this is
# the Generative-Agents "importance" idea, computed deterministically (never by
# the model, which would inflate its own reward). Below the threshold the turn
# is recorded in the ledger but no lesson is distilled.
IMPORTANCE_THRESHOLD = 5

# JAG-447: the audit ledger — an append-only changelog of everything the
# self-improvement loop did on its own (proposals opened, memories distilled,
# skills mined, proposals decided). It is the answer to "what changed, and was
# it the harness or me?". Bounded so it never grows without limit.
LEDGER_PATH = os.path.join(DATA_DIR, "improvement", "ledger.jsonl")
LEDGER_MAX = 500


def approval_kind(name):
    """JAG-451: the configured approval policy for a category.

    Reads `approvals.kinds.<name>` from the tool registry config (Settings ▸
    Tools & approvals). Returns 'auto' | 'required' | 'denied', or '' when unset
    (callers then keep their own default). Never raises.
    """
    try:
        from longrun.tools import registry
        kinds = (registry.load_config().get("approvals") or {}).get("kinds") or {}
        v = str(kinds.get(name) or "").strip().lower()
        return v if v in ("auto", "required", "denied") else ""
    except Exception:  # noqa: BLE001 — a policy lookup must never break a turn
        return ""


# ------------------------------------------------------------- ledger --------
# JAG-447: the audit ledger. Every improvement artifact the harness produces —
# on its own or because the agent asked — is appended here, with its provenance
# (`origin`) and the file it touched, so the WebUI can show a truthful changelog
# and the operator can always tell auto-generated from hand-written.

def _trim_ledger():
    """Keep the ledger bounded (last LEDGER_MAX lines). Best-effort."""
    try:
        with open(LEDGER_PATH, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > LEDGER_MAX:
            with open(LEDGER_PATH, "w", encoding="utf-8") as f:
                f.writelines(lines[-LEDGER_MAX:])
    except OSError:
        pass


def ledger_add(kind, **fields):
    """Append one improvement event to the audit ledger. Returns the entry.

    `origin` defaults to 'harness' (the loop itself); pass 'reflect'/'mining'/
    'agent'/'user' to say WHERE the artifact came from.
    """
    origin = str(fields.pop("origin", "harness") or "harness")
    entry = {"id": uuid.uuid4().hex[:10], "ts": round(time.time(), 3),
             "kind": str(kind or "event"), "origin": origin}
    entry.update(fields)
    try:
        os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
        with open(LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _trim_ledger()
    except OSError:
        pass
    if origin != "matrix":
        try:
            from longrun.core import matrix as _mtx
            _mtx.call_hook("util", "on_ledger_add", entry, default=None)
        except Exception:  # noqa: BLE001
            pass
    return entry


def ledger_tail(limit=60):
    """The most recent ledger entries, NEWEST FIRST (for the WebUI changelog)."""
    try:
        with open(LEDGER_PATH, encoding="utf-8") as f:
            raw = f.readlines()
    except OSError:
        return []
    out = []
    for line in raw:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    if not out:
        return []
    return out[-int(limit):][::-1]


# ------------------------------------------------------- LLM review (JAG-491) --
# The backlog grows on its own (proposals, distilled lessons, mined skills). Some
# of it becomes stale: a later change implemented the same idea, or a mechanism
# replaced it. This pass asks a REAL model to audit every artifact against the
# CURRENT code (retrieved from the codebase index) and classify it. It is one
# feature used by two callers — the Improvement panel button and the `improve`
# tool — never a second implementation.
REVIEW_DIR = os.path.join(DATA_DIR, "improvement", "reviews")
REVIEW_VERDICTS = ("keep", "implemented", "obsolete", "update", "conflict")
REVIEW_SYSTEM = (
    "You audit a coding agent's self-improvement backlog against the CURRENT "
    "codebase. For EACH artifact decide exactly one verdict:\n"
    "  keep        = still valid, not implemented, worth keeping as is\n"
    "  implemented = the current code already does this (evidence shows it)\n"
    "  obsolete    = superseded by a newer mechanism, or no longer relevant\n"
    "  update      = direction is valid but the wording/scope must change; "
    "write the replacement in `rewritten`\n"
    "  conflict    = contradicts another artifact or the current code\n"
    "Be conservative: without evidence of implementation, do not say "
    "`implemented`. Reply with ONLY a JSON object, no prose, no code fences:\n"
    '{"verdicts":[{"id":"<artifact id>","verdict":"keep|implemented|obsolete|'
    'update|conflict","confidence":0.0,"why":"one sentence",'
    '"rewritten":"new text when verdict=update, else empty"}]}'
)


def _memory_artifacts(limit=200):
    """The memory records that ARE self-improvement artifacts (ONE policy).

    v662: the LLM backlog review and the Improvement panel used to walk
    `memory.query` on their own, with the same three rules copied into both — skip
    user-written memory (the agent writes memory FREELY, so its own notes are not
    harness improvements), skip empty text, and label a record with no origin
    `unattributed`. Two copies of that rule can drift, and then the review audits a
    backlog the panel does not show (or the reverse). Each caller adds the fields it
    needs; WHICH records are in scope is decided only here.
    """
    rows = []
    try:
        from longrun.memory import memory as memory_mod
        for r in memory_mod.query(None, None, limit=max(1, int(limit or 200))):
            origin = str(r.get("source") or r.get("origin") or "").strip()
            if origin == "user":
                continue
            text = str(r.get("content") or "").strip()
            if not text:
                continue
            kind = r.get("kind") or ""
            rows.append({
                "mid": r.get("mid") or "", "ts": r.get("ts"), "kind": kind,
                "origin": origin or "unattributed",
                "session": str(r.get("session") or ""), "text": text,
                "path": "data/memory/" + memory_mod.MEMORY_FIELDS.get(kind, "other.md"),
            })
    except Exception:  # noqa: BLE001 — a memory hiccup must not kill the panel
        pass
    return rows


def _artifact_items(limit=40):
    """Every self-improvement artifact, deduped: proposals then distilled memory.

    Memory written by the USER is out of scope (it is not a harness
    improvement); memory with no origin is kept, labelled `unattributed`.
    """
    items, seen = [], set()
    for p in list_proposals():
        text = str(p.get("content") or "").strip()
        if not text:
            continue
        key = (p.get("scope"), text)
        if key in seen:
            continue
        seen.add(key)
        items.append({"id": p.get("id"), "kind": "proposal",
                      "scope": p.get("scope"), "status": p.get("status"),
                      "origin": p.get("origin") or "agent", "text": text,
                      "reason": str(p.get("reason") or "")[:400],
                      "target": p.get("target_path") or ""})
    for r in _memory_artifacts(200):
        key = ("memory", r["text"])
        if key in seen:
            continue
        seen.add(key)
        items.append({"id": r["mid"], "kind": "memory",
                      "scope": r["kind"], "status": "stored",
                      "origin": r["origin"], "text": r["text"],
                      "reason": "", "target": "data/memory"})
    return items[:max(1, int(limit or 40))]


def _evidence(text, k=3):
    """Codebase snippets that mention this artifact (best effort, no build)."""
    try:
        from longrun.memory import codeindex
        words = list(dict.fromkeys(re.findall(r"[A-Za-z0-9_]{4,}", text)))[:12]
        if not words:
            return []
        res = codeindex.search(REPO, " ".join(words), k=k)
        return [{"path": r.get("path"), "line": r.get("start"),
                 "snippet": (r.get("snippet") or "")[:280]}
                for r in (res.get("results") or [])]
    except Exception:  # noqa: BLE001 — no index must not block a review
        return []


def _parse_verdicts(answer):
    """Extract the verdict list from the verifier's reply (JSON array or `{verdicts:[...]}`)."""
    from longrun.util.textkit import _iter_json_objects as _scan
    for data in _scan(str(answer or "")):
        if isinstance(data, dict):
            data = data.get("verdicts") or data.get("items") or []
        if isinstance(data, list):
            return [v for v in data if isinstance(v, dict)]
    return []


def _review_batch(batch, model):
    """One LLM call for a small batch -> (verdicts, model_used)."""
    from longrun.core import server
    payload = [{"id": it["id"], "kind": it["kind"], "scope": it["scope"],
                "origin": it["origin"], "text": it["text"][:1500],
                "reason": it["reason"], "evidence": it.get("evidence") or []}
               for it in batch]
    msgs = [{"role": "system", "content": REVIEW_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    answer, _think, used = server.stream_with_fallback(
        msgs, model, "reviewer", lambda *_a: None, timeout=180, max_tokens=4000)
    return _parse_verdicts(answer), used


def latest_review():
    """The newest persisted review report (or None)."""
    try:
        names = sorted(f for f in os.listdir(REVIEW_DIR) if f.endswith(".json"))
    except OSError:
        return None
    if not names:
        return None
    try:
        with open(os.path.join(REVIEW_DIR, names[-1]), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save_review(report):
    os.makedirs(REVIEW_DIR, exist_ok=True)
    path = os.path.join(REVIEW_DIR,
                        time.strftime("%Y%m%d-%H%M%S", time.localtime(report["ts"])) + ".json")
    write_json(path, report)
    try:
        names = sorted(f for f in os.listdir(REVIEW_DIR) if f.endswith(".json"))
        for old in names[:-20]:
            os.unlink(os.path.join(REVIEW_DIR, old))
    except OSError:
        pass
    return path


def review(limit=24, model=None, batch=6):
    """Audit the improvement backlog with an LLM against the current code.

    Returns ``{ok, ts, model, counts, items:[...], report}``. Each item keeps its
    original fields plus ``verdict``/``why``/``rewritten``/``evidence``. Nothing
    is applied automatically: `implemented`/`obsolete` are findings, `update`
    carries the proposed replacement, and the human (or the agent) decides.
    """
    items = _artifact_items(limit)
    report = {"ok": True, "ts": time.time(), "model": "", "items": [],
              "counts": {v: 0 for v in REVIEW_VERDICTS}, "unrated": 0}
    if not items:
        report["note"] = "no improvement artifacts to review"
        report["ts"] = time.time()
        report["report"] = _save_review(report)
        return report
    for it in items:
        it["evidence"] = _evidence(it["text"])
    used_models = set()
    try:
        for i in range(0, len(items), max(1, int(batch or 6))):
            chunk = items[i:i + max(1, int(batch or 6))]
            verdicts, used = _review_batch(chunk, model)
            if used:
                used_models.add(str(used))
            by_id = {str(v.get("id")): v for v in verdicts}
            for it in chunk:
                v = by_id.get(str(it["id"])) or {}
                verdict = str(v.get("verdict") or "").strip().lower()
                if verdict not in REVIEW_VERDICTS:
                    verdict = "unknown"
                row = dict(it)
                row["verdict"] = verdict
                try:
                    row["confidence"] = round(float(v.get("confidence") or 0), 2)
                except (TypeError, ValueError):
                    row["confidence"] = 0.0
                row["why"] = str(v.get("why") or "")[:800]
                row["rewritten"] = str(v.get("rewritten") or "")[:4000] \
                    if verdict == "update" else ""
                if verdict == "unknown":
                    report["unrated"] += 1
                else:
                    report["counts"][verdict] += 1
                report["items"].append(row)
    except Exception as e:  # noqa: BLE001 — report what was reviewed so far
        report["ok"] = False
        report["error"] = "%s: %s" % (type(e).__name__, e)
    report["model"] = ", ".join(sorted(used_models))
    report["report"] = _save_review(report)
    if report["items"]:
        try:
            ledger_add("review", origin="reflect", model=report["model"],
                       reviewed=len(report["items"]), counts=report["counts"],
                       path=os.path.relpath(report["report"], REPO))
        except Exception:  # noqa: BLE001 — the audit must not fail the review
            pass
    return report


def _path(pid):
    # JAG-231: `pid` comes from the client (approve/deny). A non-string crashed
    # (`pid + ".json"` -> TypeError, dropping the connection) and a
    # traversal-shaped id could escape the proposals store. Only a plain token
    # ever matches a real proposal id ("<epoch-ms>-<scope>").
    if not isinstance(pid, str) or not re.match(r"^[A-Za-z0-9_-]{1,80}$", pid):
        raise ValueError("invalid proposal id")
    return os.path.join(PROPOSAL_DIR, pid + ".json")


def sweep_drafts():
    """Delete junk drafts (the ONLY owner of when the sweep runs, and where).

    v711: the sweep used to live only in the `improve` tool's mine branch, so
    drafts written by the end-of-turn pass were never pruned — the store held 77
    legacy 2-tool drafts (`min_len` is 3 since v656) that the panel then showed
    as new material. `mine_once` sweeps, so both callers get the same store.
    Never raises.
    """
    try:
        from longrun.util import selfevolve
        return (selfevolve.prune_junk(DRAFT_DIR, selfevolve.cfg()) or {}).get("removed") or []
    except Exception:  # noqa: BLE001 — a sweep must never break mining
        return []


def list_drafts(limit=50):
    """Machine-mined skill drafts awaiting verify/promote (read-only view).

    A draft is material, not a proposal: it becomes one only when someone states
    what it accomplishes. Without this view self-evolve produced folders the
    operator could not see anywhere (the panel counts proposals and INSTALLED
    skills, and a draft is neither). Unreadable folders are counted, never
    dropped silently.
    """
    rows, unreadable = [], 0
    try:
        names = sorted(os.listdir(DRAFT_DIR))
    except OSError:
        return {"drafts": [], "total": 0, "unreadable": 0}
    for name in names:
        folder = os.path.join(DRAFT_DIR, name)
        if not os.path.isdir(folder):
            continue
        try:
            with open(os.path.join(folder, "proposal.json"), encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            unreadable += 1
            continue
        if not isinstance(rec, dict):
            unreadable += 1
            continue
        verify = rec.get("verify") if isinstance(rec.get("verify"), dict) else {}
        rows.append({"name": str(rec.get("name") or name),
                     "status": str(rec.get("status") or "proposed"),
                     "support": int(rec.get("support") or 0),
                     "steps": int(rec.get("length") or len(rec.get("pattern") or [])),
                     "created": float(rec.get("created") or 0),
                     "green_streak": int(rec.get("green_streak") or 0),
                     "verified": bool(verify.get("green")) if verify else None,
                     "path": folder})
    rows.sort(key=lambda r: r.get("created") or 0, reverse=True)
    total = len(rows)
    try:
        cap = max(1, int(limit))
    except (TypeError, ValueError):
        cap = 50
    return {"drafts": rows[:cap], "total": total, "unreadable": unreadable}


def propose(scope, content, reason="", target_path="", ws=None, origin="agent",
            experiment=None, artifacts=None):
    """Register a PROPOSAL (writes nothing definitive).

    `ws` is the workspace the rule will be written to in case of approve:
    it is captured NOW (the workspace may change before the decision),
    so `decide` writes to the right project and not the "current" one.

    `origin` (JAG-447) is the provenance key: 'agent' when the model asked for
    it via the `improve` tool, 'mining' for a selfevolve draft, 'user' for a
    hand-authored one. It is shown in the WebUI and stamped on the ledger.
    `experiment` carries matched-run evidence for a harness proposal; approval
    refuses a harness proposal without it. `artifacts` is the EXACT learned
    bundle (kind, name, content, sha256) that approving a Matrix proposal writes
    — the approval is bound to those hashes, never to a re-read of the model.
    """
    if ws is None:
        try:
            from longrun.memory import rules
            ws = rules.get_workspace()
        except Exception:  # noqa: BLE001 — the ws must never break the proposal
            ws = ""
    os.makedirs(PROPOSAL_DIR, exist_ok=True)
    pid = "%d-%s" % (int(time.time() * 1000), scope)
    rec = {"id": pid, "ts": time.time(), "scope": scope,
           "content": str(content)[:8000], "reason": str(reason)[:500],
           "target_path": target_path, "status": "pending", "ws": ws,
           "origin": str(origin or "agent")}
    if experiment is not None:
        rec["experiment"] = experiment
    if artifacts:
        rec["artifacts"] = artifacts
    write_json(_path(pid), rec)
    try:
        ledger_add("proposal", origin=rec["origin"], scope=scope, proposal=pid,
                   path=os.path.join("data", "proposals", pid + ".json"),
                   summary=str(content)[:160])
    except Exception:  # noqa: BLE001 — the audit must never break a proposal
        pass
    return rec


def get_proposal(pid):
    try:
        with open(_path(pid), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def list_proposals(status=None):
    """All proposals, newest first. `status` filters ('pending', 'approved'…)."""
    out = []
    try:
        for fn in sorted(os.listdir(PROPOSAL_DIR)):
            if fn.endswith(".json"):
                p = get_proposal(fn[:-5])
                if p and (status is None or p.get("status") == status):
                    out.append(p)
    except OSError:
        pass
    out.sort(key=lambda r: r.get("ts", 0), reverse=True)
    return out


def clear_decided():
    """Delete DECIDED proposals from the store; pending ones are kept.

    v651: the panel listed decided proposals forever and nothing could remove them
    (operator: "pending proposal che è? non si annulla mai, rimarrà per sempre
    così?"). The audit ledger already records every proposal and every decision,
    so the JSON file is redundant history — removed on request, never silently.
    """
    removed, kept = 0, 0
    try:
        names = sorted(os.listdir(PROPOSAL_DIR))
    except OSError:
        return {"ok": True, "removed": 0, "kept": 0}
    for fn in names:
        if not fn.endswith(".json"):
            continue
        rec = get_proposal(fn[:-5])
        if not rec:
            continue
        if rec.get("status") == "pending":
            kept += 1
            continue
        try:
            os.remove(os.path.join(PROPOSAL_DIR, fn))
            removed += 1
        except OSError:
            pass
    try:
        ledger_add("proposals_cleared", removed=removed, kept=kept)
    except Exception:  # noqa: BLE001 — the audit must never break the cleanup
        pass
    return {"ok": True, "removed": removed, "kept": kept}


def dedupe_proposals(rows):
    """One proposal per (scope, content); a pending duplicate wins over decided.

    The improvement panel is a signal, not a flood, but hiding a still-actionable
    proposal behind a denied copy made the panel disagree with the approval inbox.
    """
    bucket = {}
    for rec in rows or []:
        key = (rec.get("scope"), str(rec.get("content") or "").strip())
        prev = bucket.get(key)
        if prev is None or (rec.get("status") == "pending"
                            and prev.get("status") != "pending"):
            bucket[key] = rec
    return sorted(bucket.values(), key=lambda r: r.get("ts", 0), reverse=True)


def diff_preview(rec):
    """What APPROVING this proposal would actually write, as a unified diff.

    project/global rules are append-writes to a known file, so we can show the
    exact patch BEFORE the human decides (the WebUI renders it). A skill
    proposal is not applied on disk (JAG-128B deferred), so we say so instead of
    pretending. Never raises.
    """
    import difflib
    rec = rec or {}
    scope = rec.get("scope")
    content = str(rec.get("content") or "")
    if scope == "matrix":
        # A learned bundle is applied by the Matrix owner; the preview is its
        # own exact diff (one line per file), never a rules-file approximation.
        from longrun.core import matrix
        return matrix.preview_learning(rec.get("artifacts") or [])
    if scope not in ("project", "global"):
        return {"applies": False, "path": "", "diff": "", "added": 0,
                "note": "scope %r is not applied on approve" % scope}
    try:
        from longrun.memory import rules
        path = (rules.global_rules_path() if scope == "global"
                else rules.project_rules_path(rec.get("ws") or rules.get_workspace()))
    except Exception:  # noqa: BLE001 — a preview must never raise
        return {"applies": False, "path": "", "diff": "", "added": 0,
                "note": "rules module unavailable"}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            cur = f.read()
    except OSError:
        cur = ""
    sep = "" if (cur.endswith("\n") or not cur) else "\n"
    new = cur + sep + content
    diff = list(difflib.unified_diff(cur.splitlines(), new.splitlines(),
                                     fromfile=path + " (current)",
                                     tofile=path + " (after approve)",
                                     lineterm=""))
    return {"applies": True, "path": path, "diff": "\n".join(diff),
            "added": sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))}


def evolve_once(note=""):
    """Stage 2 over every repeated pattern -> one report per pattern.

    v662: this body was written TWICE — here (inside `mine_once(evolve=True)`) and
    again in the `improve` tool's `action=evolve` branch, so "what does evolve do?"
    had two answers that could drift (the tool also published one SSE event per
    pattern, which is why the loop looked different). Both now run this one flow and
    differ only in what they do with the reports. `note` is accepted for signature
    parity with `mine_once` (the history miner signs its own drafts).
    """
    from longrun.util import selfevolve
    out = DRAFT_DIR
    reports = []
    for cand in selfevolve.mine(selfevolve.history(), selfevolve.cfg()):
        rep = selfevolve.pipeline(cand["pattern"], out, cand["support"])
        arc = rep.get("archived")
        rel = arc.get("rel") or arc.get("path") if isinstance(arc, dict) else (
            arc if isinstance(arc, str) else "")
        reports.append({"pattern": cand["pattern"],
                        "green": bool((rep.get("verify") or {}).get("green")),
                        "rel": rel or ""})
    return reports


def mine_once(note="", evolve=False):
    """Mine the recorded tool sequences and return the drafted proposal paths.

    JAG-447: the cross-trajectory abstraction step (selfevolve), triggered by the
    end-of-turn improvement pass on a HIGH-SIGNAL turn. JAG-451: when `evolve` is
    True (the `skills: auto` policy), each repeated pattern also runs stage 2
    (synth + verify in sandbox + promote) so ONLY verified skills get installed.
    Never raises.
    """
    try:
        from longrun.util import selfevolve
        out = DRAFT_DIR
        # v711: sweep before mining, for BOTH callers (tool and end-of-turn pass).
        sweep_drafts()
        if not evolve:
            return selfevolve.mine_history(out, note=note) or []
        return [r["rel"] for r in evolve_once(note) if r["rel"]]
    except Exception:  # noqa: BLE001 — mining must never break a turn
        return []


def _save(rec):
    write_json(_path(rec["id"]), rec)
    return rec


def decide(pid, decision):
    """approve|deny. Only 'approve' on project/global writes (appends) the rules."""
    rec = get_proposal(pid)
    if not rec or rec.get("status") != "pending":
        return {"ok": False, "error": "proposal not found or not pending"}
    if decision == "deny":
        rec["status"] = "denied"
        saved = _save(rec)
        ledger_add("decide", origin=rec.get("origin", "agent"),
                   scope=rec.get("scope"), proposal=rec["id"], decision="deny")
        return {"ok": True, **saved}
    if decision != "approve":
        return {"ok": False, "error": "decision must be approve|deny"}
    if rec.get("origin") == "harness":
        # H2R-3: a harness proposal may be approved only when it carries the
        # matched-run evidence that produced it. Legacy entries (and any entry
        # whose evidence does not bind two clean runs of distinct packages) stay
        # visible and deniable, but approval never applies unprobed text.
        exp = rec.get("experiment") or {}
        runs = exp.get("runs") or []
        verified = (exp.get("verified") is True and bool(exp.get("snapshot_digest"))
                    and len(runs) == 2
                    and all(r.get("cleanup_verified") is True for r in runs)
                    and len({r.get("run_id") for r in runs}) == 2
                    and len({r.get("digest") for r in runs}) == 2
                    and exp.get("snapshot_digest") in {r.get("digest") for r in runs})
        if not verified:
            return {"ok": False, "error": "harness proposal has no verified matched "
                    "experiment; approval is unavailable"}
    if rec.get("scope") == "matrix":
        # A learned Matrix bundle is evidence-bound AND hash-bound: the runs must
        # show an improvement, and the bytes written are the bytes approved.
        exp = rec.get("experiment") or {}
        if rec.get("origin") == "harness" and exp.get("contrast") != "improved":
            return {"ok": False, "error": "a Matrix bundle needs an improved contrast"}
        artifacts = rec.get("artifacts") or []
        if not artifacts:
            return {"ok": False, "error": "this Matrix proposal carries no artifact bundle"}
        from longrun.core import matrix
        applied = matrix.apply_learning(artifacts)
        if not applied.get("ok"):
            return {"ok": False, "error": applied.get("error") or "Matrix apply refused",
                    "failed": applied.get("failed")}
        rec["status"] = "approved"
        rec["installed_to"] = ", ".join(applied.get("installed") or [])
        saved = _save(rec)
        try:
            ledger_add("decide", origin=rec.get("origin", "agent"), scope="matrix",
                       proposal=rec["id"], decision="approve",
                       artifact_count=len(artifacts), path=rec["installed_to"])
        except Exception:  # noqa: BLE001 — the audit must never break a decision
            pass
        return {"ok": True, **saved, "installed_to": rec["installed_to"]}
    if rec.get("scope") == "skill":
        # v714: a skill can arrive as CONTENT too (a harness editor writes one
        # SKILL.md and the matched run tested exactly those bytes). Same rule as
        # the Matrix bridge — the bytes approved are the bytes installed — with
        # one installer (`skills.install_skill_file`), so there is no second path
        # into the skill set.
        artifacts = rec.get("artifacts") or []
        if artifacts:
            import hashlib
            from longrun.memory import skills as skills_mod
            installed = []
            for art in artifacts:
                target = str((art or {}).get("target") or "")
                parts = target.split("/")
                if (len(parts) != 4 or parts[0] != "skills"
                        or parts[3] != "SKILL.md" or not parts[1] or not parts[2]
                        or any(p in (".", "..") or "\\" in p for p in parts[:3])):
                    return {"ok": False, "error": "a skill artifact must target "
                            "skills/<category>/<name>/SKILL.md (got %r)" % target}
                content = str((art or {}).get("content") or "")
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                if digest != str((art or {}).get("sha256") or ""):
                    return {"ok": False, "failed": [art.get("name")],
                            "error": "skill artifact %r changed since the experiment"
                                     % (art.get("name"),)}
                made = skills_mod.install_skill_file(parts[1], parts[2], content)
                if not made.get("ok"):
                    return {"ok": False, "failed": [art.get("name")],
                            "error": made.get("error") or "skill install refused"}
                installed.append(made.get("path") or target)
            rec["status"] = "approved"
            rec["installed_to"] = ", ".join(installed)
            saved = _save(rec)
            try:
                ledger_add("decide", origin=rec.get("origin", "agent"), scope="skill",
                           proposal=rec["id"], decision="approve",
                           artifact_count=len(artifacts), path=rec["installed_to"])
            except Exception:  # noqa: BLE001 — the audit must never break a decision
                pass
            return {"ok": True, **saved, "installed_to": rec["installed_to"]}
        # v645: approving a skill draft is a REAL install, not a lie. The draft
        # must pass the sandbox check (`check.py`, generated by selfevolve) and
        # then be archived under skills/<category>/ by the same promote() the
        # automatic path uses — one write-gate for both (no second truth).
        draft = str(rec.get("target_path") or "")
        if not draft or not os.path.isdir(draft):
            return {"ok": False,
                    "error": "the drafted skill folder is missing (%s) — nothing to install" % draft}
        from longrun.util import selfevolve
        try:
            # v713: the synth-if-missing step has ONE owner (`ensure_check`), so
            # this path and the tool's verify action cannot drift apart.
            ready = selfevolve.ensure_check(draft)
            if not ready.get("ok"):
                return {"ok": False, "error": ready.get("error") or "draft is not verifiable"}
            rep = selfevolve.verify(draft)
            if not rep.get("green"):
                return {"ok": False, "verify": rep,
                        "error": "skill not verified: the sandbox check failed — "
                                 + str(rep.get("output") or "")[-300:]}
            pr = selfevolve.promote(draft, human=True,
                                    purpose=str(rec.get("content") or ""))
            if not pr.get("ok"):
                return {"ok": False, "verify": rep, "error": pr.get("error") or "promotion refused"}
        except Exception as e:  # noqa: BLE001 — a decision must answer, not crash
            return {"ok": False, "error": "skill install failed: %s" % e}
        rec["status"] = "approved"
        rec["installed_to"] = pr.get("rel") or ""
        saved = _save(rec)
        try:
            ledger_add("decide", origin=rec.get("origin", "agent"),
                       scope=rec.get("scope"), proposal=rec["id"], decision="approve",
                       path=rec.get("installed_to") or "")
        except Exception:  # noqa: BLE001 — the audit must never break a decision
            pass
        return {"ok": True, **saved, "installed_to": rec.get("installed_to")}
    if rec["scope"] in ("project", "global"):
        from longrun.memory import rules
        rules.append(rec["scope"], rec["content"], ws=rec.get("ws"))
    rec["status"] = "approved"
    saved = _save(rec)
    try:
        ledger_add("decide", origin=rec.get("origin", "agent"),
                   scope=rec.get("scope"), proposal=rec["id"], decision="approve",
                   path=diff_preview(rec).get("path", ""))
    except Exception:  # noqa: BLE001 — the audit must never break a decision
        pass
    return {"ok": True, **saved}
