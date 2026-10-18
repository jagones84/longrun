<p align="center"><img src="assets/icon.svg" alt="Longrun" width="112" height="112"></p>

<img src="assets/banner.svg" alt="Longrun — the agent harness built to DRIVE the LLM" width="100%">

# Longrun

[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab.svg?logo=python&logoColor=white)](https://www.python.org/)
[![deps](https://img.shields.io/badge/deps-stdlib%20%2B%20PyYAML-brightgreen.svg)](#quick-start-windows)
[![tests](https://img.shields.io/badge/battery-210%2F210%20green-success.svg)](#tests)

Self-hosted AI agent harness with a browser UI, tool-enabled sessions, task graphs,
team orchestration, HTTP/SSE API, and CLI. Requires Python 3.10+ and PyYAML for the
core runtime. Supports Windows 10/11 x64 and Linux x86_64/ARM64.

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
4. For OpenRouter, create an account at [openrouter.ai](https://openrouter.ai/),
   create a key at [OpenRouter API Keys](https://openrouter.ai/settings/keys),
   and enter it in **Settings → Keys** as `OPENROUTER_API_KEY`. For Ollama, follow
   [Local models](#local-models) instead.
5. Choose an available model in the chat model picker and send a message.

The launcher installs PyYAML if needed. Leave its terminal open; press **Ctrl+C**
there to stop Longrun. `LONGRUN_TOKEN` protects Longrun; provider keys authorize
model calls. Both are entered in the WebUI and saved to the gitignored `.env`.

---

## What Longrun does

- Runs chat and tool-using agent sessions through a browser UI and HTTP/SSE API.
- Tracks agent tasks with a persistent graph; team jobs can assign work across sessions.
- Uses bounded context, tool-output offload, and configurable verification gates.
- Provides session memory, a per-workspace codebase index, and a server-wide Knowledge Base.
- Connects to local or hosted model providers; supports a CLI and MCP integrations.

See [Architecture](docs/ARCHITECTURE.md) for system behavior and
[CLI reference](docs/CLI.md) for commands and API routes.

---

## Quick start: Linux (x86_64 and ARM64)

On Ubuntu 24.04, including DGX Spark ARM64, install Git, Python 3.10+, and
[PyYAML](https://packages.ubuntu.com/noble/python3-yaml):

```bash
sudo apt update
sudo apt install -y git python3 python3-yaml
git clone https://github.com/jagones84/longrun
cd longrun
./run.sh
```

Open `http://127.0.0.1:8790/`. Set a token in the first-run panel. Then configure
a provider below. Keep the terminal open; press **Ctrl+C** to stop Longrun.
For other Linux distributions, install equivalent Git, Python, and PyYAML packages.

## Model setup

### OpenRouter

After setting `OPENROUTER_API_KEY`, choose `openrouter:openai/gpt-4o-mini` in the
model picker. See the
[OpenRouter model page](https://openrouter.ai/openai/gpt-4o-mini) for its current
availability and pricing.

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

For LM Studio, use ID and name `lmstudio` / `LM Studio`, base URL
`http://127.0.0.1:1234/v1`, its exact model ID, and enable **local (no key)**.
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
| Sessions, events, indexes, and other app data | `data/` |
| User MCP definitions | `config/mcp_clients.local.json` |
| User-installed skills | `skills/local/` |

These paths are gitignored. Knowledge Base is shared across sessions within one
Longrun instance; the codebase index is separate for each workspace.

### Optional: MCP servers and skills

Neither is required for chat.

- **MCP:** install [Node.js](https://nodejs.org/) for catalog entries that use `npx`,
  then open **Settings → MCP → Catalog** and click **+ add**. GitHub needs
  `GITHUB_TOKEN` in **Settings → Keys**; Filesystem asks you to choose an absolute
  folder to expose. User server definitions are saved in
  `config/mcp_clients.local.json`.
- **Skills:** open **Settings → Skills → Install from zip**, choose a trusted skill
  `.zip`, and click **install**. User-installed skills go under `skills/local/`.

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

### Optional document extraction

`requirements.txt` lists optional document extractors (`docling` and `markitdown`).
Install them into the same Python environment Longrun uses; they are not needed for
chat and may add large dependencies. System tools provide fallback extraction when
available.

### Sandbox

Shell tools run on the host unless a sandbox backend is installed and enabled in
**Settings → Tools & approvals**.

---

## API & integration

Longrun exposes an HTTP/JSON API and SSE event stream, a CLI (`forge.py`), and MCP
integrations. API calls require a bearer token when `LONGRUN_TOKEN` is set.
See [CLI reference](docs/CLI.md) for commands and endpoints, and
[Architecture](docs/ARCHITECTURE.md) for component details.

---

## Data and search

By default, Longrun stores application data under `<repository>/data/`. Git ignores
this directory. `LONGRUN_DATA_DIR` can move the data root.

| Store | Scope | Default location |
|---|---|---|
| Session transcripts | Per session | `data/sessions/` |
| Knowledge Base | Shared by sessions in one server instance | `data/knowledge/knowledge.db` |
| Codebase index | Separate for each workspace | `data/codebase/<workspace-hash>.db` |

Manage notebooks and sources in **Settings → Knowledge**. Build or search the active
workspace index in the right-rail **Codebase** panel. Both stores support keyword
search; vector search is optional. See [CLI reference](docs/CLI.md) for commands.

---

## Tests

The acceptance battery runs tests in isolated temporary directories. The fast run
skips six heavy indexing and document-ingestion tests:

```bash
bash tests/battery.sh
LONGRUN_BATTERY_FULL=1 bash tests/battery.sh
LONGRUN_BATTERY_JOBS=1 bash tests/battery.sh
```

The full command ran successfully during this README update: **210/210 passed**.
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
