#!/usr/bin/env python3
"""v468 — Paperclip adapter documentation parity (Paperclip Task 7).

An integration nobody can install or reason about is not delivered. This test
pins the operator-facing contract to the code that actually exists:

  * `docs/CLI.md` documents the `paperclip-bot` child command and lists its
    streaming route in the endpoint-coverage table;
  * `src/longrun/core/forge.py` registers exactly that subcommand;
  * `integrations/paperclip/README.md` documents the local `localPath` install,
    the configurable Python executable + checkout path, the `LONGRUN_URL` /
    `LONGRUN_TOKEN` contract, the environment check, the deterministic test
    commands, the five-event allowlist, the unsupported capabilities, and the
    difference between adapter run events and Paperclip Runner PRP events;
  * the local maintainer runbook `.agent/README-paperclip-adapter.md` exists
    (checked only where that local-only directory is present);
  * `CHANGELOG.md` records the integration under `Unreleased` → `Added`.

Deterministic and offline: reads repository files only.

Run: python3 tests/acceptance/v468_paperclip_docs.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    """Return a repository file, or "" when it is absent (a FAIL, not a crash)."""
    path = os.path.join(REPO, *parts)
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _missing(text, tokens):
    """Tokens that must appear verbatim in a document."""
    return [tok for tok in tokens if tok not in text]


CLI = _read("docs", "CLI.md")
FORGE = _read("src", "longrun", "core", "forge.py")
CHANGELOG = _read("CHANGELOG.md")
README = _read("integrations", "paperclip", "README.md")

# --- the documented command is the registered command ----------------------
check("test_paperclip_bot_command_is_documented_and_registered",
      "paperclip-bot" in CLI and 'sub.add_parser("paperclip-bot")' in FORGE,
      "cli=%s forge=%s" % ("paperclip-bot" in CLI, 'sub.add_parser("paperclip-bot")' in FORGE))

check("test_cli_documents_the_supported_invocation",
      _missing(CLI, ["python forge.py paperclip-bot", "longrun.paperclip.invocation.v1",
                     "longrun.paperclip.event.v1"]) == [],
      _missing(CLI, ["python forge.py paperclip-bot", "longrun.paperclip.invocation.v1",
                     "longrun.paperclip.event.v1"]))

check("test_cli_endpoint_table_lists_the_streaming_route",
      "/api/agent/run/stream" in CLI and "/api/agent/runs/<id>" in CLI, "")

# --- the package README is an installable, reproducible manual --------------
check("test_package_readme_documents_local_install_and_config",
      _missing(README, ["localPath", "interpreter", "checkout", "longrunUrl", "LONGRUN_URL",
                        "LONGRUN_TOKEN", "timeoutSec", "maxSteps", "python forge.py paperclip-bot"]) == [],
      _missing(README, ["localPath", "interpreter", "checkout", "longrunUrl", "LONGRUN_URL",
                        "LONGRUN_TOKEN", "timeoutSec", "maxSteps", "python forge.py paperclip-bot"]))

check("test_package_readme_documents_the_five_event_allowlist",
      _missing(README, ["longrun.run.started", "longrun.run.progress", "longrun.run.completed",
                        "longrun.run.failed", "longrun.run.cancelled", "agent.think"]) == [],
      _missing(README, ["longrun.run.started", "longrun.run.progress", "longrun.run.completed",
                        "longrun.run.failed", "longrun.run.cancelled", "agent.think"]))

check("test_package_readme_documents_the_deterministic_commands",
      _missing(README, ["npm install", "npm test", "npm run typecheck", "/api/status"]) == [],
      _missing(README, ["npm install", "npm test", "npm run typecheck", "/api/status"]))

check("test_package_readme_separates_adapter_events_from_runner_prp_events",
      "PRP" in README and "Runner" in README, "")

check("test_package_readme_states_the_unsupported_capabilities",
      "not" in README.lower() and _missing(README, ["asset", "Out of scope"]) == [],
      _missing(README, ["asset", "Out of scope"]))

# --- the maintainer runbook is local-only (absent in a bare checkout) -------
_AGENT = os.path.join(REPO, ".agent")
if os.path.isdir(_AGENT):
    try:
        RUNBOOK = _read(".agent", "README-paperclip-adapter.md")
    except OSError:
        RUNBOOK = ""
    check("test_maintainer_runbook_exists_and_documents_setup",
          _missing(RUNBOOK, ["localPath", "LONGRUN_TOKEN", "python forge.py paperclip-bot"]) == [],
          _missing(RUNBOOK, ["localPath", "LONGRUN_TOKEN", "python forge.py paperclip-bot"]))
else:
    print("SKIP test_maintainer_runbook_exists_and_documents_setup :: .agent/ is local-only")

# --- the changelog records the integration ---------------------------------
_start = CHANGELOG.find("## [Unreleased]")
_next = CHANGELOG.find("\n## [", _start + 1)
_UNREL = CHANGELOG[_start:_next if _next != -1 else len(CHANGELOG)]
check("test_changelog_records_the_paperclip_adapter",
      _start != -1 and "integrations/paperclip" in _UNREL
      and "paperclip" in _UNREL.lower() and "Added" in _UNREL, "")

print("---")
ok = sum(RESULTS)
print("%d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
