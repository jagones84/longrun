#!/usr/bin/env python3
"""Harness² adapter package — the evidence half of recursive harness refinement.

The paper (arXiv:2610.14224) refines a harness on the task in front of it with a
contrastive Propose–Probe–Compose step that needs no answer key. What makes that
possible is not the model: it is a *record* of how the base run behaved and a
mechanical *contrast* between two records.

This package carries only that evidence machinery. It never writes harness code:
every adopted change goes through `util.improve.propose` and stays a proposal for
the operator (see `util/improve.py:21-27`).

Layout (2026-11-20), by runtime role rather than by paper:

* `checks/` — the report-only checkers (one module per paper/round). Pure data in,
  verdict out. Nothing in `agent/`, `core/` or `tools/` imports them; the only
  adapter is `core/forge.py` (`python3 forge.py <group> <action> FILE.json`).
  A checker the app needs is not a checker: two that were (`recall_log`,
  `skill_os_contract`) moved up to this root on 2026-11-22.
* `execution/` — 9 gated executors (`probe`, `runner`, `editors`, `compose`,
  `contrast`, `whole`, `snapshot`, `gateway`, `unixshim`). They execute a real
  run and are reachable only through `cycle` with `dry_run=False`, which
  refuses unless `whole.readiness()` is satisfied. The acceptance tests inject
  a fake runner/call to exercise them.
* this root — the 26 modules the running app actually imports: the live turn
  seams (`shellread`, `observation`, `workspace_check`, `effect_types`,
  `effect_recovery`, `intent_audit`, `memory_authority`, `memory_channel`,
  `counterfactual`, `modelcf`, `env_card`, `edit_loop`, `time_budget`,
  `recall_log`, `skill_os_contract`),
  the graph-topology census (`graph_topology`, round 169 — read by `orbit/api`
  and `forge.py graph`; its report-only audit lives in `checks/`), the
  read-only HTTP surfaces (`cycle`, `manifest`, `invariants`, `backtrace`,
  `reuse`, `verification_transport`, `skills_maintenance`) and their support
  (`record`, `library`, `tool_policy`).
"""
