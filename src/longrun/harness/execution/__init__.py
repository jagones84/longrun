#!/usr/bin/env python3
"""Frozen-experiment executors — gated, not part of a chat session.

These nine modules implement the recursive harness experiment:
record -> propose (editors) -> probe (runner/whole/snapshot/gateway/unixshim)
-> contrast -> compose. They EXECUTE a real agent run, spend tokens and spawn a
child process, which is why they are separated from `harness.checks/`.

No chat turn, agent tool or WebUI action can start them. The only entry point
is `POST /api/harness/cycle` with `dry_run=false`, and `cycle.run` refuses
before reaching them unless `whole.readiness()` is satisfied (POSIX non-root,
pinned sha256 image present, fixed model, loopback gateway, docker reachable,
`LONGRUN_HARNESS_ENABLED=1`). The acceptance tests exercise this package by
injecting a fake runner/editor call, which bypasses that readiness gate.
"""
