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
