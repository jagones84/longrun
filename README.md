<p align="center"><img src="assets/icon.svg" alt="Longrun" width="112" height="112"></p>

<img src="assets/banner.svg" alt="Longrun — the agent harness built to DRIVE the LLM" width="100%">

[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab.svg?logo=python&logoColor=white)](https://www.python.org/)
[![deps](https://img.shields.io/badge/deps-stdlib%20%2B%20PyYAML-brightgreen.svg)](#install--run)
[![tests](https://img.shields.io/badge/battery-208%2F208%20green-success.svg)](#the-quality-gate)

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

## Quick start

**Windows 10/11:** install [Git](https://git-scm.com/download/win) and
[Python 3.10+](https://www.python.org/downloads/windows/) (enable **Add python.exe to PATH**),
then run these in PowerShell:

```powershell
git clone https://github.com/jagones84/longrun
cd longrun
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
```

That one launch command installs PyYAML if needed, starts Longrun, and opens the
WebUI at **http://127.0.0.1:8790/**. Press **Ctrl+C** in the launcher window to stop.

On first launch, choose a server token in the security panel when it appears. Then
open the WebUI's top-right **Settings → Keys** and set `OPENROUTER_API_KEY`.
Create an OpenRouter account at
[openrouter.ai](https://openrouter.ai/), then create a key at
[OpenRouter API Keys](https://openrouter.ai/settings/keys). Longrun saves it in the
gitignored `.env`; no config-file editing or restart is needed.

The server token and OpenRouter API key are different: the token protects Longrun;
the API key pays for / authorizes model calls. If Keys reports that the browser
token is unauthorized, replace it in the **Longrun token** field at the top of
that page and click **save**. See [Install & run](#install--run) for exact defaults,
other optional keys, MCP, and skill installation.

---

## Why Longrun

|  | Longrun |
|---|---|
| **One LLM, driven hard** | Context is *bounded* (tool-output offload, budget = the model's real window, auto-compact), not dumped. The model plans inline, acts with real tools, and closes steps **with evidence**. |
| **TEAMS of meta-agents** | A 5-level object model — Team → Job → Subjob → Agent → Todo — with a coordinator that decomposes a goal and hands **dependencies** to the team. |
| **Order is enforced** | `(after AX)` dependencies become a real DAG. A dependent agent does **not** start until its prerequisites finish. |
| **Nothing is closed as fake-done** | A step can only reach `done` with evidence; a worker that fails is marked **failed**, the job becomes **partial**, and the coordinator is *told* — it can't pretend success. |
| **It drives ANY model** | Local `llama.cpp` (Linux x86_64/arm64 + Windows), vLLM, OpenRouter, DeepSeek, OpenAI, Anthropic, Google — one `<provider>:<model>` reference, automatic fallback chain. |
| **Safe by construction** | Allowlist registry + per-action approval gate; opt into a real sandbox (`docker` / `bubblewrap` / `nsjail`, network toggle) so commands can run isolated from the host. With no backend installed the topbar says `no sandbox`. |
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
- 📏 **Honest context meter** — the real prompt vs the model's real window (a **donut** breakdown by section), auto-compaction at 70% (settable in the Context panel).
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
- 🖥️ **Sessions** — a tab of the one WebUI page: dark glassmorphism, live CoT, task graph, sessions labelled with their team.
- 🛰️ **Control** — the other tab of that same page: **org chart, live constellation, job create/dispatch, team selector, model policy**, one column, mobile-style.
- ⌨️ **CLI** (`forge.py`) and a **mobile-ready HTTP API** — command the DGX from your phone over Tailscale.
- 🔌 **Bidirectional MCP** — use Longrun *from* any MCP client, and connect *external* MCP servers as native tools.

All views share one theme — pick **Indigo / Dark / Midnight / Forest / Sand / Sepia** in ⚙ → Appearance (six eye-saver palettes).

---

## Install & run

**Requirements:** Git and Python **3.10+**. On Windows, install Python from
[python.org](https://www.python.org/downloads/windows/) and select **Add python.exe to PATH**.
The Windows launcher installs the required PyYAML dependency automatically.

### Windows

From PowerShell in the cloned repository:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
```

This launches the server and opens **http://127.0.0.1:8790/**. Leave the terminal
open; press **Ctrl+C** to stop. `-ExecutionPolicy Bypass` applies to this launch only;
it does not change the machine's PowerShell policy.

### First launch

> **Already running on a remote machine?** If Longrun is already running on a server
> (DGX Spark, VPS, LAN machine), skip the local launch. Open its IP directly — for
> example `http://100.102.61.23:8790/` (Tailscale) or `http://192.168.1.37:8790/`
> (LAN). The rest of these instructions apply the same way.

1. In **First-run security setup**, choose a Longrun server token. It is saved in the
   repo-root `.env` and remembered by this browser. **Continue without token** is for
   localhost-only use.
2. Open **Settings → Keys**. Create an account at
   [openrouter.ai](https://openrouter.ai/), create a key at
   [OpenRouter API Keys](https://openrouter.ai/settings/keys), then paste it into
   `OPENROUTER_API_KEY` and click **set**. OpenRouter may charge for model usage;
   check its model prices and account limits.
3. Start chatting. On a clean clone, no model weights or API keys are bundled or
   downloaded; the WebUI starts without a key, but LLM chat needs one working model.

The server token and provider API key are **not the same**. `LONGRUN_TOKEN` protects
Longrun's API; `OPENROUTER_API_KEY` authorizes model calls. For a new browser, enter
the server token when prompted. To rotate it, change the `LONGRUN_TOKEN` row in
**Settings → Keys**; this browser and the live server update immediately.

### Shipped model defaults

These tracked files are the defaults for a fresh clone; local user choices can
override them:

| Use | Shipped default |
|---|---|
| Global model | `openrouter:openrouter/auto` |
| Chat and agent | Prefer a local router model matching `qwen`; if none is available, use the global model above |
| Context summarizer | `openrouter:meta/muse-spark-1.3-contributor` |
| Subagent | `openrouter:z-ai/glm-5.3-flash`; fallback `openrouter:meta/muse-spark-1.3-contributor` |
| Team lead / member | `openrouter:z-ai/glm-5.3-flash` / `openrouter:deepseek/deepseek-v4-flash-0731` |
| Auto-compaction | Trigger at 70% context, target 30%, keep the last 4 turns |

All shipped cloud roles use OpenRouter. One `OPENROUTER_API_KEY` enables them; if
you choose another provider, set that provider's key and models in **Settings → Models**.
No local model server or weights are installed by Longrun.

### Secrets and local settings

**Settings → Keys** is the normal place to enter secrets; you do not need to edit a
file. Every value is written to `<repository>/.env` (for example,
`C:\Users\you\longrun\.env`), which is gitignored. `.env.template` is the committed
list of supported key names and explains their uses.

| Key | Needed for |
|---|---|
| `OPENROUTER_API_KEY` | Default chat and shipped cloud roles; recommended first key |
| `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` | Only if you select those direct providers |
| `TAVILY_API_KEY` or `BRAVE_API_KEY` | Optional paid web-search backends; keyless DuckDuckGo search remains available |
| `GITHUB_TOKEN` | GitHub tool or GitHub MCP server |
| `PERPLEXITY_API_KEY` | Perplexity research provider |
| `COHERE_API_KEY`, `VOYAGE_API_KEY`, `JINA_API_KEY` | Optional embedding providers |
| `VLLM_API_KEY` | Only when your local vLLM endpoint requires authentication |
| `LONGRUN_TOKEN` | Optional Longrun server/API protection; set during first-run setup |

Other environment variables referenced by an MCP server can also be added as rows
in **Settings → Keys**; they are saved to the same `.env`.

Non-secret defaults ship in `config/*.yaml`. Personal provider choices are stored in
`config/providers.local.yaml`; external MCP definitions in
`config/mcp_clients.local.json`; uploaded skills in `skills/local/`. These local
files are ignored by Git.

### Optional: MCP servers and skills

Neither is required for chat.

- **MCP:** install [Node.js](https://nodejs.org/) for catalog entries that use `npx`,
  then open **Settings → MCP → Catalog** and click **+ add**. GitHub needs
  `GITHUB_TOKEN` in **Settings → Keys**; Filesystem asks you to choose an absolute
  folder to expose. User server definitions are saved in
  `config/mcp_clients.local.json`.
- **Skills:** open **Settings → Skills → Install from zip**, choose a trusted skill
  `.zip`, and click **install**. User-installed skills go under `skills/local/`.

### Linux (x86_64 and ARM64 / DGX Spark)

The same procedure works on any Linux machine, including the NVIDIA DGX Spark
(GB10 Grace Blackwell, ARM64 / aarch64, Ubuntu 24.04):

```bash
git clone https://github.com/jagones84/longrun
cd longrun
python3 -m pip install --user PyYAML
./run.sh
```

Open **http://127.0.0.1:8790/**. Sessions and Control are tabs on this single page.
The default Linux launcher runs in the terminal; press **Ctrl+C** to stop.

### Always-on Linux service (including DGX Spark)

Before exposing the server on a network, set `LONGRUN_TOKEN` in `.env`. For a local
first-run setup, start `./run.sh`, open the WebUI on the machine, choose a token, then
stop it with Ctrl+C. The service reads the same repo-root `.env`, so WebUI changes
remain effective after a restart. On the DGX Spark the default unit paths already
match the recommended checkout location:

```bash
cp deploy/longrun.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now longrun.service
systemctl --user status longrun.service
journalctl --user -u longrun.service -n 30
```

The unit assumes the repository is at `~/Repositories/longrun`; edit its
`WorkingDirectory`, `ExecStart`, and `EnvironmentFile` paths if yours differs.
It binds `0.0.0.0:8790`, so do not start it on a reachable network without a token.

### Optional document ingestion

The WebUI and chat need no extras beyond the launcher's PyYAML bootstrap. For richer
PDF/Office extraction, install `docling` (large; downloads model weights) or the
lighter `markitdown` package using the same Python interpreter:

```bash
python3 -m pip install --user docling 'markitdown[pdf,docx,pptx,xlsx]'
```

To install every optional runtime package listed in `requirements.txt` instead:

```bash
python3 -m pip install --user -r requirements.txt
```

This includes both document extractors and is not needed for chat.

Without these packages, PDF and Office extraction uses `pdftotext`, OCR, and
LibreOffice when installed on the host.

### Mobile

Set the token from the local WebUI first. Then launch bound to the network:

```bash
./run.sh --host 0.0.0.0
```

Open the printed URL on your phone (or use the machine's Tailscale IP). The browser
will ask for the server token once. Sessions and Control are tabs of the same page.
Use **Add to Home screen** (Android Chrome) or **Share → Add to Home Screen** (iOS
Safari). Plain HTTP creates a shortcut; HTTPS (for example `tailscale serve`) enables
the full installable PWA. After token rotation, update the saved browser credential
and reinstall the home-screen icon if it still carries the old token.

> Sandbox is optional: install `docker`, `bubblewrap` or `nsjail` for real isolation
> (and switch it on in **Settings ▸ Tools & approvals**); otherwise shell commands run
> on the host and the topbar says `no sandbox`.

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
- **ACP** — `POST /api/acp` (JSON-RPC 2.0) lets an external agent drive sessions over
  the same API (`src/longrun/interop/acp.py`).
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
new session inherits the **global default workspace** (the Workspace panel's
*set as default for new sessions*; default = the repo root). "Designate" a session as
an org agent with `POST /api/agents {session,name,role,reports_to}` — a session *is*
an agent.

### Run a benchmark, per task

Drive any benchmark by calling the agent loop once per task, each with its own session,
then score the reply:

```bash
# 1) the built-in gold tasks (eval/gold_tasks.json):
curl -s -X POST http://127.0.0.1:8790/api/eval/run -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' -d '{"model":"NEX","max_steps":8}'

# 2) your own (SWE-style): one POST /api/agent/run per instance,
#    with session="swe-<instance_id>", then read the result back:
curl -s -H 'Authorization: Bearer <token>' \
  'http://127.0.0.1:8790/api/history?session=swe-django-1234'
curl -s -H 'Authorization: Bearer <token>' \
  'http://127.0.0.1:8790/api/runs/<run_id>/trace'
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
  tool (`action=search|list_notebooks|create_notebook|add_source|add_text|discover|import|status`).

### Use it
WebUI → **Settings ▸ Knowledge** (notebooks, sources, discover, search) and the right
rail ▸ **Codebase** (build/search the workspace). Or the CLI / API — the CLI reads
`LONGRUN_TOKEN` from the environment, and each `curl` needs
`-H 'Authorization: Bearer <token>'` when a token is set:

```bash
python3 forge.py index build                       # rebuild THIS workspace's codebase index
python3 forge.py index search "parse config"       # top chunks as path:line + snippet
python3 forge.py knowledge notebooks               # list notebooks (global knowledge base)
python3 forge.py knowledge add --notebook nb_x "https://docs.example.com/guide"
python3 forge.py knowledge discover "kubernetes rollout strategies"
python3 forge.py knowledge import --notebook nb_x "https://a.example,https://b.example"
```

```bash
curl -s -H 'Authorization: Bearer <token>' -X POST \
  http://127.0.0.1:8790/api/codebase/build -d '{"force":false}'
curl -s -H 'Authorization: Bearer <token>' \
  'http://127.0.0.1:8790/api/codebase/search?q=parse+config&k=8'
curl -s -H 'Authorization: Bearer <token>' \
  'http://127.0.0.1:8790/api/knowledge/notebooks'
curl -s -H 'Authorization: Bearer <token>' -X POST \
  http://127.0.0.1:8790/api/knowledge/discover -d '{"q":"kubernetes","n":5}'
curl -s -H 'Authorization: Bearer <token>' -X POST \
  http://127.0.0.1:8790/api/knowledge/import -d '{"notebook":"default","urls":["https://example.com"]}'
```

### Semantic (optional)
Keyword search needs no setup. To add **vector** search, set an embedding model in
**Settings ▸ Models ▸ Embedding · knowledge index** (e.g.
`openrouter:openai/text-embedding-3-small`), or leave it empty for bm25-only. With a
model configured, retrieval becomes hybrid (bm25 + cosine, fused with Reciprocal Rank
Fusion); the vector size is detected from the first embed and stored in the same DB.

---

## The quality gate

The **only** regression gate is one deterministic, fully-isolated battery — it points
every `LONGRUN_*` data dir at a throwaway temp dir, so it never touches live state:

```bash
bash tests/battery.sh                          # fast gate (heavy tests skipped) → 202/202 GREEN
LONGRUN_BATTERY_FULL=1 bash tests/battery.sh   # full suite (adds the 6 heavy index/ingestion tests) → 208/208 GREEN
LONGRUN_BATTERY_TIMINGS=1 bash tests/battery.sh # optional: print the 10 slowest tests
```

The 6 tests that build real vector indexes / run document ingestion are **skipped by
default** so the gate stays quick, and the suite runs in **parallel** (each test gets
its own throwaway data dirs) — the fast gate is ~12s, the full suite ~1min. Default
parallelism is capped at 12 workers on the DGX; `LONGRUN_BATTERY_JOBS` overrides it. Set
`LONGRUN_BATTERY_FULL=1` to include the heavy tests.

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
