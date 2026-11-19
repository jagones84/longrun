# Longrun CLI — `forge.py`

> Verified 2026-11-18: structure current (thin stdlib client over `/api/*`,
> same surface as WebUI). If a command 404s, §3 is stale — fix it same-commit.
> Behavioural proof: `tests/acceptance/v785_cli_command_cases.py` (67 cases,
> handlers driven with `req` stubbed).

Command the harness from the terminal. `forge.py` is a thin, **stdlib-only** client
over the *same* REST API the WebUI and the mobile app use: it duplicates **no**
harness logic, it just calls `/api/*` and prints the result. If a command exists in
the UI, its endpoint is reachable from here.

---

## 0. How to use this document as a skill

Read this section if you are an agent (or a person) landing in Longrun with no
context. It is the order you act in, not another command list; §2 stays the
manual.

### 0.1 The one fact that unlocks everything

**An agent IS a session.** The org chart's `AX` is a *handle*; the session id is
the *address*. Every chat verb targets a session, so `--session A50` and
`--session 0e13bdb23c5b` now reach the same transcript (the CLI resolves `AX` for
you, §2). Everything the CLI writes is the same store the WebUI renders: a turn you
send from here appears in that agent's chat, with its tool cards, on reload.

### 0.2 The loop: find → talk → watch → inspect → act

| You want to | Run | What you get |
|---|---|---|
| see the org chart and each agent's session | `agents ls` | `AX  name  role  session  model  -> reports-to` |
| talk to one agent | `chat "…" --session A50` | the reply; `session:` printed; the CLI remembers it |
| **watch it work, live** | `chat "…" --session A50 --stream` | the model's text **and** the flow: `→ tool args`, `← result`, `[harness:…]`, `[approval]`, `[plan]`, `[verify]` |
| follow a turn that was started elsewhere (WebUI, a job, a routine) | §4.2 `/api/chat/live` + `/api/chat/attach` | the same event stream, replayed from the durable log |
| reconstruct a finished turn | `sessions history A50 --full` | every message untruncated + every card with args/exit/result/thought |
| see the raw event ledger of a session | `events --session A50 --kind tool.result --limit 50` | one line per event, newest first |
| know why a turn failed | `sessions tree A50` | stage→step tree, first failed step, its reason |
| know what the model actually sees | `context show --session A50` | tokens, `pct`, the assembled context |
| start a job / release a wave / approve | `jobs new … --to A54`, `jobs run J12`, `jobs wake`, `approvals ls/approve` | §2 |

### 0.3 The three things that must appear in the WebUI

1. **A turn**: `chat` writes to the session you named; open that agent's chat and
   reload — the transcript is the same file the WebUI reads.
2. **A team job**: `jobs new` + `jobs run` create the `J<n>` row the Control deck's
   Jobs panel lists (scoped to the session by `agents`/`coordinator`). In-chat Session
   Jobs (`SJ<n>`) are a different object: they never appear as team rows and are read
   with `self.sj` / `GET /api/sessions/<sid>/sj`.
3. **A document**: `docs plan|spec` write under the session's workspace and lock
   the session; `docs approve` / `docs implement` are the two decisions the
   composer bar shows.

If a surface looks stale, the page's shell fingerprint changed: accept the reload
banner instead of re-sending the command.

### 0.4 Guard rails (they cost real work if ignored)

* **Never wrap `chat` in `timeout`** — the socket is the turn's lifeline; closing it
  aborts the turn server-side (§2).
* **Check `context show --session <SID>` `pct` before a long brief**; above ~10%
  compact first (`context compact --session <SID>`), or the brief competes with the
  transcript it is meant to steer.
* **Restart only when idle** (`GET /api/chat/live` = `{"active": []}` **and**
  `GET /api/tools/running` = `{"running": []}`), then `systemctl --user restart longrun`.
  **Then prove the new code is the running code**: `ActiveEnterTimestamp` must be newer than
  the newest `src/`/`webui/` mtime. Any edit after the restart voids it — restart again.
  Full procedure: project rules §"After every codebase change the testing head verifies it".
  A CLI change needs no restart — it is a client, not the service.
* **Never invent ids.** `AX` from `agents ls`, `JN` from `jobs ls`, `SID` from
  `sessions ls`; an unknown one fails loudly instead of creating a row.

### 0.5 What this document cannot prove

It drives the backend, so it proves *data and control*. It does not prove *rendering*:
a screenshot + `getComputedStyle` through the browser is a separate act (project
rules §"Testing the WebUI live"). Say which of the two you did.

---

## 0.9 TL;DR

```bash
cd /home/jagones/Repositories/MyRepos/longrun
export LONGRUN_URL=http://127.0.0.1:8790          # default already
export LONGRUN_TOKEN=$(grep '^LONGRUN_TOKEN=' ~/.longrun/config/env | cut -d= -f2)
python3 forge.py --help
```

