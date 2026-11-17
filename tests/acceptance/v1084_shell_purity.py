#!/usr/bin/env python3
"""v1084 — a shell command may be REPLAYED only when it is provably pure.

Round 11 shipped the step-level counterfactual but could only accept
`fs.read`/`glob`/`diff`, and the live corpus had **zero** cards of those kinds:
agents read through `shell.exec`. Measured 2026-11-18 on the live store —
1076 shell commands in 138 sessions, first words `cd` 675, `python3` 63,
`grep` 46, `sed` 43 — so the instrument had no eligible card at all.

The fix is not "allow shell": it is a PURITY GATE. `harness.shellread.reads_only`
answers one question — can re-running this command change the environment? — and
the counterfactual accepts a shell card only when BOTH the recorded command and
the changed one are pure. Replaying a write is not an intervention, it is a
second experiment (REFLECT, arXiv:2606.09071: a diagnosis-specific patch whose
descendants are pure is what makes the outcome flip evidence).

`looks_read_only` moves here too: it is the LENIENT hint the read-back gate asks
("did the turn look at what it wrote?"), and its truth table must not drift.

Contract:
  P  the strict gate: allow only provable reads; refuse every write spelling
  L  the legacy hint keeps its exact truth table (moved, not rewritten)
  C  the counterfactual accepts a pure shell card and refuses an impure one
  O  one owner for the predicate (`agent` delegates to this module)
  X  coverage on a fixed corpus: the gate is not vacuous, and it refuses

Deterministic: no server, no model, no store write.
Run: python3 tests/acceptance/v1084_shell_purity.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import counterfactual as CF  # noqa: E402
from longrun.harness import shellread as SR  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- P: the strict gate ------------------------------------------------------
PURE = [
    "ls -la",
    "cat README.md",
    "cd /repo && grep -n 'def f' src/a.py",
    "grep -rn needle src/ | head -20",
    "sed -n '315,340p' src/x.py",
    "sed -n 2330,2360p src/longrun/core/httpapi.py",
    "sed -n '/^def _install_bundle/,/^def /p' src/a.py",
    "git status --short",
    "git diff --stat -- src/",
    "git log --oneline -5",
    "wc -l src/a.py && head -3 src/a.py",
    "find . -name '*.py' -type f",
    "stat -c %s f && md5sum f",
    "echo '--- tests ---' && ls tests/",
    "pytest 2>/dev/null | tail -5",       # not reached: pytest is not a read verb
    "cd /repo && git diff -- x.py 2>/dev/null | sed -n '40,140p'",
]
PURE_EXPECT = [True] * 14 + [False, True]

IMPURE = [
    "ls > out.txt",
    "ls >> out.txt",
    "ls 2> err.txt",
    "ls &> both.txt",
    "ls >/dev/null/x",
    "cat < secret",
    "echo x | tee out.txt",
    "sort -o out.txt in.txt",
    "find . -delete",
    "find . -name '*.py' -exec rm {} +",
    "git commit -m 'x'",
    "git checkout -- .",
    "sed -i 's/a/b/' f",
    "sed -n 's/a/b/w out.txt' f",
    "sed -n 's/a/b/e' f",
    "sed '1,5p' f",                        # no -n: echoes the file
    "python3 -c 'open(\"x\",\"w\")'",
    "python3 - <<'PY'\nprint(1)\nPY",
    "bash -lc 'rm -rf /tmp/x'",
    "sh script.sh",
    "xargs rm",
    "timeout 5 rm f",
    "curl -o out https://x",
    "for f in *.py; do rm $f; done",
    "echo $(date) > f",
    "echo `whoami`",
    "awk '{print}' f",
    "make",
    "mkdir d",
    "cp a b",
    "cd /repo && grep x f | xargs wc -l",
    "",
]
for cmd, want in zip(PURE, PURE_EXPECT):
    got, why = SR.reads_only(cmd)
    check("P1 pure: %r" % cmd[:44], got is want, (got, why))

for cmd in IMPURE:
    got, why = SR.reads_only(cmd)
    check("P2 impure: %r" % (cmd[:44] or "(empty)"), got is False and bool(why), (got, why))

check("P3 a refusal names its reason",
      "not a read-only verb" in SR.reads_only("rm f")[1], SR.reads_only("rm f"))
check("P4 a bad quote is refused, not crashed",
      SR.reads_only("cat 'unclosed")[0] is False, SR.reads_only("cat 'unclosed"))
check("P5 quoted separators are not split",
      SR.reads_only("grep -n 'a|b' f.py")[0] is True, SR.reads_only("grep -n 'a|b' f.py"))
check("P6 stderr discard is pure, stdout redirect is not",
      SR.reads_only("ls 2>/dev/null")[0] is True
      and SR.reads_only("ls 2>/dev/null > f")[0] is False)

# ---- L: the legacy hint is moved, not rewritten ------------------------------
LEGACY = [("cat f", True), ("echo x", False), ("echo x; cat f", True),
          ("cat f > out", False), ("ls | head", True), ("grep x f", False),
          ("rm f", False), ("tee x", False), ("cat f && rm g", False),
          ("", False), ("sed -i s/a/b/ f", False), ("diff a b", True)]
for cmd, want in LEGACY:
    got = SR.looks_read_only(cmd)
    check("L1 hint: %r" % (cmd or "(empty)"), got is want, got)

# ---- C: the counterfactual gate ---------------------------------------------
SHELL_CARD = {"tool": "shell", "args": '{"command": "cat src/a.py"}'}
p = CF.plan(SHELL_CARD, {"command": "cat src/b.py"})
check("C1 a pure shell card is accepted", "error" not in p, p)
check("C2 the plan names the purity it relied on",
      "shell command" in (p.get("purity") or ""), p.get("purity"))
check("C3 the changed command is the one replayed",
      p.get("args", {}).get("command") == "cat src/b.py", p.get("args"))

d = CF.plan({"tool": "shell", "args": {"command": "rm -rf build"}}, {"command": "rm -rf dist"})
check("C4 a mutating recorded command is refused",
      "not pure" in (d.get("error") or ""), d.get("error"))
d = CF.plan({"tool": "shell.exec", "args": {"command": "cat a"}}, {"command": "cat a > b"})
check("C5 a change that turns a read into a write is refused",
      "must not turn a read into an effect" in (d.get("error") or ""), d.get("error"))
d = CF.plan(SHELL_CARD, {"command": "cat src/a.py"})
check("C6 a no-op change is still refused",
      "does not differ" in (d.get("error") or ""), d.get("error"))
d = CF.plan({"tool": "fs.write", "args": {"path": "x"}}, {"path": "y"})
check("C7 a writer tool is still refused", "not read-only" in (d.get("error") or ""), d.get("error"))
p = CF.plan({"tool": "fs.read", "args": {"path": "a.py"}}, {"path": "b.py"})
check("C8 an fs.read card still works and says so",
      p.get("tool") == "fs.read" and p.get("purity") == "read-only tool", p)
check("C9 the shell tools are the ones the loop emits",
      {"shell", "shell.exec", "terminal"} <= CF.SHELL_TOOLS, CF.SHELL_TOOLS)

# ---- O: one owner -----------------------------------------------------------
from longrun.core import server as _srv  # noqa: E402,F401 — import order (agent cycle)
from longrun.agent import agent as AG  # noqa: E402
check("O1 agent's predicate delegates to the one implementation",
      AG._shell_looks_read_only("cat f") == SR.looks_read_only("cat f")
      and AG._shell_looks_read_only("cat f > x") == SR.looks_read_only("cat f > x"))
check("O2 agent no longer carries its own verb tuples",
      not hasattr(AG, "_SHELL_READ_VERBS") and not hasattr(AG, "_SHELL_WRITE_HINTS"))

# ---- X: coverage on a fixed corpus -----------------------------------------
CORPUS = [
    "cd /r && grep -n x a.py", "cd /r && sed -n 1,20p b.py", "ls -l",
    "cat c.md", "git status", "python3 -m pytest -q", 'python3 - <<\'PY\'\nprint(1)\nPY',
    "cd /r && sed -i s/a/b/ d.py", "curl https://x", "wc -l e.py",
]
pure = sum(1 for c in CORPUS if SR.reads_only(c)[0])
check("X1 the corpus has both outcomes (the gate is not vacuous)",
      pure == 6, pure)
check("X2 the corpus ratio is pinned",
      pure / float(len(CORPUS)) == 0.6, pure / float(len(CORPUS)))

print("\n---\nv1084: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
