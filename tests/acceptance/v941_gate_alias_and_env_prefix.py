#!/usr/bin/env python3
"""v941 — an action ALIAS cannot walk around a gated policy row, and a `VAR=`
prefix cannot hide a hard-denied command.

Two defects, one door (`registry`):

  A  `canonical_name` only remapped `<ns>.<action>` when that exact name was a
     canonical schema. The handlers accept aliases the enum does not advertise
     (`delete`, `write_core`, `uninstall`, …), so `memory{action:"delete"}`
     resolved to the plain `memory` namespace — whose row is `approval: auto` —
     and the `memory.forget: required` row was never consulted: a permanent
     delete, or a rewrite of the CORE block injected into every prompt, ran with
     no card. One alias table (`_ACTION_ALIASES`) now feeds `canonical_name`, and
     `classify` judges the call under the name the execute door runs.
  B  `_ENV_ASSIGN_RE` stripped an assignment with `\\S*`, so in `X=1;rm -rf /`
     the value swallowed the rest of the command and the hard-deny regexes saw
     only `-rf /`: the documented "never executed, even with approval" block was
     gone. The value now stops at `;`, `&` and `|`.

Deterministic: temp dirs, approvals.mode pinned to normal, no server, no model,
no network.
Run: python3 tests/acceptance/v941_gate_alias_and_env_prefix.py
"""

import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="sf-v941-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as REG  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def classify(tool, args):
    """classify() with approvals.mode pinned to normal (the gate under test)."""
    return REG.classify(tool, args)


_cfg = REG.load_config(reload=True)
_cfg.setdefault("approvals", {})["mode"] = "normal"

with REG.scoped_config(_cfg):
    # --- A. alias canonicalisation --------------------------------------------
    check("A1 memory/delete canonicalises onto memory.forget",
          REG.canonical_name("memory", {"action": "delete"}) == "memory.forget",
          REG.canonical_name("memory", {"action": "delete"}))
    check("A2 memory/erase canonicalises onto memory.forget",
          REG.canonical_name("memory", {"action": "erase"}) == "memory.forget")
    check("A3 memory/write_core canonicalises onto memory.set_core",
          REG.canonical_name("memory", {"action": "write_core"}) == "memory.set_core")
    check("A4 memory/core_write canonicalises onto memory.set_core",
          REG.canonical_name("memory", {"action": "core_write"}) == "memory.set_core")
    check("A5 memory/read_core canonicalises onto memory.core (read-only)",
          REG.canonical_name("memory", {"action": "read_core"}) == "memory.core")
    check("A6 matrix/uninstall canonicalises onto matrix.remove",
          REG.canonical_name("matrix", {"action": "uninstall"}) == "matrix.remove")
    check("A7 a canonical spelling is unchanged",
          REG.canonical_name("memory", {"action": "forget"}) == "memory.forget")
    check("A8 a name that is already dotted is unchanged",
          REG.canonical_name("memory.forget", {"action": "delete"}) == "memory.forget")

    _d, _r = classify("memory", {"action": "delete", "target": "m-1"})
    check("A9 deleting a memory through the alias now needs approval", _d == "required", _r)
    _d, _r = classify("memory", {"action": "forget", "target": "m-1"})
    check("A10 the canonical spelling takes the same decision", _d == "required", _r)
    _d, _r = classify("memory", {"action": "write_core", "content": "x"})
    check("A11 rewriting CORE memory through the alias needs approval", _d == "required", _r)
    _d, _r = classify("matrix", {"action": "uninstall", "kind": "tool", "name": "x"})
    check("A12 removing a Matrix module through the alias needs approval", _d == "required", _r)
    _d, _r = classify("memory", {"action": "recall", "query": "x"})
    check("A13 ordinary recall stays automatic", _d == "auto", _r)

    # --- B. the assignment prefix ---------------------------------------------
    _subj = REG._subject("shell", {"command": "X=1;rm -rf /"})
    check("B1 a `;` after the assignment keeps the command in the subject",
          "rm -rf /" in _subj, _subj)
    _d, _r = classify("shell", {"command": "X=1;rm -rf /"})
    check("B2 `X=1;rm -rf /` is DENIED (hard block, not a card)", _d == "denied", _r)
    _d, _r = classify("shell", {"command": "X=1;dd if=/dev/zero of=/dev/sda"})
    check("B3 `X=1;dd if=/dev/zero …` is DENIED", _d == "denied", _r)
    _subj = REG._subject("shell", {"command": "TZ=Europe/Rome date '+%H'"})
    check("B4 a plain `VAR=value` prefix is still stripped (JAG-85)",
          _subj.startswith("date"), _subj)
    _subj = REG._subject("shell", {"command": 'X="a b" ls'})
    check("B5 a quoted assignment is still stripped", _subj == "ls", _subj)
    _subj = REG._subject("shell", {"command": "A=1 B=2 ls -la"})
    check("B6 multiple assignments are still stripped", _subj == "ls -la", _subj)
    _subj = REG._subject("shell", {"command": "FOO=x|cat /etc/passwd"})
    check("B7 a `|` after the assignment keeps the pipe in the subject",
          "cat /etc/passwd" in _subj, _subj)
    _subj = REG._subject("shell", {"command": "FOO=x&rm -rf ~"})
    check("B8 an `&` after the assignment keeps the command in the subject",
          "rm -rf ~" in _subj, _subj)

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
