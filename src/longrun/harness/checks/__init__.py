#!/usr/bin/env python3
"""Report-only checkers — one deterministic module per paper/round.

The CONTRACT every module in this package honours, asserted by
`tests/acceptance/v1275_checker_conformance.py`:

* it exposes ``FORMAT`` — the result-format string ``core/forge.py`` emits with;
* it exposes at least one PUBLIC function that takes plain data (a dict/list, usually
  read from a JSON file by the CLI) and returns a verdict;
* it imports only the standard library and ``longrun.harness`` — never ``agent/``,
  ``core/`` or ``tools/``: importing a module from here inside the running app is a
  layering error, and the live seam belongs in ``longrun.harness`` instead;
* it does not write, with TWO documented exceptions that persist a CALLER-SUPPLIED path
  and never a verdict: ``setup_blocks`` (a checkpoint store under its ``state_dir``) and
  ``intent_journal`` (an append-only journal, opened per row so a kill leaves whole
  rows).

Verb uniformity is deliberately NOT part of the contract: the modules expose 566
distinct public function names because they run genuinely different analyses; forcing
one name would be a mass rename, not a contract.

`docs/ARCHITECTURE.md` calls these "report-only": a verdict is evidence about the record
it was handed, never a claim that the live system is protected.

The CLI is the only adapter: ``python3 forge.py <group> <action> FILE.json``.
"""
