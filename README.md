<p align="center"><img src="assets/icon.svg" alt="Longrun" width="112" height="112"></p>

<img src="assets/banner.svg" alt="Longrun — the agent harness built to DRIVE the LLM" width="100%">

[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab.svg?logo=python&logoColor=white)](https://www.python.org/)
[![deps](https://img.shields.io/badge/deps-stdlib%20%2B%20PyYAML-brightgreen.svg)](#install--run)
[![tests](https://img.shields.io/badge/battery-203%2F203%20green-success.svg)](#the-quality-gate)
[![CI](https://github.com/jagones84/longrun/actions/workflows/ci.yml/badge.svg)](https://github.com/jagones84/longrun/actions/workflows/ci.yml)

**Longrun is a single agent harness — one engine that drives one LLM
extremely well.** Disciplined context, a real tool loop, evidence-gated task
tracking, verifier gates. **Then it runs that same harness as a team**: every
*session* it already runs **is** an agent — its own tools, skills, plan, memory
and transcript — and you **orchestrate those sessions as an org chart** (teams,
jobs, subjobs, todos). The coordinator delegates; the team executes in enforced
dependency order; the master synthesises the result.

> **Local-first · stdlib-only core (Python 3.10+) · one pure-Python dependency (PyYAML)**
> for the shipped YAML configs. One codebase runs on
> **Linux x86_64**, **Linux arm64/aarch64** (NVIDIA **DGX Spark** / GB10 Grace Blackwell,
> Ubuntu 24.04) and **Windows 10/11 (x64)**.

---

## Why Longrun

|  | Longrun |
|---|---|
| **One LLM, driven hard** | Context is *bounded* (tool-output offload, budget = the model's real window, auto-compact), not dumped. The model plans inline, acts with real tools, and closes steps **with evidence**. |
| **TEAMS of meta-agents** | A 5-level object model — Team → Job → Subjob → Agent → Todo — with a coordinator that decomposes a goal and hands **dependencies** to the team. |
| **Order is enforced** | `(after AX)` dependencies become a real DAG. A dependent agent does **not** start until its prerequisites finish. |
| **Nothing is closed as fake-done** | A step can only reach `done` with evidence; a worker that fails is marked **failed**, the job becomes **partial**, and the coordinator is *told* — it can't pretend success. |
| **It drives ANY model** | Local `llama.cpp` (Linux x86_64/arm64 + Windows), vLLM, OpenRouter, DeepSeek, OpenAI, Anthropic, Google — one `<provider>:<model>` reference, automatic fallback chain. |
| **Safe by construction** | Allowlist registry + per-action approval gate + a real sandbox (`docker`/`bwrap`/`nsjail`, `--network none`) so the agent never touches the host. |
| **Observable end to end** | Every delta, thought, tool call, delegation and todo change is streamed over SSE and persisted — you can *watch* the team work. |

**A single harness — not a "meta-harness".** A meta-harness is a collector that
orchestrates *other* harnesses; Longrun has **one** engine. The agents it
orchestrates are simply *its own sessions*, organised into teams and an org chart
you can inspect and re-wire.

---

## The core idea: meta-agents in TEAMS

One clean object model, five levels, from a business goal down to a single checklist item:

```
T1  Team        ── a symbol + a roster (e.g. 🚀 Startup MVP Build)
└─ J12 Job      ── a goal given to a coordinator
   └─ J12.1 Subjob ── one assignment, bound to ONE agent, with deps (J12.1 → J12.2 …)
      └─ A25 Agent ── IS a session: its own harness, tools, skills, memory, chat
         └─ A25.n3 Todo ── a step, closable only with evidence
```

1. You give a **goal** to a **coordinator** (`POST /api/jobs {goal, assignee}`).
2. The coordinator's **plan turn is plan-only**: it reads the workspace, consults a
   skill if useful, records the plan, and **stops** — it cannot do the team's work.
3. The harness splits the plan into **subjobs**, enforces the declared `(after AX)`
   order, and runs the workers wave by wave.
4. Each worker runs a **full harness turn** — real tools, real skills, real files.
5. The coordinator receives the team report (with any **unfinished subjobs flagged**)
   and produces the final deliverable.

Teams can be seeded from an org chart, and **every team is scoped**: pick a team and
the orchestrator board, the chats, the constellation and the model policy all switch
to that team. A team is capped to **one local model per machine**; the rest use cheap
cloud models, and the strongest (still cheap) cloud goes to the leads.

---

## Feature highlights

**Harness (drives one LLM)**
- 💬 Streaming chat with a visible **Chain-of-Thought** timeline (`reasoning_content` / `<think>`).
- 🧩 **LLM-authored, evidence-gated task graph** — the model writes its own todos inline; `done` requires proof.
- 🔁 **Completion loop** with typed stops (`goal_reached · no_progress · budget · blocked`) — the list decides when work is done, not the model's mood.
- 🛠️ **Real tools**: `shell`, `fs.read/write/edit`, `git`, `http`, `web`, `memory`, `skills`, `sessions` (inspect another session's transcript), `chapters` (this session's thread outline — recall it across compactions), MCP tools — all through the approval gate.
- 🧠 **Memory** (store/recall/recent) auto-injected each turn; ⚠️ **checkpoints** + rollback.
- 📏 **Honest context meter** — the real prompt vs the model's real window (a **donut** breakdown by section), auto-compaction at 75%.
- 💰 **Live cost panel** — the provider's REAL per-call token usage priced per 1M: a running session total plus **one row per API call**. `↻ prices` pulls OpenRouter's public catalogue (no key); a local model reads as *unpriced*, never a fake zero.
- ▶️ **HITL** pause/resume/abort; ⏹️ Stop kills the actual tool process, not just the socket.

**Orchestration (drives a team)**
- 🗂️ **Teams · Jobs · Subjobs · Agents · Todos** — the object model above, first-class.
- 🧑✈️ **Plan-only coordinator turn** (read-only): the master plans, the workers execute.
- 🔗 **Enforced dependency waves** — a dependent subjob waits for its prerequisites.
- 🧾 **Bounded retry + escalation** — a `STATUS: BLOCKED` worker is retried a bounded number of times, then marked **failed** and surfaced to the master.
- 📡 **Both chats carry the hand-off** — the delegation appears in the coordinator's transcript *and* the worker's.
- 🔎 **Teammate inspection** — the master reads any teammate's full transcript (`sessions` tool: list → read) to understand *why* one is failing and help it.
- 🎛️ **Model policy per team** — ≤1 local/machine, cheap cloud for members, best cheap cloud for leads.
- 🧬 **Subagents** (in-loop delegation), **swarm/blackboard**, **ACP** interop — experimental.

**Interfaces**
- 🖥️ **Sessions** (`/`) — dark glassmorphism, live CoT, task graph, sessions labelled with their team.
- 🛰️ **Control** (`/orbit`) — the mission-control deck: **org chart, live constellation, job create/dispatch, team selector, model policy**, one column, mobile-style.
- ⌨️ **CLI** (`forge.py`) and a **mobile-ready HTTP API** — command the DGX from your phone over Tailscale.
- 🔌 **Bidirectional MCP** — use Longrun *from* any MCP client, and connect *external* MCP servers as native tools.

All views share one theme — pick **Indigo / Dark / Midnight / Forest / Sand / Sepia** in ⚙ → Appearance (six eye-saver palettes).

---

## Install & run

**Requirements:** Python **3.10+**, plus **PyYAML** (pure-Python — no compiler, no
wheels) to read the shipped `config/*.yaml`. Nothing else: the core
(`src/longrun/`) imports only the standard library, and every heavier extra
(`numpy`, `sentence_transformers`, OpenTelemetry, `psutil`, the voice stack) is
optional and lazily guarded. The tool allowlist stays **fail-closed**: if PyYAML is
missing while `config/tools.yaml` exists, the harness refuses to start rather than
run with an unverified policy. You need an LLM: a local **llama.cpp router**
(default `http://127.0.0.1:8080`) or a cloud key in `.env`
(OpenRouter / DeepSeek / OpenAI / Anthropic / Google).

### Platforms

| Platform | Architecture | Status | Launcher |
|---|---|---|---|
| **Windows 10/11** | x64 | ✅ verified | `run.ps1` |
| **Linux** (Ubuntu 22.04+ & similar) | x86_64 | ✅ supported | `run.sh` |
| **Linux — NVIDIA DGX Spark** (GB10 Grace Blackwell, Ubuntu 24.04) | **arm64 / aarch64** | ✅ verified | `run.sh` |

The core is **pure stdlib** (PyYAML is its only third-party import, and it is
pure-Python), so there are no compiled wheels to build — any OS/architecture
with **CPython 3.10+** runs it identically. The only OS-specific code lives in one place,
[`src/longrun/util/osutil.py`](src/longrun/util/osutil.py): shell spawn
(`/bin/sh -c` ↔ `cmd /c`), process-tree kill (`SIGTERM/SIGKILL` ↔ `taskkill /T /F`) and
`PATH`/`PATHEXT` resolution (`npx` ↔ `npx.cmd`).

```bash
git clone https://github.com/jagones84/longrun && cd longrun
cp .env.template .env          # keys stay local (gitignored) — never commit them
./run.sh                       # WebUI + API on http://127.0.0.1:8790
./run.sh --host 0.0.0.0        # expose on the Tailscale/LAN IP for your phone
```

**Windows 10/11 (x64, native, no WSL):**

```powershell
git clone https://github.com/jagones84/longrun; cd longrun
Copy-Item .env.template .env
.\run.ps1                      # WebUI + API on http://127.0.0.1:8790
```

**Interpreter & dependencies — read this once.** The app runs on whatever `python3`
`run.sh` / the service resolves to (the **system** interpreter, by design): the core is
stdlib-only + **PyYAML**. `requirements.txt` lists the **optional** extras (e.g.
`docling` for rich document ingestion). There is **no bundled virtualenv** — install the
extras with **`pip install --user`** so the running interpreter sees them without
touching system packages (install for *that same* interpreter: a venv's packages are
invisible to it). On a PEP-668 host:

```bash
python3 -m pip install --user -r requirements.txt     # optional runtime extras
```

Dev tooling (pytest / mypy / ruff / mutmut …) is optional too, in
`requirements-dev.txt`; `tests/mega_test.sh` installs it into a throwaway venv under
`$TMPDIR` so nothing pollutes the repo or the system:

```bash
python3 -m pip install --user -r requirements-dev.txt   # or just run tests/mega_test.sh
```

Open **`http://127.0.0.1:8790`** for the **Sessions** view, or
**`http://127.0.0.1:8790/orbit`** for the mission-control deck (**Control**).

**Token — optional, recommended.** There is **no token by default**: every route is
open. That is fine on localhost, but risky once you expose the port on LAN/Tailscale.
To require one, start with `--token <your-token>` (any string you choose; the always-on
service reads `LONGRUN_TOKEN` from its env file instead). With a token set, every
request needs it: the WebUI takes it from the URL (`?token=<your-token>`), the CLI and
the raw API from the header `Authorization: Bearer <your-token>`. You never have to
build the URL by hand — **the server prints the ready WebUI URL, token included, at
startup** (see below).

**Always-on (Linux, systemd user unit):**

```bash
cp deploy/longrun.service ~/.config/systemd/user/
systemctl --user enable --now longrun.service
```

### Mobile — open on your phone (installable as an app)

The WebUI is an installable **PWA**: expose the server, open it once on the phone,
then "Add to Home screen".

1. Start bound to all interfaces, with a token:
   ```bash
   ./run.sh --host 0.0.0.0 --token <your-token>
   ```
2. Copy the ready URL the server prints at startup — it already carries the LAN IP
   and the token:
   ```
   Open on your phone: http://192.168.1.37:8790/?token=<your-token>
   ```
   (Remote? use the Tailscale IP: `tailscale ip -4`.)
3. Open it on the phone and use the browser menu → **Add to Home screen**
   (Android Chrome) or **Share → Add to Home Screen** (iOS Safari). The icon opens
   the harness already authenticated.
4. Over plain HTTP this is a home-screen **shortcut**; over **HTTPS** (e.g.
   `tailscale serve`) it is a full installable PWA.

> The icon **name** and **token** are captured at install time (manifest + `start_url`).
> After renaming the project or rotating `--token`, delete the old icon and reinstall.

> Sandbox is optional: install `docker`, `bubblewrap` or `nsjail` for real isolation;
> otherwise shell commands run on the host and the topbar shows `sandbox: none (!)`.

---

## API & integration

Everything the WebUI does is a plain HTTP call, so you can drive the harness from
any other tool, script or agent:

- **REST API** — `http://<host>:8790/api/*` (JSON). Gated by `Authorization: Bearer
  <token>` when a token is set. [docs/CLI.md](docs/CLI.md) is the full endpoint
  reference: every route, with the matching CLI command.
- **MCP server** — register `mcp_server.py` with any MCP client (Claude Code, another
  harness, …) and the harness's tools become callable there; it forwards each call to
  the running instance over HTTP. Config snippet in the module docstring.
- **ACP** — `acp.py` lets an external agent drive sessions over the same API.
- **CLI** (`forge.py`) — a thin stdlib client over the *same* REST API (no duplicated
  logic): scripted/terminal control and a live reference for the endpoints.
- **WebUI / mobile** — the same API in the browser (see *Mobile*, above).

### Calling it from outside

**A call with no session id creates a NEW session for you** and returns its id — you
do not have to prepare anything:

```bash
curl -s -X POST http://127.0.0.1:8790/api/chat \
  -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' \
  -d '{"message":"hello"}'
# -> {"session":"ad499f57669e","run_id":"…","reply":"…","messages":4,"error":false}
```

**To target a specific session, pass it** — one id is one conversation/agent, so every
call with the same id reuses the same transcript, workspace and plan:

```bash
curl -s -X POST http://127.0.0.1:8790/api/agent/run \
  -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' \
  -d '{"goal":"fix the failing test","session":"my-run-42",
       "model":"deepseek:deepseek-chat","max_steps":8}'
```

Want to pin the workspace? Create the session up-front with
`POST /api/sessions {"title":"…","workspace":"/abs/path"}` (returns the id). Otherwise a
new session inherits the **global default workspace** (Settings ▸ workspace; default =
the repo root). "Designate" a session as an org agent with `POST /api/agents
{session,name,role,reports_to}` — a session *is* an agent.

### Run a benchmark, per task

Drive any benchmark by calling the agent loop once per task, each with its own session,
then score the reply:

```bash
# 1) the built-in gold tasks (eval/gold_tasks.json):
curl -s -X POST http://127.0.0.1:8790/api/eval/run -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' -d '{"model":"NEX","max_steps":8}'

# 2) your own (SWE-style): one POST /api/agent/run per instance,
#    with session="swe-<instance_id>", then read the result back:
curl -s 'http://127.0.0.1:8790/api/history?session=swe-django-1234&token=<token>'
curl -s 'http://127.0.0.1:8790/api/runs/<run_id>/trace?token=<token>'
```

---

## Two searchable stores: codebase index + knowledge base

There are **two separate stores**, different files and different lifetimes — do not
confuse them:

| Store | Scope | DB | Where |
|---|---|---|---|
| **Codebase index** | **per workspace** (per path, like project rules) | `data/codebase/<hash>.db` | right rail ▸ **Codebase** |
| **Knowledge base** | **global** (notebooks of sources) | `data/knowledge/knowledge.db` | **Settings ▸ Knowledge** |

Both live **outside the project** in the app data dir — the same convention VS Code /
Cursor use (`workspaceStorage` / `globalStorage`) — so nothing is ever written into
your repo. Retrieval is SQLite **FTS5** (`bm25()` + `snippet()`) — built into Python's
`sqlite3`, so it runs with **zero dependencies**.

- **Codebase index** — chunking is AST-aware for Python (one chunk per function /
  method / class) and heading/paragraph-aware for Markdown; a line window is the
  fallback. `.gitignore` and vendor dirs are skipped, rebuilds are incremental. Two
  workspaces have two fully isolated indexes. Query it with the **`index`** tool
  (`action=search|reindex|status`).
- **Knowledge base** — organised in **notebooks**; each notebook holds **sources**
  (a URL, a local file/folder, or pasted text). `discover` runs a **web search** and
  returns candidate URLs (NotebookLM-style); `import` feeds the ones you pick through
  the same ingestion pipeline into the chosen notebook. Query it with the **`knowledge`**
  tool (`action=search|list_notebooks|add_source|add_text|discover|import|status`).

### Use it
WebUI → **Settings ▸ Knowledge** (notebooks, sources, discover, search) and the right
rail ▸ **Codebase** (build/search the workspace). Or the CLI / API:

```bash
forge index build                       # rebuild THIS workspace's codebase index
forge index search "parse config"       # top chunks as path:line + snippet
forge knowledge notebooks               # list notebooks (global knowledge base)
forge knowledge add --notebook nb_x "https://docs.example.com/guide"
forge knowledge discover "kubernetes rollout strategies"
forge knowledge import --notebook nb_x "https://a.example,https://b.example"
```

```bash
curl -s -X POST http://127.0.0.1:8790/api/codebase/build -d '{"force":false}'
curl -s 'http://127.0.0.1:8790/api/codebase/search?q=parse+config&k=8'
curl -s 'http://127.0.0.1:8790/api/knowledge/notebooks'
curl -s -X POST http://127.0.0.1:8790/api/knowledge/discover -d '{"q":"kubernetes","n":5}'
curl -s -X POST http://127.0.0.1:8790/api/knowledge/import -d '{"notebook":"default","urls":["https://example.com"]}'
```

### Semantic (optional)
Keyword search needs no setup. To add **vector** search, set an embedding model in
**Settings ▸ Models ▸ Embedding model** (e.g. `openrouter:openai/text-embedding-3-small`),
or leave it empty for bm25-only. With a model configured, retrieval becomes hybrid
(bm25 + cosine, fused with Reciprocal Rank Fusion); the vector size is detected from
the first embed and stored in the same DB.

---

## The quality gate

The **only** regression gate is one deterministic, fully-isolated battery — it points
every `LONGRUN_*` data dir at a throwaway temp dir, so it never touches live state:

```bash
bash tests/battery.sh                          # fast gate (heavy tests skipped) → 197/197 GREEN
LONGRUN_BATTERY_FULL=1 bash tests/battery.sh   # full suite (adds the 6 heavy index/ingestion tests) → 203/203 GREEN
LONGRUN_BATTERY_TIMINGS=1 bash tests/battery.sh # optional: print the 10 slowest tests
```

The 6 tests that build real vector indexes / run document ingestion are **skipped by
default** so the gate stays quick, and the suite runs in **parallel** (each test gets
its own throwaway data dirs) — the fast gate is ~12s, the full suite ~1min. Default
parallelism is capped at 12 workers on the DGX; `LONGRUN_BATTERY_JOBS` overrides it. Set
`LONGRUN_BATTERY_FULL=1` to include the heavy tests; CI always runs the full suite.

CI runs the same battery on every push/PR ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).
For the *live* seams (reload, session swap, swap-during-run, long tasks) see
[docs/TESTING-PLAYBOOK.md](docs/TESTING-PLAYBOOK.md).

---

## Documentation

| Doc | What |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | how the harness is wired (v1.0.0) |
| [docs/CLI.md](docs/CLI.md) | every CLI command + endpoint |
| [docs/TESTING-PLAYBOOK.md](docs/TESTING-PLAYBOOK.md) | how to hunt real bugs live |
| [AGENTS.md](AGENTS.md) | orientation for an AI agent landing in the repo |
| [CONTRIBUTING.md](CONTRIBUTING.md) | how to contribute |
| [CHANGELOG.md](CHANGELOG.md) | release notes |

---

## License

© 2025–2026 Giovanni J. Agones ([jagones84](https://github.com/jagones84)).
Licensed under **AGPL-3.0** — see [LICENSE](LICENSE).

If Longrun is useful to you, ⭐ star the repo — it helps others find it.
