#!/usr/bin/env python3
"""v1140 — the optimizer is shown the LIVE policy, not its retired history.

Round 75 (2026-11-18). The registry's `policy_report()` already separates the rules
that FIRED and are still configured from the ledger keys the policy no longer owns
(`retired_rules`, round 67). `evolve/optimizer.py` ignored that split:

  * it printed the first five ledger keys as "Policy firings", retired rules
    included — one of them (`shell.exec:deny:grep[^\\n]*\\.env`) is the subject of
    the one pending proposal the registry refuses to apply;
  * it passed those full keys to `tool_spec`, which knows no such tool, so the
    "Current live policy" section read "(not available)" on the live ledger —
    the 2026-11-17 fix never produced a line of real data.

Contract:
  A `_hit_rows` splits the ledger by the registry's own `retired_rules`
  B the prompt names live rules, retired rules and never-fired rules apart
  C the live-policy snapshot resolves the TOOL NAME from the key
  D the history block marks a pending proposal that can no longer apply
  E an unparseable reply is kept in the log (dead model vs malformed reply)

Deterministic: temp data/config dirs, no model, no network.
Run: python3 tests/acceptance/v1140_optimizer_sees_live_policy.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1140-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_OPTIMIZER_LOG"] = os.path.join(TMP, "optimizer_runs.jsonl")
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.evolve import optimizer as O      # noqa: E402
from longrun.tools import registry as R        # noqa: E402
from longrun.util import improve as I          # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


LIVE_RULE = "LONGRUN_TOKEN"
GONE_RULE = "grep[^\\n]*\\.env"
NEVER_RULE = "NEVER-RAN"
HITS = {
    "firings": {
        "shell.exec:deny:" + LIVE_RULE: {"n": 4},
        "shell.exec:deny:" + GONE_RULE: {"n": 9},
        "fs.read:deny:ENV-READ": {"n": 2},
        "shell:deny:GONE-NAMESPACE": {"n": 7},
        "not-a-key": {"n": 1},
        "shell.exec:deny:a:b": {"n": 1},
    },
    "retired_rules": ["shell.exec:deny:" + GONE_RULE, "shell:deny:GONE-NAMESPACE"],
    "never_fired": ["fs.edit:deny:" + NEVER_RULE],
    "unknown_args": {},
}

# ---- A) the split ------------------------------------------------------------
live, gone = O._hit_rows(HITS)
check("A1 live rows are the ones the registry still owns", len(live) == 3, len(live))
check("A2 retired rows are named by `retired_rules`", len(gone) == 2, len(gone))
check("A3 a malformed key is skipped instead of guessed", len(live) + len(gone) == 5,
      len(live) + len(gone))
check("A4 rows are ordered by firing count, busiest first",
      live[0]["n"] == 4 and gone[0]["n"] == 9, (live[0], gone[0]))
check("A5 a pattern may contain a colon", any(r["pattern"] == "a:b" for r in live), live)
check("A6 the row carries tool, kind, pattern and n",
      {k: live[-1][k] for k in ("tool", "kind", "n")} == {"tool": "shell.exec",
                                                         "kind": "deny", "n": 1},
      live[-1])

# ---- B) the prompt names the three states apart ------------------------------
PROMPT = O._build_analysis_prompt({"tokens": 10, "steps": 2, "outcome": "ok", "model": "m"},
                                  HITS, {}, {})
LIVE_HEAD = "Rules that FIRED and are STILL in the live policy"
GONE_HEAD = "Ledger history of rules the live policy NO LONGER has"
NEVER_HEAD = "Configured rules that NEVER fired"


def section(head, stops=(LIVE_HEAD, GONE_HEAD, NEVER_HEAD, "Unknown args",
                         "Current live policy")):
    i = PROMPT.find(head)
    if i < 0:
        return ""
    ends = [j for j in (PROMPT.find(s, i + len(head)) for s in stops) if j > 0]
    return PROMPT[i:min(ends or [len(PROMPT)])]


live_sec, gone_sec, never_sec = section(LIVE_HEAD), section(GONE_HEAD), section(NEVER_HEAD)
check("B1 the live section names the rule and its count",
      LIVE_RULE in live_sec and "x4" in live_sec, live_sec)
check("B2 a retired rule is NOT listed as a live firing", GONE_RULE not in live_sec,
      live_sec)
check("B3 the retired section names it and says it cannot be removed",
      GONE_RULE in gone_sec and "cannot be removed" in gone_sec, gone_sec)
check("B4 never-fired rules are context, with the caution",
      NEVER_RULE in never_sec and "may be doing its job" in never_sec, never_sec)
check("B5 the raw first-five ledger dump is gone", "Policy firings:" not in PROMPT)
check("B6 the live section is bounded to 12 rows",
      LIVE_HEAD in PROMPT and PROMPT.count("  shell.exec deny x") <= 12,
      PROMPT.count("  shell.exec deny x"))
_big = {"firings": {"t%d:deny:p%d" % (i, i): {"n": 100 - i} for i in range(20)},
        "retired_rules": ["t%d:deny:p%d" % (i, i) for i in range(10, 20)]}
_p2 = O._build_analysis_prompt({"tokens": 1, "steps": 1, "outcome": "ok", "model": "m"},
                               _big, {}, {})
check("B7 10 live + 10 retired rows stay bounded (10 + 6)",
      _p2.count("  t") == 16, _p2.count("  t"))

# ---- C) the snapshot resolves the tool NAME from the key ---------------------
SNAP = O._policy_snapshot(HITS)
check("C1 the live policy is NOT '(not available)' for a firings-only report",
      bool(SNAP.strip()), SNAP)
check("C2 it starts with the busiest live tool", SNAP.startswith("shell.exec:"), SNAP[:80])
_spec = R.tool_spec("shell.exec") or {}
check("C3 it prints the live deny list verbatim",
      json.dumps(_spec.get("deny") or []) in SNAP, SNAP[:200])
check("C4 it names the other live tools too",
      "fs.read:" in SNAP and "fs.edit:" in SNAP, SNAP)
check("C5 a retired tool's key never reaches the snapshot", "GONE-NAMESPACE" not in SNAP, SNAP)
_nf = O._policy_snapshot({"firings": {}, "retired_rules": [],
                          "never_fired": ["fs.read:deny:X"]})
check("C6 a never-fired rule still yields its row's live values", _nf.startswith("fs.read:"),
      _nf[:80])
_many = {"firings": {"%s:deny:x" % t: {"n": 10 - i}
                     for i, t in enumerate(("shell.exec", "fs.read", "fs.write",
                                            "fs.edit", "git.run"))},
         "retired_rules": []}
check("C7 the snapshot is capped at four tool rows",
      len([ln for ln in O._policy_snapshot(_many).split("\n") if ln]) == 4,
      O._policy_snapshot(_many))

# ---- D) a pending proposal that cannot apply is marked -----------------------
_before = I.list_proposals
I.list_proposals = lambda: [{"id": "1-registry", "status": "pending", "scope": "registry",
                            "stale": "cannot be applied: `remove` names a rule that is not live",
                            "delta": {"target": "shell.exec", "field": "deny",
                                      "remove": [GONE_RULE]},
                            "reason": "drop the .env block"}]
try:
    _hist = O._evolution_history()
    _block = O._history_block(_hist)
finally:
    I.list_proposals = _before
check("D1 the history keeps the stale marker", _hist and _hist[0]["stale"], _hist)
check("D2 the prompt says it cannot apply", "cannot apply" in _block, _block)
check("D3 it still names the delta and its reason",
      "shell.exec.deny" in _block and "drop the .env block" in _block, _block)

# ---- E) an unparseable reply is kept in the log ------------------------------
O._read_trace = lambda sid: {"tokens": 10, "steps": 2, "outcome": "ok", "model": "m"}
O._read_policy_hits = lambda: HITS
O._read_job_cost = lambda jid: {}
O._read_feedback = lambda sid: {}
O._call_model = lambda prompt, model=None: "I could not find any issue."
_r = O.run("v1140-a")
check("E1 the reply is kept when it cannot be parsed", _r.get("reply") ==
      "I could not find any issue.", _r.get("reply"))
O._call_model = lambda prompt, model=None: None
_r2 = O.run("v1140-b")
check("E2 a failed model call is recorded as an empty reply", _r2.get("reply") == "",
      _r2.get("reply"))
with open(os.environ["LONGRUN_OPTIMIZER_LOG"], encoding="utf-8") as f:
    _rows = [json.loads(line) for line in f if line.strip()]
check("E3 the log row carries the reply",
      any("reply" in (r.get("proposal") or {}) for r in _rows), len(_rows))
check("E4 the evidence separates live and retired firings",
      _r2["evidence"].get("live_firings") == 3
      and _r2["evidence"].get("retired_firings") == 2
      and _r2["evidence"].get("never_fired") == 1, _r2["evidence"])
check("E5 the mixed 'policy_firings' count is gone",
      "policy_firings" not in _r2["evidence"], _r2["evidence"])

# ---- F) the assembled prompt carries the live policy -------------------------
check("F1 the prompt shows the live deny list of the row it names",
      "Current live policy" in PROMPT and json.dumps(_spec.get("deny") or []) in PROMPT)
check("F2 it does not say '(not available)' when firings exist",
      "(not available)" not in PROMPT)

print("---")
passed = sum(RESULTS)
print("%d/%d PASS" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
