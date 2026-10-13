#!/usr/bin/env python3
"""Hermes adapter — a SECOND harness arm, for a like-for-like comparison (JAG-454).

Drives the Hermes Agent CLI headlessly (`cli.py -Q` answers and exits) so the
SAME task prompt can be run through a different agent harness with the SAME
model. Pair it with `LongrunAdapter` (and `BareAdapter` as the no-harness
control) over one task file + one model: the spread between the three arms is
the harness contribution, with the model held fixed.

Like the other adapters it imports nothing from `longrun.*`.

Default paths come from `.agent/docs/HARNESS_PATHS.md` (Hermes section). Override
with env: HERMES_PY, HERMES_CLI.
"""
import os
import subprocess
import time

from .protocol import AgentRef, HarnessResult

_HOME = os.path.expanduser("~")
_DEFAULT_PY = os.path.join(_HOME, ".hermes", "venvs", "hermes-dev", "bin", "python")
_DEFAULT_CLI = os.path.join(_HOME, "Repositories", "hermes-agent", "cli.py")


class HermesAdapter:
    """Run one prompt per task through the Hermes CLI (one-shot mode)."""

    name = "hermes"

    def __init__(self, model=None, provider=None, python=None, cli=None,
                 timeout=600.0, max_turns=6, base_url=None, api_key=None):
        self.model = model
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key
        self.python = python or os.environ.get("HERMES_PY") or _DEFAULT_PY
        self.cli = cli or os.environ.get("HERMES_CLI") or _DEFAULT_CLI
        self.timeout = float(timeout)
        self.max_turns = int(max_turns)

    def provenance(self):
        return {"harness": "hermes", "cli": self.cli, "python": self.python,
                "model": self.model or "(hermes default)", "provider": self.provider,
                "base_url": self.base_url, "max_turns": self.max_turns}

    # ---- adapter contract ---------------------------------------------------
    def create_agent(self, task):
        return AgentRef(id=str(task.get("id") or "hermes"), session="")

    def send_task(self, ref, prompt, timeout=None):
        argv = [self.python, self.cli, "-Q", prompt, "--max_turns", str(self.max_turns)]
        if self.model:
            argv += ["--model", self.model]
        if self.provider:
            argv += ["--provider", self.provider]
        if self.base_url:
            argv += ["--base_url", self.base_url]
        if self.api_key:
            argv += ["--api_key", self.api_key]
        t0 = time.time()
        try:
            p = subprocess.run(argv, capture_output=True, text=True,
                               timeout=timeout or self.timeout)
        except subprocess.TimeoutExpired:
            return HarnessResult(ok=False, error="hermes timeout",
                                 duration_s=round(time.time() - t0, 3),
                                 provenance=self.provenance())
        except OSError as e:
            return HarnessResult(ok=False, error="hermes launch failed: %s" % e,
                                 duration_s=round(time.time() - t0, 3),
                                 provenance=self.provenance())
        dur = round(time.time() - t0, 3)
        out = (p.stdout or "").strip()
        if p.returncode != 0 and not out:
            return HarnessResult(ok=False, error=(p.stderr or "")[-400:],
                                 duration_s=dur, provenance=self.provenance())
        return HarnessResult(ok=bool(out), output=out, duration_s=dur,
                             error="" if out else (p.stderr or "")[-400:],
                             provenance=self.provenance())

    def backup_session(self, ref):
        return ""

    def restore(self, ref, checkpoint):
        return False

    def delete_agent(self, ref):
        return True

    def docker_args(self):
        return []