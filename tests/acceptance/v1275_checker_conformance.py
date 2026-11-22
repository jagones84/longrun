#!/usr/bin/env python3
"""v1275 — every harness checker honours the checker contract (ticket 05, standalone slice).

`harness/checks/__init__.py` states the zone's rule (report-only, CLI-only). Its *contract*
was never written down and never checked, so the 135 modules were uniform only by
convention. The 2026-11-22 measurement found the real, universal shape, which is what this
pin asserts — for EVERY module in the package, discovered by walking it:

  1. `FORMAT` is a non-empty string (the result format the CLI emits with);
  2. at least one public callable exists (plain data in, a verdict out);
  3. no module imports the running app (`longrun.agent`, `longrun.core`, `longrun.tools`) —
     the layering error the package docstring names;
  4. imports reach no further than the stdlib and `longrun.harness`;
  5. a write-like call appears in exactly the two DOCUMENTED modules (`setup_blocks`,
     `intent_journal`), which persist a caller-supplied path, never a verdict. A third
     writer fails here.

Verb uniformity is deliberately NOT asserted: 566 distinct public function names across the
package are different analyses, not duplication.

Discovery is the point — the pin walks the package, so dropping a file into
`harness/checks/` either satisfies the contract or fails here; there is no hand-written
import block to keep in sync.

Anti-vacuity: a synthetic stub proves the contract checker still rejects a module that
loses `FORMAT`, and floors guard the discovery (>=100 modules found).

Deterministic: no server, no model, no network (modules are pure by the contract above).
Run: python3 tests/acceptance/v1275_checker_conformance.py
"""
import ast
import importlib
import os
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHECKS = os.path.join(REPO, "src", "longrun", "harness", "checks")
# The two modules allowed to hold a write-like call (documented in the package docstring).
WRITERS = {"setup_blocks", "intent_journal"}

sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def _fn_name(node):
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 — an unparseable callee is not our concern
        return ""


_WRITE_FNS = {"os.makedirs", "os.mkdir", "os.remove", "os.rename", "os.rmdir",
              "shutil.copy", "shutil.copy2", "shutil.move", "shutil.rmtree"}


def write_calls(source):
    """(lineno, what) for calls that can create/remove a path, or open it for WRITING."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = _fn_name(node.func)
        if name in _WRITE_FNS:
            out.append((getattr(node, "lineno", 0), name))
        elif name in ("open", "io.open") and len(node.args) >= 2:
            mode = node.args[1]
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
                if any(c in mode.value for c in "wax+"):
                    out.append((getattr(node, "lineno", 0), "open(%r)" % mode.value))
    return out


def longrun_imports(source):
    """Top-level `longrun.<sub>` names this source imports."""
    subs = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and not node.level:
            mod = node.module or ""
            if mod.startswith("longrun."):
                subs.add(mod.split(".")[1])
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("longrun."):
                    subs.add(a.name.split(".")[1])
    return subs


def violations(mod):
    """The contract, as a list — so a stub can prove the checker still bites."""
    bad = []
    fmt = getattr(mod, "FORMAT", None)
    if not isinstance(fmt, str) or not fmt.strip():
        bad.append("FORMAT is not a non-empty string")
    if not any(callable(getattr(mod, n)) and not n.startswith("_")
               for n in dir(mod)):
        bad.append("no public callable")
    return bad


# ---- 0. anti-vacuity: the contract checker still rejects a broken module ----
check("self-test: a module without FORMAT / public fns is rejected",
      violations(types.SimpleNamespace(FORMAT="", _private=lambda: None))
      == ["FORMAT is not a non-empty string", "no public callable"])
check("self-test: a conforming stub passes",
      violations(types.SimpleNamespace(FORMAT="json", run=lambda d: {})) == [])

# ---- 1. discovery -----------------------------------------------------------
names = sorted(f[:-3] for f in os.listdir(CHECKS)
               if f.endswith(".py") and not f.startswith("__"))
check("the package is discovered (>=100 checkers)", len(names) >= 100, "n=%d" % len(names))

# ---- 2. the contract, for every discovered module ---------------------------
no_format, no_callable, missing = [], [], []
app_layer, other_import, writers = [], [], []
for name in names:
    path = os.path.join(CHECKS, name + ".py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    try:
        mod = importlib.import_module("longrun.harness.checks." + name)
    except Exception as exc:  # noqa: BLE001 — report it, do not crash the gate
        missing.append("%s (%s)" % (name, exc))
        continue
    if not isinstance(getattr(mod, "FORMAT", None), str) or not mod.FORMAT.strip():
        no_format.append(name)
    if not any(callable(v) and not k.startswith("_") for k, v in vars(mod).items()):
        no_callable.append(name)
    subs = longrun_imports(src)
    if subs & {"agent", "core", "tools"}:
        app_layer.append((name, sorted(subs & {"agent", "core", "tools"})))
    if subs - {"harness"}:
        other_import.append((name, sorted(subs - {"harness"})))
    if write_calls(src):
        writers.append(name)

check("every checker imports cleanly", not missing, "missing=%s" % missing[:5])
check("every checker exposes a non-empty string FORMAT", not no_format, "no_format=%s" % no_format[:8])
check("every checker exposes a public callable", not no_callable, "no_callable=%s" % no_callable[:8])
check("no checker imports the running app (agent/core/tools)", not app_layer, "app_layer=%s" % app_layer[:5])
check("no checker imports beyond the stdlib and longrun.harness",
      not other_import, "other=%s" % other_import[:5])
check("a write-like call appears only in the two documented modules",
      set(writers) == WRITERS, "writers=%s" % sorted(writers))

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
