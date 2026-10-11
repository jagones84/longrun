#!/usr/bin/env python3
"""v420 — local decision-model hooks (JAG-426 · Domain 6).

A pluggable decision layer in front of the loop. `mode: null` (the default) must
be a strict no-op, every hook must FAIL OPEN, and `heuristic` must reject a
hard-denied action BEFORE the approval round-trip using only local, model-free
primitives.

Deterministic, no live server, no model call. Run: python3 tests/v420_decision_hooks.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v420-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import decision                # noqa: E402
from longrun.tools import tools as T              # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _set_mode(mode, enabled=True):
    p = os.path.join(TMP, "decisions-%s.yaml" % mode)
    with open(p, "w", encoding="utf-8") as f:
        f.write("enabled: %s\nmode: %s\nspeculative:\n  enabled: false\n  k: 2\n"
                "  readonly_only: true\n" % ("true" if enabled else "false", mode))
    decision.CONFIG_PATH = p


# ---- 1. default = null = a strict no-op -------------------------------------
os.environ.pop("LONGRUN_DECISIONS", None)
_set_mode("null")
decision.CONFIG_PATH = os.path.join(TMP, "missing.yaml")   # absent file -> defaults
check("1a with no config the layer is null (disabled)",
      decision.get().name == "null" and decision.load_config().get("enabled") is False)
check("1b null mode never blocks anything",
      decision.pre_tool("shell", {"command": "shutdown now"}).get("ok") is True)
check("1c speculative is OFF by default",
      decision.speculative({"speculative": {}}).get("enabled") in (False, None))

# ---- 2. heuristic: validate BEFORE the approval round-trip ------------------
_set_mode("heuristic")
d = decision.get()
check("2a heuristic mode is selected", d.name == "heuristic")
v = decision.pre_tool("shell", {"command": "shutdown now"})
check("2b a hard-denied command is rejected with a reason",
      v.get("ok") is False and "deny" in (v.get("reason") or ""), v)
check("2c a safe command is allowed",
      decision.pre_tool("shell", {"command": "ls -la /tmp"}).get("ok") is True)
check("2d a denied rm -rf / is rejected",
      decision.pre_tool("shell", {"command": "rm -rf /"}).get("ok") is False)

# ---- 3. fail-open: garbage never blocks -------------------------------------
check("3a pre_tool(None, None) fails open",
      decision.pre_tool(None, None).get("ok") is True)
check("3b an unknown tool fails open",
      decision.pre_tool("no-such-tool", {"x": 1}).get("ok") is True)

# ---- 4. prune ranks with the deterministic PRM ------------------------------
cands = ["I will do it", '{"action": "finish", "summary": "done"}']
out = d.prune(decision.StepCtx(), cands)
check("4 prune puts the real action before the announcement-only reply",
      out and out[0].startswith("{"), out)

# ---- 5. route returns a hint (no model call) --------------------------------
h = d.route(decision.StepCtx(role="agent", goal="x"))
check("5a route returns a RoutingHint", isinstance(h, decision.RoutingHint))
check("5b a null-mode route hint is empty",
      decision.NullDecision().route(decision.StepCtx()).model == "")

# ---- 6. the guard is wired INTO tool execution ------------------------------
res = T.execute("shell", {"command": "shutdown now"}, run_id="v420")
check("6a execute() blocks it at the decision layer (not the approval gate)",
      res.get("ok") is False and res.get("decision_blocked") is True, res.get("error"))
_set_mode("null")
res2 = T.execute("shell", {"command": "echo ok"}, run_id="v420")
check("6b back in null mode the same call is untouched by the layer",
      res2.get("decision_blocked") is not True)

print("---")
okc = sum(results)
print("\nv420: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
