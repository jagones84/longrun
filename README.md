<div align="center">

<img src="assets/banner.svg" alt="Longrun — the agent harness built to DRIVE the LLM" width="100%">

# Longrun

### The agent harness built to DRIVE the LLM.

[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab.svg?logo=python&logoColor=white)](https://www.python.org/)
[![deps](https://img.shields.io/badge/deps-stdlib%20%2B%20PyYAML-brightgreen.svg)](#quick-start-windows)
[![tests](https://img.shields.io/badge/battery-330%2F330%20tests-blue.svg)](#tests)

**Longrun is the self-hosted AI agent harness that drives the LLM — teams of
agents, real tools, and verification, on your own machine.** One Python process
serves a browser UI, an HTTP/SSE API, and a CLI. The runtime is stdlib-only
plus PyYAML: no framework to learn, no lock-in to any provider.

</div>

| | |
|---|---|
| **Teams of agents** | Dispatch work to teammates' own sessions — in parallel — or run coordinated jobs with dependency waves; subagents take ordered subtasks with their outputs wired in as input. |
| **Real tools, gated** | Shell, filesystem, git, web, browser, skills, memory, knowledge — every world-changing call passes an approval gate (auto / approve / deny), with sandboxed execution for the shell. |
| **Self-evolution** | The Matrix zone lets the harness extend itself live (tools, hooks, skills, rules); proven artifacts graduate into the protected Nucleus through verification gates. |
| **Memory that lasts** | Session memory, a per-workspace codebase index, a shared Knowledge Base, and one compaction policy for manual and automatic summarization. |
| **Honest costs** | Per-session model costs as exact provider charges, token-rate estimates, or explicitly unpriced calls — cached input included, attempts included. |
| **Deterministic quality** | Every behavior above is pinned by an isolated acceptance test (see the badge); the battery runs them all in seconds. |

---

## Table of Contents

- [Why Longrun](#why-longrun)
- [Quick start: Windows](#quick-start-windows)
- [What Longrun does](#what-longrun-does)
- [Self-evolution: Nucleus vs. Matrix](#self-evolution-nucleus-vs-matrix)
- [Quick start: Linux (x86_64 and ARM64)](#quick-start-linux-x86_64-and-arm64)
- [Model setup](#model-setup)
- [CLI](#cli)
- [API & integration](#api--integration)
- [Data and search](#data-and-search)
- [Tests](#tests)
- [Documentation](#documentation)
- [License](#license)

## Why Longrun

- **Self-hosted AI agent harness, local-first.** Everything the harness owns lives outside the checkout in one
  data home — a `git pull` can never eat your sessions, costs, or rules.
- **Provider-neutral.** OpenRouter, DeepSeek, OpenAI, Anthropic, Gemini, Ollama,
  llama.cpp, LM Studio, vLLM — switch with the model picker, no code changes.
- **Reproducible by construction.** The same battery that guards development
  (`tests/battery.sh`) pins every user-visible behavior; a fix lands with its test.
- **Grows without forking.** Agents add Matrix tools live; maintainers promote
  the proven ones into the Nucleus through gates, not rewrites.
- **Honest about money.** Costs are exact charges where providers report them
  and labeled estimates everywhere else — never a silent "$0.00".

---

## Quick start: Windows

1. Install [Git](https://git-scm.com/download/win) and
   [Python 3.10+](https://www.python.org/downloads/windows/). In the Python installer,
   enable **Add python.exe to PATH**.
2. Clone Longrun and start it from PowerShell:

   ```powershell
   git clone https://github.com/jagones84/longrun
   cd longrun
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
   ```

3. When the WebUI opens at `http://127.0.0.1:8790/`, set a Longrun token in the
   first-run panel.
4. Configure a provider using [Model setup](#model-setup). Add required credentials
   in [Secrets and local settings](#secrets-and-local-settings).
5. Choose an available model in the chat model picker and send a message.

The launcher installs PyYAML if needed. Leave its terminal open; press **Ctrl+C**
there to stop Longrun. `LONGRUN_TOKEN` protects Longrun; provider keys authorize
model calls. Both are entered in the WebUI and saved to the gitignored `.env`.

Optional setup: [MCP servers and skills](#optional-mcp-servers-and-skills),
[remote access](#remote-access), [document extraction](#optional-document-extraction),
and [sandbox](#sandbox).

---

## What Longrun does

- Runs chat and tool-using agent sessions through a browser UI and HTTP/SSE API.
- Tracks agent tasks with a persistent graph; team jobs can assign work across sessions.
- Uses bounded context, tool-output offload, and configurable verification gates.
- Provides session memory, a per-workspace codebase index, and a server-wide Knowledge Base.
- Shares one automatic/manual compaction policy in **Settings → Knowledge → Compaction**.
- Lets agents message peer sessions asynchronously, inspect their live transcript, and wait for a job-specific reply.
- Reorders teams and sessions by dragging their names; visual order syncs across clients connected to the same server.
- Reports per-session model cost as exact provider charges, token-rate estimates, or unpriced calls, including cached input usage.
- Connects to local or hosted model providers; supports a CLI and MCP integrations.

See [Architecture](docs/ARCHITECTURE.md) for system behavior and
[CLI reference](docs/CLI.md) for commands and API routes.

---

## Self-evolution: Nucleus vs. Matrix

Longrun can extend *itself* without a fork and without a restart. It splits into
two zones:

- **Nucleus** — `src/longrun/`: the protected core (13 subpackages). Stable, reviewed, and hard to break.
- **Matrix** — `src/Matrix/` (Python) plus `.Matrix/` (trash, docs, rules, skills, checkpoints, git).
  A live, agent-editable zone. Drop a file and it takes effect on the next call — no rebuild.

Every Nucleus seam exposes a **fail-open** hook point: `agent`, `core`, `integrations`, `interop`,
`memory`, `model`, `orbit`, `orchestrate`, `plan`, `research`, `tools`, `util`, `webui`.
Matrix code is loaded in an isolated `try/except`; a broken Matrix file is reported and skipped
rather than crashing the harness.

### Write once, run live

```python
# src/Matrix/tools/live_probe.py — every tool is namespaced <namespace>.<subtool>
TOOL_SCHEMAS = {"live_probe.ping": {"description": "probe", "type": "object", "properties": {}}}
def execute(args, run_id=None, subtool=None): return {"ok": True, "stdout": "hello from Matrix"}
```

```python
# src/Matrix/plan/hooks.py — nudges the planner, no restart required
def score_candidate(candidate, score, **kwargs): return min(1.0, score + 0.05)
```

Enable or disable the whole Matrix zone **live** — from the WebUI
(*Settings ▸ Tools & approvals ▸ Enable live Matrix zone*) or from the agent:

```jsonc
{"tool": "matrix.disable", "args": {}}   // only the Nucleus stays active
{"tool": "matrix.enable", "args": {}}    // Matrix hooks come back
{"tool": "matrix.status", "args": {}}    // {"enabled": true, "hooks": {...}, "tools": [...]}
```

### Promote to Nucleus, deterministically

When a Matrix artifact has proven itself, move it into the protected core with
`promote_to_nucleus`. It is universal — any kind under `src/Matrix`/`.Matrix`:

```jsonc
{"tool": "matrix.verify_target", "args": {"kind": "tool", "name": "live_probe"}}
{"tool": "matrix.promote_to_nucleus", "args": {"kind": "tool", "name": "live_probe"}}
```

`kind` ∈ `tool`, `hook`, `module`, `skill`, `rule`, `webui`. Promotion runs four gates:
a **verified test** must pass first (an unverified target is refused), a dedicated
**checkbox** in *Settings ▸ Tools & approvals* must be on (even `full` approval mode does
not authorize it), the workspace is **auto-checkpointed and auto-committed**, and only then
is the artifact moved into the Nucleus and deleted from Matrix. Broken code returns the exact
`file:line` and offending source line for fast debugging.

---

## Quick start: Linux (x86_64 and ARM64)

### DGX Spark (ARM64 / aarch64)

Confirm the architecture, then install Git, Python 3.10+, and
[PyYAML](https://packages.ubuntu.com/noble/python3-yaml):

```bash
uname -m
sudo apt update
sudo apt install -y git python3 python3-yaml
git clone https://github.com/jagones84/longrun
cd longrun
./run.sh
```

`uname -m` should print `aarch64`. These same package and launch steps work on
Ubuntu x86_64; there, `uname -m` prints `x86_64`.

Open `http://127.0.0.1:8790/`. Set a token in the first-run panel. Configure a
provider with [Model setup](#model-setup), then choose it in the model picker.
Keep the terminal open; press **Ctrl+C** to stop Longrun. For other Linux
distributions, install equivalent Git, Python, and PyYAML packages.

Next: [Secrets and local settings](#secrets-and-local-settings),
[MCP servers and skills](#optional-mcp-servers-and-skills),
[remote access](#remote-access), [Linux service](#optional-linux-service),
[document extraction](#optional-document-extraction), and [sandbox](#sandbox).

## Model setup

### OpenRouter

Create an account at [OpenRouter](https://openrouter.ai/) and an API key at
[OpenRouter API Keys](https://openrouter.ai/settings/keys). Enter it in
**Settings → Keys** as `OPENROUTER_API_KEY`, then choose
`openrouter:openai/gpt-4o-mini` in the model picker. See the
[model page](https://openrouter.ai/openai/gpt-4o-mini) for current availability
and pricing.

### Local models

1. Run `ollama list` and copy an installed chat model ID.
2. In **Settings → Models → Add/edit provider**, enter:
   - ID: `ollama`
   - Name: `Ollama`
   - Kind: `openai-compatible`
   - Base URL: `http://127.0.0.1:11434/v1`
   - Models: the exact ID copied from `ollama list`
   - API key environment variable: leave blank
   - **local (no key):** enabled
3. Save, then select `ollama:<model-id>` in the chat model picker.

This URL assumes Ollama and Longrun run on the same machine. The provider URL is
accessed by the Longrun server, not the browser. Use the model server's reachable
address when they run on different machines.

For llama.cpp, open **Settings → Models → Add/edit provider** and set ID
`llamacpp-local`, name `llama.cpp local`, kind `llama.cpp`, base URL
`http://127.0.0.1:8080/v1`, and the exact model ID reported by `/v1/models`.
Leave the key variable blank and enable **local (no key)**. After saving, choose
`llamacpp-local:<model-id>` in the picker.

For LM Studio, use ID and name `lmstudio` / `LM Studio`, base URL
`http://127.0.0.1:1234/v1`, kind `openai-compatible`, its exact model ID, and
enable **local (no key)**.
Official references:
[Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility) and
[LM Studio OpenAI-compatible endpoints](https://lmstudio.ai/docs/developer/openai-compat).

If a local endpoint requires a key, enter its environment-variable name in the
provider form and set the value in **Settings → Keys**.

### Secrets and local settings

Enter secrets in **Settings → Keys**. Longrun writes them to the gitignored
`<repository>/.env`; `.env.template` lists supported keys without values.

| Key | Used for |
|---|---|
| `OPENROUTER_API_KEY` | OpenRouter model calls |
| `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` | The matching direct provider |
| `TAVILY_API_KEY`, `BRAVE_API_KEY`, `PERPLEXITY_API_KEY` | Optional search/research providers |
| `GITHUB_TOKEN` | GitHub tool or MCP server |
| `COHERE_API_KEY`, `VOYAGE_API_KEY`, `JINA_API_KEY` | Optional embedding providers |
| `VLLM_API_KEY` | vLLM, when its endpoint requires authentication |
| `LONGRUN_TOKEN` | Protects Longrun API routes |

Other variables used by configured MCP servers can also be added in **Settings → Keys**.

| Data | Default path |
|---|---|
| Keys and server token | `<repository>/.env` |
| User provider settings | `config/providers.local.yaml` |
| Sessions, events, indexes, and other app data | the **data home** (see below) |
| User MCP definitions | `config/mcp_clients.local.json` |
| User-installed skills | `skills/local/` |

### Where your data lives (not in the repository)

Everything the harness owns lives under ONE root, `~/.longrun` (`%LOCALAPPDATA%\Longrun`
on Windows), never inside the checkout: a `git pull`, a fresh clone or a container
image must not be able to replace or expose sessions, the event log, indexes, costs,
the self-evolution runtime or your project rules.

```
~/.longrun/
  config/       config.json, Global_rules.md, AGENTS.md, prompt.d/   (tiny, human-editable)
  data/         sessions, events.db, knowledge/, codebase/, costs/, projects/ ...
  matrix/       the self-evolution runtime (ex .Matrix)
  workspaces/   default root for new projects
```

The data root can be moved: `LONGRUN_DATA_HOME` (explicit override) →
`data_home` in `~/.longrun/config/config.json` (what **Settings → Info → Data home**
writes) → the platform default above. `config/` always stays at the DEFAULT
location, because it is the file that records where the data root is.

Per-workspace PROJECT state (`Project_rules.md`, `rules/`, `prompt.d/`) is kept in
`<data>/projects/<slug>-<sha8>/`, exactly like the per-workspace codebase index —
a harness checkout must not drop a `.longrun/` folder into your projects. A legacy
`<workspace>/.longrun` is moved there the first time that workspace is used, so
nothing is lost.

**Settings → Info → Data home** shows the current location and can MOVE it: the
old tree is copied, the copy is verified file by file, and only then is the source
removed — with a progress bar, then a restart. A repository that still has a
legacy `<repository>/data` keeps being served from there (nothing is lost) and the
panel flags it as "still inside the repository" until you move it.

These paths are gitignored. Knowledge Base is shared across sessions within one
Longrun instance; the codebase index is separate for each workspace.

### Optional: MCP servers and skills

Neither is required for chat.

#### MCP servers

1. Install [Node.js](https://nodejs.org/) on the machine running Longrun if the
   server uses `npx` (stdio). Streamable HTTP servers do not need `npx`.
2. Open **Settings → MCP**. Use **Catalog · add in one click** for a preset, or
   **MCP JSON** to paste one server's `mcpServers` snippet and confirm it.
   **Edit mcp.json** opens the local server definitions for direct editing.
3. Complete any required values before saving:
   - **Filesystem:** replace the placeholder with an absolute allowed directory.
     Choose a narrow folder; do not expose the whole home directory.
   - **GitHub:** set `GITHUB_TOKEN` in **Settings → Keys**.
   - **Other servers:** use `command` and `args` for stdio, or `url` and optional
     `headers` for Streamable HTTP. For HTTP auth headers, store the key in
     **Settings → Keys** and reference it as `${VARIABLE_NAME}`.
4. Click **reload** in Settings → MCP. Check that each enabled server is connected
   and reports the expected tools.

User server definitions are saved in the gitignored
`config/mcp_clients.local.json`; the shipped `config/mcp_clients.yaml` contains
generic examples only.

#### Skills

Open **Settings → Skills → Install from zip**, choose a trusted skill `.zip`, and
click **install**. User-installed skills go under `skills/local/`.

### Remote access

1. Start Longrun on localhost. Set and save a token in the first-run panel.
2. Stop Longrun, then restart it bound to the network:
   - Linux: `./run.sh --host 0.0.0.0`
   - Windows: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 --host 0.0.0.0`
3. On the other device, open `http://<server-address>:8790/`. Use the server's
   current LAN or VPN address; `127.0.0.1` only works on the server itself.

Do not expose an unauthenticated Longrun server to a network. Plain HTTP does not
encrypt traffic; use a trusted network or a secured HTTPS proxy.

### Optional Linux service

The repository includes `deploy/longrun.service` for a user-level systemd service.
First run Longrun locally, set and verify `LONGRUN_TOKEN` in the WebUI, then stop it.
Install and start the service:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/longrun.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now longrun.service
systemctl --user status longrun.service
```

The unit expects the checkout at `~/Repositories/longrun`. Edit its paths if your
checkout is elsewhere. It binds `0.0.0.0:8790`.

Once the service is installed, these are the three commands you need day to day.
**A backend Python change (anything under `src/`) only takes effect after a
restart**; static WebUI files are served from disk and only need a page reload.

```bash
systemctl --user restart longrun.service   # apply Python changes
systemctl --user stop longrun.service      # stop the app
systemctl --user start longrun.service     # start it again
journalctl --user -u longrun.service -n 100 --no-pager   # recent logs
```

Before restarting, check that no turn is running — a restart kills an in-flight
turn. With a token configured:

```bash
curl -s -H "Authorization: Bearer $LONGRUN_TOKEN" \
  http://127.0.0.1:8790/api/chat/live     # proceed only when "active" is []
```

Use `systemctl --user`, never `sudo systemctl`: the unit runs in your user session
and a system-level restart starts it under the wrong account.

### Optional document extraction

`requirements.txt` lists optional document extractors (`docling` and `markitdown`).
Install them into the same Python environment Longrun uses; they are not needed for
chat and may add large dependencies. System tools provide fallback extraction when
available.

### Sandbox

Shell tools run on the host unless a sandbox backend is installed and enabled in
**Settings → Tools & approvals**.

---

## CLI

`forge.py` commands the harness from the terminal — the same REST API the
WebUI uses, stdlib only, no install. Full reference: [CLI reference](docs/CLI.md).

```bash
cd /home/jagones/Repositories/longrun
export LONGRUN_TOKEN=<your-token>   # set it in the WebUI first-run panel
python3 forge.py status             # server, router, versions
python3 forge.py sessions ls        # your sessions
python3 forge.py chat "ping" --stream
python3 forge.py tools ls           # tools, approvals, sandbox backend
python3 forge.py agents ls          # team org chart
python3 forge.py jobs ls            # coordinated jobs
python3 forge.py --help             # every command (30+ subcommands)
```

Data commands print JSON (or aligned tables for `ls`); streaming commands
(`chat --stream`, `agent`, `feed`, `blackboard watch`) print live until
`Ctrl-C`. Exit `0` on success, `1` on `{"error": ...}`, `2` on malformed JSON
args.

---

## API & integration

Longrun exposes an HTTP/JSON API and SSE event stream, a CLI (`forge.py`), and MCP
integrations. API calls require a bearer token when `LONGRUN_TOKEN` is set.
See [CLI reference](docs/CLI.md) for commands and endpoints, and
[Architecture](docs/ARCHITECTURE.md) for component details.

Orchestration has three native shapes — pick the cheapest that fits:

```jsonc
// one teammate, one turn in its own session
{"action": "dispatch", "agent": "A48", "goal": "read the first line of README.md"}
// many teammates at once (different teammates run concurrently)
{"action": "batch", "calls": [
  {"action": "dispatch", "agent": "A48", "goal": "read README.md"},
  {"action": "dispatch", "agent": "A49", "goal": "read docs/CLI.md"} ]}
// a durable job with dependency waves, observable via /api/jobs
{"tool": "job.dispatch", "args": {"job": "J22"}}
```

---

## Data and search

Application data lives in the **data home** (`~/.longrun`, `%LOCALAPPDATA%\Longrun`
on Windows) — never inside the checkout; see
[Where your data lives](#where-your-data-lives-not-in-the-repository). `LONGRUN_DATA_DIR`
can move the data root for tests and custom setups.

| Store | Scope | Default location |
|---|---|---|
| Session transcripts | Per session | `data/sessions/` |
| Knowledge Base | Shared by sessions in one server instance | `data/knowledge/knowledge.db` |
| Codebase index | Separate for each workspace | `data/codebase/<workspace-hash>.db` |

Manage notebooks and sources in **Settings → Knowledge**. Build or search the active
workspace index in the right-rail **Codebase** panel. Both stores support keyword
search; vector search is optional. See [CLI reference](docs/CLI.md) for commands.

The Compaction form owns the global policy and summarizer settings. Manual and
automatic compaction use the same policy; large transcripts are summarized in parts.
For agent collaboration, `sessions.send` returns immediately with a `message_id`;
`sessions.read` inspects the peer while it works, and `sessions.wait` returns the
matching job's final reply or failure.

---

## Tests

The acceptance battery runs tests in isolated temporary directories. The fast run
skips six heavy indexing and document-ingestion tests:

```bash
bash tests/battery.sh
LONGRUN_BATTERY_FULL=1 bash tests/battery.sh
LONGRUN_BATTERY_JOBS=1 bash tests/battery.sh
```

The acceptance suite now contains **330/330 test files**.
See [Testing Playbook](docs/TESTING-PLAYBOOK.md) for live WebUI checks.

---

## Documentation

| Doc | What |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | architecture and data flow |
| [docs/CLI.md](docs/CLI.md) | CLI commands and API endpoints |
| [docs/TESTING-PLAYBOOK.md](docs/TESTING-PLAYBOOK.md) | live WebUI verification |
| [AGENTS.md](AGENTS.md) | orientation for an AI agent landing in the repo |
| [CONTRIBUTING.md](CONTRIBUTING.md) | how to contribute |
| [CHANGELOG.md](CHANGELOG.md) | release notes |

---

## License

© 2025–2026 Giovanni J. Agones ([jagones84](https://github.com/jagones84)).
Licensed under **AGPL-3.0** — see [LICENSE](LICENSE).

If Longrun is useful to you, ⭐ star the repo — it helps others find it.
