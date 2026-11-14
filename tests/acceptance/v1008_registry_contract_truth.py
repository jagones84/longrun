#!/usr/bin/env python3
"""v1008 — registry contract truth + guidance + risk gates (R1/R2/R3/R4).

The residual-worth audit (2026-11-15) measured eight contract lies (C1–C8), 43
actions with no guidance and seven destructive verbs under `approval: auto`.
This test pins the fixed state, so the next omission fails here instead of
shipping a schema the handler cannot run.

Deterministic: temp stores, no server, no model, no network.
Run: python3 tests/acceptance/v1008_registry_contract_truth.py
"""
import collections
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1008-")
for key, path in (
        ("LONGRUN_DATA_DIR", os.path.join(TMP, "data")),
        ("LONGRUN_CONFIG_DIR", os.path.join(TMP, "config")),
        ("LONGRUN_SESSIONS_DIR", os.path.join(TMP, "sessions")),
        ("LONGRUN_DB", os.path.join(TMP, "events.db")),
        ("LONGRUN_POLICY_HITS", os.path.join(TMP, "policy_hits.json"))):
    os.environ[key] = path
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


CANON = registry._CANONICAL_SCHEMAS
GUIDE = registry._SUBTOOL_GUIDANCE

# ---- A) C1/C2: required names the handler cannot run without ----------------
check("A1 every required name is a declared property",
      all(set(s.get("required") or []) <= set(s.get("properties") or {})
          for s in CANON.values()))
check("A2 matrix.scaffold requires name",
      CANON["matrix.scaffold"]["required"] == ["name"], CANON["matrix.scaffold"]["required"])
check("A3 memory.supersede and memory.restore require target",
      CANON["memory.supersede"]["required"] == ["target"]
      and CANON["memory.restore"]["required"] == ["target"])

# ---- B) C3/C4/C5: field maps are explicit and truthful ----------------------
check("B1 improve.scan declares only what the handler reads",
      CANON["improve.scan"]["required"] == []
      and set(CANON["improve.scan"]["properties"]) == {"limit", "model", "agent"},
      CANON["improve.scan"])
check("B2 self.trace declares only session",
      set(CANON["self.trace"]["properties"]) == {"session"},
      list(CANON["self.trace"]["properties"]))
check("B3 skills.audit is argument-free; skills.retire takes days/confirm",
      CANON["skills.audit"]["properties"] == {}
      and set(CANON["skills.retire"]["properties"]) == {"days", "confirm"})
check("B4 memory.hygiene takes kind/confirm",
      set(CANON["memory.hygiene"]["properties"]) == {"kind", "confirm"})
check("B5 knowledge.search no longer advertises an undeclared `kind`",
      "kind" not in CANON["knowledge.search"]["properties"])
_missing_maps = []
for ns, schema in registry._LEGACY_SCHEMAS.items():
    if "." in ns or ns in registry._SINGLE_SUBTOOL_MAP:
        continue
    actions = list(((schema.get("properties") or {}).get("action") or {}).get("enum") or [])
    if len(actions) < 2:
        continue
    for action in actions:
        if action not in registry._SUBTOOL_FIELDS.get(ns, {}):
            _missing_maps.append("%s.%s" % (ns, action))
check("B6 every multi-action canonical tool has an explicit field map",
      _missing_maps == [], _missing_maps)

# ---- C) C6/C7/C8: prose matches the shipped policy --------------------------
check("C1 browser.fetch no longer says 'Disabled by default'",
      "disabled by default" not in CANON["browser.fetch"]["description"].lower()
      and "ssrf" in CANON["browser.fetch"]["description"].lower())
check("C2 improve prose names scan",
      "scan" in (registry._LEGACY_SCHEMAS["improve"].get("description") or "").lower())
check("C3 memory.list is an alias, not a 14th canonical action",
      "memory.list" not in CANON
      and registry.canonical_name("memory.list", {}) == "memory.recent"
      and registry.canonical_name("memory", {"action": "list"}) == "memory.recent")

# ---- D) R2: one actionable line per multi-action tool ----------------------
_acts = collections.defaultdict(list)
for ns, schema in registry._LEGACY_SCHEMAS.items():
    if "." in ns:
        continue
    _acts[ns] = list(((schema.get("properties") or {}).get("action") or {}).get("enum") or [])
_missing_guide = []
for ns, actions in _acts.items():
    if len(actions) < 2 or ns in registry._SINGLE_SUBTOOL_MAP:
        continue
    for action in actions:
        name = "%s.%s" % (ns, action)
        if name in CANON and name not in GUIDE:
            _missing_guide.append(name)
check("D1 every multi-action canonical tool has guidance",
      _missing_guide == [], _missing_guide)
check("D2 no canonical description still carries the 160-char fallback",
      not any("performs only action=" in (s.get("description") or "")
              for s in CANON.values()))
check("D3 no guidance carries an internal ticket id",
      not [k for k, v in GUIDE.items() if "JAG-" in v])
check("D4 guidance stays inside the descriptive ceiling (700 chars)",
      not [(k, len(v)) for k, v in GUIDE.items() if len(v) > 700])

# ---- E) R3: the dangerous form asks, the plain form does not ---------------
_GATED_ALWAYS = ("matrix.scaffold", "matrix.load_module", "sessions.reset",
                 "improve.evolve", "improve.promote", "improve.forge")
_check_always = all((registry.subtool_gate(t, {}) or ("",))[0] == "required"
                    for t in _GATED_ALWAYS)
check("E1 the always-destructive verbs ask", _check_always,
      {t: registry.subtool_gate(t, {}) for t in _GATED_ALWAYS})
_CASES = [
    ("matrix.test", {"code": "print(1)"}, True),
    ("matrix.test", {"target": "tool:x"}, False),
    ("sessions.compact", {"force": True}, True),
    ("sessions.compact", {"session": "S"}, False),
    ("skills.retire", {"confirm": True}, True),
    ("skills.retire", {"days": 30}, False),
    ("memory.hygiene", {"confirm": True}, True),
    ("memory.hygiene", {}, False),
]
_bad = [(tool, args, want, registry.subtool_gate(tool, args))
        for tool, args, want in _CASES
        if bool(registry.subtool_gate(tool, args)) != want]
check("E2 conditional gates fire only on the dangerous form", _bad == [], _bad)

# ---- F) R4: the staged count surface records, and refuses nothing ----------
registry.note_rule_hit("fs.read", "unknown_arg", "startline")
_report = registry.policy_report()
check("F1 an unknown argument is counted in the policy report",
      any(k.endswith(":unknown_arg:startline") for k in _report.get("unknown_args") or {}),
      _report.get("unknown_args"))
check("F2 the count does not masquerade as a configured rule firing",
      not any(":unknown_arg:" in k for k in _report.get("firings") or {}))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
