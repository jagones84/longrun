#!/usr/bin/env python3
"""v744 — the system prompt must tell the model HOW to verify what it produced.

Operator rule (2026-10-31): no reviewer agent, no task-specific rules. The SAME model
that produced an artefact must verify it, and the prompt must carry generic checks that
hold for any artefact type (file, table, sheet, document, slide, image, chart, code,
archive, message). Examples are allowed, but only as the SHAPE of an example.

Contract locked here:
  * `prompt.SECTIONS` carries {"id": "verify-policy", "order": 47, "kind": "static"};

  * `server.VERIFY_POLICY` lists the generic checks (request, inputs, consistency,
    declared rules, usability, code execution, visual output, traceability, delivery);
  * it tells the model to RE-OPEN the artefact with a tool, not to trust the harness;
  * it stays domain-free: no profession, task, file or system of record is named;
  * it lands in the rendered prompt once, between task-policy and self-summary;
  * both loops (chat and the v2 agent loop) carry it.

Run: python3 v744_artifact_verification_policy.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo(start):
    p = start
    while True:
        if os.path.isdir(os.path.join(p, "src", "longrun")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            raise SystemExit("repository root not found from %s" % start)
        p = parent


REPO = _repo(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402
from longrun.model import prompt  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- A: registered in the right slot --------------------------------------
_sec = next((s for s in prompt.SECTIONS if s.get("id") == "verify-policy"), None)
check("A1 SECTIONS has verify-policy", _sec is not None)
check("A2 order is 47 (after task-policy 45, before self-summary 50)",
      bool(_sec) and _sec.get("order") == 47, repr(_sec))
check("A3 kind is static (cache-safe prefix)", bool(_sec) and _sec.get("kind") == "static")
check("A4 _STATIC_ATTRS points at VERIFY_POLICY",
      prompt._STATIC_ATTRS.get("verify-policy") == "VERIFY_POLICY", repr(_sec))

TEXT = server.VERIFY_POLICY or ""
LOW = TEXT.lower()

# ---- B: the generic checks are all there ----------------------------------
CHECKS = [
    ("B1 answers the request", "answers the request"),
    ("B2 complete against the inputs", "complete against the inputs"),
    ("B3 internally consistent (totals add up)", "internally consistent"),
    ("B4 applies its own declared rules", "applies its own rules"),
    ("B5 usable as delivered", "usable as delivered"),
    ("B6 code runs", "code runs"),
    ("B7 visual output is visible", "visual output is visible"),
    ("B8 nothing fabricated", "nothing fabricated"),
    ("B9 delivery is named", "delivery is named"),
]
for _name, _needle in CHECKS:
    check(_name, _needle in LOW, repr(_needle))

# ---- C: it instructs the model to re-open the artefact itself -------------
check("C1 names a read tool", "fs.read" in TEXT)
check("C2 says the model itself must verify", "you verify it" in LOW)
check("C3 refuses a prose explanation of a failure", "fix the artefact" in LOW)
check("C4 typo-fix loop: check again after the fix", "check again" in LOW)
check("C5 no reviewer agent is offered as the way out",
      "reviewer" not in LOW and "subagent" not in LOW)

# ---- D: it stays generic (no domain, no task, no file named) --------------
DOMAIN = ["ledger", "invoice", "payroll", "referral", "patient", "dispatch",
          "battalion", "vendor", "reconcil", "tax", "medical", "bookkeep",
          "xlsx", "csv", "docx", "pdf", "sqlite"]
_hits = [_w for _w in DOMAIN if _w in LOW]
check("D1 no profession, task, file format or system of record is named",
      not _hits, repr(_hits))
check("D2 artefact types are named generically (list, not one format)",
      all(t in LOW for t in ("file", "table", "document", "image", "code")))
check("D3 examples are marked as examples", "shape" in LOW)

# ---- E: it is rendered once, after task-policy, before self-summary -------
_rendered = prompt.render_sections(None, None, None)
check("E1 the block is in the assembled system prompt",
      "## Verifying what you produced" in _rendered)
check("E2 it appears exactly once",
      _rendered.count("## Verifying what you produced") == 1,
      str(_rendered.count("## Verifying what you produced")))
_i_task = _rendered.find("## Your task list")
_i_ver = _rendered.find("## Verifying what you produced")
_i_self = _rendered.find("Self-knowledge:")
check("E3 placed after the task list",
      _i_task >= 0 and _i_ver > _i_task, "%s -> %s" % (_i_task, _i_ver))
check("E4 placed before the dynamic sections",
      _i_self < 0 or _i_ver < _i_self, "%s -> %s" % (_i_ver, _i_self))

# ---- F: no phrase stolen from a section pinned exactly-once --------------
check("F1 does not duplicate 'prompt injection' (v557 pins it once)",
      "prompt injection" not in _rendered.lower().split("## verifying what you produced")[-1])
check("F2 does not duplicate the rules-policy phrases (v665 pins them once)",
      "code wins" not in LOW and "project rules override global ones" not in LOW)

# ---- G: both loops carry it ----------------------------------------------
_apiv2 = os.path.join(REPO, "src", "longrun", "core", "api_v02.py")
_src = open(_apiv2, encoding="utf-8").read()
check("G1 the v2 agent loop injects VERIFY_POLICY", "srv.VERIFY_POLICY" in _src)
check("G2 the chat path gets it through the section registry",
      "verify-policy" in [s.get("id") for s in prompt.SECTIONS])

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