* **Data commands** print pretty JSON (or aligned tables for `ls` commands).
* **Streaming commands** print live text: `chat --stream` (text **and** the render
  flow: tool calls, results, harness injects, approvals, plan/verify notes),
  `agent`, `feed`, `blackboard watch`, `swarm` finishes with a summary.
* The token is **never** stored in the repo; it lives in `~/.longrun/config/env`.
* **Testing the CLI against a live service:** §6 is the one recipe — every session +
  document verb, on a throwaway pointer and workspace, failing loudly on the first red.

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
| `chat "msg" [--session ID|AX] [--model ALIAS] [--stream] [--new]` | `POST /api/chat` (or `SSE /api/chat/stream`) | no `--session`: this CLI's CURRENT session (printed as `session: ID`); an agent id (`A50`) resolves to that agent's session — an UNKNOWN `AX` exits 1 instead of creating a row; `--new` forces a fresh one |
| `agent "goal" [--max-steps N] [--model ALIAS]` | `SSE /api/agent/run` | tool-enabled loop, iterations printed |
| `control pause\|resume\|abort RUN_ID` | `POST /api/agent/control` | stop/pause a running agent |

```bash
python3 forge.py chat "spiega questo repo" --session demo
python3 forge.py chat "ping" --stream          # lands in the current session, id printed
python3 forge.py agent "trova e correggi un typo nel README" --max-steps 4
python3 forge.py control abort run_abc123
```

**The current session.** The CLI remembers one session per machine
(`data/cli_session.json`, override with `LONGRUN_CLI_STATE`). `sessions new` and
`sessions fork` set it, `sessions use ID` switches it, `sessions current` prints it and `sessions ls` marks
it with `*`. A `chat` without `--session` uses it, and every chat prints the id it
wrote to — so a turn can never land in an anonymous row again. Without a stored
session, a bare `chat` creates one and adopts its id (as before); `--new` keeps the
old one-shot behaviour explicitly.

**`chat` waits for the turn, however long it runs** (up to 6 h). The client socket
is the turn's lifeline: if it closes, the server's `watch_client` aborts the turn
(measured 2026-11-16 20:48:37 — a 5-minute CLI timeout killed a live turn). So do not
wrap `chat` in `timeout 60`; use `--stream` when you want to watch progress, or
`control abort` when you mean to stop one.

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
| `sessions new "title" [--workspace DIR]` | `POST /api/sessions` (or `GET /api/sessions/new?workspace=…` when a folder is named) |
| `sessions fork ID [--at N] [--title T] [--model M] [--workspace DIR]` | `POST /api/sessions/<id>/fork` (new session with `messages[:N]`; the source is untouched; the reply carries `replay` — `transcript-only`, `unverified-effects` or `effects-not-restored`, plus the workspace `head`/`dirty`) |
| `sessions use ID` | `GET /api/history?session=ID` (validates, then remembers) |
| `sessions current` | — (the local pointer) |
| `sessions rm ID` | `DELETE /api/sessions/<id>` |
| `sessions history [ID|AX] [--full]` | `GET /api/history?session=ID` (ID omitted → current; `--full` = every message untruncated + every tool card with args/exit/result/thought) |
| `sessions card HANDLE` | `GET /api/history?session=<current>&card=<handle>` (ONE tool card by the handle the compacted manifest prints: `#id`, or `t<ms>` for a card persisted before ids) |
| `sessions counterfactual HANDLE --arg k=v` | `POST /api/sessions/<id>/counterfactual` (change ONE argument of a recorded **read-only** call, re-execute it through the same gate, report `same-observation` / `different-observation`; a mutating card is refused) |
| `sessions model-counterfactual INDEX --content "text"` | `POST /api/sessions/<id>/counterfactual/model` (replace ONE stored message's CONTENT, re-ask the session's model, report `same-action` / `different-action` / `no-action`; nothing executes, one model call; INDEX is the `#N` from `sessions history` or a negative offset, `-1` = the last intervenable message — see below) |
| `sessions graph [ID]` | `GET /api/sessions/<id>/graph` |
| `sessions tree [ID]` | `GET /api/sessions/<id>/trace-tree` |
| `sessions reset ID` | `POST /api/sessions/<id>/graph/reset` |

