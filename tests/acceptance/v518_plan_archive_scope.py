#!/usr/bin/env python3
"""v518 — archived plan nodes never become current model work."""
import atexit
import os
import shutil
import sys
import tempfile
from typing import Callable

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v518-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
for key in ("CONFIG_DIR", "GRAPH_DIR", "SESSIONS_DIR"):
    path = os.path.join(TMP, key.lower())
    os.makedirs(path, exist_ok=True)
    os.environ["LONGRUN_" + key] = path
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}

from longrun.core import server  # noqa: E402
from longrun.agent import agent  # noqa: E402
from longrun.plan import taskgraph  # noqa: E402

results = []


def check(name: str, ok: bool, detail: object = "") -> None:
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


SID = "plan-archive-scope"
graph = taskgraph.ensure(SID, session_id=SID)
old_open = taskgraph.add_node(graph, "Archived open action")
taskgraph.add_node(graph, "Archived completed action",
                   status="done", evidence="completed in prior plan")
taskgraph.begin_plan(graph)
taskgraph.begin_plan(taskgraph.load(SID))
graph = taskgraph.load(SID)
archived_labels = {"Archived open action", "Archived completed action"}

rendered = taskgraph.render_todos(graph, compact=True)
check("the current-plan prompt omits archived steps",
      not any(label in rendered for label in archived_labels), rendered)
state = server.state_block(session_id=SID)
check("the assembled user-turn state omits archived steps",
      not any(label in state for label in archived_labels), state)

step = {"label": "Archived open action"}
check("deduplication allows a label reused in a new plan",
      taskgraph._missing(graph, [step]) == [step])

check("an index cannot resolve into an archived plan",
      agent._resolve_graph_node(graph, {"index": 0}) is None)
check("an archived node id cannot be updated through current-plan actions",
      agent._resolve_graph_node(graph, {"id": old_open["id"]}) is None)

added = taskgraph.apply_write_todos(
    graph, [{"label": "Archived open action", "deps": []}], skip_existing=True)
check("write_todos creates a same-label step in the current plan",
      len(added) == 1 and added[0].get("plan") == graph.get("plan"), added)

completion_graph = taskgraph.ensure("plan-archive-completion",
                                   session_id="plan-archive-completion")
taskgraph.add_node(completion_graph, "Archived open action")
taskgraph.begin_plan(completion_graph)
taskgraph.add_node(completion_graph, "Current completed action",
                   status="done", evidence="verified in current plan")
check("completion of current plan ignores open archived steps",
      taskgraph.all_done(completion_graph))

empty_graph = taskgraph.ensure("plan-archive-empty",
                               session_id="plan-archive-empty")
taskgraph.add_node(empty_graph, "Archived completed action",
                   status="done", evidence="completed in prior plan")
taskgraph.begin_plan(empty_graph)
check("an empty current plan is not already complete",
      not taskgraph.all_done(empty_graph))
empty_session = {"id": "plan-archive-empty"}
empty_brief = agent._open_todo_brief(empty_session)[1]
check("an empty plan is described as empty, not closed",
      "current plan is empty" in empty_brief.lower()
      and "every step is closed" not in empty_brief.lower(), empty_brief)
empty_nudge = agent._nudge_open_todos(empty_session)
check("an empty-plan nudge does not claim all steps are closed",
      "no current task list" in empty_nudge.lower()
      and "every step is now closed" not in empty_nudge.lower(), empty_nudge)

open_count_graph = taskgraph.ensure("plan-archive-open-count",
                                   session_id="plan-archive-open-count")
taskgraph.add_node(open_count_graph, "Archived open action")
taskgraph.begin_plan(open_count_graph)
check("open-step count ignores archived tasks",
      agent._open_plan_steps({"id": "plan-archive-open-count"}) == 0)

replan_graph = taskgraph.ensure("plan-archive-replan",
                                session_id="plan-archive-replan")
taskgraph.add_node(replan_graph, "Archived open action")
taskgraph.begin_plan(replan_graph)
captured = {}
original_router_stream = server._router_stream


def fake_router_stream(messages: list[dict[str, object]], model: str,
                       on_delta: Callable[[str, str], None]) -> tuple[str, None]:
    """Capture the re-plan prompt and return one deterministic todo line."""
    captured["prompt"] = messages[0]["content"]
    on_delta("text", '{"label":"Archived open action"}\n')
    return "", None


server._router_stream = fake_router_stream
try:
    replanned = taskgraph.replan_from_model(
        replan_graph, note="replan current task", model="test-model")
finally:
    server._router_stream = original_router_stream
check("replan prompt omits archived labels",
      "Archived open action" not in captured.get("prompt", ""))
check("replan can reuse a historical label in the current plan",
      len(replanned) == 1 and replanned[0].get("plan") == replan_graph.get("plan"),
      replanned)

print("---")
passed = sum(results)
print("v518: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
