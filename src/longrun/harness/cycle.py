#!/usr/bin/env python3
"""H2-7 — one cycle: record -> editors -> probe -> compose -> library.

This is the whole recursion as ONE call, and it exists so the mechanism is
reachable and observable instead of being five modules nobody wires together.

What a cycle does, in the paper's order (`research/papers/harness2/
harness2_2610.14224.txt:225-368`):

1. **record** the run we want to learn from (`harness.record`);
2. **propose** with the two scoped editors (`harness.editors`) — conditioned on the
   reference run's failures, because the first step of a cycle has no contrast yet;
3. **probe** the candidates on the same task in an isolated copy (`harness.probe`);
4. **compose** — adopt only an `improved` contrast (`harness.compose`), and write
   one library entry (`harness.library`);
5. report, and keep the last report in `<data>/harness/cycle/last.json`.

Bounds: `dry_run` is the default and stops after step 1 (record + library hits,
no model, no probe). A real run requires `LONGRUN_HARNESS_ENABLED=1`, at most
`max_candidates` (2), one probe per task, and it always ends in proposals — never
in a live harness change.
"""
import json
import os
import time

from longrun.harness import compose as compose_mod
from longrun.harness import editors as editors_mod
from longrun.harness import library as library_mod
from longrun.harness import probe as probe_mod
from longrun.harness import record as record_mod
from longrun.util import paths
from longrun.util.fswrite import write_json

SCOPES = ("invariant", "domain")


def _cycle_dir():
    """`<harness>/cycle` — the last report lives here."""
    return os.path.join(record_mod.dir_path(), "cycle")


def last_path():
    """Path of the last cycle report."""
    return os.path.join(_cycle_dir(), "last.json")


def last():
    """The last cycle report, or None."""
    try:
        with open(last_path(), "r", encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, dict) else None
    except (OSError, ValueError):
        return None


def status():
    """Everything the panel needs, read from real state (no constants)."""
    c = probe_mod.cfg()
    domains = {}
    try:
        base = os.path.join(record_mod.dir_path(), "library")
        for name in sorted(os.listdir(base)):
            if os.path.isdir(os.path.join(base, name)):
                domains[name] = len(library_mod.index(name)["entries"])
    except OSError:
        domains = {}
    return {
        "enabled": bool(c.get("enabled")),
        "config": {"max_candidates": c.get("max_candidates"),
                   "max_steps": c.get("max_steps"),
                   "max_seconds": c.get("max_seconds"),
                   "copy_max_mb": c.get("copy_max_mb")},
        "library": {"domains": domains, "entries": sum(domains.values())},
        "data_dir": paths.DATA_DIR,
        "cycle_dir": _cycle_dir(),
        "last": last(),
    }


