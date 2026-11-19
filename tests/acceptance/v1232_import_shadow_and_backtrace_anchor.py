#!/usr/bin/env python3
"""v1232 — no local-import shadowing, and the backtrace anchor is a position.

Two defects from the review of the round-106+ HTTP endpoints:

  * a function-local `import` binds the name for the WHOLE function frame, so a
    later `from longrun.harness import manifest` turns every earlier branch that
    reads a global `manifest` into an `UnboundLocalError`. That is exactly the
    `list_sessions` failure already recorded at httpapi.py:2968. This module
    scans every function in `core/` for a NAME LOAD that precedes the first
    binding of that name, and requires the local imports in the new endpoint
    block to be aliased.
  * the `/backtrace?card=…` endpoint found the card's index with `c is card`.
    Object identity is not what `backtrace.explain` needs — a position in the
    same filtered card list is — and a handle whose resolver returned a copy
    left `anchor = None` and answered `200 anchor-not-found`.

Deterministic: static source scan + plain dicts; no server, no model.

Run: python3 tests/acceptance/v1232_import_shadow_and_backtrace_anchor.py
"""
import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores as S        # noqa: E402
from longrun.harness import backtrace as BT  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- A. a load before its first local binding is an UnboundLocalError ------
def _scan(body, imports, binds, loads):
    def visit(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            binds[node.name] = min(binds.get(node.name, 10 ** 9), node.lineno)
            return                      # its body is another scope
        if isinstance(node, ast.Lambda):
            return
        if isinstance(node, ast.Import):
            for a in node.names:
                name = a.asname or a.name.split(".")[0]
                imports[name] = min(imports.get(name, 10 ** 9), node.lineno)
            return
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == "*":
                    continue
                name = a.asname or a.name
                imports[name] = min(imports.get(name, 10 ** 9), node.lineno)
            return
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                loads.append((node.id, node.lineno))
            else:
                binds[node.id] = min(binds.get(node.id, 10 ** 9), node.lineno)
            return
        if isinstance(node, ast.ExceptHandler) and node.name:
            name = node.name if isinstance(node.name, str) else ""
            if name:
                binds[name] = min(binds.get(name, 10 ** 9), node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child)

    for stmt in body:
        visit(stmt)


def _hazards_src(text, label):
    tree = ast.parse(text, filename=label)
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        imports, binds, loads = {}, {}, []
        args = list(fn.args.posonlyargs) + list(fn.args.args) + list(fn.args.kwonlyargs)
        for a in args + [x for x in (fn.args.vararg, fn.args.kwarg) if x]:
            binds[a.arg] = min(binds.get(a.arg, 10 ** 9), fn.lineno)
        _scan(fn.body, imports, binds, loads)
        for name, imp in imports.items():
            first = min(binds.get(name, 10 ** 9), imp)
            for load, line in loads:
                if load == name and line < first:
                    out.append("%s:%d loads %r before its binding at %d"
                               % (label, line, name, first))
    return out


def _hazards(path):
    return _hazards_src(open(path, encoding="utf-8").read(), os.path.basename(path))


# The scanner's own oracle: the historical shape must be flagged.
_DEMO = ("def f(x):\n"
         "    if x:\n"
         "        return list_sessions()\n"
         "    from longrun.memory.stores import list_sessions\n"
         "    return []\n")
check("the scanner finds the historical list_sessions shape",
      bool(_hazards_src(_DEMO, "demo.py")))


CORE = os.path.join(REPO, "src", "longrun", "core")
_haz = []
for _name in sorted(os.listdir(CORE)):
    if _name.endswith(".py"):
        _haz.extend(_hazards(os.path.join(CORE, _name)))
check("no function reads a name before its own local binding", not _haz, _haz)

_http = open(os.path.join(CORE, "httpapi.py"), encoding="utf-8").read()
check("the new endpoint block aliases its local imports",
      all(("import %s as _%s" % (mod, mod)) in _http
          for mod in ("stopping", "skills_maintenance", "reuse", "residency",
                      "verification_transport", "backtrace", "invariants",
                      "manifest", "trace_export")))


# ---- B. the backtrace anchor is a POSITION in the filtered card list ------
CARDS = [{"id": "a1", "tool": "fs.read", "ok": True},
         {"id": "a2", "tool": "shell.exec", "ok": False, "exit_code": 1},
         {"id": "a3", "tool": "fs.write", "ok": True}]
SESS = {"tool_cards": CARDS, "messages": []}
idx = S.card_index_by_handle(SESS, "#a2")
check("a handle resolves to its position, not to object identity", idx == 1, idx)
check("the card resolver still returns the card object",
      S.card_by_handle(SESS, "a2") is CARDS[1])
check("an unknown handle has no position", S.card_index_by_handle(SESS, "zz") is None)

cards = [c for c in SESS["tool_cards"] if isinstance(c, dict)]
out = BT.explain(cards, idx)
check("the resolved position anchors the backtrace",
      out["anchor"] and out["anchor"]["handle"] == "a2", out)
check("a non-dict card cannot shift the anchor position",
      S.card_index_by_handle({"tool_cards": ["junk"] + CARDS}, "a2") == 1)

check("the endpoint anchors with the position resolver",
      "anchor = card_index_by_handle(sess, handle)" in _http)
check("no object-identity anchor scan remains", "if c is card" not in _http)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
