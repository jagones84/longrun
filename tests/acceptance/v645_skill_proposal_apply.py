#!/usr/bin/env python3
"""v645 — a skill proposal you can actually decide.

Operator, verbatim: "guarda immagine cosa è la lista di approve senza scrivere COSA
devo fare approve? e perché non appaiono dentro approvals nel RH panel? e inoltre
non posso approvare" and "ALCUNI sono autogenerati da matrix quindi devi rafforzare
le regole per crearli bene".

Gap analysis found THREE separate defects behind that one screen:
  1. the chat card carried no content and no id — mining published
     `{scope:"skill", path:...}`, so the card had nothing to show and its buttons
     sent the SSE sequence number to POST /api/improve;
  2. nothing was stored as a proposal, so the Inspector ▸ Approvals inbox could
     never list them (it reads data/proposals/*.json);
  3. approving a skill refused by design ("skill apply not implemented"), a dead
     button rendered as an enabled one.

Contract:
  A) approving a skill VERIFIES the draft in the sandbox and installs it through
     selfevolve.promote under skills/<category>/ (one write-gate, no second path);
  B) a draft that fails its check stays pending and answers with the real error;
  C) a proposal whose draft folder is gone is not approvable (blocked, deniable);
  D) the approval inbox exposes skill proposals as pending + installable;
  E) mining no longer publishes a proposal per bare tool sequence.

Deterministic: temp data dir + temp skills root, no model, no network.
Run: python3 tests/acceptance/v645_skill_proposal_apply.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v645_")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPHS_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(TMP, "threads")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_SKILLS_DIR"] = os.path.join(TMP, "skills")
os.environ["LONGRUN_HELDOUT_DIR"] = os.path.join(TMP, "heldout")
for d in ("cfg", "sessions", "graphs", "threads", "data", "skills", "heldout"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import approvals  # noqa: E402
from longrun.util import improve  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


DRAFTS = os.path.join(TMP, "drafts")


def make_draft(name, exit_code):
    d = os.path.join(DRAFTS, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump({"kind": "skill", "status": "proposed", "name": name,
                   "pattern": ["fs.read", "fs.edit"], "origin": "auto"}, f)
    with open(os.path.join(d, "skill.json"), "w", encoding="utf-8") as f:
        json.dump({"name": name, "steps": [{"tool": "fs.read"}, {"tool": "fs.edit"}]}, f)
    with open(os.path.join(d, "check.py"), "w", encoding="utf-8") as f:
        f.write("import sys\nprint('green' if %d == 0 else 'red')\nsys.exit(%d)\n"
                % (exit_code, exit_code))
    return d


# ---- A. a green draft is verified and installed ------------------------------
good = make_draft("read-then-edit", 0)
rec = improve.propose("skill", "Read a file, then apply the reviewed edit in one pass.",
                     reason="repeated read+edit pair", target_path=good, origin="mining")
check("A1 the proposal stores what it does", rec.get("content", "").startswith("Read a file"))
check("A2 the proposal stores the draft folder", rec.get("target_path") == good)
res = improve.decide(rec["id"], "approve")
check("A3 approve succeeds", res.get("ok") is True, res.get("error", ""))
installed = os.path.join(os.environ["LONGRUN_SKILLS_DIR"], "created", "read-then-edit")
check("A4 the skill is installed under skills/created/<name>", os.path.isdir(installed))
check("A5 the answer names where it landed", bool(res.get("installed_to")), res.get("installed_to"))
check("A6 the proposal is approved, not pending",
      (improve.get_proposal(rec["id"]) or {}).get("status") == "approved")
# A7/A8: the operator IS the release authority, the machine is not — the sealed
# held-out suite (absent here, exactly like the live install) must not block a
# human decision, and must still block the automatic path.
_machine_draft = make_draft("machine-only", 0)
selfevolve.verify(_machine_draft)
_machine = selfevolve.promote(_machine_draft)
check("A7 a human approval does not need the sealed judge suite", res.get("ok") is True)
check("A8 the machine path still refuses without it",
      _machine.get("ok") is False and "no_manifest" in str(_machine.get("error", "")),
      _machine.get("error", "")[:90])
with open(os.path.join(installed, "proposal.json"), encoding="utf-8") as f:
    check("A9 the release is stamped with its provenance",
          (json.load(f) or {}).get("released_by") == "operator")

# ---- B. a red draft stays pending and says why -------------------------------
bad = make_draft("broken-draft", 1)
rec_bad = improve.propose("skill", "Does something the sandbox check rejects.",
                          target_path=bad, origin="mining")
res_bad = improve.decide(rec_bad["id"], "approve")
check("B1 a red check is refused", res_bad.get("ok") is False)
check("B2 the refusal names the verification", "not verified" in str(res_bad.get("error", "")),
      res_bad.get("error", "")[:80])
check("B3 the proposal is still pending",
      (improve.get_proposal(rec_bad["id"]) or {}).get("status") == "pending")
check("B4 nothing was installed for it",
      not os.path.isdir(os.path.join(os.environ["LONGRUN_SKILLS_DIR"], "created", "broken-draft")))

# ---- C. a vanished draft is not approvable ----------------------------------
rec_gone = improve.propose("skill", "Draft that was deleted from disk.",
                           target_path=os.path.join(DRAFTS, "no-such-draft"), origin="agent")
view_gone = approvals._improvement_view(rec_gone)
check("C1 can_approve is false when the draft folder is gone", view_gone["can_approve"] is False)
check("C2 the reason is explained", "gone" in view_gone["blocked_reason"])

# ---- D. the inbox exposes a pending skill proposal ---------------------------
view_ok = approvals._improvement_view(improve.propose(
    "skill", "Second describable skill.", target_path=bad, origin="agent"))
check("D1 the inbox lists the skill proposal as pending", view_ok["status"] == "pending")
check("D2 it is approvable now (the old build blocked every skill)",
      view_ok["can_approve"] is True, view_ok["blocked_reason"])
check("D3 the inbox row carries the draft folder", view_ok["draft"] == bad)
check("D4 the summary is the description, not a path",
      view_ok["summary"].startswith("Second describable skill"))

# ---- E. mining does not mint proposals from bare tool sequences --------------
src_tools = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"),
                 encoding="utf-8").read()
# v662 re-pin: the tool no longer re-implements the miner — it calls
# `improve.mine_once` (the same flow the end-of-turn pass runs), per the operator's
# single-source-of-truth request. Same guarantee checked below: the mining branch
# mints DRAFTS, never proposals.
mine_block = src_tools[src_tools.index("paths = improve.mine_once("):]
mine_block = mine_block[:mine_block.index("if scope not in")]
check("E1 mining publishes no improve.proposal event", '_pub("improve.proposal"' not in mine_block)
check("E2 mining reports drafts, not proposals", '"drafts": recs' in mine_block)
check("E3 the answer tells how to propose one", "scope=skill with a description" in mine_block)

# ---- F. the UI no longer promises an unimplemented action --------------------
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("F1 no 'Skill apply is not implemented' sentence is left",
      "Skill apply is not implemented" not in UI)
check("F2 the chat card refuses to show dead buttons for an id-less event",
      'if (typeof pid !== "string" || !pid)' in UI)
check("F3 the card shows the description, not only a scope name",
      # v648 re-pin: the body is no longer one inline `d.content || path` ternary —
      # it resolves `what` (the description) and `draft` separately and appends the
      # draft path on its own line. Same guarantee: the card states the object.
      'const what = String(d.content || "").trim()' in UI
      and "body.textContent = what" in UI)

print("---")
ok = sum(results)
print("\nv645: %d/%d PASS" % (ok, len(results)))
raise SystemExit(0 if ok == len(results) else 1)
