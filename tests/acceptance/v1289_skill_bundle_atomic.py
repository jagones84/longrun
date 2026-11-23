#!/usr/bin/env python3
"""v1289 — a skill bundle is installed whole or not at all (RSI round 1).

Measured on the parent tree: `improve.decide(approve)` validated and installed a
skill bundle ONE ARTIFACT AT A TIME, inside the same `for` loop. A second
artifact that failed therefore left the first one installed, the proposal still
`pending`, and a retry that would meet its own leftovers — a self-improvement
that is half live and half refused. The Matrix branch of the SAME function
already promises the opposite ("a load error caused by the bundle restores every
touched file, so a partial or broken artifact never becomes live"), so this is
an asymmetry inside one seam, not a new policy.

Contract:
  A a bundle whose SECOND write fails installs NOTHING (the first is rolled back)
  B that refusal leaves the proposal pending and writes no `decide approve` row
  C a bundle that would overwrite an EXISTING skill is refused before any write
  D two artifacts aimed at the SAME target are refused before any write
  E the happy path still installs every artifact, approves, and records the audit

Deterministic: no model, no network, isolated temp dirs; the failing installer is
injected.
Run: python3 tests/acceptance/v1289_skill_bundle_atomic.py
"""
import hashlib
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1289-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "PROPOSALS_DIR",
           "IMPROVEMENT_DIR", "SKILLS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import skills                    # noqa: E402
from longrun.util import improve                      # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def art(name, content, category="created"):
    return {"kind": "skill_file", "name": name,
            "target": "skills/%s/%s/SKILL.md" % (category, name),
            "content": content,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}


def on_disk(name, category="created"):
    return os.path.isdir(os.path.join(skills.SKILLS_DIR, category, name))


def ledger_rows():
    rows = []
    try:
        with open(os.path.join(os.environ["LONGRUN_IMPROVEMENT_DIR"],
                               "ledger.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError):
        return []
    return rows


orig_install = skills.install_skill_file


# ---- A + B: the second write fails -> nothing installed, still pending -------
rec = improve.propose("skill", "install two procedures",
                      artifacts=[art("alpha", "# Alpha\n"), art("beta", "# Beta\n")])


def flaky(category, name, content, root=None):
    if name == "beta":
        return {"ok": False, "error": "write failed: disk full"}
    return orig_install(category, name, content, root=root)


skills.install_skill_file = flaky
try:
    res = improve.decide(rec["id"], "approve")
finally:
    skills.install_skill_file = orig_install

check("A1 the approval answers with a refusal", res.get("ok") is False, res)
check("A2 the artifact written BEFORE the failure is not left behind",
      not on_disk("alpha"), sorted(os.listdir(skills.SKILLS_DIR))
      if os.path.isdir(skills.SKILLS_DIR) else [])
check("A3 the failed target is absent too", not on_disk("beta"))
check("B1 the proposal is still pending",
      (improve.get_proposal(rec["id"]) or {}).get("status") == "pending",
      improve.get_proposal(rec["id"]))
check("B2 no `decide approve` is recorded for it",
      not [r for r in ledger_rows()
           if r.get("kind") == "decide" and r.get("proposal") == rec["id"]
           and r.get("decision") == "approve"], ledger_rows()[-3:])

# ---- C: an existing skill is refused BEFORE the earlier artifact is written --
made = orig_install("created", "taken", "# Already here\n")
check("C0 fixture: the existing skill is on disk", bool(made.get("ok")), made)
rec_c = improve.propose("skill", "bundle with a collision",
                        artifacts=[art("fresh", "# Fresh\n"), art("taken", "# New body\n")])
res_c = improve.decide(rec_c["id"], "approve")
check("C1 the approval is refused", res_c.get("ok") is False, res_c)
check("C2 the earlier artifact was not installed", not on_disk("fresh"),
      os.listdir(os.path.join(skills.SKILLS_DIR, "created")))
body = open(os.path.join(skills.SKILLS_DIR, "created", "taken", "SKILL.md"),
            encoding="utf-8").read()
check("C3 the existing skill is untouched", body == "# Already here\n", body)
check("C4 the proposal is still pending",
      (improve.get_proposal(rec_c["id"]) or {}).get("status") == "pending")

# ---- D: two artifacts on ONE target are refused before any write ------------
rec_d = improve.propose("skill", "bundle with a duplicate target",
                        artifacts=[art("dup", "# First\n"), art("dup", "# Second\n")])
res_d = improve.decide(rec_d["id"], "approve")
check("D1 the approval is refused", res_d.get("ok") is False, res_d)
check("D2 nothing was written for the duplicated target", not on_disk("dup"),
      os.listdir(os.path.join(skills.SKILLS_DIR, "created")))
check("D3 the refusal names the duplicated target",
      "dup" in str(res_d.get("error") or ""), res_d.get("error"))
check("D4 the proposal is still pending",
      (improve.get_proposal(rec_d["id"]) or {}).get("status") == "pending")

# ---- E: the happy path is unchanged ------------------------------------------
rec_e = improve.propose("skill", "install three procedures",
                        artifacts=[art("e1", "# E1\n"), art("e2", "# E2\n"),
                                   art("e3", "# E3\n")])
res_e = improve.decide(rec_e["id"], "approve")
check("E1 the approval succeeds", res_e.get("ok") is True, res_e)
check("E2 every artifact is installed",
      all(on_disk(n) for n in ("e1", "e2", "e3")), sorted(os.listdir(
          os.path.join(skills.SKILLS_DIR, "created"))))
check("E3 the bytes on disk are the approved bytes",
      all(open(os.path.join(skills.SKILLS_DIR, "created", n, "SKILL.md"),
               encoding="utf-8").read() == "# %s\n" % n.upper()
          for n in ("e1", "e2", "e3")))
check("E4 the proposal reads approved",
      (improve.get_proposal(rec_e["id"]) or {}).get("status") == "approved",
      improve.get_proposal(rec_e["id"]))
check("E5 the audit carries one approve row naming the install",
      [r for r in ledger_rows()
       if r.get("kind") == "decide" and r.get("proposal") == rec_e["id"]
       and r.get("decision") == "approve" and r.get("path")],
      ledger_rows()[-3:])

print("---")
print("v1289: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
