#!/usr/bin/env python3
"""Trend view — read every stored benchmark sample as its own billing record.

A score alone cannot say whether the harness improved: a pass can cost 3x the
calls, the same tokens can hide a different number of duplicate best-of-N
samples, and a provider cache hit is not work the harness saved. Every sample
writes `result.json` with a `session` (v842) and the session ledger is
`data/costs/<session>.json`, one row per model call. This joins the two, so a run
is described by what it actually spent:

    tokens_in/tokens_out   real prompt/completion counts (not a lump total)
    cached%                share of prompt tokens served from the provider cache
    calls                  model calls in the turn (loop efficiency)
    dup                    duplicate samples (`tag: bestofn`, or a row with no
                           latency before v838) — test-time compute nobody keeps

A sample whose session/ledger is gone is reported `recorded` (the numbers the
driver stored at run time) or `no-ledger`, never as a zero: a missing
measurement is not a free run.

Usage:
    python3 -m benchmarks.trend                    # every sample, oldest first
    python3 -m benchmarks.trend --arm longrun
    python3 -m benchmarks.trend --since 2026-11-06T22:26
    python3 -m benchmarks.trend --root .agent/BENCHMARKS/runs
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ROOT = os.path.join(REPO, ".agent", "BENCHMARKS", "runs")
_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}_\d{6})")


def costs_dir():
    """The ledger directory, resolved the way `longrun.model.costs` does (no import)."""
    env = os.environ.get("LONGRUN_COSTS_DIR")
    if env:
        return env
    data = os.environ.get("LONGRUN_DATA_DIR")
    if not data:
        home = os.environ.get("LONGRUN_DATA_HOME") or os.path.expanduser("~/.longrun")
        data = os.path.join(home, "data")
    return os.path.join(data, "costs")


def ledger(session):
    """Every model call of one session, or None when the ledger is gone."""
    if not session:
        return None
    path = os.path.join(costs_dir(), "%s.json" % session)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if isinstance(data, dict):
        return data.get("calls") or []
    return data if isinstance(data, list) else None


def _is_dup(call):
    return call.get("tag") == "bestofn" or not call.get("latency_ms")


def _arm_of(row, rel):
    return row.get("arm") or ("openclaw" if "openclaw" in rel else "longrun")


def _status(row):
    if "strict" in row:
        return "pass" if row.get("strict") else "fail"
    if "resolved" in row:
        return "pass" if row.get("resolved") else "fail"
    return str(row.get("status") or "?")


def _task_of(row, rel):
    return str(row.get("task") or row.get("instance") or rel)


def samples(root):
    """One record per stored sample, oldest first."""
    out = []
    for name in sorted(os.listdir(root)):
        run_dir = os.path.join(root, name)
        if not os.path.isdir(run_dir):
            continue
        m = _STAMP.match(name)
        when = (dt.datetime.strptime(m.group(1), "%Y-%m-%d_%H%M%S") if m else None)
        for base, _dirs, files in os.walk(run_dir):
            if "result.json" not in files:
                continue
            try:
                with open(os.path.join(base, "result.json"), encoding="utf-8") as fh:
                    row = json.load(fh)
            except (OSError, ValueError):
                continue
            rel = os.path.relpath(base, run_dir)
            rec = row.get("usage") or {}
            calls = ledger(row.get("session") or row.get("session_key"))
            if calls is not None:
                src = "ledger"
                calls_n = len(calls)
                tin = sum(int(c.get("prompt") or 0) for c in calls)
                tout = sum(int(c.get("completion") or 0) for c in calls)
                cached = sum(int(c.get("cached") or 0) for c in calls)
                dup = sum(1 for c in calls if _is_dup(c))
                # The per-call rows are the bill: sum them instead of trusting a
                # driver that never stored a total (a run with priced calls but no
                # `usage.total_usd` used to print "?").
                priced = [float(c["usd"]) for c in calls if c.get("usd") is not None]
                usd = round(sum(priced), 6) if priced else None
            else:
                src = "recorded" if rec else "no-ledger"
                calls_n = int(rec.get("calls") or 0)
                tin = int(rec.get("tokens_in") or 0)
                tout = int(rec.get("tokens_out") or 0)
                cached = int(rec.get("cached") or 0)
                dup = int(rec.get("dup_calls") or 0)
                usd = rec.get("total_usd", row.get("cost_usd"))
            out.append({
                "when": when, "run": name, "arm": _arm_of(row, rel),
                "task": _task_of(row, rel), "status": _status(row),
                "wall_s": float(row.get("duration_s") or 0),
                "calls": calls_n, "tin": tin, "tout": tout, "cached": cached,
                "dup": dup, "usd": usd, "src": src,
            })
    out.sort(key=lambda r: (r["when"] or dt.datetime.min, r["run"], r["task"]))
    return out


def _ago(when):
    return when.strftime("%m-%d %H:%M:%S") if when else "?"


def _table(rows):
    print("%-9s %-9s %-30s %-5s %8s %6s %10s %9s %7s %5s %8s %s" % (
        "run", "arm", "task", "verdict", "wall_s", "calls", "tokens_in", "tokens_out",
        "cached%", "dup", "usd", "src"))
    for r in rows:
        # A cache share is only printed when the per-call rows were read: a stored
        # lump total has no cache number, and 0.0% would read as "no caching".
        cache = ("%6.1f%%" % (100.0 * r["cached"] / r["tin"])
                 if (r["tin"] and r["src"] == "ledger") else "      -")
        usd = "?" if r["usd"] is None else "%.4f" % float(r["usd"])
        print("%-9s %-9s %-30s %-5s %8.1f %6d %10d %9d %7s %5d %8s %s" % (
            _ago(r["when"])[-9:], r["arm"], r["task"][-30:], r["status"][:5],
            r["wall_s"], r["calls"], r["tin"], r["tout"], cache, r["dup"], usd, r["src"]))


def _totals(label, rows):
    if not rows:
        print("%-34s (no samples)" % label)
        return
    tok = sum(r["tin"] + r["tout"] for r in rows)
    dup = sum(r["dup"] for r in rows)
    cached = sum(r["cached"] for r in rows)
    usd = [float(r["usd"]) for r in rows if r["usd"] is not None]
    ok = sum(1 for r in rows if r["status"] == "pass")
    print("%-34s n=%d pass=%d wall=%.0fs calls=%d tok=%d cached=%.1f%% dup=%.1f%% "
          "usd=%s" % (
              label, len(rows), ok, sum(r["wall_s"] for r in rows),
              sum(r["calls"] for r in rows), tok,
              100.0 * cached / sum(r["tin"] for r in rows) if sum(r["tin"] for r in rows) else 0.0,
              100.0 * dup / sum(r["calls"] for r in rows) if sum(r["calls"] for r in rows) else 0.0,
              ("%.4f" % sum(usd)) if usd else "?"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="benchmarks.trend")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="benchmark runs root")
    ap.add_argument("--arm", default="", help="only this arm")
    ap.add_argument("--since", default="", metavar="ISO",
                    help="report a before/after split at this instant")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.root):
        print("no runs at %s" % args.root)
        return 2
    rows = samples(args.root)
    if args.arm:
        rows = [r for r in rows if r["arm"] == args.arm]
    if not rows:
        print("no samples under %s" % args.root)
        return 2
    _table(rows)
    print()
    # Per run, per arm: the unit that is actually comparable (one suite, one day).
    groups = {}
    for r in rows:
        groups.setdefault((r["run"], r["arm"]), []).append(r)
    print("== per run")
    for (run, arm) in sorted(groups):
        _totals("%s %s" % (run[-15:], arm), groups[(run, arm)])
    if args.since:
        cut = dt.datetime.fromisoformat(args.since)
        print()
        print("== before / after %s" % args.since)
        _totals("before", [r for r in rows if r["when"] and r["when"] < cut])
        _totals("after", [r for r in rows if r["when"] and r["when"] >= cut])
    missing = [r for r in rows if r["src"] == "no-ledger"]
    if missing:
        print("\n%d sample(s) have no ledger and no recorded usage: %s"
              % (len(missing), ", ".join(sorted({r["run"] for r in missing}))[:200]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
