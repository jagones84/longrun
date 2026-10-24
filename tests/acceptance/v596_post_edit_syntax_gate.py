#!/usr/bin/env python3
"""v596 (RED) — Aider post-edit loop: zero-config Python syntax gate.

Aider runs a lint check after EVERY edit with zero configuration and feeds
the error back so the model fixes it in the next turn. Longrun has the
JAG-131 verifier (apply-only-if-green + rollback), but it is DISABLED by
default and needs an operator-configured command: out of the box a broken
Python edit is accepted silently and only discovered later.

The slice (dependency-verified: no py_compile/compile gate on fs.write /
fs.edit anywhere in src/longrun):
- `plan.verify.syntax_gate(tool, path, snap, res)` — pure helpers around
  the existing `restore()`: for `.py` targets under fs.write/fs.edit,
  `compile()` the new content; on SyntaxError/ValueError roll back to the
  pre-image and return a failure carrying the error (fix-and-retry, Aider
  style); green or out-of-scope passes `res` through untouched.
- `_verify_edit()` runs the syntax gate FIRST (zero-config — no verifier
  command needed), then the operator verifier unchanged.

Deterministic: isolated dirs, no model, no network.
Run: python3 tests/acceptance/v596_post_edit_syntax_gate.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp = tempfile.mkdtemp(prefix="lr-syntax-v596-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_DATA_DIR"] = _tmp
for d in ("cfg", "sessions"):
    os.makedirs(os.path.join(_tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.plan import verify as _v  # noqa: E402
from longrun.tools import tools as _tools  # noqa: E402
from longrun.tools import registry as _reg  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: the pure gate ---------------------------------------------------------
check("A1 verify.syntax_gate exists", callable(getattr(_v, "syntax_gate", None)))
gate = getattr(_v, "syntax_gate", None)
ws = os.path.join(_tmp, "ws")
os.makedirs(ws, exist_ok=True)
if callable(gate):
    good = os.path.join(ws, "good.py")
    with open(good, "w", encoding="utf-8") as f:
        f.write("x = 1\n")
    snap = {"exists": True, "content": "x = 1\n"}
    res = {"ok": True, "path": good}
    out, rep = gate("fs.edit", good, snap, res)
    check("A2 valid python passes through green",
          out.get("ok") is True and rep.get("ran") is True and rep.get("green") is True,
          repr(rep))
    bad = os.path.join(ws, "bad.py")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("def broken(:\n")
    snap = {"exists": True, "content": "x = 1\n"}
    res = {"ok": True, "path": bad}
    out, rep = gate("fs.edit", bad, snap, res)
    with open(bad, encoding="utf-8") as f:
        restored = f.read()
    check("A3 broken python fails with the error",
          out.get("ok") is False and "line" in str(out.get("error") or "").lower(),
          repr({k: out.get(k) for k in ("ok", "error")})[:200])
    check("A4 broken python is rolled back to the pre-image",
          restored == "x = 1\n" and rep.get("rolled_back") is True,
          repr(restored[:60]))
    txt = os.path.join(ws, "notes.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("def broken(:\n")
    out, rep = gate("fs.edit", txt, {"exists": True, "content": "def broken(:\n"},
                    {"ok": True, "path": txt})
    check("A5 non-python files are out of scope",
          out.get("ok") is True and rep.get("ran") is False, repr(rep))
    out, rep = gate("shell", good, snap, {"ok": True})
    check("A6 non-write/edit tools are out of scope",
          out.get("ok") is True and rep.get("ran") is False, repr(rep))
else:
    for n in ("A2", "A3", "A4", "A5", "A6"):
        check(n, False, "syntax_gate missing")

# ---- B: the tools honor the gate with zero config ------------------------------
_orig_spec = _reg.tool_spec


def _fake_spec(name):
    if name in ("fs.write", "fs.edit"):
        return {"roots": [ws]}
    return _orig_spec(name)


_tools.registry.tool_spec = _fake_spec
try:
    target = os.path.join(ws, "mod.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write("y = 2\n")
    r = _tools._fs_edit({"path": target, "search": "y = 2",
                         "replace": "def broken(:\n"}, "v596")
    with open(target, encoding="utf-8") as f:
        after = f.read()
    check("B1 _fs_edit with broken python fails",
          r.get("ok") is False and r.get("syntax_failed") is True,
          repr({k: r.get(k) for k in ("ok", "syntax_failed", "error")})[:200])
    check("B2 _fs_edit rolls back the broken edit", after == "y = 2\n",
          repr(after[:60]))
    r = _tools._fs_edit({"path": target, "search": "y = 2",
                         "replace": "y = 3"}, "v596")
    with open(target, encoding="utf-8") as f:
        after = f.read()
    check("B3 _fs_edit with valid python still applies",
          r.get("ok") is True and after == "y = 3\n",
          repr({k: r.get(k) for k in ("ok",)}) + " " + repr(after[:60]))
    r = _tools._fs_write({"path": os.path.join(ws, "new.py"),
                          "content": "def broken(:\n"}, "v596")
    check("B4 _fs_write with broken python fails and leaves no file",
          r.get("ok") is False and not os.path.exists(os.path.join(ws, "new.py")),
          repr({k: r.get(k) for k in ("ok", "syntax_failed")}))
finally:
    _tools.registry.tool_spec = _orig_spec

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
