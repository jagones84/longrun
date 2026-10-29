#!/usr/bin/env python3
"""v724 — the forged tool's proof is BEHAVIOURAL, so a rewrite cannot sneak past (EV-19).

arXiv 2610.15964 ("Small but Mighty"): verifying a rewrite with sparse checks lets
behaviour-changing rewrites through — the repository's own tests rejected only
25.3% of them. Our generated proof used to pin ONLY the refusals, so a tool whose
step order, argument passthrough or stop-on-failure changed would still pass.

  A  the generated proof runs green on the bytes a forge writes
  B  swapping two steps is REJECTED (order is pinned)
  C  dropping the caller's arguments is REJECTED (passthrough is pinned)
  D  continuing after a failed step is REJECTED (stop is pinned)
  E  restoring the original bytes is green again (the proof is about the bytes)
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v724-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.environ["LONGRUN_MATRIX_SRC"] = os.path.join(TMP, "src", "Matrix")
os.environ["LONGRUN_MATRIX_DOT"] = os.path.join(TMP, ".Matrix")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve as SE  # noqa: E402
from longrun.core import matrix as MTX  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


PATTERN = ["fs.read", "fs.edit", "shell.exec"]
r = SE.forge_matrix(PATTERN, support=4, name="learned_proof_v724")
check("A0 the forge itself is green", r.get("ok") is True, r)
ns, full = "learned_proof_v724", r.get("matrix_tool")
path = r.get("path") or ""
original = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
check("A1 the forge already ran the new proof", (r.get("test") or {}).get("ok") is True
      and "behaviour pinned" in str((r.get("test") or {}).get("stdout")), r.get("test"))

PROOF = SE._forge_test(ns, full, PATTERN)


def proof_of_current_bytes(label, mutate):
    """Rewrite the module with `mutate(body)` and run the SAME generated proof."""
    body = mutate(original)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    out = MTX.run_test("v724_%s.py" % label, code=PROOF, target="tool:%s" % ns,
                       timeout_secs=60) or {}
    return out


def swap_steps(body):
    return body.replace("STEPS = %r" % PATTERN, "STEPS = %r" % [PATTERN[1], PATTERN[0],
                                                               PATTERN[2]])


def drop_args(body):
    # the step receives the caller's object; ignore it entirely
    return body.replace("res = _tools.execute(name, step_args, run_id=run_id) or {}",
                        "res = _tools.execute(name, {}, run_id=run_id) or {}")


def keep_going(body):
    return body.replace("        if not ok:\n            break\n", "        if not ok:\n            pass\n")


out = proof_of_current_bytes("order", swap_steps)
check("B1 a swapped step order is REJECTED", out.get("ok") is False, out)
out = proof_of_current_bytes("args", drop_args)
check("C1 ignoring the caller's arguments is REJECTED", out.get("ok") is False, out)
out = proof_of_current_bytes("stop", keep_going)
check("D1 continuing after a failed step is REJECTED", out.get("ok") is False, out)
with open(path, "w", encoding="utf-8", newline="\n") as f:
    f.write(original)
out = MTX.run_test("v724_restore.py", code=PROOF, target="tool:%s" % ns,
                   timeout_secs=60) or {}
check("E1 the original bytes are green again", out.get("ok") is True, out)

MTX.remove("tool", ns)
print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
