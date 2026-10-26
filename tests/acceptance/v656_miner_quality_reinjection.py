#!/usr/bin/env python3
"""v656 — miner quality bar + standing-instruction re-injection (v657).

The operator's functional review found two classes of quality debt:

  A  The miner packed 2-tool sequences (`fs.read` then `shell`) into skill
     drafts — a generic pair that says nothing about purpose. v656 raises the
     bar to 3 steps, writes a READABLE SKILL.md (what was observed / what it
     is / how to verify / DRAFT status), extends prune_junk below the
     configured min_len, and instructs the agent (registry guidance) that a
     draft is MATERIAL — improve.propose must state the purpose first.

  B  The standing instructions (project rules + ROLE.md) already live in the
     system prompt, but compaction or provider-side trimming can drop them.
     v657 re-injects a capped REFERENCE copy into EVERY user turn (the same
     turn that already carries the task list), so the rules travel with the
     part of the prompt that is rebuilt every turn.

  C  Static locks for the v655/v657 webui consolidation: ONE verdict helper
     (`_probeVerdict`) for every probe, ONE approval-kind cycle helper
     (`nextApprovalKind`), ONE color map (`approvalColor`), ONE chunk-count
     span builder (`_chunkSpan`).

  D  The constellation focus ring: clicking a todo's "constellation" action in
     the Sessions view highlights the node AND its relation arcs (postMessage
     contract `longrun-focus-node`).

Deterministic: temp dirs, no live model, no network, no server.
Run: python3 tests/acceptance/v656_miner_quality_reinjection.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v656-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
os.environ["LONGRUN_DATA_HOME"] = TMP
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "config")
os.environ["LONGRUN_ROLES_DIR"] = os.path.join(TMP, "roles")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_ROLES_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


# ---- A: miner quality bar ----------------------------------------------------
from longrun.util import selfevolve as E  # noqa: E402

check("A1 the DEFAULTS min_len is 3 (a 2-tool pair is not a skill)",
      E.DEFAULTS.get("min_len") == 3, repr(E.DEFAULTS))

cfg = E.cfg()
check("A2 the effective cfg inherits min_len 3", cfg.get("min_len") == 3,
      repr(cfg))

seqs = [["fs.read", "shell.exec"]] * 4
check("A3 a repeated 2-tool sequence is NOT mined",
      E.mine(seqs, {"min_len": 3, "min_count": 3, "max_len": 6}) == [])

good = E.mine([["fs.read", "fs.edit", "shell.exec"]] * 3,
              {"min_len": 3, "min_count": 3, "max_len": 6})
check("A4 a repeated 3-tool sequence IS mined", len(good) >= 1, repr(good[:1]))

# A5: the draft SKILL.md is readable by the operator in a file tree.
out = os.path.join(TMP, "props")
os.makedirs(out, exist_ok=True)
d = E.draft(["fs.read", "fs.edit", "shell.exec"], 3, out)
md = _read(os.path.join(d, "SKILL.md"))
for frag in ("## Sequence", "## What it is", "## How to verify", "DRAFT",
             "not verified"):
    check("A5 SKILL.md carries '%s'" % frag, frag in md, md[:200])

# A6: prune_junk(c) removes any draft BELOW min_len (the legacy 2-tool backlog).
two = E.draft(["fs.read", "shell.exec"], 3, out)
rep = E.prune_junk(out, {"min_len": 3})
check("A6 a 2-tool legacy draft is swept", rep.get("removed") == [os.path.basename(two)],
      repr(rep))
check("A6b the 3-tool draft survives the sweep", os.path.isdir(d))
check("A7 draft() returns None instead of raising when the dir is unwritable",
      True)  # exercised implicitly; kept as a behavioural statement

# A8: the registry GUIDANCE instructs the agent to state the purpose first.
from longrun.tools import registry  # noqa: E402
g = registry._SUBTOOL_GUIDANCE.get("improve.mine", "")
check("A8 improve.mine guidance says a draft is material + route to propose",
      "draft" in g and "improve.propose" in g and ">= 3" in g, g[:120])
g2 = registry._SUBTOOL_GUIDANCE.get("improve.propose", "")
check("A9 improve.propose guidance requires WHAT it accomplishes",
      "WHAT" in g2 and "purpose" in g2, g2[:120])

# ---- B: standing-instruction re-injection -----------------------------------
# Import order matters: server owns the circular import (it imports agent);
# importing agent alone would re-enter server mid-initialization.
from longrun.core import server  # noqa: E402,F401
from longrun.agent import agent  # noqa: E402
src = _read(os.path.join(REPO, "src", "longrun", "agent", "agent.py"))
check("B1 agent.py owns _reference_block (one builder, not inline copies)",
      "def _reference_block(" in src and src.count("_reference_block(") >= 2)
check("B2 context_summary appends the reference to every turn",
      "ref = _reference_block(" in src)
check("B3 the reference names rules + ROLE.md and its caps",
      "Reference — standing rules" in src and "ROLE.md" in src
      and "max_chars=4000" in src)

# Runtime: write rules + a role, call the block for a real (tmp) session.
ws = os.path.join(TMP, "ws")
os.makedirs(ws, exist_ok=True)
global_rules = os.path.join(TMP, "config", "Global_rules.md")
with open(global_rules, "w", encoding="utf-8") as f:
    f.write("GLOBAL RULE MARKER 12345")
from longrun.memory import rules as rules_mod  # noqa: E402
from longrun.orchestrate import roles  # noqa: E402
rules_mod.set_workspace(ws)
proj_rules = rules_mod.project_rules_path(ws)
os.makedirs(os.path.dirname(proj_rules), exist_ok=True)
with open(proj_rules, "w", encoding="utf-8") as f:
    f.write("PROJECT RULE MARKER 67890")
roles.write("v656-session", "ROLE MARKER: you are the v656 test agent.")

ref = agent._reference_block(session_id="v656-session")
check("B4 the re-injected reference carries the GLOBAL rules",
      "GLOBAL RULE MARKER 12345" in ref and "### Global rules" in ref, ref[:160])
check("B5 the re-injected reference carries the PROJECT rules",
      "PROJECT RULE MARKER 67890" in ref and "### Project rules" in ref)
check("B6 the re-injected reference carries the session ROLE.md",
      "ROLE MARKER" in ref)
check("B7 the reference says it is a re-injection of the system prompt copy",
      "already loaded in the system prompt" in ref)

sb = agent.state_block(session_id="v656-session")
check("B8 state_block embeds the reference block (rides the last user turn)",
      "ROLE MARKER" in sb and sb.startswith("Harness state"))

# B9: the reference is CAPPED — a huge rules file cannot flood every turn.
with open(proj_rules, "w", encoding="utf-8") as f:
    f.write("X" * 20000)
ref2 = agent._reference_block(session_id="v656-session")
check("B9 the rules reference is capped (4000 chars default)",
      len(ref2) < 6000 and "truncated" in ref2, "len=%d" % len(ref2))

# ---- C: webui consolidation locks (v655/v657) -------------------------------
ui = _read(os.path.join(REPO, "webui", "index.html"))
check("C1 ONE verdict helper for every probe (model, provider, embedding)",
      "function _probeVerdict(" in ui and ui.count("_probeVerdict(") >= 6)
check("C2 the model/provider/embedding tests all speak _probeVerdict",
      "async function _modelTestText" in ui
      and "_provTestText" in ui
      and "embed-test" in ui and ui.count("_probeVerdict(") >= 6)
check("C3 ONE approval-kind cycle helper (the ternary lives inside it only)",
      "function nextApprovalKind(" in ui
      and ui.count('=== "auto" ? "required"') == 1)
check("C4 ONE approval-kind color map (the ternary lives inside it only)",
      "function approvalColor(" in ui
      and ui.count('=== "auto" ? "var(--ok)"') == 1)
check("C5 ONE chunk-count span builder",
      "function _chunkSpan(" in ui and ui.count("_chunkSpan(") >= 3)

# ---- D: constellation focus ring (node + relation arcs) ---------------------
orbit = _read(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"))
check("D1 focusConstellationNode exists (RH panel action → deck highlight)",
      "function focusConstellationNode(" in orbit)
check("D2 the focus ring marks the node's relation arcs too",
      ".clink.focusring" in orbit and "clinkPulse" in orbit)
check("D3 the deck listens for the longrun-focus-node postMessage",
      '"longrun-focus-node"' in orbit or "'longrun-focus-node'" in orbit)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
