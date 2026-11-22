# Longrun

Longrun is a self-hosted agent harness: one stdlib-only Python process that drives an
LLM through a disciplined tool loop, composes meta-agents into teams, and can extend
itself live. This glossary is the vocabulary the code, the docs and the operator are
expected to share.

## Language

### The object hierarchy

**Team**:
A symbol (`T<n>`) and a roster. A team owns its members; membership is edited in one place only.
_Avoid_: group, squad, org.

**Agent** (`A<n>`):
A teammate. An agent **is a session** — its own harness, tools, skills, memory and chat.
_Avoid_: bot, worker, runner, assistant.

**Job** (`J<n>`, "Team Job"):
Durable work between the agents of a team, run by a coordinator across dependency waves. Survives a restart and is deleted explicitly.
_Avoid_: task, work item.

**Subjob** (`J<n>.k`):
One assignment inside a Team Job, bound to exactly ONE agent, carrying its dependency edges.
_Avoid_: subtask, step, ticket.

**Session Job** (`SJ<n>`):
A `batch` of subagents inside ONE chat. It is never dispatched, lives in the session's own ledger, and dies with the chat (on `/clear` or delete).
_Avoid_: Team Job, job, batch (the action is `batch`; the object is a Session Job).

**Todo** (`A<n>.mY`):
A step in an agent's plan. It can only be closed `done` with evidence; a vague close is refused.
_Avoid_: task, item, checklist entry.

### The engineering flow

**Ticket**:
A unit of planned work in the local issue tracker (`.scratch/<feature>/issues/NN-*.md`), the thing a
plan is broken into. It is an artifact of the *process*, never a `Subjob` (which is a unit of a Team
Job) and never a `Todo` (which is a step in a session's plan).
_Avoid_: issue, task, work item.

### Work and time

**Plan**:
Not an object but a SCOPE — a number per session, tagged on every node, so a transcript's cards keep resolving their ids forever. The model reads only the CURRENT plan.
_Avoid_: todo list, backlog.

**Turn**:
One LLM call plus the tool executions it triggers.
_Avoid_: run, step, cycle.

**Run**:
A recorded execution of the harness that leaves a trace and an audit row, and is reconciled when the process restarts.
_Avoid_: turn, job, session.

**Session**:
The durable chat and state an agent (or the operator) works in.
_Avoid_: chat, conversation, thread.

**Injected turn kinds** — `nudge`, `observation`, `continue`:
Synthetic turns the harness injects into a chat; they are persisted, so a reload rebuilds them exactly.
_Avoid_: message, system prompt.

### Self-evolution

**Nucleous**:
The protected core (`src/longrun/`). Stable, reviewed, and hard to break.
_Avoid_: core (ambiguous — "core" is also the `core/` package's name).

**Matrix**:
The live, agent-editable zone. A dropped file takes effect on the next call; a broken file is reported and skipped rather than crashing the harness.
_Avoid_: plugins, extensions, sandbox.

**Promote to Nucleous**:
Move a proven Matrix artifact into the protected core through verification gates.
_Avoid_: merge, install, publish.

**Hook point**:
One of the Nucleous seams that exposes a fail-open extension point.
_Avoid_: callback, event, listener.

### State and memory

**Data home**:
The single root (`~/.longrun`) holding everything the harness owns — sessions, events, indexes, costs, self-evolution runtime. Never inside the checkout.
_Avoid_: data dir, workspace.

**Workspace**:
A project directory the agent operates in.
_Avoid_: project, repo.

**Project state**:
Per-workspace rules and prompt files, kept in the data home (never dropped into the workspace).
_Avoid_: config, settings.

**Codebase index**:
A per-workspace, searchable index of that workspace's source. Separate for each workspace.
_Avoid_: knowledge base.

**Knowledge Base**:
One store shared by every session in a single Longrun instance.
_Avoid_: codebase index, memory.

**Session memory**:
What one session remembers across its turns.
_Avoid_: knowledge base.

**Compaction**:
The single summarisation policy — manual and automatic use the same one — that condenses a long transcript in parts.
_Avoid_: truncation, summarization (the generic term).

### Harness behaviour

**Harness action**:
A structured action the model may emit instead of prose: a tool call, a todo write/update/replan, or a subagent.
_Avoid_: command, tool call (that is only one of its kinds).

**Approval gate**:
The point every world-changing call passes, where it is auto-approved, approved, or denied.
_Avoid_: permission check, policy gate (the gate composes policies; it is not one).

**Sandbox**:
The isolation a shell call runs under, when a backend is enabled.
_Avoid_: container.

**Closing report**:
A turn's final output, in one of exactly two shapes: **RESULT** (the value, plus the inputs actually opened) or **BLOCKED** (the missing input, named). The mechanical part is verified.
_Avoid_: answer, summary, final message.
