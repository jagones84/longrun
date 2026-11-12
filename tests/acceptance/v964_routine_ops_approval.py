#!/usr/bin/env python3
"""RSI-W — a routine operation may not disable the approval gate.

The paper (arXiv:2611.09088) shows a prohibited edit executing in five released
harnesses after ordinary operations — re-applying a plugin, saving an allow rule,
compacting — with every plugin still active. The relation lives in the RUNNING
system and its history, so this pin drives the operations longrun actually
performs and asserts the decision after each one:

  A) saving the policy unchanged keeps a covered action `required`;
  B) a deliberate flip is LIVE immediately (no restart, no stale cache);
  C) the flip survives a reload (the overlay round-trips — the save is durable);
  D) restoring gives `required` back;
  E) a settings save in ANOTHER domain changes nothing;
  F) compaction changes nothing;
  G) a second covered tool is never collateral damage.

Deterministic: temp data/config dirs, no model, no network, no server.
"""
import copy
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v964-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server      # noqa: E402,F401  (import order)
from longrun.core import api_v02     # noqa: E402,F401
from longrun.core import settings    # noqa: E402
from longrun.model import context_engine  # noqa: E402
from longrun.tools import registry    # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def decision(tool):
    return registry.classify(tool, {})[0]


cfg = registry.load_config(reload=True)
tools = cfg.get("tools") or {}
covered = []
for name in sorted(tools):
    spec = registry.tool_spec(name)
    if not spec or spec.get("approval") != "required":
        continue
    origin = (spec.get("schema") or {}).get("_origin")
    if origin in ("exclusive", "delegation"):
        continue
    covered.append(name)

check("A0 the shipped policy has at least two covered actions",
      len(covered) >= 2, covered[:6])
TOOL = covered[0]
OTHER = covered[1]
check("A1 the chosen action starts `required`", decision(TOOL) == "required", decision(TOOL))
check("A2 the control action starts `required`", decision(OTHER) == "required", decision(OTHER))

# ---- A: the panel saves the policy unchanged -----------------------------
registry.save_config(copy.deepcopy(cfg))
check("A3 saving the policy unchanged keeps the gate",
      decision(TOOL) == "required", decision(TOOL))

# ---- B: a deliberate flip is live at once -------------------------------
flipped = copy.deepcopy(cfg)
flipped["tools"][TOOL]["approval"] = "auto"
registry.save_config(flipped)
check("B1 the saved policy takes effect without a restart",
      decision(TOOL) == "auto", decision(TOOL))

# ---- C: it survives a reload (the overlay is durable, not in-memory) ----
registry.load_config(reload=True)
check("C1 the flip survives a reload",
      decision(TOOL) == "auto", decision(TOOL))

# ---- D: restoring brings the gate back ----------------------------------
registry.save_config(copy.deepcopy(cfg))
check("D1 restoring the policy restores `required`",
      decision(TOOL) == "required", decision(TOOL))
registry.load_config(reload=True)
check("D2 the restore survives a reload",
      decision(TOOL) == "required", decision(TOOL))

# ---- E: a settings save in another domain is not collateral -------------
try:
    settings._save("compaction.yaml", {"trigger_pct": 72, "target_pct": 55})
    saved_other = True
except Exception as exc:  # noqa: BLE001 — report what happened, do not hide it
    saved_other = False
    print("note: settings save raised %r" % (exc,))
check("E1 another domain's settings save leaves the gate alone",
      saved_other and decision(TOOL) == "required",
      (saved_other, decision(TOOL)))

# ---- F: compaction is not a policy event --------------------------------
msgs = []
for i in range(20):
    msgs.append({"role": "user", "content": "step %d %s" % (i, "x" * 40)})
    msgs.append({"role": "assistant", "content": "ack %d %s" % (i, "y" * 40)})
_packed, stats = context_engine.compact(msgs, 60, keep_recent=2, force=True)
check("F1 compaction actually ran", (stats.get("compacted") or 0) > 0, stats)
check("F2 the gate survives a compaction", decision(TOOL) == "required", decision(TOOL))

# ---- G: the control action was never collateral -------------------------
check("G1 the second covered action never moved", decision(OTHER) == "required",
      decision(OTHER))

# ---- H: an unknown tool is still denied, never `auto` -------------------
check("H1 an unknown tool stays denied", decision("no.such.tool") == "denied",
      decision("no.such.tool"))

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
