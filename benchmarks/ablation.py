#!/usr/bin/env python3
"""Harness ablation planner (HA-3, lot H).

Every rule, skill and hook is a hypothesis about what the model cannot do alone,
and the hypothesis expires with each model change — the talk behind lot H reports
Anthropic removing >80% of Claude Code's base instructions for one model release
with no regression. Longrun can compare two RUNS (`harness/contrast.py`) but has no
way to say "run this task set WITH and WITHOUT this layer", so nothing ever gets
removed.

This module is the missing half and nothing else: it materialises an EMPTY scratch
root for exactly one layer and returns the env overlay that points the harness at
it, plus a `compare()` over two stored run trees. It starts no model call, writes
nothing outside the scratch root it is given, and refuses a layer it cannot remove.

Removable layers are the FILE-BACKED ones. A layer that lives in code (tool
descriptions, prompt sections) has no switch and is refused rather than faked.

Usage:
    python3 -m benchmarks.ablation --check
    python3 -m benchmarks.ablation --plan skills --tasks benchmark/tasks/x.yaml
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: name -> (env var -> path template, why the layer is worth ablating)
LAYERS = {
    "skills": (
        {"LONGRUN_SKILLS_DIR": "{root}/skills"},
        "the installed procedures: without them the model must improvise",
    ),
    "rules": (
        {"LONGRUN_CONFIG_DIR": "{root}/config",
         "LONGRUN_PROJECTS_DIR": "{root}/projects"},
        "the global + project instruction files injected on every turn",
    ),
    "hooks": (
        {"LONGRUN_HOOKS": "{root}/hooks.yaml",
         "LONGRUN_HOOKS_OVERLAY": "{root}/hooks.overlay.yaml"},
        "the commands that fire before/after a tool and at Stop",
    ),
    # CO-2 (2026-11-14): the cross-session memory store. Without this layer the
    # question "does memory pay for itself?" (CoReMem, arXiv 2611.17316) cannot
    # be asked: every arm would carry the same lessons and the same anchors.
    "memory": (
        {"LONGRUN_MEMORY_DIR": "{root}/memory"},
        "the persistent memory store: core, user facts, lessons, repo anchors",
    ),
}

_DIRS = {"LONGRUN_SKILLS_DIR", "LONGRUN_CONFIG_DIR", "LONGRUN_PROJECTS_DIR",
         "LONGRUN_MEMORY_DIR"}


def materialize(layer, root):
    """Create the EMPTY root that removes `layer`; returns its env overlay.

    Raises ValueError for a layer that cannot be removed by pointing the harness
    somewhere else (never a silent no-op: an ablation that removes nothing is the
    exact failure this instrument exists to avoid).
    """
    spec = LAYERS.get(str(layer))
    if not spec:
        raise ValueError("unknown layer %r (known: %s)"
                         % (layer, ", ".join(sorted(LAYERS))))
    env = {}
    for key, tmpl in spec[0].items():
        path = tmpl.format(root=os.path.abspath(root))
        if key in _DIRS:
            os.makedirs(path, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w", encoding="utf-8").close()
        env[key] = path
    return env


def plan(layer, command, root=None):
    """The two arms of one ablation: identical command, ONE layer different."""
    root = root or tempfile.mkdtemp(prefix="longrun-ablation-")
    without = materialize(layer, root)
    return {
        "layer": layer,
        "why": LAYERS[layer][1],
        "scratch": root,
        "arm_base": {"env": {}, "command": command},
        "arm_without": {"env": without, "command": command},
        "differs_by": sorted(without),
    }


def _results(root):
    """{relative sample dir: result.json} under a run tree."""
    out = {}
    for base, _dirs, files in os.walk(root):
        if "result.json" not in files:
            continue
        rel = os.path.relpath(base, root)
        try:
            with open(os.path.join(base, "result.json"), encoding="utf-8") as fh:
                out[rel] = json.load(fh)
        except (OSError, ValueError):
            continue
    return out


def compare(dir_a, dir_b):
    """Score / pass / cost delta between the two arms of one ablation.

    Only samples present in BOTH trees enter the delta; a sample that ran in one
    arm only is listed, never averaged in (that is how a missing arm turns into a
    fake improvement).
    """
    a, b = _results(dir_a), _results(dir_b)
    both = sorted(set(a) & set(b))
    rows = []
    for key in both:
        ra, rb = a[key], b[key]
        sa = (ra.get("score") or {})
        sb = (rb.get("score") or {})
        ua = (ra.get("usage") or {})
        ub = (rb.get("usage") or {})
        rows.append({
            "sample": key,
            "score_a": sa.get("score"), "score_b": sb.get("score"),
            "max": sa.get("max") or sb.get("max"),
            "pass_a": bool(sa.get("all_pass")),
            "pass_b": bool(sb.get("all_pass")),
            "usd_a": ua.get("total_usd"), "usd_b": ub.get("total_usd"),
        })

    def _sum(key):
        vals = [r[key] for r in rows if isinstance(r[key], (int, float))]
        return round(sum(vals), 6) if vals else None

    return {
        "samples": len(rows),
        "only_a": sorted(set(a) - set(b)),
        "only_b": sorted(set(b) - set(a)),
        "score_a": _sum("score_a"), "score_b": _sum("score_b"),
        "delta_score": (round(_sum("score_b") - _sum("score_a"), 6)
                        if _sum("score_a") is not None and _sum("score_b") is not None
                        else None),
        "pass_a": sum(1 for r in rows if r["pass_a"]),
        "pass_b": sum(1 for r in rows if r["pass_b"]),
        "usd_a": _sum("usd_a"), "usd_b": _sum("usd_b"),
        "rows": rows,
    }


def run(layer, command, root=None, timeout=None):
    """EXECUTE the two arms of one ablation, then compare them (HA-3).

    `command` is the operator's own benchmark command; `{out}` is replaced by that
    arm's output directory (the arm marker is also exported as
    `LONGRUN_ABLATION_ARM`). Both arms run the SAME command: the only difference is
    the layer's env overlay. Timeouts propagate (a hung arm is reported, not
    silently compared as a zero).
    """
    root = root or tempfile.mkdtemp(prefix="longrun-ablation-")
    arms = plan(layer, command, root=root)
    executed = {}
    for name in ("arm_base", "arm_without"):
        out = os.path.join(root, "out_" + name)
        os.makedirs(out, exist_ok=True)
        env = dict(os.environ)
        env.update(arms[name]["env"])
        env["LONGRUN_ABLATION_ARM"] = name
        cmd = arms[name]["command"].replace("{out}", out)
        proc = subprocess.run(cmd, shell=True, env=env, timeout=timeout)
        executed[name] = {"out": out, "rc": proc.returncode, "command": cmd}
    return {
        "layer": layer,
        "root": root,
        "arms": executed,
        "compare": compare(executed["arm_base"]["out"],
                           executed["arm_without"]["out"]),
    }


def check():
    """Offline proof of the instrument: (name, ok, detail) triples."""
    out = []
    for layer in sorted(LAYERS):
        root = tempfile.mkdtemp(prefix="ablation-check-")
        env = materialize(layer, root)
        ok_paths = all(os.path.exists(p) for p in env.values())
        empty = True
        for p in env.values():
            if os.path.isdir(p):
                empty = empty and not os.listdir(p)
            else:
                empty = empty and os.path.getsize(p) == 0
        out.append(("%s: the scratch root exists" % layer, ok_paths, env))
        out.append(("%s: it is EMPTY (the layer is really gone)" % layer, empty, env))
        arms = plan(layer, "python3 -m benchmarks.run", root=root)
        out.append(("%s: the arms differ by exactly this layer" % layer,
                    arms["arm_base"]["env"] == {}
                    and sorted(arms["arm_without"]["env"]) == arms["differs_by"],
                    arms["differs_by"]))
    try:
        plan("tool_descriptions", "true", root=tempfile.mkdtemp())
        out.append(("an unremovable layer is refused", False, "no error raised"))
    except ValueError as exc:
        out.append(("an unremovable layer is refused", True, str(exc)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="harness ablation planner")
    ap.add_argument("--check", action="store_true", help="offline proof only")
    ap.add_argument("--plan", metavar="LAYER", help="print the two arms as JSON")
    ap.add_argument("--run", action="store_true",
                    help="execute both arms (the command must contain {out})")
    ap.add_argument("--command", default="python3 -m benchmarks.run --help")
    args = ap.parse_args(argv)
    if args.run:
        if not args.plan or "{out}" not in args.command:
            print("error: --run needs --plan LAYER and a --command containing {out}",
                  file=sys.stderr)
            return 2
        try:
            res = run(args.plan, args.command)
        except ValueError as exc:
            print("error: %s" % exc, file=sys.stderr)
            return 2
        print(json.dumps(res, indent=2, default=str))
        return 0 if all(a["rc"] == 0 for a in res["arms"].values()) else 1
    if args.check or not args.plan:
        results = check()
        bad = 0
        for name, ok, detail in results:
            print(("PASS " if ok else "FAIL ") + name + (
                (" :: " + str(detail)) if detail and not ok else ""))
            bad += 0 if ok else 1
        print("%d/%d PASS" % (len(results) - bad, len(results)))
        return 0 if bad == 0 else 1
    try:
        print(json.dumps(plan(args.plan, args.command), indent=2))
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
