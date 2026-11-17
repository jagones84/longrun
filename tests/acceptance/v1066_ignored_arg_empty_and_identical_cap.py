#!/usr/bin/env python3
"""v1066 — three lies the harness used to hand the model (measured on `architect`).

From the transcript of session `architect` (226 tool calls, 2026-11-17):

  B. msg 19: `glob.list {"pattern":..,"path":..}` → the harness dropped `path` with
     only a warning, searched the DEFAULT root, and returned
     `ok=True, exit_code=0, stdout="(no match)"`. The model read that as "the file
     does not exist" and changed course on a false premise.
  A. the same `workspace.json` was read 5 times (msg 34/62/74/80) before the
     "YOU ARE STUCK" nudge fired ONCE (msg 81): the anti-loop counter compared only
     the PREVIOUS call, and the hard block covered only FAILED calls.
  D. 6 refusals read `"… is not exploration; only read-only tools work …"` — jargon
     that never told the operator to click ▶, so the agent re-proposed the plan.

Contract pinned here:
  B1 an ignored argument on a call that returns NO payload is INVALID_INPUT (exit 64)
  B2 that reply names the ignored key and says the answer is NOT "it does not exist"
  B3 the SAME call with the RIGHT key still succeeds (no new strictness)
  B4 an ignored argument on a call that DOES return data stays a warning (v874 A3)
  A1 the loop remembers each call's observation across the whole turn
  A2 the HARD block fires ONLY on the re-run of a FAILED call — a SUCCESSFUL
     repeat (`shell {action:"status"}` polling a job, a re-read after an edit) is
     NEVER refused, because refusing it broke legitimate work and lied ("it FAILED")
  A3 the "stuck" nudge fires only when the OBSERVATION also repeats: a poll that
     returns a new state each time is progress, not a loop (measured live: 5
     legitimate polls drew 4 nudges and the model argued with the harness)
  D1 the plan-mode refusal still says "plan mode" (v597 B2/B5)
  D2 it now names the OPERATOR action (the ▶ / `forge.py docs implement`)

Deterministic: isolated temp dirs, no model, no network.
Run: python3 tests/acceptance/v1066_ignored_arg_empty_and_identical_cap.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1066-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for _d in ("cfg", "sessions", "data"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores       # noqa: E402
from longrun.tools import registry      # noqa: E402
from longrun.tools import tools as T    # noqa: E402

# Deterministic: never start a configured external MCP client in a test.
registry._external_tools = lambda: {}
registry._matrix_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- B: an ignored argument that produced an EMPTY answer -------------------
_empty = T._dispatch_execute(
    "glob.list", {"pattern": "**/*__v1066_no_such_file__*", "path": "/home/jagones/.trae"})
check("B1 an ignored arg + empty result is INVALID_INPUT (exit 64)",
      _empty.get("ok") is False and _empty.get("exit_code") == 64,
      "ok=%s exit=%s" % (_empty.get("ok"), _empty.get("exit_code")))
check("B2 the reply NAMES the ignored key and denies 'it does not exist'",
      "path" in (_empty.get("error") or "")
      and "NOT 'it does not exist'" in (_empty.get("error") or ""),
      _empty.get("error"))
check("B2b the ignored key is still listed for the model",
      bool(_empty.get("ignored_args")) and "path" in str(_empty.get("warning") or ""),
      repr((_empty.get("ignored_args"), _empty.get("warning"))))

_control = T._dispatch_execute(
    "glob.list", {"pattern": "*.yaml", "root": os.path.join(REPO, "config")})
check("B3 the SAME call with the RIGHT key still succeeds",
      _control.get("ok") is True and (_control.get("count") or 0) > 0,
      "ok=%s count=%s" % (_control.get("ok"), _control.get("count")))

_warn = T._dispatch_execute(
    "self", {"action": "tools", "tool": "fs.read", "bogus_arg": "v1066-X1"})
check("B4 an ignored arg on a call that RETURNS data stays a warning (v874 A3)",
      _warn.get("ok") is True and "bogus_arg" in (_warn.get("warning") or ""),
      "ok=%s warning=%r" % (_warn.get("ok"), _warn.get("warning")))

# ---- A: identical calls across the WHOLE turn ------------------------------
with open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
          encoding="utf-8") as _fh:
    _src = _fh.read()
check("A1 the loop remembers each call's observation across the whole turn",
      "_call_obs = {}" in _src and "_same_obs_n = Counter()" in _src, "")
check("A2 the HARD block fires ONLY on a FAILED re-run (a successful repeat runs on)",
      "_call_h == _last_failed_hash" in _src and "_same_before >= 2" not in _src, "")
check("A3 the nudge requires the OBSERVATION to repeat too (polling is progress)",
      "_same_obs = _call_obs.get(_call_h) == obs" in _src
      and "_same_obs_n[_call_h] >= 1" in _src, "")

# ---- D: the plan-mode refusal names the OPERATOR action --------------------
_s = stores.get_or_create_session(None, title="v1066-plan")
_sid = _s["id"]
stores.set_plan_mode(_sid, True)
stores.propose_plan(_sid, ["step one"])
stores.approve_plan(_sid)          # implement=False -> approved but still locked
_dec, _why = registry.classify("shell", {"_session": _sid})
check("D1 the refusal still says 'plan mode' (v597 B2/B5)",
      _dec == "denied" and "plan mode" in _why, repr((_dec, _why)))
check("D2 it names the OPERATOR action (the ▶ / forge.py docs implement)",
      "▶" in _why and "implement" in _why, _why)
check("D3 it states the real plan status instead of 'unapproved'",
      "APPROVED" in _why and "NOT authorised" in _why, _why)

print("---")
ok = sum(results)
print("\nv1066: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
