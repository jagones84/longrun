# Frontier Agent Harnesses — 2026 Research Survey

> SUPERSEDED (2026-10-25): the 2026-09-28 design-base snapshot. Current
> reference is `.agent/docs/research/` (dated reports, papers, notes) plus
> `.agent/docs/harness-strengths.md` (actionable port map). Kept for history.

*Research performed 2026-09-28 as the design base for Longrun (JAG-32). Live web search across MarkTechPost, TrueFoundry, Winder.AI, Lil'Log, FutureAGI, Atlan, awesome-harness-engineering (Sep 2026).*

## 1. What a "harness" is in 2026

> "An agent harness is the runtime layer around an LLM that turns it into a reliable, long-running agent. It manages the execution loop, tool calls, context, sandboxing, approvals and session state." — TrueFoundry, *Best Open Source Agent Harness 2026*

> "A production agent in 2026 has: an LLM matched to the problem, a harness that wraps the model in a simple and observable loop, a sandbox so the agent cannot damage real systems, the context that connects it to what it needs, actionable tools, a store with write rules, and an evaluation harness." — Winder.AI, *How to Build an AI Agent in 2026*

Consensus thesis: **the harness matters more than the model you drop into it** (buildmvpfast, 2026-07). Capability comes from the loop: reason → act → observe, with context engineering around it.

## 2. The state of the art (projects surveyed)

| Harness | Pattern worth stealing |
|---|---|
| **OpenHands** (ex-OpenDevin) | Event-stream architecture: agent reasons → emits action → environment executes → observation returns. Most mature open-source coding agent; per-session sandbox. |
| **deepagents** (LangChain) | Everything-included harness: planning tools, virtual filesystem, subagent delegation, context engineering, persistent memory, HITL. Model-agnostic, streaming + checkpointing. |
| **OpenCode** | First-class local path: `llama.cpp llama-server` via OpenAI-compatible `baseURL`; recommends ≥64k ctx, raise `num_ctx` when tool calls fail. Directly relevant to our router. |
| **Cline** | Plan/Act mode separation; compact prompts for local models; per-action approval gates with opt-out auto-approve. |
| **Open Interpreter** | Focus: frontier-level output from *low-cost/local* models — exactly our constraint class. |
| **Codex CLI** | Apache-2.0, Rust, sandbox-first; tens of millions of installs — approval gates + sandboxing as default. |
| **Goose** | Model independence, MCP extension system (70+ tools), CLI + GUI + API from one core. |
| **Claude Code** | Deep MCP support, subagents, terminal-first loop. |

## 3. Cross-cutting SoA findings (2026)

1. **Agent Client Protocol (ACP) convergence** — Zed Agent, OpenHands and others speak ACP so they can drive each other; DeepSeek Harness runs Claude Code/Codex as child processes. Harnesses are becoming *interoperable runtimes*, not monoliths. (Winder.AI)
2. **Foundations formalized** — Linux Foundation's Agentic AI Foundation (2026) anchored by MCP (Anthropic), AGENTS.md (OpenAI), Goose. Context/instruction formats are now standards, not conventions.
3. **Model-native harnesses** — OpenAI's April-2026 Agents SDK update added native sandbox execution, configurable memory, sandbox-aware orchestration ("model-native harness" shift; awesome-harness-engineering).
4. **Meta-harness / self-improvement** — Lil'Log (2026-07): outer-loop optimization where a coding agent *proposes harness candidates* on a Pareto frontier. Harness engineering itself is becoming agentic.
5. **Local-model guidance converged** — OpenHands: ≥22k ctx (32k recommended), quantized needs ≥24GB VRAM/64GB unified. Our GB10 unified memory + llama.cpp router with 262k-ctx presets comfortably clears the local bar.
6. **Structured thinking is exposed, not hidden** — `reasoning_content` (DeepSeek/GLM/Qwen chat templates) and inline `<think></think>` blocks surfaced as a first-class UI timeline (visible CoT), with Plan/Act separation.

## 4. Design decisions for Longrun (what we adopt, v0.1)

| SoA pattern | Longrun adoption |
|---|---|
| Reason→act→observe event loop | `/api/agent/run`: model proposes one JSON action per iteration (`thought/action/observation`), harness executes it against plan/task stores, observation feeds the next iteration |
| Plan/Act separation | Dedicated **PLAN** store (model-generated strategy) + **TASKS** board (execution units) kept as separate, inspectable state |
| Visible CoT timeline | `reasoning_content` + `<think></think>` parsing streamed as a distinct channel (`think`) to CLI/WebUI/mobile |
| Observable loop / event stream | Global **loopback feed**: SSE `/api/feed` with monotonic ids + backlog replay (`?since=`) — one event bus for WebUI, CLI and mobile |
| Approval gates / sandbox-first | Agent loop is **structurally sandboxed**: its only writable surface is the harness's own plan/task stores — no shell, no filesystem, by design. Shell/file tools with approval gates = v0.2 |
| Local-first model path | llama.cpp router `:8080` (OpenAI-compatible), streaming, 262k-ctx presets, model-agnostic |
| Session state / memory | Durable JSON stores (`data/plan.json`, `data/tasks.json`, `data/sessions/`) with atomic writes |
| MCP extensibility | Noted as v0.3 direction; v0.1 uses native JSON actions to stay dependency-free |

## 5. Sources

- MarkTechPost — *Best Open-Source Agent Harnesses for Local LLMs in 2026* (2026-09-18)
- TrueFoundry — *Best Open Source Agent Harness: Top 5 Projects Compared for 2026*
- Winder.AI — *A Comparison of AI Agent Harnesses in 2026*; *How to Build an AI Agent in 2026* (2026-08-15)
- Lil'Log (Lilian Weng) — *Harness Engineering for Self-Improvement* (2026-07-04)
- FutureAGI — *Best Agent Harnesses 2026: A Builder's Field Guide* (2026-07-22)
- Atlan — *Top AI Agent Harness Tools and Frameworks 2026* (2026-09-18)
- github.com/ai-boost/awesome-harness-engineering (2026-09-24)
- buildmvpfast — *Agentic Coding Framework: Build the Agent Loop* (2026-07-02)
- SiliconFlow — *Best Open Source LLM For Agent Workflow in 2026*
- ayautomate — *Best Open-Source AI Agents 2026: 12 Picks, Licenses Checked*