```bash
python3 forge.py sessions ls
python3 forge.py sessions new "probe docs" --workspace /tmp/lr-probe   # becomes current
python3 forge.py sessions current
python3 forge.py sessions history              # no id: the current session
python3 forge.py sessions card 3f2a91c4        # one tool card by its manifest handle
python3 forge.py sessions counterfactual 3f2a91c4 --arg path=README.md   # one fact changed
python3 forge.py sessions model-counterfactual 211 --content '[harness] exit=124 timed out'
python3 forge.py sessions fork 4f503dc92a29 --at 12 --model gpt-local   # A/B arm
python3 forge.py sessions use 4f503dc92a29
python3 forge.py sessions tree                 # stage→step tree + the first failed step
python3 forge.py sessions rm 4f503dc92a29
python3 forge.py sessions reset my-session      # clears the persistent task list
```

**`model-counterfactual`: what INDEX means, and what comes back.** A positive
INDEX is the 0-based position printed by `sessions history`. A negative INDEX
counts INTERVENABLE messages from the end — `-1` is the last message an
intervention can target, `-2` the one before it — and an offset past the
available ones is refused with how many exist (`-1 .. -N`). An intervenable
message is a text USER message — an observation or a nudge — whose successor is
the assistant's recorded reply. The final message, and any message without a
recorded assistant successor, is refused, because there is nothing to compare
the replayed action against; so is an assistant message (editing the model's own
reply is history editing, not an intervention on its input), a structured-content
message, and an unchanged replacement.

Three verdicts: `same-action` (same tool and arguments), `different-action`
(named in `moved`) and `no-action` (neither reply carried a tool action — a plain
answer on both sides). The JSON body carries: `ok`, `status`, `session`, `index`,
`model`, `fidelity` (`transcript+live-system` or `transcript-window+live-system`),
`caveat`, `dropped`, `first`, `original`, `replacement`, `recorded_action`,
`replayed_action`, `compare`, `usage`, `recorded_reply`, `replayed_reply`, `think`.
A refused plan returns `ok: false` with `status`, `error` and, when a plan was
built, `plan`. A provider failure is `status: 502` with `error` and `model`.

### Documents (`/plan` and `/spec`)

The reviewed **document** behind the plan/spec bar — not the task graph of the
section below. `plan`/`spec` write the markdown, record it on the session and
lock the session. `--session ID` is optional: it defaults to the CLI's current
session.

There are **two decisions**: `approve` accepts the CONTENT (the session stays
locked), `implement` authorises the IMPLEMENTATION and opens the write gate. A
spec can be approved without authorising its implementation.

