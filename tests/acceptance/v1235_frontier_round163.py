#!/usr/bin/env python3
"""v1235 — the newest online harness papers, wired (round 163).

Sources (all submitted 2026-11-18/19, read in full from the archive):
  S-2026-11-20-015  Wang et al., *Replication of Agentic Security Events: Audit and
                    Investigation (ROGUE-AI)*, arXiv:2611.26553 — a warning after
                    each tool output that names the HAZARD and its CONSEQUENCE
                    lowered harm for all five models; a fact-only note did not.
  S-2026-11-20-016  Jayaram et al., *How Much Should an Agent Remember? Deployment
                    Lessons from Self-Distilled Memory for LLM Agents*,
                    arXiv:2611.26361 — support-conserving consolidation, a dose
                    that is a property of the model, provenance as an invariant.
  S-2026-11-20-017  Xu et al., *SkillBridge: Cost-Aware Diagnosis and Repair of
                    Cross-OS Compatibility Defects in Agent Skills*, arXiv:2611.26256
                    — a contract screen (G/P/M/D/A), never a verdict.
  S-2026-11-20-018  Yang et al., *Forget Freely, Grep Later: Lossless, Index-Free
                    Memory for Long-Horizon LLM Agents*, arXiv:2611.25123 — an
                    append-only log plus a regex search tool, paginated/count-only.

What this pins:

  A  a hazard notice fires on a production + destructive call and is SILENT on a
     plain read; the line carries hazard AND consequence
  B  the replication audit classifies supported / suggestive / not-reproduced from
     counts, and marks a harmful control
  C  every message, tool card and harness inject lands in the lossless log
  D  `context.grep` returns chronologically located matches, paginates, and
     `context.count` returns no matched text
  E  `recall_log.verify` reports a body the log lost
  F  the OS contract screen finds a POSIX-only skill for Windows, honours a
     fallback, and `skills.install_skill_file` still installs and reports
  G  consolidation conserves support; the dose is smaller for a weak model
  H  the registry contract (schema, fields, guidance, effects) carries grep/count

Deterministic: temp stores, no model, no network, no server.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

TMP = tempfile.mkdtemp(prefix="sf-v1235-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR", "SUBAGENT_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")

# core/server.py imports the prompt constants out of agent.py, so import it first.
from longrun.core import server as _server  # noqa: E402,F401
from longrun.harness import hazard_notice  # noqa: E402
from longrun.harness.checks import guideline_budget  # noqa: E402
from longrun.harness import recall_log, skill_os_contract  # noqa: E402
from longrun.memory import skills, stores  # noqa: E402
from longrun.tools import registry, tools  # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


SID = "v1235sess"

# ── A · the hazard notice names hazard AND consequence ──────────────────────
PROD = ("make test\ncreating executives table\n"
        "DROP TABLE executives; -- 1,206 rows in the production database\n")
found = hazard_notice.classify("shell.exec", {"command": "make test"}, PROD)
check("A1 a production + destructive call fires",
      found["hazard"] and any(f["rule"] == "production-target" for f in found["findings"]),
      json.dumps(found["findings"])[:220])
line = hazard_notice.notice("shell.exec", {"command": "make test"}, PROD)
check("A2 the line carries the hazard and its consequence",
      line.startswith("HAZARD:") and "CONSEQUENCE:" in line, line[:200])
check("A3 a plain read is silent",
      hazard_notice.notice("fs.read", {"path": "README.md"}, "# Longrun\nhello") == "")
check("A4 credentials in reach fire",
      hazard_notice.classify("fs.read", {"path": ".env"}, "API_KEY=sk-live-123")["hazard"])
check("A5 a destructive verb on a protected target fires",
      hazard_notice.classify("shell.exec", {"command": "rm -rf ~/work"}, "")["hazard"])
check("A6 a build-directory clean is the task, not a hazard",
      hazard_notice.notice("shell.exec", {"command": "rm -rf build/tmp"}, "") == "")
check("A7 a force-push fires on its own",
      hazard_notice.classify("shell.exec",
                             {"command": "git push --force origin main"}, "")["hazard"])

# ── B · the replication audit (incident vs matched control) ─────────────────
sup = hazard_notice.audit({"incident": {"harm": 6, "runs": 30},
                           "control": {"harm": 0, "runs": 30}})
check("B1 a harmed incident against a clean control is supported",
      sup["verdict"] == "supported" and sup["p_value"] < 0.05, sup["verdict"])
check("B2 no incident harm is not reproduced",
      hazard_notice.audit({"incident": {"harm": 0, "runs": 15},
                           "control": {"harm": 0, "runs": 15}})["verdict"] == "not-reproduced")
check("B3 harm in incident and control is suggestive",
      hazard_notice.audit({"incident": {"harm": 1, "runs": 3},
                           "control": {"harm": 1, "runs": 3}})["verdict"] == "suggestive")
check("B4 a clean control raises no control-also-harmful finding",
      not any(f["kind"] == "control-also-harmful" for f in sup["findings"]))
check("B5 no-control is not a claim test",
      hazard_notice.audit({"incident": {"harm": 2, "runs": 3},
                           "control": {"harm": 0, "runs": 0}})["verdict"] == "suggestive")

# ── C · the lossless log receives every interaction ─────────────────────────
sess = {"id": SID, "messages": [], "tool_cards": [], "workspace": TMP}
stores.append_message(sess, "user", "remember the invoice ID INV-7781")
stores.persist_tool_card(sess, "fs.read", True, args={"path": "notes.md"},
                         result="line one\ninvoice INV-7781 ships Friday", after=1)
stores.persist_inject(sess, "observation", "[harness] continue", after=2)
stores.save_session(sess)
log_path = stores.history_log_path(SID)
check("C1 the log exists beside the transcript",
      bool(log_path) and os.path.isfile(log_path), log_path)
log_text = open(log_path, encoding="utf-8").read() if log_path and os.path.isfile(log_path) else ""
check("C2 the user message, the tool output and the inject are all present",
      all(probe in log_text for probe in ("INV-7781", "ships Friday", "[harness] continue")),
      log_text[:120].replace("\n", " / "))
check("C3 the log is append-only (two entries never overwrite the first)",
      log_text.count("=== ") == 3, log_text.count("=== "))

# ── D · grep/count over the log ─────────────────────────────────────────────
res = tools._context_recall({"session": SID, "pattern": "INV-7781", "page_size": 1}, SID)
check("D1 grep finds the exact detail and its line",
      res.get("ok") and res.get("total_matches") == 2
      and all("line" in m for m in res.get("matches") or []),
      json.dumps({k: res.get(k) for k in ("ok", "total_matches", "pages")}))
check("D2 pagination is reported",
      res.get("pages") == 2 and res.get("returned") == 1, (res.get("page"), res.get("pages")))
cnt = tools._context_recall({"session": SID, "pattern": "INV-7781"}, SID, count_only=True)
check("D3 count returns the number and no matched text",
      cnt.get("ok") and cnt.get("count") == 2 and "matches" not in cnt,
      json.dumps({k: cnt.get(k) for k in ("ok", "count")}))
bad = tools._context_recall({"session": SID, "pattern": "("}, SID)
check("D4 an invalid regex is an error, never a crash",
      bad.get("ok") is False and "invalid regex" in (bad.get("error") or ""), bad.get("error"))
missing = tools._context_recall({"session": "nosuchsess", "pattern": "x"}, "nosuchsess")
check("D5 a session with no log says so",
      missing.get("ok") is False and "no history log" in (missing.get("error") or ""))

# ── E · verify catches a lost body ──────────────────────────────────────────
ok = recall_log.verify([{"role": "user", "text": "remember the invoice ID INV-7781"},
                        {"role": "tool", "text": "ships Friday"}], log_text)
check("E1 a complete log verifies lossless", ok["lossless"] and ok["checked"] == 2)
lost = recall_log.verify([{"role": "user", "text": "a detail that was never logged"}], log_text)
check("E2 a missing body is reported, not passed",
      lost["lossless"] is False and lost["missing_count"] == 1)

# ── F · the OS contract screen and the install hook ─────────────────────────
FILES = {
    "SKILL.md": "---\nname: deploy\nplatform: linux, windows\n---\n"
                "Run `./run.sh --deploy` after `chmod +x run.sh`.\n",
    "run.sh": "#!/bin/bash\nset -e\n./deploy.sh\n",
}
contract = skill_os_contract.build(FILES)
screen = skill_os_contract.screen(contract, "windows")
check("F1 a POSIX-only skill raises evidence for Windows",
      screen["hypothesis"] == "validate" and bool(screen["evidence"]))
check("F2 evidence names the contract field and a repair target",
      all(e.get("field") in ("G", "P", "M", "D", "A", "X") and e.get("repair")
          for e in screen["evidence"]))
check("F3 executable blockers rank before guide wording",
      screen["evidence"][0]["field"] in ("P", "X"), screen["evidence"][0]["field"])
guarded = skill_os_contract.screen(skill_os_contract.build({
    "SKILL.md": "Run `./run.sh`, or on Windows use powershell ./run.ps1 (fallback).\n",
    "run.sh": "#!/bin/bash\n",
}), "windows")
check("F4 a stated fallback suppresses the finding", guarded["evidence"] == [])
decl = skill_os_contract.screen(skill_os_contract.build({
    "SKILL.md": "---\nplatform: linux\n---\nread the file\n",
}), "windows")
check("F5 metadata that excludes the OS is a finding",
      any(e["rule"] == "declared-unsupported" for e in decl["evidence"]))
root = os.path.join(TMP, "skills")
inst = skills.install_skill_file("local", "deploy", FILES["SKILL.md"], root=root)
check("F6 an install still succeeds and carries the screen",
      inst.get("ok") and isinstance(inst.get("os_warnings"), dict)
      and inst["os_warnings"].get("hypothesis") in ("validate", "skip"), json.dumps(inst)[:240])

# ── G · support-conserving consolidation and the dose ───────────────────────
lessons = ([{"text": "pass an explicit page limit", "outcome": "success",
             "source_task": "t1"}] * 5
           + [{"text": "resolve the entity by id", "outcome": "failure",
               "source_task": "t2"}] * 2
           + [{"text": "convert the receipt before submitting", "outcome": "success",
               "source_task": "t3"}])
cons = guideline_budget.consolidate(lessons)
check("G1 support is conserved across the merge",
      cons["lossless"] and cons["conserved"] == len(lessons) == 8,
      (cons["conserved"], cons["lessons"]))
check("G2 the merged guideline records its support and sources",
      cons["guidelines"][0]["support"] == 5 and cons["guidelines"][0]["sources"] == ["t1"])
synth = [{"text": "guideline %d" % i, "support": 1 + (i % 5)} for i in range(60)]
strong = guideline_budget.dose(synth, "strong")
weak = guideline_budget.dose(synth, "weak")
check("G3 a strong model gets the full set, a weak one a subset",
      strong["count"] == 60 and weak["count"] < strong["count"],
      (strong["count"], weak["count"]))
aud = guideline_budget.audit({"lessons": 8, "guidelines": cons["guidelines"],
                              "store_before": 4, "store_after": 4, "calls": 0})
kinds = {f["kind"] for f in aud["findings"]}
check("G4 the audit names a store that never grew and a run with no call",
      {"store-did-not-grow", "no-model-calls"} <= kinds, sorted(kinds))
check("G5 support is not read as correctness (the failure lesson is flagged)",
      "high-support-failure" in {f["kind"] for f in
                                 guideline_budget.audit({
                                     "lessons": 6,
                                     "guidelines": [{"support": 6, "polarity": "failure"}],
                                 })["findings"]})

# ── H · the registry contract carries grep/count ────────────────────────────
sch = registry._CANONICAL_SCHEMAS["context.grep"]
check("H1 the context canonical set carries grep and count",
      {"context.grep", "context.count"} <= set(registry._CANONICAL_SCHEMAS),
      sorted(k for k in registry._CANONICAL_SCHEMAS if k.startswith("context")))
check("H2 grep declares pattern and pagination",
      {"pattern", "page", "page_size", "context_lines"} <= set(sch["properties"]))
check("H3 every canonical subtool has a field list and guidance",
      all(a in registry._SUBTOOL_FIELDS["context"] for a in ("grep", "count"))
      and all(k in registry._SUBTOOL_GUIDANCE for k in ("context.grep", "context.count")))
check("H4 both are declared reads (no write effect)",
      registry.TOOL_EFFECTS["context.grep"]["effect"] == "read"
      and registry.TOOL_EFFECTS["context.count"]["effect"] == "read")

print()
if FAILED:
    print("FAILED %d/%d: %s" % (len(FAILED), len(CHECKS), ", ".join(FAILED)))
    sys.exit(1)
print("PASS %d/%d" % (len(CHECKS), len(CHECKS)))
