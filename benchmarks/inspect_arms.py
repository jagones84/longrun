#!/usr/bin/env python3
"""Both harnesses as Inspect agents — the same task, the same model, two arms.

Why the sandbox bridge: Inspect's `sandbox_agent_bridge()` starts a proxy INSIDE the
task container that speaks the OpenAI API on `localhost:<port>/v1` and relays every
request to the model the eval selected. The harness runs in that same container, so:

  * the model is the eval's model, not a per-harness choice — that is what makes the
    comparison a comparison;
  * the harness's own tools act on the evaluated machine, not on the host;
  * Inspect still logs tokens, limits and transcripts.

The payload (longrun source, node + openclaw) is baked into the sandbox image
(`benchmarks/inspect_sandbox/`), so a trial only starts the harness.

Usage:
    inspect eval inspect_evals/gaia --subset 2023_level1 \
        -T sandbox=("docker","benchmarks/inspect_sandbox/Dockerfile") \
        --solver benchmarks/inspect_arms.py@longrun_arm --model openrouter/z-ai/glm-5.3-flash

    ... --solver benchmarks/inspect_arms.py@openclaw_arm
"""
from inspect_ai.agent import Agent, AgentState, agent, sandbox_agent_bridge
from inspect_ai.model import ModelOutput, user_prompt
from inspect_ai.util import sandbox

import os

#: The name the sandbox bridge ANSWERS to. `targets_inspect_model()` only redirects a
#: request into the eval's model when the `model` field matches `^inspect/?`, so a bare
#: provider id (`z-ai/glm-5.3-flash`) is passed through to a real endpoint that is not
#: there — measured 2026-11-01 as a plain `HTTP 502 Bad Gateway` from the harness.
BRIDGE_MODEL = "inspect"

#: Per-SAMPLE budget. A launcher fixes it in the environment so a whole run has a wall
#: clock: `ARM_TIMEOUT=600 scripts/bench-gaia.sh both 6`. Read at import, because an
#: agent's keyword defaults are evaluated once.
ARM_TIMEOUT = int(os.environ.get("ARM_TIMEOUT", "1800"))
ARM_MAX_STEPS = int(os.environ.get("ARM_MAX_STEPS", "40"))


def _answer(state: AgentState, text: str) -> AgentState:
    state.output = ModelOutput.from_content(model="sandbox-bridge", content=text)
    return state


@agent
def longrun_arm(timeout: int = ARM_TIMEOUT, max_steps: int = ARM_MAX_STEPS,
                model: str = BRIDGE_MODEL) -> Agent:
    """The Longrun harness, driven over its own REST API inside the sandbox."""

    async def execute(state: AgentState) -> AgentState:
        prompt = user_prompt(state.messages)
        await sandbox().write_file("/tmp/question.txt", prompt.text)
        async with sandbox_agent_bridge(state) as bridge:
            res = await sandbox().exec(
                cmd=["bash", "/opt/longrun/longrun_turn.sh", "/tmp/question.txt"],
                env={"LR_BASE_URL": "http://localhost:%d/v1" % bridge.port,
                     "LR_MODEL": model,
                     "LR_MAX_STEPS": str(max_steps),
                     # the turn budget, not a smaller default: the driver waits for
                     # the whole turn, so its client timeout IS the budget
                     "LR_TURN_TIMEOUT": str(max(60, timeout - 30))},
                timeout=timeout,
            )
        text = (res.stdout or "").strip()
        if not res.success and not text:
            # Keep enough of stderr to carry the harness's own diagnosis
            # (base url, provider yaml, server log tail) into the Inspect log.
            text = "(longrun arm failed: %s)" % (res.stderr or "")[-6000:]
        return _answer(state, text)

    return execute


@agent
def openclaw_arm(timeout: int = ARM_TIMEOUT, model: str = BRIDGE_MODEL) -> Agent:
    """The OpenClaw harness, one headless embedded turn inside the sandbox."""

    async def execute(state: AgentState) -> AgentState:
        prompt = user_prompt(state.messages)
        await sandbox().write_file("/tmp/question.txt", prompt.text)
        async with sandbox_agent_bridge(state) as bridge:
            res = await sandbox().exec(
                cmd=["bash", "/opt/longrun/openclaw_turn.sh", "/tmp/question.txt"],
                env={"OC_BASE_URL": "http://localhost:%d/v1" % bridge.port,
                     "OC_MODEL": model,
                     "OC_TIMEOUT": str(timeout)},
                timeout=timeout + 60,
            )
        text = (res.stdout or "").strip()
        if not res.success and not text:
            text = "(openclaw arm failed: %s)" % (res.stderr or "")[-6000:]
        return _answer(state, text)

    return execute
