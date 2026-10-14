#!/usr/bin/env python3
"""v273 — duplicated-task-list removal, cache-hit meter, cache-safe order, junk cleanup (JAG-273).

Four things, all deterministic (no live server, no network):
  1. `render_todos(compact=True)` (the always-on `state` section) lists ONLY the
     open steps + a closed count and drops the ownership paragraph that already
     lives in the static `task-policy` section (the old "double cost"); the default
     render keeps the ownership contract for the `todo` tool + the legacy test.
  2. The keepgoing CONTINUE/pivot injections no longer re-paste the FULL list —
     they use the open-only `_open_todo_brief` (the list is already in `state`).
  3. The provider's prefix-cache hit is captured (`cached_tokens` / `cache_hit_pct`)
     and exposed by `context_usage` + `context_items`.
  4. Prompt order: every static section precedes every dynamic one, `memory` is the
     last dynamic, `state` is last overall.
Plus: the dead code removed in the same pass is really gone.

Run: python3 tests/v273_cache_and_cleanup.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v273-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import prompt as P  # noqa: E402
from longrun.core import server as S  # noqa: E402
from longrun.plan import taskgraph as TG  # noqa: E402
from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- 1) compact render_todos -------------------------------------------------
g = {"nodes": [
    {"id": "n1", "label": "done step", "status": "done"},
    {"id": "n2", "label": "open step A", "status": "todo"},
    {"id": "n3", "label": "doing step B", "status": "doing"},
]}
full = TG.render_todos(g)
compact = TG.render_todos(g, compact=True)
check("full render still keeps the ownership contract", "This list is YOURS" in full)
check("compact drops the duplicated ownership paragraph", "This list is YOURS" not in compact)
check("compact lists ONLY the open steps",
      "open step A" in compact and "doing step B" in compact and "done step" not in compact)
check("compact reports the closed count", "+1 closed" in compact, compact)
check("compact keeps the open/total header", "2 open / 3 total" in compact, compact)
check("compact is shorter than the full render", len(compact) < len(full),
      "%d < %d" % (len(compact), len(full)))

# the always-on `state` section uses the compact rendering
gg = TG.ensure("c1", session_id="c1")
a = TG.add_node(gg, "alpha done")
b = TG.add_node(gg, "beta open")
TG.update_node(TG.load("c1"), a["id"], status="done", evidence="did it")
cs = S.context_summary(session_id="c1")
check("`state` uses the compact list (no ownership paragraph)", "This list is YOURS" not in cs, cs)
check("`state` still names the open step", "beta open" in cs, cs)

# --- 2) injections no longer duplicate the full list -------------------------
srv_src = open(os.path.join(REPO, "src", "longrun", "core/server.py"),
               encoding="utf-8").read()
srv_src += open(os.path.join(REPO, "src", "longrun", "agent/agent.py"),
                encoding="utf-8").read()
check("keepgoing injections stopped re-rendering the full list",
      "render_todos(taskgraph.load" not in srv_src)
check("keepgoing injections use the open-only brief",
      srv_src.count("_open_todo_brief(sess)[1]") >= 4,
      str(srv_src.count("_open_todo_brief(sess)[1]")))

# --- 3) cache-hit meter ------------------------------------------------------
S.save_session({"id": "s1", "title": "s1", "created": 0,
                "messages": [{"role": "user", "content": "hello world"}]})
S._REAL_PROMPT_TOKENS["s1"] = 1000
S._REAL_CACHED_TOKENS["s1"] = 750
u = S.context_usage("s1")
check("context_usage exposes cached_tokens", u.get("cached_tokens") == 750, str(u.get("cached_tokens")))
check("context_usage computes cache_hit_pct", abs(float(u.get("cache_hit_pct") or 0) - 75.0) < 0.01,
      str(u.get("cache_hit_pct")))
ci = S.context_items("s1")
check("context_items exposes the cache hit too",
      ci.get("cached_tokens") == 750 and abs(float(ci.get("cache_hit_pct") or 0) - 75.0) < 0.01,
      "%s / %s" % (ci.get("cached_tokens"), ci.get("cache_hit_pct")))

# --- 4) cache-safe order (JAG-271/273/276) -----------------------------------
by_id = {s["id"]: s for s in P.SECTIONS}
stat = [s["order"] for s in P.SECTIONS if s["kind"] == "static"]
dyn = [s["order"] for s in P.SECTIONS if s["kind"] == "dynamic"]
check("EVERY static section precedes EVERY dynamic one",
      max(stat) < min(dyn), "static_max=%s dyn_min=%s" % (max(stat), min(dyn)))
check("memory is the LAST cached section (the most volatile block left)",
      by_id["memory"]["order"] == max(stat + dyn))
check("the live task list is no longer a SYSTEM section (JAG-276)",
      "state" not in by_id)
check("state_block injects the list into the user turn (JAG-276)",
      hasattr(S, "state_block")
      and S.state_block(session_id=None).startswith("Harness state"))

# --- 5) the removed junk is really gone --------------------------------------
check("server.extract_actions removed", "def extract_actions" not in srv_src)
check("server.breakdown_tasks removed", "def breakdown_tasks" not in srv_src)
check("server.BREAKDOWN_PROMPT removed", "BREAKDOWN_PROMPT" not in srv_src)

from longrun.tools import approvals as AP  # noqa: E402
from longrun.util import meta as MT  # noqa: E402,F401
from longrun.model import otel_tracing as OT  # noqa: E402
from longrun.model import providers as PR  # noqa: E402
from longrun.model import runmetrics as RM  # noqa: E402
from longrun.agent import subagent as SA  # noqa: E402
from longrun.plan import verify as VF  # noqa: E402

check("runmetrics.human removed", not hasattr(RM, "human"))
check("otel_tracing.provider_ready removed", not hasattr(OT, "provider_ready"))
check("subagent.handle_agent_action removed", not hasattr(SA, "handle_agent_action"))
check("approvals.pending_count removed", not hasattr(AP, "pending_count"))
check("verify.snapshot removed", not hasattr(VF, "snapshot"))
check("providers.is_local removed", not hasattr(PR, "is_local"))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
