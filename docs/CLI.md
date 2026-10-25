# Longrun CLI — `forge.py`

> Verified 2026-10-25: structure current (thin stdlib client over `/api/*`,
> same surface as WebUI). If a command 404s, §3 is stale — fix it same-commit.

Command the harness from the terminal. `forge.py` is a thin, **stdlib-only** client
over the *same* REST API the WebUI and the mobile app use: it duplicates **no**
harness logic, it just calls `/api/*` and prints the result. If a command exists in
the UI, its endpoint is reachable from here.

---

## 0. TL;DR

```bash
cd /home/jagones/Repositories/longrun
export LONGRUN_URL=http://127.0.0.1:8790          # default already
export LONGRUN_TOKEN=$(grep '^LONGRUN_TOKEN=' ~/.longrun/config/env | cut -d= -f2)
python3 forge.py --help
```

* **Data commands** print pretty JSON (or aligned tables for `ls` commands).
* **Streaming commands** print live text: `chat --stream`, `agent`, `feed`,
  `blackboard watch`, `swarm` finishes with a summary.
* The token is **never** stored in the repo; it lives in `~/.longrun/config/env`.

---

## 1. Prerequisites

1. The server must be running (`./run.sh`, or `.\run.ps1` on Windows).
2. If the server requires a token (`--token ...`), export `LONGRUN_TOKEN`.
3. `forge.py` uses only the Python standard library (no `pip install`).

Exit codes: `0` success; `1` when chat/plan/history/roles show return `{"error": ...}`;
`2` when a `'<json>'` argument is malformed.

---

## 2. Command reference

Legend: `[x]` = optional, `<x>` = required, `A | B` = alternatives.

### Chat & agent

| Command | Endpoint | Notes |
|---|---|---|
| `chat "msg" [--session ID] [--model ALIAS] [--stream]` | `POST /api/chat` (or `SSE /api/chat/stream`) | one-shot; `--stream` prints deltas live |
| `agent "goal" [--max-steps N] [--model ALIAS]` | `SSE /api/agent/run` | tool-enabled loop, iterations printed |
| `control pause\|resume\|abort RUN_ID` | `POST /api/agent/control` | stop/pause a running agent |

```bash
python3 forge.py chat "spiega questo repo" --session demo
python3 forge.py chat "ping" --stream
python3 forge.py agent "trova e correggi un typo nel README" --max-steps 4
python3 forge.py control abort run_abc123
```

### Paperclip adapter (child process)

| Command | Endpoint | Notes |
|---|---|---|
| `paperclip-bot` | `POST /api/agent/run/stream` + `GET /api/agent/runs/<id>` | Paperclip's external adapter spawns this; **not** an operator command |

`paperclip-bot` is the child process Paperclip's Longrun adapter starts:

```bash
python forge.py paperclip-bot     # one invocation JSON on stdin, NDJSON frames on stdout
```

* **stdin** — one object with schema `longrun.paperclip.invocation.v1`
  (`goal`, `paperclip_run_id`, `agent_id`, `company_id`, optional `task_id`,
  `model`, `max_steps`, `session_id`).
* **stdout** — one protocol frame per line, schema
  `longrun.paperclip.event.v1`, strictly increasing `seq`; the allowlist is
  `longrun.run.started`, `longrun.run.progress`, `longrun.run.completed`,
  `longrun.run.failed`, `longrun.run.cancelled`. Reasoning, raw observations,
  tool arguments, and credentials are never emitted.
* **environment** — `LONGRUN_URL` and `LONGRUN_TOKEN` only; never argv or stdin.
* **exit codes** — `0` only for a corroborated `completed` run, `1` for anything
  else (incomplete, failed, indeterminate, rejected input), `130` after
  SIGINT/SIGTERM (the known run id is aborted first).

See `integrations/paperclip/README.md` for the adapter install and configuration.

### Sessions & history

