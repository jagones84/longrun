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

# scope -> write mode allowed to the agent
AGENT_WRITE = {
    "memory": "auto",       # data/memory/**  -> free write (silent)
    "skill": "propose",     # skills/**       -> proposal, threshold
    "project": "propose",   # <ws>/.longrun/RULES.md -> PROPOSAL only
    "global": "propose",    # ~/.config/longrun/RULES.md -> PROPOSAL only
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


def should_nudge(used_tools=0, errored=False, corrected=False):
    """True when the self-improvement nudge triggers (Hermes pattern)."""
    if corrected or errored:
        return True
    try:
        return int(used_tools) >= _TOOLCALL_THRESHOLD
    except (TypeError, ValueError):
        return False


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
    try:
        from longrun.memory import memory as memory_mod
        for r in memory_mod.query(None, None, limit=200):
            origin = str(r.get("source") or r.get("origin") or "").strip()
            if origin == "user":
                continue
            text = str(r.get("content") or "").strip()
            if not text:
                continue
            key = ("memory", text)
            if key in seen:
                continue
            seen.add(key)
            items.append({"id": r.get("mid") or "", "kind": "memory",
                          "scope": r.get("kind") or "", "status": "stored",
                          "origin": origin or "unattributed", "text": text,
                          "reason": "", "target": "data/memory"})
    except Exception:  # noqa: BLE001 — the review must survive a memory hiccup
        pass
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
    """Lenient: take the first COMPLETE JSON object/array in the model's answer.

    Models wrap JSON in prose or code fences. Find the first `{`/`[`, then walk
    to its matching close (string-escape aware) and parse exactly that slice.
    """
    text = str(answer or "")
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0] or [-1])
    if start < 0:
        return []
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(text[start:i + 1])
                except ValueError:
                    return []
                if isinstance(data, dict):
                    data = data.get("verdicts")
                return [v for v in (data or []) if isinstance(v, dict)] \
                    if isinstance(data, list) else []
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


def propose(scope, content, reason="", target_path="", ws=None, origin="agent"):
    """Register a PROPOSAL (writes nothing definitive).

    `ws` is the workspace the rule will be written to in case of approve:
    it is captured NOW (the workspace may change before the decision),
    so `decide` writes to the right project and not the "current" one.

    `origin` (JAG-447) is the provenance key: 'agent' when the model asked for
    it via the `improve` tool, 'mining' for a selfevolve draft, 'user' for a
    hand-authored one. It is shown in the WebUI and stamped on the ledger.
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
        out = os.path.join(PROPOSAL_DIR, "skills")
        if not evolve:
            return selfevolve.mine_history(out, note=note) or []
        installed = []
        c = selfevolve.cfg()
        for cand in selfevolve.mine(selfevolve.history(), c):
            rep = selfevolve.pipeline(cand["pattern"], out, cand["support"])
            arc = rep.get("archived")
            rel = arc.get("rel") or arc.get("path") if isinstance(arc, dict) else (arc if isinstance(arc, str) else "")
            if rel:
                installed.append(rel)
        return installed
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
    if rec.get("scope") == "skill":
        # JAG-128B deferred: applying a skill is not implemented. It is NOT
        # silently marked 'approved': the status stays 'pending' and we tell the truth.
        return {"ok": False, "error": "skill apply not implemented (JAG-128B deferred)"}
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

