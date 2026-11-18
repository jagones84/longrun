#!/usr/bin/env python3
"""v1129 — a hard-deny refusal explains itself, and the rule carries the why.

Round 63. Measured 2026-11-18 over the live store: 13 `shell.exec · permission`
cards were answered with nothing but the regex —

  matches hard-deny pattern 'LONGRUN_TOKEN'
  matches hard-deny pattern 'grep[^\\n]*\\.env'
  matches hard-deny pattern '(?:curl|wget)[^\\n]*127\\.0\\.0\\.1[^\\n]*/api/(jobs|…)'

— so the model learned WHICH rule fired and never what is protected or what to use
instead; 4 of the 14 never recovered. The explanation now lives BESIDE the rule
that enforces it (`- pattern: … / why: …` in `config/tools.yaml`), so there is no
second table to drift, and `classify` appends it after the unchanged prefix.

  A  a deny list mixes bare patterns and {pattern, why} without loss
  B  a noted shell rule answers with the why
  C  a noted fs.read rule answers with the why
  D  a noted fs.write rule answers with the why
  E  a rule WITHOUT a note answers byte-identically to the old message
  F  `deny` stays a plain string list and `deny_why` names only real patterns
  G  every shipped `why` is a sentence (no tuple-repr artifact)
  H  the refusal is still the `permission` family (the register keeps classifying it)

Deterministic: config + registry only; nothing executes.
Run: python3 tests/acceptance/v1129_deny_reason_teaches.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1129-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as R  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# --- A: the parser keeps both shapes -----------------------------------------
pats, notes, proofs = R._deny_parts(["alpha", {"pattern": "beta", "why": "because b"},
                                     {"pattern": "gamma"}, {"why": "no pattern"}])
check("A1 bare and mapped patterns both survive",
      pats == ["alpha", "beta", "gamma"], pats)
check("A2 only a pattern WITH a why gets a note",
      notes == {"beta": "because b"}, notes)
check("A3 round 68: no proof is invented from a why", proofs == {}, proofs)

# --- B/C/D: the shipped rules explain themselves ------------------------------
d, why = R.classify("shell.exec", {"command": "cat .env"})
check("B1 the env read is still denied", d == "denied", d)
check("B2 the reason keeps the pinned prefix",
      why.startswith("matches hard-deny pattern '") and "denied because" in why, why)
check("B3 and says what the rule protects",
      "env file" in why and "provider key" in why, why)
check("B4 and what to use instead", "self.info" in why or "providers" in why, why)

d2, why2 = R.classify("fs.read", {"path": os.path.join(REPO, ".env")})
check("C1 fs.read of the env file is denied", d2 == "denied", d2)
check("C2 with the why", "denied because" in why2 and "env file" in why2, why2)
check("C3 the template stays readable",
      R.classify("fs.read", {"path": os.path.join(REPO, ".env.template")})[0] != "denied",
      R.classify("fs.read", {"path": os.path.join(REPO, ".env.template")}))

d3, why3 = R.classify("fs.write", {"path": "/home/jagones/.longrun/data/events.db"})
check("D1 writing the event log is denied", d3 == "denied", d3)
check("D2 with the why", "denied because" in why3 and "audit" in why3, why3)

# --- E: a rule without a note answers exactly as before -----------------------
d4, why4 = R.classify("shell.exec", {"command": "rm -rf /"})
check("E1 the root delete is still denied", d4 == "denied", d4)
check("E2 and carries no invented explanation",
      why4.startswith("matches hard-deny pattern '") and "denied because" not in why4,
      why4)

# --- F/G: the shipped config is well formed ----------------------------------
bad_types, orphan = [], []
for tool in ("shell.exec", "fs.read", "fs.write", "fs.edit"):
    spec = R.tool_spec(tool)
    for p in spec["deny"]:
        if not isinstance(p, str):
            bad_types.append((tool, type(p).__name__))
    for p in (spec.get("deny_why") or {}):
        if p not in spec["deny"]:
            orphan.append((tool, p))
check("F1 `deny` is a plain string list everywhere", not bad_types, bad_types[:4])
check("F2 `deny_why` names only patterns that exist", not orphan, orphan[:4])

notes_all = {}
for tool in ("shell.exec", "fs.read", "fs.write", "fs.edit"):
    notes_all.update(R.tool_spec(tool).get("deny_why") or {})
check("G1 the shipped rules carry their why", len(notes_all) >= 6, len(notes_all))
weird = [w for w in notes_all.values()
         if w.startswith("(") or w.startswith('"') or " \" \"" in w]
check("G2 every why is a plain sentence (no YAML tuple artifact)", not weird, weird[:2])

# --- H: the register still files it as a permission answer -------------------
fam = selfevolve.failure_family("shell.exec", selfevolve.error_class(why), why)
check("H1 the refusal is the permission family", fam == "permission", fam)

print("\n---\nv1129: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
