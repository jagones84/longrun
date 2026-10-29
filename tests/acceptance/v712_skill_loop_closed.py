#!/usr/bin/env python3
"""v712 — the self-evolve loop is closed: a mined draft can become an approvable
skill proposal, and installing a skill always asks.

Two seams found while driving the WebUI:

  A  the Improve panel told the operator "approve verifies the draft in the sandbox
     and installs it", and `improve.mine` told the model "call improve.propose
     (scope=skill)" — but `propose` never set `target_path`, so EVERY skill
     proposal was refused at approval with "the drafted skill folder is missing".
  B  `improve.evolve` asked before archiving a skill (M11) while `improve.promote`
     — the same final act, one call shorter — did not.

Deterministic: fixture drafts + the real tool entry points, no model, no network.
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v712-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import improve  # noqa: E402
from longrun.tools import tools as T  # noqa: E402
from longrun.tools import registry  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


DRAFTS = os.path.join(TMP, "data", "proposals", "skills")
improve.DRAFT_DIR = DRAFTS
os.makedirs(DRAFTS, exist_ok=True)
draft = os.path.join(DRAFTS, "fs.read-fs.edit-shell")
os.makedirs(draft, exist_ok=True)
with open(os.path.join(draft, "proposal.json"), "w", encoding="utf-8") as f:
    json.dump({"kind": "skill", "status": "proposed", "name": "fs.read-fs.edit-shell",
               "pattern": ["fs.read", "fs.edit", "shell"]}, f)

# ------------------------------------- A: a skill proposal binds ONE draft ----
r = T._improve({"action": "propose", "scope": "skill", "path": draft,
                "content": "read a file, edit it, then run the command"}, run_id="v712")
rec = (r.get("proposal") or {})
check("A1 the proposal is created", bool(rec.get("id")), r)
check("A2 it carries the draft folder the approval would install",
      rec.get("target_path") == draft, rec.get("target_path"))

r = T._improve({"action": "propose", "scope": "skill", "path": "/etc",
                "content": "escape attempt"}, run_id="v712")
check("A3 a draft outside the drafts store is refused",
      bool(r.get("error")) and "must be under" in str(r.get("error")), r)

r = T._improve({"action": "propose", "scope": "project", "path": draft,
                "content": "a rule that happens to pass a path"}, run_id="v712")
rec = (r.get("proposal") or {})
check("A4 a project proposal never binds a draft",
      rec.get("scope") == "project" and not rec.get("target_path"), rec)

check("A5 the tool schema lets the model pass the draft",
      "path" in registry._SUBTOOL_FIELDS["improve"]["propose"]
      and "path" not in registry._SUBTOOL_REQUIRED["improve.propose"], "")

# ------------------------------------- B: installing a skill always asks -----
gate = registry.subtool_gate("improve", {"action": "promote", "scope": "skill", "path": draft})
check("B1 promote is approval-gated like evolve",
      bool(gate) and gate[0] == "required" and "skill" in gate[1], gate)
gate_e = registry.subtool_gate("improve", {"action": "evolve", "scope": "skill"})
check("B2 evolve keeps its gate", bool(gate_e) and gate_e[0] == "required", gate_e)
check("B3 a read-only action stays ungated",
      registry.subtool_gate("improve", {"action": "review", "scope": "review"}) is None, "")

# ------------------------------------- C: approval installs that draft -------
from longrun.util import selfevolve as SE  # noqa: E402

_old_verify, _old_promote = SE.verify, SE.promote
SE.verify = lambda d, runner=None, c=None: {"green": True, "output": "ok"}
SE.promote = lambda d, skills_dir=None, c=None, human=False, purpose="": {
    "ok": True, "name": "fs.read-fs.edit-shell",
    "rel": "skills/created/fs.read-fs.edit-shell", "human": human,
    "purpose": purpose}
try:
    pid = (T._improve({"action": "propose", "scope": "skill", "path": draft,
                       "content": "install me"}, run_id="v712").get("proposal") or {}).get("id")
    got = improve.decide(pid, "approve")
finally:
    SE.verify, SE.promote = _old_verify, _old_promote
check("C1 approving a bound skill proposal is a REAL install",
      got.get("ok") is True
      and (got.get("installed_to") or "").endswith("fs.read-fs.edit-shell"), got)

print("\n---\nv712: %d/%d PASS" % (sum(results), len(results)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if all(results) else 1)
