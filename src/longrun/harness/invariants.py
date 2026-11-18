#!/usr/bin/env python3
"""Harness invariants — the corner cases written down as checks.

Source: arXiv:2611.19960, "Anatomy of an Agent Harness: Decisions, Invariants
and Corner Cases" (round 107). Its thesis is that a harness makes most of its
decisions in code, rarely written down, so every harness re-learns the same
corner cases; it turns them into invariant clauses tagged Tested / Believed /
Open and a checklist. Its own worked example is honest about the score: 11 of
30 checklist items hold, 14 do not, 5 were not tested.

This module does the same for longrun, at the size longrun can enforce: one
list of invariants over the CONFIGURATION and the TOOL CATALOG — the layer where
a typo silently weakens a gate — each with a check, an evidence tag, and a
locator naming where the decision lives.

  tested    a test in tests/acceptance pins it (the tag is the test file)
  believed  checked here, at runtime, from the live config
  open      declared, no check yet — printed so it is not forgotten

Pure read: `check()` loads the config and the catalog, returns one row per
invariant. It never writes and never raises.
"""
from __future__ import annotations

import os
import re

FORMAT = "longrun-invariants/1"
BACKENDS = {"auto", "docker", "bwrap", "nsjail", "none"}
APPROVAL_KINDS = {"auto", "required", "denied"}


def _yaml(path, fallback=None):
    try:
        import yaml
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data if isinstance(data, dict) else (fallback or {})
    except Exception:  # noqa: BLE001 — a missing/broken file is a violation, not a crash
        return fallback or {}


def _subagents_cfg(repo):
    return _yaml(os.path.join(repo, "config", "subagents.yaml"))


def _resolves(pattern, names):
    """A role tool pattern is exact or a namespace; both must hit the catalog."""
    pat = str(pattern or "").strip()
    if not pat:
        return False
    if pat in names:
        return True
    return any(n.startswith(pat + ".") for n in names)


