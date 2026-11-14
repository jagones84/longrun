#!/usr/bin/env python3
"""v996 — the always-injected memory index respects the session's WORKSPACE.

CO-1 (2026-11-14), from CoReMem (arXiv 2611.17316) §3.2: a memory of the wrong
repository is a "misplaced memory" and costs steps. Longrun wrote `workspace=`
on every lesson and filtered the turn RETRIEVAL, but the index injected into
every turn (`prompt._provider_memory` -> `memory.governed_query`) accepted a
workspace argument and ignored it, so the newest lessons of every OTHER project
rode this project's prompt.

  A) the rendered block carries this workspace's records and not another's;
  B) `governed_query(workspace=)` filters, and the unscoped call is unchanged;
  C) the turn and the Context panel render the SAME scoped block (one truth);
  D) a record with NO workspace stays global — the change can hide nothing that
     was already global.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v996-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_MESSAGES_DIR"] = os.path.join(TMP, "messages")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                 # noqa: E402,F401 — import cycle
from longrun.core import httpapi                # noqa: E402
from longrun.agent import agent                 # noqa: E402
from longrun.memory import memory               # noqa: E402
from longrun.model import context_engine        # noqa: E402
from longrun.model import prompt                # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


WS_A = os.path.join(TMP, "alpha")
WS_B = os.path.join(TMP, "beta")
os.makedirs(WS_A, exist_ok=True)
os.makedirs(WS_B, exist_ok=True)

memory.store("agent.note", "ALPHA_LESSON only valid in alpha", workspace=WS_A,
             origin="reflect")
memory.store("agent.note", "BETA_LESSON only valid in beta", workspace=WS_B,
             origin="reflect")
memory.store("agent.note", "GLOBAL_LESSON every project may use", origin="reflect")
memory.store("memory.store", "BETA_FACT told for beta", workspace=WS_B, origin="user")
memory.core_write("CORE_FACT the box is a dgx spark")

SESS_A = {"id": "996a", "messages": [], "created": 1.0, "workspace": WS_A}
SESS_B = {"id": "996b", "messages": [], "created": 1.0, "workspace": WS_B}

# ---- A. the rendered block is scoped --------------------------------------
blk_a = prompt.memory_block(SESS_A, ws=WS_A)
blk_b = prompt.memory_block(SESS_B, ws=WS_B)
check("A1 alpha's block carries alpha's lesson", "ALPHA_LESSON" in blk_a, blk_a)
check("A2 alpha's block does NOT carry beta's lesson", "BETA_LESSON" not in blk_a)
check("A3 beta's block carries beta's lesson and not alpha's",
      "BETA_LESSON" in blk_b and "ALPHA_LESSON" not in blk_b)
check("A4 a record with no workspace is still global",
      "GLOBAL_LESSON" in blk_a and "GLOBAL_LESSON" in blk_b)
check("A5 the CORE block is still FIRST", blk_a.startswith("## Core memory"), blk_a[:40])
check("A6 a scoped FACT does not cross the workspace", "BETA_FACT" not in blk_a)

# ---- B. governed_query -----------------------------------------------------
scoped = memory.governed_query(kind="agent.note", limit=50, workspace=WS_A)
texts = " ".join(r.get("content", "") for r in scoped)
check("B1 governed_query(workspace=) keeps this workspace",
      "ALPHA_LESSON" in texts and "GLOBAL_LESSON" in texts)
check("B2 governed_query(workspace=) drops the other workspace", "BETA_LESSON" not in texts)
allhits = memory.governed_query(kind="agent.note", limit=50)
alltext = " ".join(r.get("content", "") for r in allhits)
check("B3 governed_query() with no workspace is unchanged (both visible)",
      "ALPHA_LESSON" in alltext and "BETA_LESSON" in alltext)

# ---- C. the turn and the panel render the same block ----------------------
turn = agent.user_turn_context(session_id=SESS_A["id"], sess=SESS_A, history=[])
check("C1 the turn carries alpha's lesson and not beta's",
      "ALPHA_LESSON" in turn and "BETA_LESSON" not in turn, turn[:200])

_saved = httpapi.load_session
httpapi.load_session = lambda sid=None: SESS_A if sid == SESS_A["id"] else None
try:
    items = httpapi.context_items(SESS_A["id"])
    panel = int(items["tokens"]["memory"])
finally:
    httpapi.load_session = _saved
same = context_engine.count_tokens(blk_a)
global_blk = context_engine.count_tokens(prompt._provider_memory(SESS_A, None, None))
check("C2 the Context panel counts the SAME scoped block the turn sends",
      panel == same, "panel=%d scoped=%d" % (panel, same))
check("C3 the panel's number is smaller than the unscoped one (the leak had a cost)",
      panel < global_blk, "panel=%d unscoped=%d" % (panel, global_blk))

print("checks: %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