| Command | Endpoint |
|---|---|
| `sessions ls` | `GET /api/sessions` |
| `sessions new "title"` | `POST /api/sessions` |
| `sessions rm ID` | `DELETE /api/sessions/<id>` |
| `sessions history ID` | `GET /api/history?session=ID` |
| `sessions graph ID` | `GET /api/sessions/<id>/graph` |
| `sessions reset ID` | `POST /api/sessions/<id>/graph/reset` |

```bash
python3 forge.py sessions ls
python3 forge.py sessions history 4f503dc92a29
python3 forge.py sessions rm 4f503dc92a29
python3 forge.py sessions reset my-session      # clears the persistent task list
```

### Context (the token meter / compaction)

| Command | Endpoint |
|---|---|
| `context show [--session ID]` | `GET /api/context` |
| `context compact [--session ID]` | `POST /api/context/compact` |
| `context preview "msg" [--session ID]` | `POST /api/context/preview` |

```bash
python3 forge.py context show --session demo
python3 forge.py context compact --session demo     # model-generated summary (JAG-103)
python3 forge.py context preview "nuova domanda" --session demo
```

`context show` returns `tokens_used` (the model's REAL prompt size when known),
`estimate_tokens_used` (chars/4 proxy), `budget_tokens`, `auto_compact_pct`,
`auto_compact_target_pct`, `pct`, `over_threshold`, `over_budget`, `source`.
`context compact` shrinks the transcript to a fraction of its current size and
stores a **model-written** summary (falls back to a local merge if the router fails).

### Plan & tasks

The **plan** is the PER-SESSION persistent task graph (the same list the model
owns and re-receives every turn) — pass `--session ID` or you get the empty
default. **tasks** targets the legacy global `/api/tasks` board and is unrelated
to the per-session plan.

| Command | Endpoint |
|---|---|
| `plan show [--session ID]` | `GET /api/plan` |
| `plan generate "goal"` | `POST /api/plan/generate` |
| `plan toggle STEP_ID [--session ID]` | `POST /api/plan/toggle` |
| `plan set "goal" [--steps '<json>'] [--session ID]` | `POST /api/plan` |
| `tasks ls` | `GET /api/tasks` |
| `tasks add "title"` | `POST /api/tasks` |
| `tasks done ID` | `PATCH /api/tasks` |
| `tasks set ID STATUS` | `PATCH /api/tasks` (status: todo/doing/done) |

```bash
python3 forge.py plan show --session 48c6e90156c5    # this session's task graph
python3 forge.py plan generate "migliora la UI della WebUI"
python3 forge.py plan toggle n3 --session 48c6e90156c5
python3 forge.py tasks add "scrivere i test per la CLI"
python3 forge.py tasks set t_42 done
```

### Tools, approvals, hooks

| Command | Endpoint |
|---|---|
| `tools ls` | `GET /api/tools` |
| `tools call <tool> '<json-args>'` | `POST /api/tools/call` |
| `tools running` | `GET /api/tools/running` |
| `tools cancel JOB` | `POST /api/tools/cancel` |
| `tools policy TOOL [--enable\|--disable] [--approval MODE]` | `POST /api/tools` |
| `approvals ls` | `GET /api/approvals` |
| `approvals show ID` | `GET /api/approvals/<id>` |
| `approvals approve\|deny ID` | `POST /api/approvals/<id>` |
| `hooks` | `GET /api/hooks` |
| `sandbox` | `GET /api/sandbox?force=1` |

```bash
python3 forge.py tools ls
python3 forge.py tools call shell.exec '{"command":"ls -la"}'
python3 forge.py tools policy shell.exec --approval always
python3 forge.py approvals ls
python3 forge.py approvals approve ap_123
```

### Runs & observability

| Command | Endpoint |
|---|---|
| `runs ls` | `GET /api/agent/runs` |
| `runs show RUN_ID` | `GET /api/agent/runs/<id>` |
| `runs summary` | `GET /api/runs` |
| `runs trace RUN_ID` | `GET /api/runs/<id>/trace` |
| `runs node RUN_ID '<json>'` | `POST /api/runs/<id>/graph/nodes` |
| `events [--since N] [--limit N]` | `GET /api/feed/recent` |
| `feed` | `SSE /api/feed` (loopback tail, live) |
| `status` | `GET /api/status` |
| `self` / `selfcheck` | `GET /api/self` / `GET /api/selfcheck` |

```bash
python3 forge.py runs summary
python3 forge.py runs trace 4f503dc92a29
python3 forge.py events --limit 20
python3 forge.py feed
```

### Models & providers

| Command | Endpoint |
|---|---|
| `models ls` | `GET /api/models` |
| `models ensure ALIAS` | `POST /api/model/ensure` (loads/switches, can take ~60s) |
| `providers` | `GET /api/providers` |

`models ls` prints the **local router roster** (`alias · LOADED/unloaded · Nk ctx`)
followed by the configured **providers** and their models (ref · context length).

```bash
python3 forge.py models ls
python3 forge.py models ensure qwen-3.8-27b-uncensored-q8
python3 forge.py providers
```

### Memory & blackboard

| Command | Endpoint |
|---|---|
| `memory store <kind> <content>` | `POST /api/memory` |
| `memory search "q" [--kind K] [--semantic] [--limit N]` | `GET /api/memory` |
| `blackboard post <topic> <content> [--tags a,b]` | `POST /api/blackboard` |
| `blackboard get [--id I] [--topic T] [--limit N]` | `GET /api/blackboard` |
| `blackboard search "q" [--limit N]` | `GET /api/blackboard?query=` |
| `blackboard stats` | `GET /api/blackboard` |
| `blackboard watch` | `SSE /api/blackboard/watch` |

```bash
python3 forge.py memory store note "lo staging gira su 8790"
python3 forge.py memory search "porta staging" --semantic
python3 forge.py blackboard post idea "usare SQLite per i checkpoint" --tags db,arch
```

### Subagents, meta, swarm

| Command | Endpoint |
|---|---|
| `subagent spawn "goal" [--max-steps N]` | `POST /api/subagent/spawn` |
| `subagent collect ID` | `POST /api/subagent/collect` |
| `subagent status [ID]` | `GET /api/subagent` |
| `meta run [--n-candidates N]` | `POST /api/meta` |
| `meta status` / `meta best` | `GET /api/meta` |
| `swarm "goal" [--n-workers N] [--max-steps N]` | `POST /api/swarm/run` |

```bash
python3 forge.py subagent spawn "riassumi il file X" --max-steps 3
python3 forge.py meta run --n-candidates 6
python3 forge.py swarm "progetta una CLI" --n-workers 4
```

### Teams, agents, jobs, routines, roles

The orchestration layer: designate sessions as **agents**, organise them into an
**org chart**, create **jobs** and dispatch them in dependency waves, schedule
**routines**, and give a session a **role**.

| Command | Endpoint |
|---|---|
| `agents ls` | `GET /api/agents/tree` |
| `agents new NAME [--role R] [--model M] [--reports-to AX]` | `POST /api/orbit/sessions` + `POST /api/agents` |
| `agents set AX [--name N] [--role R] [--model M] [--reports-to AX]` | `POST /api/agents` |
| `agents rm AX` | `DELETE /api/agents/<sid>` (blocked while it has reports) |
| `jobs ls` | `GET /api/jobs` |
| `jobs get JN` | `GET /api/jobs/<id>` |
| `jobs new "goal" [--to AX] [--blocked-by JN,JN] [--agents AX,AX] [--coordinator AX] [--mode m]` | `POST /api/jobs` |
| `jobs run JN` | `POST /api/jobs/<id>/dispatch` (coordinator + workers, dependency waves) |
| `jobs wake` | `POST /api/jobs/wake` (release blocked jobs whose blockers are done) |
| `routines ls` | `GET /api/routines` |
| `routines new "goal" --agent AX [--every N]` | `POST /api/routines` |
| `routines enable RID` / `routines disable RID` | `POST /api/routines/<id>/<action>` |
| `routines rm RID` | `DELETE /api/routines/<id>` |
| `roles show --session SID` | `GET /api/roles?session=` |
| `roles set --session SID [--text T]` | `POST /api/roles` (no `--text` reads stdin) |
| `roles clear --session SID` | `POST /api/roles {text:""}` |
| `roles reset --session SID` | `DELETE /api/roles?session=` |

```bash
python3 forge.py agents ls
python3 forge.py agents new "Docs Lead" --role "owns the docs site"
python3 forge.py jobs new "ship the docs site" --to A25 --mode run
python3 forge.py jobs run J12
python3 forge.py routines new "check the feed" --agent A25 --every 3600
python3 forge.py roles set --session A25 --text "You are the docs lead."
```

### Checkpoints, routing, eval, voice, MCP

| Command | Endpoint |
|---|---|
| `checkpoints ls` | `GET /api/checkpoints` |
| `checkpoints create "label" [--session ID]` | `POST /api/checkpoints` |
| `checkpoints show CP_ID` | `GET /api/checkpoints/<id>` |
| `checkpoints rollback CP_ID` | `POST /api/checkpoints/<id>/rollback` |
| `routing show` | `GET /api/routing` |
| `routing update '<json>'` | `POST /api/routing` |
| `eval tasks` | `GET /api/eval/tasks` |
| `eval run [--task ID] [--model A] [--max-steps N] [--no-save]` | `POST /api/eval/run` |
| `voice status` | `GET /api/voice/status` |
| `voice stt "text"` | `POST /api/voice/stt` |
| `voice tts "text"` | `POST /api/voice/tts` |
| `mcp` | `POST /mcp` (initialize + `tools/list`) |
| `acp server <method> '[params]'` | `POST /api/acp` |
| `acp connect <name> <url> [--token T]` | `POST /api/acp/connect` |
| `acp list` | `GET /api/mcp/clients` |

```bash
python3 forge.py checkpoints create "prima del refactor" --session demo
python3 forge.py checkpoints rollback cp_71cf8545
python3 forge.py routing show
python3 forge.py eval tasks
python3 forge.py voice tts "ciao dal DGX"
```

---

## 3. Full endpoint coverage

Every HTTP route the server exposes has a CLI entry point:

| HTTP | Path | CLI |
|---|---|---|
| GET | `/` `/index.html` | (WebUI) |
| GET | `/api/self` | `self` |
| GET | `/api/context` | `context show` |
| GET | `/api/status` | `status` |
| GET | `/api/models` | `models ls` |
| GET | `/api/providers` | `providers` |
| GET | `/api/selfcheck` | `selfcheck` |
| GET | `/api/feed` | `feed` |
| GET | `/api/plan` | `plan show` |
| GET | `/api/tasks` | `tasks ls` |
| GET | `/api/sessions` | `sessions ls` |
| GET | `/api/sessions/new` | `sessions new` |
| GET | `/api/history` | `sessions history` |
| GET | `/api/eval/tasks` | `eval tasks` |
| GET | `/api/voice/status` | `voice status` |
| GET | `/api/tools` | `tools ls` |
| GET | `/api/tools/running` | `tools running` |
| GET | `/api/hooks` | `hooks` |
| GET | `/api/sandbox` | `sandbox` |
| GET | `/api/approvals` | `approvals ls` |
| GET | `/api/approvals/<id>` | `approvals show` |
| GET | `/api/feed/recent` | `events` |
| GET | `/api/agent/runs` | `runs ls` |
| GET | `/api/agent/runs/<id>` | `runs show` |
| GET | `/api/runs` | `runs summary` |
| GET | `/api/runs/<id>/trace` | `runs trace` |
| GET | `/api/sessions/<id>/graph` | `sessions graph` |
| GET | `/api/memory` | `memory search` |
| GET | `/api/mcp/clients` | `acp list` |
| GET | `/api/subagent` | `subagent status` |
| GET | `/api/meta` | `meta status` / `meta best` |
| GET | `/api/blackboard` | `blackboard get` |
| GET | `/api/blackboard/watch` | `blackboard watch` |
| GET | `/api/checkpoints` | `checkpoints ls` |
| GET | `/api/checkpoints/<id>` | `checkpoints show` |
| GET | `/api/routing` | `routing show` |
| POST | `/api/chat` `/api/chat/stream` | `chat` / `chat --stream` |
| POST | `/api/agent/run` | `agent` |
| POST | `/api/agent/run/stream` | `paperclip-bot` (Paperclip child) |
| POST | `/api/model/ensure` | `models ensure` |
| POST | `/api/plan` | `plan set` |
| POST | `/api/plan/generate` | `plan generate` |
| POST | `/api/plan/toggle` | `plan toggle` |
| POST | `/api/tasks` | `tasks add` |
| POST | `/api/runs/<id>/graph/nodes` | `runs node` |
| POST | `/api/sessions/<id>/graph/reset` | `sessions reset` |
| POST | `/api/context/compact` | `context compact` |
| POST | `/api/context/preview` | `context preview` |
| POST | `/api/sessions` | `sessions new` |
| POST | `/api/eval/run` | `eval run` |
| POST | `/api/voice/stt` | `voice stt` |
| POST | `/api/voice/tts` | `voice tts` |
| POST | `/api/tools` | `tools policy` |
| POST | `/api/tools/call` | `tools call` |
| POST | `/api/tools/cancel` | `tools cancel` |
| POST | `/api/approvals/<id>` | `approvals approve/deny` |
| POST | `/api/agent/control` | `control` |
| POST | `/api/memory` | `memory store` |
| POST | `/api/subagent/spawn` | `subagent spawn` |
| POST | `/api/subagent/collect` | `subagent collect` |
| POST | `/api/meta` | `meta run` |
| POST | `/api/acp` | `acp server` |
| POST | `/api/acp/connect` | `acp connect` |
| POST | `/api/blackboard` | `blackboard post` |
| POST | `/api/swarm/run` | `swarm` |
| POST | `/api/checkpoints` | `checkpoints create` |
| POST | `/api/checkpoints/<id>/rollback` | `checkpoints rollback` |
| POST | `/api/routing` | `routing update` |
| POST | `/mcp` | `mcp` |
| PATCH | `/api/tasks` | `tasks done` / `tasks set` |
| DELETE | `/api/sessions/<id>` | `sessions rm` |
| GET | `/api/agents` `/api/agents/tree` | `agents ls` |
| GET | `/api/agents/<sid>` `/api/agents/<sid>/chain` | delete-guards / chain of command |
| POST | `/api/agents` | `agents new` / `agents set` |
| DELETE | `/api/agents/<sid>` | `agents rm` |
| GET | `/api/jobs` `/api/jobs/<id>` | `jobs ls` / `jobs get` |
| POST | `/api/jobs` `/api/jobs/<id>/dispatch` `/api/jobs/wake` | `jobs new` / `jobs run` / `jobs wake` |
| GET | `/api/routines` `/api/routines/<id>` | `routines ls` |
| POST | `/api/routines` `/api/routines/<id>/<action>` | `routines new` / `routines enable\|disable` |
| DELETE | `/api/routines/<id>` | `routines rm` |
| GET | `/api/roles?session=` | `roles show` |
| POST | `/api/roles` | `roles set` / `roles clear` |
| DELETE | `/api/roles?session=` | `roles reset` |

---

## 4. Streaming (SSE) commands

These connect to a `text/event-stream` and print until `Ctrl-C` / completion:

* `chat "msg" --stream` — chat deltas; reasoning on the `think` channel.
* `agent "goal"` — `agent.iteration`, `agent.thought`, `agent.observation`,
  `agent.finish`.
* `feed` — the loopback event feed (`backlog` + live events).
* `blackboard watch` — new blackboard entries.

---

## 5. Notes

* `forge.py` never talks to the model directly — it only calls the REST API. The
  same policy (compaction, routing, approvals) applies as in the WebUI/app.
* `models ensure` and `eval run` can be slow (model load / multiple turns).
* Add a shell alias for convenience:
  `alias forge='python3 /home/jagones/Repositories/longrun/forge.py'`.
