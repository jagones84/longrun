#!/usr/bin/env python3
"""v1267 — cheap first, escalate on evidence (round 166).

Source: S-2026-11-22-009, Zhou et al., *Reducing Inference Cost of Coding Agents
with Timeout Cascades*, arXiv:2611.24324 — a small-first cascade keeps the large
model's resolve rate (73.4% vs 71.2%) at 16.4% fewer GPU-hours overall and 33.5%
on easy tasks, for 1.5 points less than an oracle router, at the price of
wall-clock time on tasks that fall back. S-2026-11-22-010 (Vanguard) and
S-2026-11-22-011 (calibrated decision rewards) support trusting the cheap stage
until evidence disagrees.

What this pins:

  A  the config: off by default, and a plan is only enabled with two model names
  B  the decision: small until a failure/repeat/invalid streak or a wall-clock
     budget, then the large model, once
  C  the summary counts escaped turns and a cost proxy, and reports no-rows
  D  the live seam: the prompt is assembled for the cascade's first model and the
     decision runs before every call
  E  the forge group runs headless

Deterministic: no model, no network, no server.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from longrun.harness import model_cascade as mc  # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


def cfg(**extra):
    base = {"enabled": True, "small": "small-a", "large": "large-a",
            "interactive": True,
            "escalate": {"failure_streak": 2, "same_obs": 2, "invalid_streak": 2,
                         "wall_seconds": 0}}
    base.update(extra)
    return base


# ── A · configuration ──────────────────────────────────────────────────────
base = mc.load("/nonexistent/cascade.yaml")
check("A1 a missing file means disabled with defaults",
      base["enabled"] is False and base["small"] == "" and "escalate" in base, base)
plan = mc.plan(base)
check("A2 a disabled config plans nothing", plan["enabled"] is False, plan["reason"])
plan = mc.plan({"enabled": True, "small": "s", "large": ""})
check("A3 one model name is not a cascade", plan["enabled"] is False, plan["reason"])
plan = mc.plan(cfg(interactive=False), interactive=True)
check("A4 interactive:false keeps the cascade off for a chat turn", plan["enabled"] is False)
plan = mc.plan(cfg(), interactive=True)
check("A5 a complete config starts on the small model",
      plan["enabled"] and plan["model"] == "small-a" and plan["large"] == "large-a")
cfgfile = os.path.join(REPO, "config", "cascade.yaml")
# The TOGGLE is operator state (it moved to `enabled: true` on 2026-11-26 when
# `roles.subagent` became deepseek-flash); what this pins is that the shipped file
# parses and is COMPLETE, not which way the operator last flipped it.
check("A6 the shipped config parses and carries its keys", os.path.isfile(cfgfile)
      and isinstance(mc.load(cfgfile).get("enabled"), bool)
      and "escalate" in mc.load(cfgfile))

# ── B · the decision ───────────────────────────────────────────────────────
p = mc.plan(cfg())
state = {"current": "small-a", "failure_streak": 0, "same_obs": 0,
         "invalid_streak": 0, "wall_seconds": 1}
d = mc.decide(state, p)
check("B1 a clean step stays on the cheap model",
      d["model"] == "small-a" and d["escalate"] is False, d["reason"])
d = mc.decide(dict(state, failure_streak=2), p)
check("B2 a failure streak escalates",
      d["model"] == "large-a" and d["escalate"] and d["reason"] == "failure-streak")
d = mc.decide(dict(state, same_obs=2), p)
check("B3 a repeated state-action pair escalates",
      d["escalate"] and d["reason"] == "repeated-state-action")
d = mc.decide(dict(state, invalid_streak=2), p)
check("B4 an invalid-output streak escalates", d["escalate"] and d["reason"] == "invalid-output")
pwall = mc.plan(cfg(escalate={"failure_streak": 2, "same_obs": 2, "invalid_streak": 2,
                              "wall_seconds": 30}))
d = mc.decide(dict(state, wall_seconds=45), pwall)
check("B5 the wall-clock budget escalates",
      d["escalate"] and d["reason"] == "wall-clock" and d["threshold"] == 30)
d = mc.decide(dict(state, escalated=True, failure_streak=9), p)
check("B6 escalation happens once per turn",
      d["model"] == "large-a" and d["escalate"] is False, d["reason"])
d = mc.decide({"current": "m", "failure_streak": 9}, {"enabled": False})
check("B7 a disabled cascade never changes the model",
      d["model"] == "m" and d["escalate"] is False)
check("B8 the thresholds are configurable",
      mc.decide(dict(state, failure_streak=1), mc.plan(cfg(escalate={
          "failure_streak": 1, "same_obs": 2, "invalid_streak": 2,
          "wall_seconds": 0})))["escalate"])

# ── C · accounting ─────────────────────────────────────────────────────────
rows = [{"tier": "small", "solved": True, "calls_small": 8},
        {"tier": "escalated", "solved": True, "calls_small": 4, "calls_large": 6},
        {"tier": "small", "solved": False, "calls_small": 10}]
s = mc.summary(rows)
check("C1 the summary counts escalations and cheap solves",
      s["turns"] == 3 and s["escalated"] == 1 and s["small_solved"] == 1
      and s["escalation_rate"] == 0.3333, s)
check("C2 an empty sample reports no-rows", mc.summary([])["verdict"] == "no-rows")

# ── D · the live seam ──────────────────────────────────────────────────────
source = open(os.path.join(SRC, "longrun", "agent", "agent.py"), encoding="utf-8").read()
assemble = source.find("msgs, ctx_stats = assemble_turn(")
check("D1 the cascade is planned before the prompt is assembled",
      "_mc.plan(" in source[:assemble][-1200:])
call = source.find("server.stream_with_fallback(")
check("D2 the decision runs before the model call",
      "_mc.decide(" in source[:call][-4000:]
      and "_cascade.get(\"enabled\")" in source[:call][-4000:])
check("D3 an escalation is announced",
      'publish("model.escalated"' in source)

# ── E · the forge group ────────────────────────────────────────────────────
import subprocess  # noqa: E402
doc = os.path.join(tempfile.mkdtemp(prefix="sf-v1267-"), "cascade.json")
with open(doc, "w", encoding="utf-8") as fh:
    json.dump({"config": cfg(), "state": {"current": "small-a", "failure_streak": 2,
                                          "same_obs": 0, "invalid_streak": 0,
                                          "wall_seconds": 0}}, fh)
env = dict(os.environ, PYTHONPATH=SRC)
out = subprocess.run([sys.executable, os.path.join(SRC, "longrun", "core", "forge.py"),
                      "cascade", "decide", doc], capture_output=True, text=True,
                     env=env, timeout=60)
check("E1 cascade decide runs headless",
      out.returncode == 0 and '"escalate": true' in out.stdout, out.stdout[:160])

print("\n%d/%d checks passed" % (len(CHECKS) - len(FAILED), len(CHECKS)))
if FAILED:
    print("FAILED: " + ", ".join(FAILED))
    sys.exit(1)
