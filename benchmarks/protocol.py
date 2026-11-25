#!/usr/bin/env python3
"""Harness-agnostic adapter protocol (JAG-426 · Domain 3).

Mirrors the contract a benchmark orchestrator uses to drive ANY agent harness
(the interface popularised by Claw-SWE-Bench, arXiv 2606.12344):

    create_agent(task)          -> AgentRef
    send_task(ref, prompt)      -> HarnessResult
    backup_session(ref)         -> checkpoint id
    restore(ref, checkpoint)    -> bool
    delete_agent(ref)           -> bool
    docker_args()               -> list[str]

Plus `provenance()` — a harness benchmark is worthless if the run is not
reproducible, so every result carries the harness version, git sha and the model
+ sampling settings that produced it.

Stdlib only. Typed with `typing.Protocol` so `isinstance(adapter, HarnessAdapter)`
works at runtime (method-presence check).
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol, runtime_checkable


# ETCSLV tags (Round 171). Source: the survey *Agent Harness for LLM Agents*
# (Awesome-Agent-Harness, v4) — its framework H=(E,T,C,S,L,V) and §4 evaluation
# landscape. Each suite is tagged with the harness FUNCTIONS it stresses, so a
# score can say which half of the harness it measured. This is attribution from a
# published catalogue, never a claim that the suite was re-run here.
#
#   E execution loop · T tool registry · C context manager ·
#   S state store     · L lifecycle hooks · V evaluation interface
COMPONENTS = {
    # suites this repo ships
    "humaneval":       ("E", "T"),
    "swebench":        ("E", "T", "S"),
    "gaia":            ("E", "C", "T"),
    "jobbench":        ("E", "C", "V"),
    "polyglot":        ("E", "T"),
    "lhb":             ("E", "C", "L", "V"),
    "terminal_bench":  ("E", "T", "S"),
    # suites the survey catalogues (not shipped here): tagged for cross-reference
    "harnessbench":    ("E", "T", "C", "S", "L", "V"),
    "longhorizon":     ("E", "S", "V"),
    "harnessaudit":    ("L", "V"),
    "sclate":          ("S", "C"),
    "clawswebench":    ("E", "T"),
}
COMPONENT_ORDER = ("E", "T", "C", "S", "L", "V")
COMPONENT_NAMES = {"E": "Execution loop", "T": "Tool registry", "C": "Context manager",
                   "S": "State store", "L": "Lifecycle hooks", "V": "Evaluation iface"}


@dataclass
class AgentRef:
    """A live agent/session on the harness side."""
    id: str
    session: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HarnessResult:
    """The outcome of one task submission."""
    ok: bool = False
    output: str = ""
    patch: str = ""
    run_id: str = ""
    tokens: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    error: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)
    # v842: WHERE the sample left its record. Without the id a stored result can
    # only be described by its aggregate score — the per-call ledger (calls,
    # cache hits, duplicate best-of-N samples) was unreachable, so no run could be
    # compared with the next one. `usage` is that ledger's summary, read while the
    # session still exists (benchmarks/trend.py joins the two).
    session: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class HarnessAdapter(Protocol):
    """The benchmark-facing surface every harness adapter must implement."""

    name: str

    def create_agent(self, task: Dict[str, Any]) -> AgentRef:
        ...

    def send_task(self, ref: AgentRef, prompt: str, timeout: float = 900.0) -> HarnessResult:
        ...

    def backup_session(self, ref: AgentRef) -> str:
        ...

    def restore(self, ref: AgentRef, checkpoint: str) -> bool:
        ...

    def delete_agent(self, ref: AgentRef) -> bool:
        ...

    def docker_args(self) -> List[str]:
        ...

    def provenance(self) -> Dict[str, Any]:
        ...