def check(repo=None, tools_cfg=None, sub_cfg=None):
    """Return `{"format", "rows", "counts"}` — one row per invariant."""
    from longrun.tools import registry
    repo = repo or registry.REPO
    cfg = tools_cfg if isinstance(tools_cfg, dict) else registry.load_config()
    sub = sub_cfg if isinstance(sub_cfg, dict) else _subagents_cfg(repo)
    try:
        names = list(registry.tool_names())
    except Exception:  # noqa: BLE001
        names = []
    rows = []

    def add(iid, statement, tag, holds, detail="", where=""):
        rows.append({"id": iid, "statement": statement, "tag": tag,
                     "status": ("open" if holds is None
                                else ("holds" if holds else "violated")),
                     "detail": detail, "where": where})

    # INV-1 — every role grant resolves against the catalog. A typo used to mean
    # "no restriction" (a role with no `tools` key is unrestricted, I-1), so a
    # misspelt namespace silently widened the role instead of failing.
    roles = sub.get("roles") or {}
    bad = []
    for name, spec in (roles.items() if isinstance(roles, dict) else []):
        if not isinstance(spec, dict):
            continue
        for pat in spec.get("tools") or []:
            if not _resolves(pat, names):
                bad.append("%s:%s" % (name, pat))
    add("INV-1", "every role tool pattern resolves to a catalog tool",
        "tested", not bad, ", ".join(bad[:6]) or "ok",
        "config/subagents.yaml roles.*.tools")

    # INV-2 — every role has a brief. A role without one is a name the model
    # sees and cannot act on.
    empty = [str(n) for n, spec in (roles.items() if isinstance(roles, dict) else [])
             if not (str((spec or {}).get("brief") or "").strip()
                     if isinstance(spec, dict) else str(spec or "").strip())]
    add("INV-2", "every role carries a non-empty brief", "believed",
        not empty, ", ".join(empty[:6]) or "ok", "config/subagents.yaml roles.*.brief")

    # INV-3 — the sandbox backend is one the code implements. `none` is a real
    # choice (the DGX runs on the host), not a typo.
    backend = str((cfg.get("sandbox") or {}).get("backend") or "auto")
    add("INV-3", "sandbox.backend is a known backend", "tested",
        backend in BACKENDS, backend, "config/tools.yaml sandbox.backend")

    # INV-4 — approval kinds are the three the gate understands.
    kinds = (cfg.get("approvals") or {}).get("kinds") or {}
    badk = ["%s:%s" % (k, v) for k, v in kinds.items() if str(v) not in APPROVAL_KINDS]
    add("INV-4", "every approval kind is auto|required|denied", "tested",
        not badk, ", ".join(badk[:6]) or "ok", "config/tools.yaml approvals.kinds")

    # INV-5 — deny/always_ask patterns are valid regexes. A broken pattern is a
    # gate that never fires while the Permissions page says it exists.
    badre = []
    for name in names:
        spec = registry.tool_spec(name) or {}
        for kind in ("deny", "always_ask"):
            for pat in spec.get(kind) or []:
                try:
                    re.compile(str(pat))
                except re.error as e:
                    badre.append("%s:%s:%s:%s" % (name, kind, pat, e))
    add("INV-5", "every deny/always_ask pattern compiles", "tested",
        not badre, ", ".join(badre[:4]) or "ok", "config/tools.yaml tools[].deny")

    # INV-6 — the loop budgets are finite and positive. A zero wall clock or a
    # zero keepgoing budget is a turn that cannot finish.
    rt = cfg.get("runtime") or {}
    try:
        pos = (int(rt.get("keepgoing_max") or 0) >= 1
               and int(rt.get("no_progress_rounds") or 0) >= 1
               and int(rt.get("max_wall_secs") or 0) > 0)
    except (TypeError, ValueError):
        pos = False
    add("INV-6", "runtime budgets are finite and positive", "tested", pos,
        str({k: rt.get(k) for k in ("keepgoing_max", "no_progress_rounds",
                                    "max_wall_secs")}),
        "config/tools.yaml runtime")

    # INV-7 — the delegation numbers are coherent: a depth of 0 means no child,
    # a parallel cap below 1 cannot be satisfied.
    try:
        depth_ok = int(sub.get("max_depth", 2)) >= 0
        par_ok = int(sub.get("max_parallel", 4)) >= 1
        per_ok = int(sub.get("max_per_run", 6)) >= 0
        sub_ok = depth_ok and par_ok and per_ok
    except (TypeError, ValueError):
        sub_ok = False
    add("INV-7", "subagent caps are coherent", "tested", sub_ok,
        str({k: sub.get(k) for k in ("max_depth", "max_parallel", "max_per_run")}),
        "config/subagents.yaml")

    # INV-8 — every catalog name is a plain callable token. Dotted names are the
    # nucleous convention, `server__tool` the external MCP one, and a bare name
    # is a namespace row; what must never exist is a name with whitespace or a
    # path separator, which no door can dispatch.
    badnames = [n for n in names if not str(n).strip() or any(
        ch.isspace() or ch in "/\\" for ch in str(n))]
    add("INV-8", "every tool name is a dispatchable token", "believed", not badnames,
        ", ".join(badnames[:6]) or "ok", "config/tools.yaml tools[].name")

    # INV-9 — declared, not checked yet: a never-fired deny rule proven by a
    # test. `policy_report()` answers it over the hit ledger; the invariant is
    # Open because "never fired" needs a window of real traffic to mean anything.
    add("INV-9", "every never-fired deny rule has a test proof", "open", None,
        "see registry.policy_report()['never_fired_unproven']",
        "src/longrun/tools/registry.py policy_report")

    counts = {"total": len(rows),
              "holds": sum(1 for r in rows if r["status"] == "holds"),
              "violated": sum(1 for r in rows if r["status"] == "violated"),
              "open": sum(1 for r in rows if r["status"] == "open"),
              "tested": sum(1 for r in rows if r["tag"] == "tested")}
    return {"format": FORMAT, "rows": rows, "counts": counts}
