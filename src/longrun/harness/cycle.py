#!/usr/bin/env python3
"""H2-7 — bounded evidence cycle; production execution is unavailable.

This is the whole recursion as ONE call, and it exists so the mechanism is
reachable and observable instead of being five modules nobody wires together.

What a cycle does, in the paper's order (`research/papers/harness2/
harness2_2610.14224.txt:225-368`):

1. **record** the run we want to learn from (`harness.record`);
2. **propose** with the two scoped editors (`harness.editors`) — conditioned on the
   reference run's failures, because the first step of a cycle has no contrast yet;
3. **probe** candidates independently with an injected offline runner;
4. **compose** supported candidates and execute the successor, retaining
   confounded reflection rows without writing a durable lesson;
5. report, and keep the last report in `<data>/harness/cycle/last.json`.

Bounds: `dry_run` is the default and stops after step 1 (record + library hits,
no model, no probe). Production refuses before editor spend: no supported
whole-run isolation exists. Injected tests allow up to `max_candidates`
independent trials plus one successor. No live approval or adoption is available.
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
    isolation = probe_mod.isolation_status()
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
        "ready": bool(c.get("enabled") and isolation["available"]),
        "isolation": isolation,
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
        report["reason"] = "dry run: no editor calls or probes; production isolation is unavailable"
        return _save(report)
    if not c.get("enabled"):
        report["status"] = "refused"
        report["reason"] = "harness probe is disabled (LONGRUN_HARNESS_ENABLED=1)"
        return _save(report)
    if runner is None and not probe_mod.isolation_status()["available"]:
        report["status"] = "refused"
        report["reason"] = probe_mod.isolation_status()["reason"]
        return _save(report)

    candidates, skips, names = [], [], []
    for scope in SCOPES:
        try:
            got = editors_mod.propose(scope, base, None, hits, model=model, call=call,
                                      domain=domain, exclude=names)
        except Exception as exc:
            # Provider errors can carry credentials; report the phase and class only.
            report.update(status="failed",
                          reason="%s editor failed: %s" % (scope, type(exc).__name__))
            return _save(report)
        candidates += got.get("candidates") or []
        names = [c.get("name") for c in candidates]
        report["proposals"] += got.get("proposals") or []
        report["refusals"] += got.get("rejected") or []
        if got.get("skipped"):
            skips.append("%s: %s" % (scope, got["skipped"]))
    report["skipped"] = skips
    if not candidates:
        report["status"] = "no candidates"
        report["reason"] = (", ".join(skips)
                            or "; ".join(str(r.get("reason")) for r in report["refusals"])
                            or "the editors returned nothing")
        return _save(report)

    if len(candidates) > int(c.get("max_candidates") or 1):
        report.update(status="refused", reason="editor candidates exceed the cycle cap")
        return _save(report)
    report["trials"], report["kept"], report["rejected"] = [], [], []
    scratch_ids, supported, targets = [], [], set()
    try:
        # Each candidate differs from the reference by ONE component. An
        # aggregate successful run cannot identify which of its edits helped.
        for candidate in candidates:
            trial = probe_mod.run(base, [candidate], runner=runner, c=c)
            if trial.get("probe_id"):
                scratch_ids.append(trial["probe_id"])
            report["trials"].append({"candidate": candidate, **trial})
            report["refusals"] += trial.get("refusals") or []
            chosen = compose_mod.select(trial.get("contrast"), [candidate])
            if trial.get("status") == "ran" and chosen["adopt"]:
                target, _ = probe_mod._target(candidate["kind"], candidate["name"])
                if target in targets:
                    report["refusals"].append(
                        {"name": candidate["name"], "reason": "same file as another selected candidate"})
                    continue
                targets.add(target)
                supported.append(candidate)
            else:
                report["rejected"] += chosen["rejected"] or [
                    {"name": candidate["name"], "reason": trial.get("reason") or chosen["decision"]}]
        if supported:
            # Even selecting a single unchanged candidate gets another execution:
            # the paper returns an EXECUTED successor, not a selection opinion.
            successor = probe_mod.run(base, supported, runner=runner, c=c)
            if successor.get("probe_id"):
                scratch_ids.append(successor["probe_id"])
            report["successor"] = successor
            contrast = successor.get("contrast") or {}
            applied = [s for s in supported if s["name"] in (successor.get("staged") or {})]
            chosen = compose_mod.select(contrast, applied)
            report["decision"] = chosen["decision"]
            report["probe"] = {"status": successor.get("status"),
                               "probe_id": successor.get("probe_id"),
                               "reason": successor.get("reason"), "contrast": contrast.get("verdict")}
            report["contrast"] = {key: contrast.get(key) for key in
                                  ("verdict", "comparable", "steps", "errors", "deliverables")}
            if successor.get("status") == "ran" and chosen["adopt"]:
                report["kept"] = [s["name"] for s in chosen["kept"]]
            else:
                report["rejected"] += chosen["rejected"]
        report["reflection"] = compose_mod.reflect(report["trials"], report.get("successor"))
        report["status"] = "no adoption"
        report["reason"] = report["reflection"]["reason"]
    finally:
        if not c.get("keep"):
            for pid in scratch_ids:
                probe_mod.cleanup(pid)
    try:
        from longrun.util import improve
        improve.ledger_add("harness_cycle", domain=domain, session=session_id,
                           status=report["status"],
                           adopted=(report["adopted"] or {}).get("id") if report["adopted"] else "",
                           probe=(report["probe"] or {}).get("probe_id") or "")
    except Exception:  # noqa: BLE001 — an audit line must never break a cycle
        pass
    return _save(report)


def _save(report):
    """Persist the report and return it (a write failure never hides the run)."""
    try:
        os.makedirs(_cycle_dir(), exist_ok=True)
        write_json(last_path(), report)
    except Exception:  # noqa: BLE001
        pass
    return report