def run(session_id=None, domain="general", dry_run=True, model=None, call=None,
        runner=None, c=None):
    """Run one cycle and return its report.

    Args:
        session_id: the session to learn from (its run becomes the reference).
        domain: the library bucket (a task family).
        dry_run: default True — record + library hits only, no model, no probe.
        model: model alias for the editors (ignored when `call` is given).
        call: injected editor model call (tests).
        runner: injected probe runner (tests).
        c: probe config override (tests).
    Returns:
        {"ts", "session", "domain", "dry_run", "status", "base", "library_hits",
         "proposals", "probe", "decision", "adopted", "refusals", "reason"?}
    """
    if not session_id:
        return {"status": "refused", "reason": "session_id required"}
    c = c or probe_mod.cfg()
    base = record_mod.build(session_id)
    if not base.get("steps"):
        return {"status": "refused", "reason": "the session has no tool steps to learn from"}
    record_mod.save(base)
    hits = library_mod.relevant(domain, base.get("goal") or "")
    failures = [s for s in base["steps"] if s.get("ok") is False]
    report = {
        "ts": round(time.time(), 3), "session": session_id, "domain": domain,
        "dry_run": bool(dry_run), "status": "dry-run",
        "base": {"run_id": base["run_id"], "steps": len(base["steps"]),
                 "failures": len(failures),
                 "error_classes": sorted({str(s.get("error") or "")[:60]
                                          for s in failures if s.get("error")}),
                 "deliverables": len(base.get("deliverables") or [])},
        "library_hits": [h.get("id") for h in hits],
        "proposals": [], "probe": None, "decision": "", "adopted": None,
        "refusals": [],
    }
    if dry_run:
        report["reason"] = ("dry run: editors and the probe need "
                            "LONGRUN_HARNESS_ENABLED=1")
        return _save(report)
    if not c.get("enabled"):
        report["status"] = "refused"
        report["reason"] = "harness probe is disabled (LONGRUN_HARNESS_ENABLED=1)"
        return _save(report)

    candidates, skips, names = [], [], []
    for scope in SCOPES:
        got = editors_mod.propose(scope, base, None, hits, model=model, call=call,
                                  domain=domain, exclude=names)
        candidates += got.get("candidates") or []
        names = [c.get("name") for c in candidates]
        report["proposals"] += got.get("proposals") or []
        report["refusals"] += got.get("rejected") or []
        if got.get("skipped"):
            skips.append("%s: %s" % (scope, got["skipped"]))
    report["skipped"] = skips
    if not candidates:
        report["status"] = "no candidates"
        report["reason"] = ", ".join(skips) or "the editors returned nothing"
        return _save(report)

    probed = probe_mod.run(base, candidates, runner=runner, c=c)
    report["probe"] = {"status": probed.get("status"), "probe_id": probed.get("probe_id"),
                       "reason": probed.get("reason"),
                       "contrast": (probed.get("contrast") or {}).get("verdict")}
    report["refusals"] = (report.get("refusals") or []) + (probed.get("refusals") or [])
    if probed.get("status") != "ran":
        report["status"] = probed.get("status") or "failed"
        report["reason"] = probed.get("reason") or ""
        return _save(report)

    contrast = probed.get("contrast") or {}
    chosen = compose_mod.select(contrast, candidates)
    report["decision"] = chosen["decision"]
    report["kept"] = [k.get("name") for k in chosen["kept"]]
    report["rejected"] = chosen["rejected"]
    report["contrast"] = {k: contrast.get(k) for k in
                          ("verdict", "comparable", "steps", "errors", "deliverables")}
    if chosen["adopt"]:
        lesson = _lesson(base, contrast, candidates)
        report["adopted"] = compose_mod.adopt(
            domain, base.get("goal") or "", lesson, contrast, chosen["kept"],
            probed.get("staged") or {})
    report["status"] = "adopted" if report["adopted"] else "no adoption"
    try:
        from longrun.util import improve
        improve.ledger_add("harness_cycle", domain=domain, session=session_id,
                           status=report["status"],
                           adopted=(report["adopted"] or {}).get("id") if report["adopted"] else "",
                           probe=(report["probe"] or {}).get("probe_id") or "")
    except Exception:  # noqa: BLE001 — an audit line must never break a cycle
        pass
    if probed.get("probe_id") and not c.get("keep"):
        probe_mod.cleanup(probed["probe_id"])
    return _save(report)


def _lesson(base, contrast, candidates):
    """One or two sentences a later task can reuse (the library lesson)."""
    fixed = ", ".join((contrast.get("errors") or {}).get("fixed") or []) or "the observed failure"
    names = ", ".join(str(c.get("name")) for c in candidates)
    return ("On a task like %r, %s removed %s." %
            ((base.get("goal") or "")[:80], names, fixed))


def _save(report):
    """Persist the report and return it (a write failure never hides the run)."""
    try:
        os.makedirs(_cycle_dir(), exist_ok=True)
        write_json(last_path(), report)
    except Exception:  # noqa: BLE001
        pass
    return report
