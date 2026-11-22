#!/usr/bin/env python3
"""v1272 — the core stays stdlib-only (ADR-0001), mechanically.

`docs/adr/0001-stdlib-only-core.md`: the core imports only the standard library, with
ONE documented exception — PyYAML, used to read the shipped `config/*.yaml`. Every
other third-party module (numpy, opentelemetry, psutil, the document extractors, the
voice stack, ...) must be an OPTIONAL import: lazily inside a function, or inside a
`try:` — so the app still starts without it installed.

Nothing enforced that before. The 2026-11-22 retro audited 339 modules in `src/longrun`
and found 15 distinct third-party top-level modules, all optional except PyYAML — true
today, with no guard against the next `import numpy` written at module level (it would
make the app hard-require a package the docs promise is optional). This pin IS that guard.

The classifier is deliberately simple and explainable: an import at column 0 is
module-level ("hard"); an indented one lives in a `try:` / a function / an `if`, so it is
guarded. Three synthetic self-tests prove the classifier still tells them apart, so the
pin can never pass vacuously when the AST logic rots.

Deterministic: no server, no model, no network.
Run: python3 tests/acceptance/v1272_stdlib_only_core.py
"""
import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORE = os.path.join(REPO, "src", "longrun")
ALLOWED_HARD = {"yaml"}          # ADR-0001: the one documented exception (PyYAML)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


_STDLIB = set(getattr(sys, "stdlib_module_names", ()))
_LOCAL = {d for d in os.listdir(CORE) if os.path.isdir(os.path.join(CORE, d))}


def _third_party(names):
    for n in names:
        top = (n or "").split(".")[0]
        if top and top not in _STDLIB and top not in _LOCAL and top != "longrun":
            yield top


def scan(source):
    """-> (hard, optional): third-party top-level imports, module-level vs guarded."""
    hard, optional = [], []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            mods = [node.module or ""]
        else:
            continue
        bucket = hard if node.col_offset == 0 else optional
        for top in _third_party(mods):
            bucket.append(top)
    return hard, optional


# ---- 0. the classifier still tells hard from guarded (anti-vacuity) ---------
_h, _o = scan("import numpy\n")
check("self-test: a module-level import is HARD", _h == ["numpy"] and not _o, "hard=%s" % _h)
_h, _o = scan("try:\n    import numpy\nexcept ImportError:\n    numpy = None\n")
check("self-test: an indented (try) import is OPTIONAL", _o == ["numpy"] and not _h, "opt=%s" % _o)
_h, _o = scan("def f():\n    import numpy\n    return numpy\n")
check("self-test: a lazy (in-function) import is OPTIONAL", _o == ["numpy"] and not _h, "opt=%s" % _o)

# ---- 1. scan the real core --------------------------------------------------
hard, optional = [], []
files = 0
for dp, _, fs in os.walk(CORE):
    if "__pycache__" in dp:
        continue
    for f in fs:
        if not f.endswith(".py"):
            continue
        files += 1
        path = os.path.join(dp, f)
        with open(path, encoding="utf-8") as fh:
            h, o = scan(fh.read())
        hard += [(t, path) for t in h]
        optional += o

check("the scan really read the core", files >= 200, "files=%d" % files)
check("the scan sees the guarded imports too (it is not blind)",
      len(optional) >= 10, "optional=%d" % len(optional))

# ---- 2. the invariant -------------------------------------------------------
hard_set = sorted({t for t, _ in hard})
unexpected = [t for t in hard_set if t not in ALLOWED_HARD]
check("no third-party module is a HARD import (ADR-0001)",
      not unexpected,
      "offenders=%s" % ([(t, os.path.relpath(p, REPO)) for t, p in hard] or "none"))
check("PyYAML really is used (the documented exception is not stale)",
      "yaml" in hard_set or "yaml" in optional, "hard=%s" % hard_set)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
