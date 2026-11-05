#!/usr/bin/env python3
"""v801 — a BLOCKED tool call says WHY (it is not an approval and never will be).

Live incident 2026-11-04 (operator: *"the shell is blocked … I am on full settings
in tools e approval!! … nothing appeared in the approval menu RH panel very very
grave"*). Session `longrunAgent` (agent A1) tried to shut the Windows PC down:

    result: "blocked"   error: ""   backend: "harness"   approval: None

`registry.classify` DOES return a precise reason (`matches hard-deny pattern
'\\b(shutdown|reboot|poweroff)\\b'`), and `api_v02.gated_call` returns it in
`.reason`. The agent loop built the observation from
`observation -> error -> status`, so the reason was DROPPED and the model — and the
operator — got the single word "blocked". The card carried an empty `error`.
Retrying was the only thing the model could do, and it did, four times.

Contract locked here:
  * `gated_call` surfaces the reason as `error` too, so every consumer that only
    reads `error` stays correct;
  * `_gate_observation` turns a block into a sentence that names the rule and says
    an approval cannot exist (so a retry is pointless);
  * an approval-gated outcome keeps its existing wording (no behaviour change);
  * `mode=full` is NOT what this fixes: a hard deny is a capability boundary and
    must stay absolute — only its visibility changes.

Deterministic, no live model, no network, no server.

Run: python3 tests/acceptance/v801_blocked_reason.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v801-")
for _k, _v in (("LONGRUN_DATA_DIR", "data"), ("LONGRUN_CONFIG_DIR", "cfg"),
               ("LONGRUN_SESSIONS_DIR", "sessions"), ("LONGRUN_RUNS_DIR", "runs"),
               ("LONGRUN_DB", "events.db"), ("LONGRUN_GRAPH_DIR", "graphs")):
    os.environ[_k] = os.path.join(TMP, _v)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                    # noqa: E402,F401  (import order)
from longrun.core import api_v02                   # noqa: E402
from longrun.agent import agent as A               # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ------------------------------------------- A. gated_call keeps the reason -----
_blk = api_v02.gated_call("shell", {"command": "echo shutdown /s /t 5"})
check("A1 a deny-listed command is blocked", _blk.get("status") == "blocked", _blk.get("status"))
check("A2 the reason names the hard-deny pattern",
      "hard-deny" in str(_blk.get("reason")) and "shutdown" in str(_blk.get("reason")),
      _blk.get("reason"))
check("A3 the reason is ALSO in `error` (consumers that read only error are correct)",
      _blk.get("error") == _blk.get("reason"), (_blk.get("error"), _blk.get("reason")))
check("A4 no approval record is created for a hard block",
      _blk.get("approval") in (None, {}), _blk.get("approval"))

# ------------------------------------- B. the observation the MODEL reads -------
_obs, _err = A._gate_observation(
    "shell.exec", {"status": "blocked",
                   "reason": "matches hard-deny pattern 'shutdown'"})
check("B1 the observation names the tool", "shell.exec" in _obs, _obs)
check("B2 the observation carries the rule", "matches hard-deny pattern 'shutdown'" in _obs, _obs)
check("B3 the observation says it was NOT executed", "NOT executed" in _obs, _obs)
check("B4 the observation says an approval cannot exist (a retry is pointless)",
      "approval" in _obs and ("cannot" in _obs or "no " in _obs), _obs)
check("B5 the card error carries the reason", _err == "matches hard-deny pattern 'shutdown'", _err)

_obs2, _err2 = A._gate_observation("shell.exec", {"status": "blocked"})
check("B6 a block with no reason still reads sanely",
      "no reason given" in _obs2 and bool(_err2), (_obs2, _err2))

# --------------------------- C. an approval outcome is untouched (no regression) --
_p, _pe = A._gate_observation("fs.write", {"status": "pending", "approval": {"id": "ap1"}})
check("C1 pending keeps its existing wording", "approval pending" in _p and "ap1" in _p, _p)
check("C2 pending leaves the card error empty", _pe == "", _pe)
_d, _de = A._gate_observation("fs.write", {"status": "denied"})
check("C3 a user denial keeps its wording", "DENIED by the user" in _d, _d)
_x, _xe = A._gate_observation("fs.write", {"status": "executed"})
check("C4 an executed call produces no gate sentence", _x == "" and _xe == "", (_x, _xe))

# ------------------------------------------------------------- D. wiring ------
_src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
            encoding="utf-8").read()
check("D1 the chat loop uses the one helper", "_gate_observation(" in _src
      and _src.count("def _gate_observation(") == 1)
check("D2 the observation fallback includes the reason",
      'res.get("reason")' in _src)
check("D3 the card gets the reason when the tool produced none",
      '_gerr' in _src and 'dict(sub, error=' in _src)

_ap = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
           encoding="utf-8").read()
check("D4 both blocked return sites carry an error field",
      _ap.count('"status": "blocked"') >= 2
      and '"error": reason' in _ap
      and '"error": "tool %r is disabled (allowlist)" % tool' in _ap)

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
