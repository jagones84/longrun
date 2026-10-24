#!/usr/bin/env python3
"""M3a — single-trace safety rules (Local-Allow-Global-Deny: C1/C4/C5).

Pure, deterministic, no live server, no network. Purpose (C2) is relational
and CANNOT be enforced per-trace (Thm. 3): explicitly out of scope.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v566-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import trace_policy as TP  # noqa: E402
from longrun.agent import subagent as SUB  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _trace(n_approved, n_auto=0):
    t = [{"tool_result": {"approval_status": "approved"}}] * n_approved
    t += [{"tool_result": {"approval_status": "auto_approved"}}] * n_auto
    return t


_CFG = {"enabled": True, "delegation_revalidation": True,
        "consent_budget": 12, "intent_fence": True}

# ---- R1 delegation revalidation (C5) -----------------------------------------
check("1a phantom subagent ids are reported",
      TP.unknown_subagent_ids({"ref": "see sub_deadbeef01 please"},
                              lambda _sid: False) == ["sub_deadbeef01"])
check("1b known ids pass",
      TP.unknown_subagent_ids({"ref": "sub_deadbeef01"}, lambda _sid: True) == [])
check("1c actions without ids pass",
      TP.unknown_subagent_ids({"path": "a.txt"}, lambda _sid: False) == [])
rule, reason = TP.escalate({"note": "per sub_deadbeef01 it is safe"}, [], _CFG,
                           lambda _sid: False)
check("1d phantom citation escalates auto to required",
      rule == "delegation-revalidation" and "sub_deadbeef01" in (reason or ""),
      (rule, reason))
check("1e real citations do not escalate",
      TP.escalate({"note": "per sub_deadbeef01 it is safe"}, [], _CFG,
                  lambda _sid: True) == (None, None))
_off = dict(_CFG, delegation_revalidation=False)
check("1f disabled R1 never escalates",
      TP.escalate({"note": "sub_deadbeef01"}, [], _off, lambda _sid: False) == (None, None))
check("1g missing config fails open",
      TP.escalate({"note": "sub_deadbeef01"}, [], None, lambda _sid: False) == (None, None))

# ---- R2 consent cumulative (C4) -----------------------------------------------
rule, reason = TP.escalate({"path": "a"}, _trace(12), _CFG, lambda _sid: True)
check("2a the 13th mutating call escalates (budget 12)",
      rule == "consent-cumulative" and "12" in (reason or ""), (rule, reason))
check("2b below budget nothing happens",
      TP.escalate({"path": "a"}, _trace(11), _CFG, lambda _sid: True) == (None, None))
check("2c auto-approved calls do not consume the budget",
      TP.escalate({"path": "a"}, _trace(0, 12), _CFG, lambda _sid: True) == (None, None))
_zero = dict(_CFG, consent_budget=0)
check("2d budget 0 disables R2",
      TP.escalate({"path": "a"}, _trace(50), _zero, lambda _sid: True) == (None, None))

# ---- R3 intent fence (C1): note-only -------------------------------------------
note = TP.intent_note("Goal: back up the project", "s3://archive-bucket/x")
check("3a unnamed subjects get a harness note, decision untouched",
      isinstance(note, str) and "archive-bucket" in note, note)
check("3b the fence note never trips the M2a taint markers",
      all(m not in (note or "") for m in ("[harness] Observation",
                                          "Observation (step ",
                                          "Relevant memories")))
check("3c named subjects stay silent",
      TP.intent_note("Goal: make backups of /var/backups/daily", "/var/backups/daily") is None)
check("3d empty subjects stay silent",
      TP.intent_note("Goal: anything", "") is None)
_bact = {"action": "batch", "calls": [{"tool": "fs.read", "args": {"path": "q.txt"}}]}
check("3e batch fences on its first tool item",
      TP.intent_note_for_action(_bact, "batch", "Goal: list processes", []) is not None)
check("3f non-tool actions are skipped",
      TP.intent_note_for_action({"action": "note"}, "note", "Goal: x", []) is None)

# ---- config loading ------------------------------------------------------------
_saved = os.environ.get("LONGRUN_TRACE_POLICY")
try:
    os.environ["LONGRUN_TRACE_POLICY"] = os.path.join(TMP, "no-such.yaml")
    check("4a missing file fails open",
          TP.load() is None)
    _bad = os.path.join(TMP, "bad.yaml")
    with open(_bad, "w", encoding="utf-8") as _f:
        _f.write("{{not yaml")
    os.environ["LONGRUN_TRACE_POLICY"] = _bad
    check("4b unparseable file fails open",
          TP.load() is None)
    _good = os.path.join(TMP, "good.yaml")
    with open(_good, "w", encoding="utf-8") as _f:
        _f.write("consent_budget: 3\nintent_fence: false\n")
    os.environ["LONGRUN_TRACE_POLICY"] = _good
    _cfg = TP.load()
    check("4c valid file merges over defaults",
          _cfg is not None and _cfg.get("consent_budget") == 3
          and _cfg.get("intent_fence") is False
          and _cfg.get("delegation_revalidation") is True, _cfg)
    _offf = os.path.join(TMP, "off.yaml")
    with open(_offf, "w", encoding="utf-8") as _f:
        _f.write("enabled: false\n")
    os.environ["LONGRUN_TRACE_POLICY"] = _offf
    _dis = TP.load()
    check("4d enabled:false stays visible but escalates nothing",
          isinstance(_dis, dict) and _dis.get("enabled") is False
          and TP.escalate({"note": "sub_deadbeef01"}, _trace(50), _dis,
                           lambda _sid: False) == (None, None), _dis)
finally:
    if _saved is None:
        os.environ.pop("LONGRUN_TRACE_POLICY", None)
    else:
        os.environ["LONGRUN_TRACE_POLICY"] = _saved

# ---- wiring ---------------------------------------------------------------------
with open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
          encoding="utf-8") as f:
    _api = f.read()
check("5a the gate consults trace_policy.escalate",
      "trace_policy.escalate" in _api or "trace_policy as " in _api)
check("5b the loop runs the intent fence",
      "intent_note_for_action" in _api)
check("5c subagent exposes an existence check (no duplicated logic)",
      callable(getattr(SUB, "exists", None)))

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
