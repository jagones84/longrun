#!/usr/bin/env python3
"""v822 — a sub-tool must not freeze the guardrails it INHERITS.

Found while re-checking the policy layer after the deny-union revert. The live
overlay carried:

    tools:
      shell.exec:
        enabled: true
        deny: [8 patterns]        # the namespace `shell` ships 9

`config/tools.yaml` keys the NAMESPACE (`shell`, `git`); `shell.exec` / `git.run`
inherit its policy through `tool_spec`. `_diff_overlay` compared a sub-tool
against `eff_tools.get(name)` — which for `shell.exec` is None, so `e = {}` — and
therefore wrote the WHOLE effective entry (inherited deny included) into the
overlay. Once frozen there, a LATER change to the shipped `shell.deny` (the
2026-11-04 `grep[^\\n]*\\.env` rule) silently shadowed: `classify("shell.exec",
{grep .env})` was `auto` while `classify("shell", …)` was `denied`.

The base for a sub-tool is its NAMESPACE entry, exactly as `tool_spec`/
`shipped_tool` resolve it, so only a real DELTA is stored:

  A) an entry equal to its namespace inheritance leaves NO overlay entry, and the
     inherited guardrail still denies;
  B) a DELIBERATE narrowing IS stored (deletability — the invariant v808 pins),
     and the removed pattern stops denying;
  C) restoring the field (`reset`) brings the guardrail back and drops the key;
  D) the resolution matches `shipped_tool` (one rule, no second precedence).

Deterministic: temp data dir, no model, no network, no server.
Run: python3 tests/acceptance/v822_subtool_policy_inheritance.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v822-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server      # noqa: E402,F401  (import order)
from longrun.core import api_v02     # noqa: E402
from longrun.tools import registry   # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def overlay_tools():
    path = registry.OVERLAY_YAML
    if not os.path.exists(path):
        return {}
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        return {}
    return (doc.get("tools") or {}) if isinstance(doc, dict) else {}


NS = registry.shipped_tool("shell.exec") or {}
NINE = list(NS.get("deny") or [])
DENIED_CMD = {"command": "grep TOKEN .env"}      # matches the 9th shipped rule

check("A0 the namespace ships the .env guardrail",
      any("env" in p for p in NINE), NINE)

# ---- A: an inherited entry is not frozen into the overlay ----------------
_cfg = registry.load_config(reload=True)
# what the Permissions panel writes when it touches the sub-tool: the entry it
# read from the catalogue (== the namespace inheritance).
_cfg["tools"]["shell.exec"] = {"enabled": True, "deny": list(NINE)}
registry.save_config(_cfg)
registry.load_config(reload=True)

check("A1 an entry equal to its inheritance leaves no overlay entry",
      "shell.exec" not in overlay_tools(), overlay_tools().get("shell.exec"))
_d, _why = registry.classify("shell.exec", DENIED_CMD)
check("A2 the inherited guardrail still denies after the save",
      _d == "denied", (_d, _why))

# ---- B: a deliberate narrowing IS persisted ------------------------------
_cfg = registry.load_config(reload=True)
_cfg["tools"]["shell.exec"] = {"enabled": True, "deny": list(NINE[1:])}
registry.save_config(_cfg)
registry.load_config(reload=True)

check("B1 a deliberate deletion is stored in the overlay",
      (overlay_tools().get("shell.exec") or {}).get("deny") == list(NINE[1:]),
      overlay_tools().get("shell.exec"))
_d2, _why2 = registry.classify("shell.exec", {"command": "rm -rf / "})
check("B2 the deleted rule no longer denies (deletability, v808)",
      _d2 != "denied", (_d2, _why2))
_d3, _why3 = registry.classify("shell.exec", DENIED_CMD)
check("B3 the rules that were NOT deleted still deny",
      _d3 == "denied", (_d3, _why3))

# ---- C: restore brings the guardrail back --------------------------------
api_v02.update_policy({"tool": "shell.exec", "reset": ["deny"]})
registry.load_config(reload=True)
check("C1 the key is gone from the overlay after the restore",
      "deny" not in (overlay_tools().get("shell.exec") or {}), overlay_tools().get("shell.exec"))
_d4, _why4 = registry.classify("shell.exec", DENIED_CMD)
check("C2 the guardrail denies again", _d4 == "denied", (_d4, _why4))

# ---- D: one precedence, shared with shipped_tool -------------------------
check("D1 shipped_tool resolves the namespace for the sub-tool",
      registry.shipped_tool("shell.exec") == registry.shipped_tool("shell"))
check("D2 the same precedence answers for git.run, and an unknown name is None",
      registry.shipped_tool("git.run") == registry.shipped_tool("git")
      and registry.shipped_tool("nope.nope") is None)

print("\n---")
print("v822: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
