"""Persistent ledger of `longrunAgent` (VEO) automation runs — visibility for a
stateless agent (JAG-535 follow-up).

`longrunAgent` wipes its own transcript AND its task graph before and after every
automation turn (`longrun_agent.reset_stateless_session`). That isolation is by
design — but it left NO record of what was written to the substrate. Verified
2026-10-26: an operator clicked `⚡ automate (Teamorg)`, six `ROLE.md` files were
written at 22:56, the run graph was archived as an orphan
(`data/graphs/longrunAgent_run_<id>.json`), and the session, the plan panel and
the chat showed nothing at all. Asking the agent "what did you do last time?"
could only answer "my transcript resets" — true, and useless.

ONE append-only NDJSON file is that record (`data/automation/ledger.ndjson`):

    {"kind": "run",   run_id, section, model, at, ok, summary, writes}
    {"kind": "write", run_id, at, tool, target, ok, chars}

**Single truth.** The `write` rows are DERIVED from the run's own trace
(`api_v02._result` → `trace`, whose entries already carry `tool` + `args` +
`tool_result`), so nothing is captured twice and the ledger cannot disagree with
what the run actually did. Read-only subtools (`agent.get`, `team.list`, …) are
never recorded: a ledger that lists a scan as a change is a lie.

The ledger is bounded: past `_MAX_BYTES` it is rewritten keeping the last
`_KEEP_LINES` rows, trimmed so a `run` row never loses its `write` rows.
"""
import json
import os
import time

from longrun.util import paths

LEDGER_DIR = os.path.join(paths.DATA_DIR, "automation")
LEDGER_FILE = os.environ.get("LONGRUN_AUTOMATION_LEDGER") or os.path.join(
    LEDGER_DIR, "ledger.ndjson")

_MAX_BYTES = 512 * 1024
_KEEP_LINES = 400
_MAX_SUMMARY = 4000
_MAX_TARGET = 80
_MAX_CHARS_ARG = 40000

# Subtools that only READ the substrate. Derived by name so the list cannot drift
# away from `TOOL_SCHEMAS` (the single declaration of every exclusive tool).
_READ_ONLY_SUBTOOLS = frozenset((
    "get", "list", "prompt_get", "status", "inspect", "search", "read", "show",
))

# Where a tool names its subject. First non-empty wins.
_TARGET_KEYS = ("agent", "team", "job", "routine", "session", "id", "name", "slug")


def mutating_tools():
    """The exclusive tools that CHANGE the substrate, from `TOOL_SCHEMAS`.

    Imported lazily: `longrun_agent` imports this module, so a module-level
    import would be circular.
    """
    try:
        from longrun.agent import longrun_agent as lra
        schemas = getattr(lra, "TOOL_SCHEMAS", {}) or {}
    except Exception:  # noqa: BLE001 — an empty ledger beats a broken automation
        return frozenset()
    out = set()
    for name, spec in schemas.items():
        if not isinstance(spec, dict) or spec.get("_origin") != "exclusive":
            continue
        sub = str(spec.get("_subtool") or "").strip().lower()
        if sub in _READ_ONLY_SUBTOOLS:
            continue
        out.add(str(name))
    return frozenset(out)


def _target(tool, args):
    """The subject a call names (`A48`, `T8`, …), or ``""`` when it names none.

    The tool's own NAMESPACE wins: `team.member_add` is an operation ON a team, so
    its target is the team, even though the arg it also carries is an agent.
    """
    a = args if isinstance(args, dict) else {}
    ns = str(tool or "").split(".", 1)[0]
    for k in (ns,) + _TARGET_KEYS:
        v = a.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:_MAX_TARGET]
    return ""


def _chars(args):
    """Size of the text argument (a prompt, a body) — 0 when the call carries none."""
    a = args if isinstance(args, dict) else {}
    for k in ("prompt", "content", "text", "body"):
        v = a.get(k)
        if isinstance(v, str):
            return min(len(v), _MAX_CHARS_ARG)
    return 0


def _ok_of(meta, ok_hint=None):
    """Tri-state outcome of a call: True / False / None (cannot be attributed)."""
    if ok_hint is not None:
        return bool(ok_hint)
    m = meta if isinstance(meta, dict) else {}
    if m.get("blocked"):
        return False
    if m.get("ok") is not None:
        return bool(m.get("ok"))
    if m.get("approval_status") is not None:
        return str(m.get("approval_status")) == "approved"
    return None


