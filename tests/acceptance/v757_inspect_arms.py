#!/usr/bin/env python3
"""v757 — both harnesses as Inspect AI agents (the cross-benchmark arms).

Why Inspect: an Inspect eval owns the task, the sandbox and the model, and
`sandbox_agent_bridge()` exposes that model to a process INSIDE the task container
on `localhost:<port>/v1`. The harness therefore runs in the same machine it is being
scored on and speaks to the eval's model — same task, same model, two arms.

The image is built once by `benchmarks/inspect_sandbox/build_image.sh` and both
drivers live in it at fixed paths; this file pins the two halves of that contract
together, because a path that disagrees between the builder and the agent is a
silent "arm did nothing" (no output, no error).

Deterministic: no docker, no model, no network, no inspect_ai import.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SBX = os.path.join(REPO, "benchmarks", "inspect_sandbox")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def read(*parts):
    path = os.path.join(REPO, *parts)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


arms = read("benchmarks", "inspect_arms.py")
build = read("benchmarks", "inspect_sandbox", "build_image.sh")
dockerfile = read("benchmarks", "inspect_sandbox", "Dockerfile")
lr_turn = read("benchmarks", "inspect_sandbox", "longrun_turn.sh")
oc_turn = read("benchmarks", "inspect_sandbox", "openclaw_turn.sh")

# ---- A. two arms, one mechanism ---------------------------------------------
check("A1 the longrun arm is defined", "@agent" in arms and "def longrun_arm(" in arms)
check("A2 the openclaw arm is defined", "def openclaw_arm(" in arms)
# The whole point: the model is the eval's model. A per-arm model choice would make
# any difference between the arms unassignable.
check("A3 both arms take the model from the sandbox bridge, not their own config",
      arms.count("sandbox_agent_bridge(state)") == 2, arms.count("sandbox_agent_bridge(state)"))
check("A4 the bridge port is what the harness is pointed at",
      "LR_BASE_URL" in arms and '"http://localhost:%d/v1" % bridge.port' in arms
      and "OC_BASE_URL" in arms)
check("A5 the answer Inspect records is the harness's final text",
      "ModelOutput.from_content(" in arms and "state.output = " in arms)

# ---- B. the paths the agent calls are the paths the image installs -----------
for arm, driver in (("longrun", "longrun_turn.sh"), ("openclaw", "openclaw_turn.sh")):
    target = "/opt/longrun/" + driver
    check("B1 the %s arm calls %s" % (arm, target), target in arms)
    check("B2 build_image.sh installs that same driver at that same path",
          ("/opt/longrun/" + driver) in build
          and "COPY longrun_turn.sh openclaw_turn.sh /opt/longrun/" in build)
check("B3 the image carries both runtimes the drivers need",
      "tar -C \"$(dirname \"$NODE\")\"" in build and "arcname" not in build
      and "openclaw.tar" in build and "longrun.tar" in build)
check("B4 the committed Dockerfile only derives from the built image (no second payload)",
      "FROM inspect-arms:latest" in dockerfile and "COPY" not in dockerfile)

# ---- C. each driver is a turn, not a chat ------------------------------------
check("C1 the longrun driver answers on stdout and keeps diagnostics off it",
      'print("(no answer: the harness returned an empty reply)")' in lr_turn
      and "file=sys.stderr" in lr_turn)
check("C2 the longrun driver replaces the provider list with the bridge",
      "providers.yaml" in lr_turn and "api_key_env: LR_API_KEY" in lr_turn)
check("C3 the longrun driver runs the turn headless",
      '"headless": True' in lr_turn and "max_steps" in lr_turn)
# Measured 2026-11-01: a hardcoded 300 s client timeout threw away a GAIA turn that was
# still reasoning, and its answer had ALREADY been persisted by the harness.
check("C7 the turn timeout is a budget, not a magic number",
      'LR_TURN_TIMEOUT' in lr_turn and 'LR_TURN_TIMEOUT' in arms)
check("C8 a failed transport still returns the reply the harness saved",
      "def persisted_reply(" in lr_turn and '/api/sessions/%s' in lr_turn
      and "persisted_reply(sid)" in lr_turn)
check("C4 the openclaw driver prints the final answer, not the envelope",
      'd.get("final")' in oc_turn)
# openclaw addresses a model as `<provider>/<id>` and refuses any id its catalog does
# not contain ("Unknown model: openai/inspect"). The run therefore carries its own
# config: a provider speaking openai-completions whose model is named the way the
# sandbox bridge answers. Schema taken from openclaw's own docs/providers/litellm.md.
check("C5 openclaw is given an openai-completions provider from its own config",
      '"api": "openai-completions"' in oc_turn and "OPENAI_BASE_URL" in oc_turn)
check("C6 the openclaw turn is embedded and self-contained (no gateway, no ambient config)",
      "agent exec" in oc_turn and '--config "$CFG"' in oc_turn)
# An `openai-completions` provider APPENDS `/chat/completions` to baseUrl, so the `/v1`
# must survive: stripping it made openclaw call `<origin>/chat/completions`, the bridge
# answered 404 and openclaw reported "This model was not found" (measured 2026-11-01).
check("C9 openclaw keeps the bridge's /v1 in baseUrl (a stripped /v1 is a 404)",
      'endswith("/v1")' not in oc_turn and 'base[:-3]' not in oc_turn)

# ---- D. the driver is a file, not an inline ssh line ------------------------
import subprocess  # noqa: E402

for name in ("longrun_turn.sh", "openclaw_turn.sh", "build_image.sh"):
    path = os.path.join(SBX, name)
    check("D1 %s exists and is committed" % name, os.path.isfile(path))
    with open(path, "rb") as fh:
        raw = fh.read()
    check("D2 %s is LF (a CRLF shell script dies with exit 127)" % name, b"\r\n" not in raw)
    # The turn drivers embed python inside a single-quoted shell string, so ONE
    # apostrophe in a comment ends the program and the shell then parses python as
    # shell (`syntax error near unexpected token '('`). Measured 2026-11-01.
    syntax = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
    check("D3 %s parses as shell (no apostrophe escaped the embedded python)" % name,
          syntax.returncode == 0, (syntax.stderr or "").strip()[:200])

# Inspect's `docker:<Dockerfile>` form hard-codes `network_mode: none` in the
# auto-compose it generates, so an arm that must browse (GAIA) has to be handed a
# COMPOSE file instead — that is the only supported place to choose the mode.
_cpath = os.path.join(SBX, "compose.yaml")
_compose = open(_cpath, encoding="utf-8").read() if os.path.isfile(_cpath) else ""
check("D4 a network-enabled compose exists for the browsing tasks",
      "network_mode: bridge" in _compose and "dockerfile: \"Dockerfile\"" in _compose,
      _cpath)

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
