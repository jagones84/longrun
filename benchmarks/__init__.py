"""Benchmark drivers for Longrun (JAG-426 · Domain 3).

A harness that cannot be measured cannot be improved. This package exposes
Longrun through a harness-agnostic adapter so external benchmark orchestrators
(SWE-bench, GAIA, Terminal-Bench, …) drive it exactly like any other harness.

The adapter talks to the PUBLIC REST API, not internal callables, so what is
measured is what an external user gets.
"""

from .protocol import AgentRef, HarnessResult, HarnessAdapter  # noqa: F401