def _calls_of(step):
    """The `(tool, args, ok)` triples a trace entry contains (single or batch)."""
    if step.get("action") == "batch":
        calls = [c for c in (step.get("calls") or []) if isinstance(c, dict)]
        results = [r for r in (step.get("results") or []) if isinstance(r, dict)]
        out, used = [], set()
        for c in calls:
            tool = str(c.get("tool") or "")
            ok = None
            for n, r in enumerate(results):
                if n in used or str(r.get("tool") or "") != tool:
                    continue
                used.add(n)
                ok = _ok_of(None, r.get("ok"))
                break
            out.append((tool, c.get("args"), ok))
        return out
    tool = str(step.get("tool") or "")
    return [(tool, step.get("args"), _ok_of(step.get("tool_result")))] if tool else []


def writes_from_trace(trace):
    """The mutating exclusive calls a run actually executed, in order.

    Each row is ``{tool, target, ok, chars}``. `ok` is ``None`` when the trace
    cannot attribute the outcome — the surface renders that as unknown instead of
    claiming a write that may not have happened.
    """
    mutating = mutating_tools()
    out = []
    for step in trace or []:
        if not isinstance(step, dict):
            continue
        for tool, args, ok in _calls_of(step):
            if tool not in mutating:
                continue
            out.append({"tool": tool, "target": _target(tool, args), "ok": ok,
                        "chars": _chars(args)})
    return out


def _read_lines(path=None):
    try:
        with open(path or LEDGER_FILE, encoding="utf-8") as f:
            return [ln for ln in f.read().splitlines() if ln.strip()]
    except FileNotFoundError:
        return []
    except OSError:
        return []


def _compact(rows):
    """Rewrite the ledger with its tail when it grows past `_MAX_BYTES`."""
    try:
        if os.path.getsize(LEDGER_FILE) <= _MAX_BYTES:
            return
    except OSError:
        return
    keep = rows[-_KEEP_LINES:]
    # Start the kept window at a `run` row so no write row is orphaned from the run
    # that produced it. A window with no `run` row at all is left as it is: there is
    # nothing to align it to, and dropping it would lose history for no gain.
    for n, r in enumerate(keep):
        if r.get("kind") == "run":
            keep = keep[n:]
            break
    try:
        with open(LEDGER_FILE, "w", encoding="utf-8") as f:
            for r in keep:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass


def record(section, run_id, model, ok, summary="", trace=None):
    """Append one `run` row plus one `write` row per mutating call it executed.

    Returns the appended rows (the caller's own evidence, handy in a test).
    """
    rid = str(run_id or "")
    at = round(time.time(), 3)
    writes = writes_from_trace(trace)
    rows = [{"kind": "run", "run_id": rid, "section": str(section or ""),
             "model": str(model or ""), "at": at, "ok": bool(ok),
             "summary": str(summary or "")[:_MAX_SUMMARY], "writes": len(writes)}]
    for w in writes:
        rows.append({"kind": "write", "run_id": rid, "at": at, "tool": w["tool"],
                     "target": w["target"], "ok": w["ok"], "chars": w["chars"]})
    _append(rows)
    return rows


def _append(rows):
    try:
        os.makedirs(os.path.dirname(LEDGER_FILE), exist_ok=True)
    except OSError:
        pass
    try:
        with open(LEDGER_FILE, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        return
    _compact(_parse(_read_lines()))


def _parse(lines):
    out = []
    for ln in lines:
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _runs(limit=None):
    """Every recorded run, newest first, each carrying its own `detail` writes."""
    out, by_run = [], {}
    for row in _parse(_read_lines()):
        kind = row.get("kind")
        if kind == "run":
            rec = dict(row)
            rec["detail"] = []
            out.append(rec)
            by_run[str(row.get("run_id") or "")] = rec
        elif kind == "write":
            rec = by_run.get(str(row.get("run_id") or ""))
            if rec is not None:                      # a write for a pruned run
                rec["detail"].append(row)
    out.reverse()
    return out[:limit] if limit else out


def read_runs(limit=20):
    """The last `limit` automation runs, newest first (`detail` = what was written)."""
    return _runs(limit=max(1, int(limit or 20)))


def last_write_by_target():
    """`{target: {at, run_id, section, tool, chars, ok}}` — newest write per target.

    This is the `AI-written` badge: it names WHO was written, WHEN and by WHICH
    run, so a prompt an automation wrote is never mistaken for one the operator
    typed.
    """
    out = {}
    for rec in reversed(_runs()):                    # oldest → newest: newest wins
        for w in rec.get("detail") or []:
            t = str(w.get("target") or "")
            if not t:
                continue
            out[t] = {"at": w.get("at"), "run_id": rec.get("run_id"),
                      "section": rec.get("section"), "tool": w.get("tool"),
                      "chars": w.get("chars"), "ok": w.get("ok")}
    return out


def clear():
    """Drop the ledger (tests, and an operator who wants a clean history)."""
    try:
        os.remove(LEDGER_FILE)
        return True
    except FileNotFoundError:
        return False
