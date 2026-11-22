#!/usr/bin/env python3
"""v1280 — the approval gate's precedence is ONE ordered chain, pinned at one seam.

Ticket 07 asked for "an ordered list of gate entries behind one interface" and, as its
own checklist item, that "the composition and ordering of gates is testable at one
seam". The gate already answers one interface — `registry.classify()` returns
`(decision, reason)` with decision in `disabled | denied | auto | required` — and tool
EXECUTION already happens after it (`api_v02.gated_call`). What no single test pinned is
the ORDER: several entries must run BEFORE the `approvals.mode=full` fast path, or FULL
would silently unlock a hard-deny, a locked plan, the matrix-promote checkbox, a delegated
role's scope or a matched `always_ask` rule.

This file pins those relations — "X beats mode=full" and the relative order of the entries
that sit above the fast path — at one seam, so a reorder that flips one of them fails here
by name. It is the ordering half of ticket 07; the internal data-list rewrite is
deliberately parked (see the ticket) because the interface, the execution separation and
the data-driven policy (config/tools.yaml) are already in place.

Deterministic: `registry.scoped_config` (never writes the live config), isolated dirs, no
model, no network. Run: python3 tests/acceptance/v1280_gate_precedence_order.py
"""
import copy
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-v1280-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "DATA_DIR", "GRAPH_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(_tmp, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores              # noqa: E402
from longrun.tools import registry             # noqa: E402

# Hermetic: the gate never needs the live external (MCP) catalog, and resolving it
# would open sockets — the project requires every acceptance test to be no-network.
registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def merged(mode, **approvals):
    """A complete merged config with the approvals mode forced, never the live one."""
    base = copy.deepcopy(registry.load_config())
    ap = base.setdefault("approvals", {})
    ap["mode"] = mode
    ap.update(approvals)
    return base


def raw(tool, args, mode, **kw):
    """classify() under a controlled config (scoped_config: the live config is untouched)."""
    approval_keys = {k: kw.pop(k) for k in ("allow_matrix_promote",)
                     if k in kw}
    with registry.scoped_config(merged(mode, **approval_keys)):
        return registry.classify(tool, args, **kw)


def beats_full(tool, args, expected, **kw):
    """True when a rule still decides `expected` even under `approvals.mode=full`."""
    dec, why = raw(tool, args, "full", **kw)
    return dec == expected, (dec, why)


# ---- 0. anti-vacuity: the seam really reaches classify -----------------------
_norm, _ = raw("fs.write", {"path": "x.txt", "content": "y"}, "normal")
_full, _ = raw("fs.write", {"path": "x.txt", "content": "y"}, "full")
check("self-test: mode=normal needs approval for a mutating tool", _norm == "required", _norm)
check("self-test: mode=full auto-approves the SAME call (the seam flips it)", _full == "auto", _full)
# The helper must be able to answer False: a plain mutating call does NOT beat FULL.
_ok_false, _det_false = beats_full("fs.write", {"path": "x.txt", "content": "y"}, "required")
check("self-test: beats_full reports False when a rule does NOT beat FULL", not _ok_false, _det_false)
_ok_true, _det_true = beats_full("fs.read", {"path": ".env"}, "denied")
check("self-test: beats_full reports True when a rule DOES beat FULL", _ok_true, _det_true)

# ---- 1. the entries that must sit ABOVE the mode=full fast path --------------
# Hard-deny (config/tools.yaml `deny`): the env file in every fs verb.
for _verb in ("fs.read", "fs.write", "fs.edit"):
    _ok, _det = beats_full(_verb, {"path": ".env", "content": "x"}, "denied")
    check("%s of .env is DENIED even at mode=full (hard-deny > full)" % _verb, _ok, _det)
# The sealed judge path is denied too (a second deny pattern, not the same rule).
_ok, _det = beats_full("fs.read", {"path": "data/heldout/case.json"}, "denied")
check("reading the sealed held-out judge is denied even at mode=full", _ok, _det)

# `enabled: false` (the allowlist) is decided BEFORE deny and before mode=full.
_off = merged("full")
_off["tools"]["fs.read"]["enabled"] = False
with registry.scoped_config(_off):
    _d_off, _r_off = registry.classify("fs.read", {"path": ".env"})
check("a disabled tool is 'disabled' even when disable+deny+FULL all apply", _d_off == "disabled",
      (_d_off, _r_off))

# A delegated role's tool scope is the delegation CONTRACT: denied before mode=full.
_ok, _det = beats_full("shell", {"command": "ls"}, "denied", allow=["fs"], scope_name="reader")
check("role_scope denies a tool outside the role even at mode=full (scope > full)", _ok, _det)

# `always_ask` is a matched subject that must reach a human even under FULL.
_ok, _det = beats_full("git", {"args": "push origin main"}, "required")
check("a matched always_ask rule still asks at mode=full (always_ask > full)", _ok, _det)

# The dedicated matrix-promote checkbox: unchecked denies, checked auto-approves, both at FULL.
_ok_no, _det_no = beats_full("matrix",
                             {"action": "promote_to_nucleous", "kind": "tool", "name": "fast_calc"},
                             "denied", allow_matrix_promote=False)
check("promote_to_nucleous is denied at mode=full without the checkbox", _ok_no, _det_no)
_ok_yes, _det_yes = beats_full("matrix",
                               {"action": "promote_to_nucleous", "kind": "tool", "name": "fast_calc"},
                               "auto", allow_matrix_promote=True)
check("promote_to_nucleous is authorised at mode=full WITH the checkbox", _ok_yes, _det_yes)

# An explicit plan lock is never bypassed by mode=full.
_sid = stores.get_or_create_session(None, title="v1280 plan lock")["id"]
stores.set_plan_mode(_sid, True)
_ok, _det = beats_full("fs.write", {"path": "x.txt", "content": "y"}, "denied", session=_sid)
check("a locked plan still denies a write at mode=full (plan-lock > full)", _ok, _det)
check("a read-only tool still passes a locked plan",
      raw("fs.read", {"path": "x.txt"}, "normal", session=_sid)[0] in ("auto", "required"),
      raw("fs.read", {"path": "x.txt"}, "normal", session=_sid))

# Unknown tool is refused before anything else (also at FULL).
_ok, _det = beats_full("zzz.not_a_tool", {}, "denied")
check("an unknown tool is denied even at mode=full", _ok, _det)

# ---- 2. mode=full is what relaxes the workspace boundary --------------------
# Outside the session workspace: normal needs approval even for an auto-read tool;
# FULL (the explicit opt-out) is the only thing that lifts it.
_ws = os.path.join(_tmp, "ws")
os.makedirs(_ws, exist_ok=True)
_out_norm, _ = raw("fs.read", {"path": "/etc/passwd"}, "normal", workspace=_ws)
_out_full, _ = raw("fs.read", {"path": "/etc/passwd"}, "full", workspace=_ws)
check("a call outside the workspace asks under mode=normal (outside > per-tool auto)",
      _out_norm == "required", _out_norm)
check("mode=full is the ONLY thing that lifts the workspace boundary", _out_full == "auto", _out_full)

# ---- 3. floors --------------------------------------------------------------
_decisions = {raw("fs.read", {"path": "x.txt"}, "normal")[0],
              raw("fs.write", {"path": "x.txt", "content": "y"}, "normal")[0],
              raw("zzz", {}, "normal")[0]}
check("every decision is one of the four documented values",
      _decisions <= {"disabled", "denied", "auto", "required"}, _decisions)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
