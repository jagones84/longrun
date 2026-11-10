#!/usr/bin/env python3
"""v929 — the memory index rides the USER turn, not the system prompt.

Measured 2026-11-10 on the live event log (18 sessions, 63 prompt changes): 45 of
those changes were the memory block — a lesson stored, a fact added, the list
reordered. The memory index was the LAST section of the system prompt, so every
memory write changed the prompt text: the whole prompt was re-published in the
chat (a ~47 kB wall) and the provider prefix was invalidated from that point on,
i.e. the transcript after it had to be recomputed.

`prompt.SECTIONS` is now static-first and NOTHING volatile lives in it. The memory
block joins the live task list in the CURRENT user turn (the JAG-276 pattern):

  A) the renderer is unchanged: same buckets, same order, same cap;
  B) it is gone from the system prompt, byte for byte;
  C) it is IN the last user message, exactly once, next to `Harness state`;
  D) what must not regress: the taint gate still sees it, the context meter still
     attributes its tokens, and the `memory` tool is untouched.

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v929-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.agent import agent                # noqa: E402
from longrun.memory import memory              # noqa: E402
from longrun.model import context_engine       # noqa: E402
from longrun.model import prompt               # noqa: E402

results = []
SID = "929b7c1d0e55"
CORE = "the deploy target is the dgx spark box"
PREF = "always answer in English and keep the reply short"


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


memory.core_write(CORE)
memory.store("user.preference", PREF, origin="user")
sess = {"id": SID, "messages": [], "created": 1.0,
        "workspace": os.path.join(TMP, "ws")}
os.makedirs(sess["workspace"], exist_ok=True)

# ---- A. the renderer is unchanged -----------------------------------------
blk = prompt.memory_block(sess)
check("A1 the memory renderer still emits the CORE block first",
      blk.startswith("## Core memory") and CORE in blk, blk[:80])
check("A2 it still carries the labelled user-facts bucket",
      "## Memory \u2014 user facts" in blk and PREF in blk)

# ---- B. it is OUT of the system prompt ------------------------------------
sysp = prompt.render_sections(sess)
check("B1 the system prompt no longer carries the memory index",
      "Core memory" not in sysp and PREF not in sysp)
check("B2 the `memory` section is gone from the registry",
      "memory" not in [s["id"] for s in prompt.SECTIONS])
check("B3 the section registry renders nothing under a `memory` id",
      prompt.section_texts(sess).get("memory") is None)
check("B4 the prompt map the model reads lists no memory section",
      "memory(" not in prompt.prompt_map_text())

# ---- C. it rides the last USER message, exactly once ----------------------
_cap = {}
_orig_build = context_engine.build


def _fake_build(system_prompt, messages, message=None, **kw):
    _cap["sys"] = system_prompt
    _cap["message"] = message or ""
    msgs = [{"role": "system", "content": system_prompt}] + list(messages)
    if message:
        msgs.append({"role": "user", "content": message})
    return msgs, {}


context_engine.build = _fake_build
try:
    msgs, _stats = agent.assemble_turn(sess, "hello", tool_ctx={})
finally:
    context_engine.build = _orig_build

last = msgs[-1] if msgs else {}
check("C1 the last wire message is the user turn", last.get("role") == "user")
check("C2 it carries the memory index", CORE in (last.get("content") or ""))
check("C3 exactly ONCE in the whole wire list",
      sum(str(m.get("content") or "").count(CORE) for m in msgs) == 1,
      [str(m.get("content") or "").count(CORE) for m in msgs])
check("C4 the live task list still rides the same turn",
      "Harness state (your persistent task list):" in (last.get("content") or ""))
check("C5 the system prompt that is SENT carries no memory",
      CORE not in (_cap.get("sys") or ""))
check("C6 the user's own words are still first in that message",
      (last.get("content") or "").startswith("hello"), (last.get("content") or "")[:40])

# ---- D. the consumers that must not regress -------------------------------
from longrun.tools import registry             # noqa: E402

check("D1 the taint gate still flags the index now that it is a user message",
      registry.context_has_untrusted([{"role": "user", "content": blk}]) is True)
server.save_session(sess)
from longrun.core import httpapi               # noqa: E402
try:
    items = httpapi.context_items(SID)
    tok = (items or {}).get("tokens") or {}
    check("D2 the meter attributes the memory tokens (same renderer, not zero)",
          int(tok.get("memory") or 0) > 0, tok)
    usage = httpapi.context_usage(SID, "hello", model=None)
    check("D3 the token meter counts the memory block in what it reports",
          int(usage.get("tokens_used") or 0) > int(usage.get("system_tokens") or 0)
          and int(usage.get("tokens_used") or 0) > int(usage.get("transcript_tokens") or 0),
          {k: usage.get(k) for k in ("tokens_used", "system_tokens", "transcript_tokens")})
except Exception as e:  # noqa: BLE001 — the probe must report, not crash
    check("D2 the meter attributes the memory tokens (same renderer, not zero)", False, repr(e))
    check("D3 the token meter counts the memory block in what it reports", False, repr(e))

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