| Command | Endpoint |
|---|---|
| `docs status [--session ID]` | `GET /api/docs?session=ID` |
| `docs plan "request" [--session ID]` | `POST /api/docs/plan` (origin `cli`: document only) |
| `docs spec "request" [--session ID]` | `POST /api/docs/spec` (origin `cli`: document only) |
| `docs approve [--implement] [--session ID]` | `POST /api/docs/approve` (`--implement` also opens the gate) |
| `docs implement [--session ID]` | `POST /api/docs/implement` (the bar's ▶; requires an approved document) |
| `docs reject [--session ID]` | `POST /api/docs/reject` |
| `docs unlock [--session ID]` | `POST /api/docs/unlock` (release the gate and forget the record; the file stays) |

**The CLI inherits the server's policy and cannot change it.** With
`approvals.mode=full` the server auto-approves the document as it is created; the
"auto-approve plans and specs" checkbox (`approvals.auto_implement_documents`)
additionally authorises the implementation — but only for a request that ASKED to
implement, i.e. the agent's `docs` tool. The composer's `/plan`·`/spec` and the
CLI never implement, so with `full`+checkbox they still land `approved` with the
gate closed. There is **no CLI verb that writes the policy**: `POST /api/tools`
and `POST /api/settings` refuse a body that carries a `session`/`run_id` (a turn's
call is never an operator act) and publish every accepted change as
`policy.changed`. There is ONE token — the API bearer in `.env` — and the
**permission layer** is the control: `fs.read`/`fs.write`/`fs.edit` hard-deny the
env file, `shell.exec` hard-denies reading it (`cat`, `grep`, …) and reaching the
control API (`curl …/api/tools|settings|docs|fs|edits`). Honest limit: that is a
set of hard denies, not a sandbox.

```bash
SID=$(python3 forge.py sessions new "docs probe" --workspace /tmp/lr-probe | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
python3 forge.py docs plan "add a /health endpoint" --session "$SID"
python3 forge.py docs status                         # no --session: the current session
python3 forge.py docs approve                        # content only: still locked
python3 forge.py docs implement                      # ▶: the write gate opens
python3 forge.py chat "Reply with exactly PONG"      # same session, id printed
python3 forge.py docs unlock                         # bar gone, file kept
python3 forge.py sessions rm "$SID"
```

A document write refuses while a chat turn is running in that session
(`error: a chat turn is running…`, exit 1), and a second `docs plan|spec` for the
same session is refused while the first is still generating.


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
| `tools runtime\|verifier\|bestofn\|difficulty\|selfevolve\|reasoning\|approvals` | `POST /api/tools` (the global policy presets the Settings panel writes) |
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
python3 forge.py approvals audit   # no FILE: refusal safety + completeness over the LIVE store
python3 forge.py hooks            # configured git/event hooks
python3 forge.py sandbox          # sandbox backend + isolation state (force probe)
```

### Per-paper harness groups (`forge harness`)

The ~140 groups added from rounds 110–159 are all one shape: a JSON record in,
one deterministic verdict out. Their index is generated from the parser, not
hand-maintained:

```bash
python3 forge.py harness              # every group, its actions, and where its JSON goes
python3 forge.py harness recovery     # one group's own -h
python3 forge.py recovery adjudicate /tmp/record.json
```

- **Input**: `FILE` is a positional (or `value` where the parser keeps the path
  there — `skills value FILE.json`). `harness` prints which one a group uses.
- **Exit codes**: `0` clean/complete, `1` the checker's negative verdict, `2`
  bad or missing input, `3` not decidable (only the tri-state groups, e.g.
  `effects verify`).
- **FORMAT**: every result carries the module's own `format` string; the CLI
  refuses (exit 2) a result whose format does not match, so a renamed key cannot
  silently flip the exit code.

### Runs & observability

| Command | Endpoint |
|---|---|
| `runs ls` | `GET /api/agent/runs` |
| `runs show RUN_ID` | `GET /api/agent/runs/<id>` |
| `runs summary` | `GET /api/runs` |
| `runs trace RUN_ID` | `GET /api/runs/<id>/trace` |
| `runs node RUN_ID '<json>'` | `POST /api/runs/<id>/graph/nodes` |
| `events [--since N] [--limit N]` | `GET /api/events` |
| `feed` | `SSE /api/feed` (loopback tail, live) |
| `status` | `GET /api/status` |
| `self` / `selfcheck` | `GET /api/self` / `GET /api/selfcheck` |

```bash
python3 forge.py runs summary
python3 forge.py runs trace 4f503dc92a29
python3 forge.py events --limit 20
python3 forge.py feed
python3 forge.py status           # service + router + model roster + telemetry
python3 forge.py self             # this process's own identity/capabilities
python3 forge.py selfcheck        # deterministic self-diagnosis
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
| `memory forget <target>` | `DELETE /api/memory?target=` |
| `memory purge` | `POST /api/memory` (`{"action": "purge"}`) |
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

### Knowledge, research, index, embeddings

| Command | Endpoint | Notes |
|---|---|---|
| `knowledge status` | `GET /api/knowledge/status` | counts |
| `knowledge notebooks` | `GET /api/knowledge/notebooks` | id + name + sources |
| `knowledge create "name"` | `POST /api/knowledge/notebooks` | make a notebook |
| `knowledge add <url-or-ref> [--notebook NB]` | `POST /api/knowledge/sources` | fetch + index into NB |
| `knowledge search "q" [--notebook NB] [--limit N]` | `GET /api/knowledge/search` | lexical (+ vectors when configured) |
| `knowledge discover "q" [--limit N]` | `POST /api/knowledge/discover` | web candidates, pick before import |
| `knowledge import <url…> [--notebook NB]` | `POST /api/knowledge/import` | import chosen URLs |
| `knowledge research "q" [--notebook NB] [--depth shallow\|medium\|deep] [--limit N] [--max-rounds M]` | `POST /api/knowledge/research` | auto agent: search + fetch + summarise + import |
| `research ls` / `research active` / `research set <id>` | `GET`/`POST /api/research/model` | pick the research LLM |
| `index status` / `index build [--force]` / `index search "q"` | `GET /api/codebase/status`, `POST /api/codebase/build`, `GET /api/codebase/search` | the workspace code index |
| `embedding models` / `active` / `set <id>` / `add '<json>'` / `remove <id>` / `costs` / `cost-test` | `GET`/`POST /api/embedding/*` | embedding model catalogue + cost log (`cost-test` probes in-process) |

```bash
python3 forge.py knowledge notebooks
python3 forge.py knowledge research "llama.cpp server options" --depth shallow --limit 3
python3 forge.py research ls
python3 forge.py index status     # codebase index: files, chunks, last build
python3 forge.py index build --force
python3 forge.py index search "system_prompt" --limit 5
python3 forge.py embedding models # ids, dims, local-vs-paid, active model
python3 forge.py embedding costs   # spend log: total, by model, last 30 days
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

`jobs …` is the **team-job** surface (`J<n>`, `data/jobs.json`). In-chat Session Jobs
(`SJ<n>`) are a different object: read them with `self.sj` or
`GET /api/sessions/<sid>/sj`; they are never dispatched and die with the session.

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
| `checkpoints rm CP_ID` | `DELETE /api/checkpoints/<id>` |
| `checkpoints prune` | `DELETE /api/checkpoints` (the store's own pruning policy) |
| `routing show` | `GET /api/routing` |
| `routing update '<json>'` | `POST /api/routing` |
| `eval tasks` | `GET /api/eval/tasks` |
| `eval run [--task ID] [--model A] [--max-steps N] [--no-save]` | `POST /api/eval/run` |
| `voice status` | `GET /api/voice/status` |
| `voice stt "text"` | `POST /api/voice/stt` |
| `voice tts "text"` | `POST /api/voice/tts` |
| `mcp tools` (default) | `POST /mcp` (initialize + `tools/list`) |
| `mcp ls` / `mcp add <preset>\|--json '<spec>'` / `mcp remove <name>` | `GET`/`POST /api/mcp/clients` (+ `/remove`) |
| `mcp reload` / `mcp local-file <path>` | `POST /api/mcp/reload` / `POST /api/mcp/local-file` |
| `acp server <method> '[params]'` | `POST /api/acp` |
| `acp connect <name> <url> [--token T]` | `POST /api/acp/connect` |
| `acp list` | `GET /api/mcp/clients` |

```bash
python3 forge.py checkpoints create "prima del refactor" --session demo
python3 forge.py checkpoints rollback cp_71cf8545
python3 forge.py routing show
python3 forge.py eval tasks
python3 forge.py voice tts "ciao dal DGX"
python3 forge.py mcp ls           # configured MCP clients + live connection state
python3 forge.py mcp tools        # tools the harness itself exposes over MCP
python3 forge.py acp list         # ACP/MCP clients as the server sees them
```

### Marketplace

Five kinds, and `--kind` takes any of them: `plugin` (a bundle whose members are `skill`, `mcp` or
`connector` entries, each installed by the store that owns it), `skill`, `mcp`, `connector`, and
`matrix` (an in-process Matrix module — it ships with the harness and is never installable).

| Command | Endpoint | Notes |
|---|---|---|
| `market ls [--kind K] [--category C] [--source S] [--q TEXT] [--limit N] [--offset N]` | `GET /api/market/catalog` | `source` is a catalogue ORIGIN (`bundled`, `local`, `imported:mcp-registry`, `imported:clawhub`); a trailing `:` is a prefix. Prints area, origin and `matched N` |
| `market sources` | `GET /api/market/sources` | each adapter with its age, its item count, its cost wording and the running job |
| `market status` | `GET /api/market/sync/status` | the ONE background job: pages, rows_seen, items, skipped, capped, error |
| `market sync [--source S] [--limit N] [--wait]` | `POST /api/market/sync` | starts the job; `--wait` follows it to the end (a full registry pass is minutes) |
| `market remote <query> [--source S] [--limit N]` | `GET /api/market/remote` | live search; the rows are PREVIEWS and carry no digest |
| `market import <source> <slug>` | `POST /api/market/import-remote` | pins one row's digest, writes it into that source's group, then installs it |
| `market install <id> [--overwrite]` | `POST /api/market/install` | the same digest-gated install the page uses |
| `market installed` | `GET /api/market/installed` | the install RECORD with its catalogue label |
| `market rm <id> [--files]` | `DELETE /api/market/installed/<id>` (`?files=1`) | removes the record; `--files` also removes what THAT install created — a plugin's skills and MCP servers, while a pre-existing one stays |
| `market plugin-scan` | `GET /api/market/plugin-scan` | Trae / Claude / OpenClaw packages found on this machine, converted but not installed |
| `market plugin-add <path\|url> [--overwrite]` | `POST /api/market/plugin-import` | converts one package (a local directory or an https ZIP) into its skill + MCP members, installs it, and ACTIVATES the servers: each one is enabled and verified in the same call. A connector waits for its key; a server that cannot start is reported with its own stderr, not rolled back |

```bash
python3 forge.py market sources                                   # is the mirror current?
python3 forge.py market ls --category "Research & Analysis" --limit 15
python3 forge.py market sync --source mcp-registry --wait         # full registry mirror
python3 forge.py market remote research --limit 10                # live ClawHub search
python3 forge.py market import clawhub research-helper            # pin that one, then install
python3 forge.py market installed
python3 forge.py market plugin-scan                               # what other harnesses installed here
python3 forge.py market plugin-add ~/.trae/plugins/trae-remote-official/pdf-monster/0.1.0
```

A remote row is **not** installable until it is pinned: `market install skill/<slug>` answers
`unknown item` for a row that was only searched.

---

## 3. Full endpoint coverage

Every route `forge.py` calls is listed below, and `v588` pins that each one exists on the server
under the same HTTP method — a renamed route fails the battery, not the first terminal run.
Coverage is **not** total: of the 182 `/api/*` route literals in the four route files, the CLI calls
94. The rest are WebUI-only surfaces (the config editors, the artifact and filesystem browsers, the
architect / improvement / cost panels, and the marketplace's single-item plus `/api/skills` and
`/api/connectors/*` views). The marketplace's operator actions ARE covered (see §2). Adding a verb
for a WebUI-only route is a deliberate change with its own test, not a missing line in this table.

**Document surface** (shared by the WebUI, the CLI and the agent's `docs` tool):
`GET /api/slash` (the `/` catalogue), `GET /api/docs` (the active plan/spec
document), `POST /api/docs/{plan,spec,approve,implement,reject,unlock}`. One
backend (`plan/docs.py`), no per-surface policy; the composer's `/plan`·`/spec`
are aliases of the same verbs.

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
| GET | `/api/sessions/new` | `sessions new --workspace DIR` (the WebUI first-open route) |
| GET | `/api/docs` | `docs status` |
| GET | `/api/history` | `sessions history`, `sessions card HANDLE` (`?card=<handle>` returns that one card) |
| GET | `/api/eval/tasks` | `eval tasks` |
| GET | `/api/voice/status` | `voice status` |
| GET | `/api/tools` | `tools ls` |
| GET | `/api/tools/running` | `tools running` |
| GET | `/api/hooks` | `hooks` |
| GET | `/api/sandbox` | `sandbox` |
| GET | `/api/approvals` | `approvals ls` |
| GET | `/api/approvals/<id>` | `approvals show` |
| GET | `/api/events` | `events` |
| GET | `/api/agent/runs` | `runs ls` |
| GET | `/api/agent/runs/<id>` | `runs show` |
| GET | `/api/runs` | `runs summary` |
| GET | `/api/runs/<id>/trace` | `runs trace` |
| GET | `/api/sessions/<id>/graph` | `sessions graph` |
| GET | `/api/sessions/<id>/trace-tree` | `sessions tree` |
| GET | `/api/memory` | `memory search` |
| GET | `/api/mcp/clients` | `acp list` |
| GET | `/api/subagent` | `subagent status` |
| GET | `/api/meta` | `meta status` / `meta best` |
| GET | `/api/blackboard` | `blackboard get` |
| GET | `/api/blackboard/watch` | `blackboard watch` |
| GET | `/api/checkpoints` | `checkpoints ls` |
| GET | `/api/checkpoints/<id>` | `checkpoints show` |
| GET | `/api/routing` | `routing show` |
| GET | `/api/knowledge/status` | `knowledge status` |
| GET | `/api/knowledge/notebooks` | `knowledge notebooks` |
| GET | `/api/knowledge/sources` | (source list for a notebook) |
| GET | `/api/knowledge/search` | `knowledge search` |
| GET | `/api/research/model` | `research ls` / `research active` |
| GET | `/api/codebase/status` | `index status` |
| GET | `/api/codebase/search` | `index search` |
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
| POST | `/api/sessions/<id>/fork` | `sessions fork` |
| POST | `/api/sessions/<id>/counterfactual` | `sessions counterfactual HANDLE --arg k=v` (one read-only call re-executed with one fact changed) |
| POST | `/api/sessions/<id>/counterfactual/model` | `sessions model-counterfactual INDEX --content "text"` (one stored message replaced; the model re-asked, nothing executed; `-1` = last intervenable message; verdict `same-action`/`different-action`/`no-action`) |
| POST | `/api/docs/plan` | `docs plan` |
| POST | `/api/docs/spec` | `docs spec` |
| POST | `/api/docs/approve` | `docs approve [--implement]` |
| POST | `/api/docs/implement` | `docs implement` |
| POST | `/api/docs/reject` | `docs reject` |
| POST | `/api/docs/unlock` | `docs unlock` |
| POST | `/api/eval/run` | `eval run` |
| POST | `/api/voice/stt` | `voice stt` |
| POST | `/api/voice/tts` | `voice tts` |
| POST | `/api/tools` | (a web/operator write — no CLI verb; refused when the body carries a session) |
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
| POST | `/api/knowledge/notebooks` | `knowledge create` |
| POST | `/api/knowledge/sources` | `knowledge add` |
| POST | `/api/knowledge/discover` | `knowledge discover` |
| POST | `/api/knowledge/import` | `knowledge import` |
| POST | `/api/knowledge/research` | `knowledge research` |
| POST | `/api/research/model` | `research set` |
| POST | `/api/codebase/build` | `index build` |
| POST | `/api/embedding/active` | `embedding set` |
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
| GET | `/api/market/catalog` | `market ls` |
| GET | `/api/market/sources` | `market sources` |
| GET | `/api/market/sync/status` | `market status` |
| POST | `/api/market/sync` | `market sync` |
| GET | `/api/market/remote` | `market remote` |
| POST | `/api/market/import-remote` | `market import` |
| POST | `/api/market/install` | `market install` |
| GET | `/api/market/installed` | `market installed` |
| DELETE | `/api/market/installed/<id>` | `market rm` |

---

## 4. Streaming (SSE) commands

These connect to a `text/event-stream` and print until `Ctrl-C` / completion:

* `chat "msg" --stream` — the turn as the chat renders it: the model's text,
  reasoning on the `think` channel, and the render events
  `→ tool args` / `← result` / `[harness:kind] note` / `[approval] tool id` /
  `[plan] …` / `[verify] …`. The server sends them on this same stream
  (`httpapi.chat_stream_gen` passes `_emit` to `chat_once`), so the terminal sees
  what the WebUI card stack shows.
* `agent "goal"` — `agent.iteration`, `agent.thought`, `agent.observation`,
  `agent.finish`.
* `feed` — the loopback event feed (`backlog` + live events), all sessions.
* `blackboard watch` — new blackboard entries.

### 4.1 Reading the flow afterwards (no streaming)

| Question | Command |
|---|---|
| what was said, full text | `sessions history <ID\|AX> --full` |
| what tools ran, with args and output | same `--full` (cards section), or `events --session <SID> --kind tool.result` |
| what the harness injected (nudges, gates) | `events --session <SID> --kind harness.inject` |
| why it failed | `sessions tree <ID\|AX>` |

`events` prints newest first and truncates each payload at 140 chars; `--full` does not
truncate the transcript. Use `events` to locate, `--full` to read.

### 4.2 Following a turn that was started somewhere else

A turn started by the WebUI, a job, a routine or another terminal keeps running when
your client disconnects — the CLI never re-attaches by itself. The two endpoints the
WebUI uses work from `curl` too (token in `~/.longrun/config/env`):

```bash
# is anything running right now? (the same gate before a restart)
curl -s -H "Authorization: Bearer $LONGRUN_TOKEN" http://127.0.0.1:8790/api/chat/live
# {"active": ["<SID>", …]}  ->  follow that turn from its durable log
curl -N -s -H "Authorization: Bearer $LONGRUN_TOKEN" \
  "http://127.0.0.1:8790/api/chat/attach?session=<SID>"
```

`attach` replays the turn's events (`chat.delta`, `tool.call`, `tool.result`,
`harness.inject`, approvals, plan/verify) and then tails new ones until `done`, so a
reconnected client shows exactly what a turn begun in that tab would show.

---

## 5. Notes

* `forge.py` never talks to the model directly — it only calls the REST API. The
  same policy (compaction, routing, approvals) applies as in the WebUI/app.
* `models ensure` and `eval run` can be slow (model load / multiple turns).
* Add a shell alias for convenience:
  `alias forge='python3 /home/jagones/Repositories/MyRepos/longrun/forge.py'`.

---

## 6. Live test recipe — sessions and documents, end to end

The one recipe to run after touching `forge.py`, the session routes or `/api/docs*`:
it exercises **every** session and document verb against a real running service, in
order, on a throwaway session and workspace. It is the executable twin of
`.agent/trash/cli_session_probe.py` (22/22 on 2026-11-16); the deterministic twin is
`tests/acceptance/v785_cli_command_cases.py` M1–M16 + `v1052`.

**Runtime changes:** this recipe proves the CLIENT. Before it, the service must run the code
under test — project rules §"After every codebase change the testing head verifies it" owns
the gate: battery on the final tree, idle restart, `ActiveEnterTimestamp` newer than the
newest `src/`/`webui/` mtime, and another restart if any source file changed afterwards.
A recipe that passes against a stale process proves the stale process.

```bash
#!/usr/bin/env bash
# Live smoke: sessions + documents through the CLI only. Fails loudly on the first red.
set -euo pipefail
cd /home/jagones/Repositories/MyRepos/longrun
forge(){ python3 forge.py "$@"; }
step(){ printf '\n── %s\n' "$*"; }
need(){ grep -q -- "$2" <<<"$1" || { printf 'FAIL: %s\n%s\n' "$3" "$1"; exit 1; }; }

# 0. Isolate: a throwaway pointer + workspace. Your real current session and the repo stay untouched.
export LONGRUN_CLI_STATE="$(mktemp -d)/cli_session.json"
WS="$(mktemp -d)"

# 1. Create: prints the id AND makes it current.
step "sessions new"
OUT=$(forge sessions new "cli smoke" --workspace "$WS"); echo "$OUT"
SID=$(grep -o '"id": "[0-9a-f]*"' <<<"$OUT" | cut -d'"' -f4); [ -n "$SID" ] || { echo "FAIL: no id"; exit 1; }

# 2. The pointer, and use = the same validation a switch runs.
step "sessions current / use"
[ "$(forge sessions current)" = "$SID" ] || { echo "FAIL: pointer not set"; exit 1; }
forge sessions use "$SID"

# 3. A turn lands in THAT session and prints its address (the defect this recipe was born from).
step "chat (no --session)"
OUT=$(forge chat "Reply with exactly PONG"); echo "$OUT"
need "$OUT" "^session: $SID$" "the turn did not land in the current session"
need "$OUT" "PONG" "no reply"

# 4. --new: a fresh session on demand; then come back to the probe one.
step "chat --new, then sessions use"
forge chat "second" --new
forge sessions use "$SID"

# 5. Look inside — no id anywhere: everything reads the current session.
step "history / tree / graph / context / ls"
forge sessions history          # every turn, role by role
forge sessions tree             # stage→step tree + the first failed step
forge sessions graph            # the plan/todo graph as JSON
forge context show              # tokens, pct, what the model actually sees
forge sessions ls               # the current row is marked with * and shows "N msg"

# 6. A plan: written under $WS/.longrun/documents/plans/, recorded, session LOCKED.
step "docs plan + status"
forge docs plan "Add a health endpoint that returns the build sha"
OUT=$(forge docs status); echo "$OUT"
need "$OUT" "plan_mode=True" "the plan did not lock the session"
need "$OUT" "status=proposed" "the plan is not proposed"

# 7. Approve the CONTENT, then authorise the IMPLEMENTATION (two decisions).
step "docs approve + docs implement"
forge docs approve
OUT=$(forge docs status); echo "$OUT"
need "$OUT" "plan_mode=True" "approve alone must NOT release the gate"
need "$OUT" "status=approved" "the decision was not recorded"
forge docs implement
OUT=$(forge docs status); echo "$OUT"
need "$OUT" "plan_mode=False" "implement did not release the gate"
need "$OUT" "implement=True" "the authorisation was not recorded"

# 8. A spec: THREE files (spec.md, tasks.md, checklist.md) and the lock again.
step "docs spec"
forge docs spec "Tiny uptime route with a test plan"
forge docs status               # kind=spec + the three paths

# 9. Reject: recorded, gate released, the files stay.
step "docs reject"
forge docs reject
OUT=$(forge docs status); echo "$OUT"
need "$OUT" "plan_mode=False" "reject did not release the gate"

# 10. Abandon: generate, then unlock — the record is dropped, the file stays on disk.
step "docs unlock"
forge docs spec "One more, abandoned mid-way"
forge docs unlock
OUT=$(forge docs status); echo "$OUT"
need "$OUT" "plan_mode=False" "unlock did not release the gate"

# 11. Delete: the pointer follows (a rm of ANOTHER session would keep it).
step "sessions rm"
forge sessions rm "$SID"
forge sessions current          # -> none — run `sessions new` or `sessions use ID`
```

What each step pins:

| Step | Proves |
|---|---|
| 1–2 | `sessions new` returns a real id and makes it current; `use` validates before switching |
| 3 | a bare `chat` writes to the **current** session and prints `session: <id>` — never an anonymous row |
| 4 | `--new` still gives a one-shot fresh session; coming back is one `use` |
| 5 | history / tree / graph / context / ls read the current session when the id is omitted |
| 6–10 | the seven document verbs: `plan` and `spec` write + lock, `status` reads, `approve` decides the content (gate stays closed), `implement` opens it, `reject`/`unlock` release |
| 11 | deleting the current session clears the pointer instead of leaving a dead id |

Traps this recipe is built to catch (each one was a real defect):

* **An empty session is not a chat bug.** `messages: []` means no turn was ever sent
  to that id. Step 3 is the guard: the id is printed and it is current, so a turn
  cannot silently land elsewhere.
* **Never wrap `chat` in `timeout N`.** Closing the client socket makes the server
  abort the turn (`httpapi.watch_client`). Use `--stream` to watch, `control abort`
  to stop.
* **A document write refuses while a turn runs in that session** (`error: a chat turn
  is running…`, exit 1) and a second generate is refused while the first is still
  working. Wait, then retry — do not force it.
* **`docs plan` costs one model call (~10 s), `docs spec` about three (`~2–4 min`).**
  A red `timeout` here is almost always the model, not the CLI: read the message.
* **The files land in `<workspace>/.longrun/documents/`** (`plans/…md`,
  `specs/<slug>/{spec,tasks,checklist}.md`), i.e. under the throwaway `$WS` above —
  never in the repo when you follow the recipe.
* **One pointer per machine.** Two CLIs in parallel share the last value; use a
  distinct `LONGRUN_CLI_STATE` per job (as step 0 does).

