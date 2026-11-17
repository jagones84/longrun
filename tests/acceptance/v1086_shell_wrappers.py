#!/usr/bin/env python3
"""v1086 — the purity gate reads the COMMAND, not the wrapper (round 17).

Round 15 (v1084) made a shell card replayable only when its command is pure.
Measured 2026-11-18 on the live store: 1076 shell commands, 437 pure; among the
refusals the shape was often a pure read behind a lead-in — `timeout` 41,
`VAR=x` 16, `rg` 16, `git -C`/`git branch -a` 15, and 142 `'<'` of which the
heredocs were already-refused interpreters. So the gate under-counted reads it
could PROVE.

Round 17 teaches it to look through the lead-ins and to read `< file` for what
it is, while every spelling that can change something stays refused:

  * wrappers `VAR=x`, `timeout [-s SIG] [-k DUR] DURATION`, `env`, `time`
  * `rg`, with `--pre` refused (it executes a command per file)
  * `git` global options (`-C`, `-c`, `--git-dir`, `--work-tree`, `--no-pager`)
    and the read-only forms of `branch`, `remote`, `reflog`, `stash`,
    `worktree`, `fsck`, `check-ignore`
  * `< plainfile` is a READ; `<<`, `<>`, `<&`, `<(` and `/dev/tcp|/dev/udp` are not

Contract:
  W  wrappers are unwrapped; an unparseable wrapper refuses
  G  git reads are allowed, git writes are not
  R  input redirects: a plain file is pure, every other spelling is not
  H  ripgrep is a read except its command-executing flag
  X  the corpus shape: these are the live spellings, not invented ones
  O  the counterfactual gate uses the same predicate (no second truth)

Deterministic: no server, no model, no store write.
Run: python3 tests/acceptance/v1086_shell_wrappers.py
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


def pure(cmd):
    return SR.reads_only(cmd)


# ---- W: the lead-ins --------------------------------------------------------
WRAPPED_PURE = [
    "timeout 5 grep -n x f",
    "timeout 30 git status",
    "timeout -s KILL 2 cat f",
    "timeout --signal=TERM 1s ls",
    "env PYTHONPATH=src rg -n x src",
    "env -i FOO=1 cat f",
    "env -u HOME grep x f",
    "env",
    "PYTHONPATH=src grep -rn x src",
    "FOO=1 BAR=2 wc -l f",
    "time grep -c x f",
    "time -p ls",
    "cd /repo && timeout 10 git -C sub status",
    "timeout 5 ls -la | head -3",
]
for cmd in WRAPPED_PURE:
    got, why = pure(cmd)
    check("W1 pure behind a lead-in: %r" % cmd[:44], got is True, why)

WRAPPED_IMPURE = [
    "timeout 5 python3 x.py",
    "timeout 5 rm f",
    "timeout 5",
    "timeout",
    "env FOO=1 bash -c 'rm x'",
    "env -S 'cat f'",
    "env -X cat f",
    "timeout -Z 5 cat f",
    "PYTHONPATH=src python3 -m pytest",
    "FOO=1 make",
]
for cmd in WRAPPED_IMPURE:
    got, why = pure(cmd)
    check("W2 still refused: %r" % cmd[:44], got is False and bool(why), (got, why))

check("W3 the refusal names the wrapper",
      "timeout option" in pure("timeout -Z 5 cat f")[1], pure("timeout -Z 5 cat f"))
check("W4 `env` alone is the same read as printenv",
      pure("env")[0] is True and pure("printenv")[0] is True)

# ---- G: git reads -----------------------------------------------------------
GIT_PURE = [
    "git -C repo log --oneline -5",
    "git -c core.pager=cat log -1",
    "git --no-pager diff",
    "git --git-dir=.git status",
    "git branch",
    "git branch -a",
    "git branch -av",
    "git branch --show-current",
    "git branch --format='%(refname)'",
    "git remote",
    "git remote -v",
    "git remote show origin",
    "git remote get-url origin",
    "git reflog",
    "git reflog -5",
    "git reflog show --all",
    "git stash list",
    "git stash show -p",
    "git worktree list",
    "git fsck",
    "git check-ignore -v data/x",
]
for cmd in GIT_PURE:
    got, why = pure(cmd)
    check("G1 git read: %r" % cmd[:44], got is True, why)

GIT_IMPURE = [
    "git commit -m x",
    "git checkout -- .",
    "git branch new",
    "git branch -D old",
    "git branch -m a b",
    "git remote add origin u",
    "git remote remove origin",
    "git remote prune origin",
    "git remote set-url origin u",
    "git reflog expire --all",
    "git reflog delete HEAD@{1}",
    "git stash",
    "git stash pop",
    "git stash drop",
    "git worktree add /tmp/x",
    "git worktree prune",
    "git fsck --lost-found",
    "git -C repo commit -m x",
    "git --git-dir=.git gc",
]
for cmd in GIT_IMPURE:
    got, why = pure(cmd)
    check("G2 git write refused: %r" % cmd[:44], got is False and bool(why), (got, why))

# ---- R: input redirection ---------------------------------------------------
check("R1 `< plainfile` is a read",
      pure("cat < f")[0] is True, pure("cat < f"))
check("R2 it composes with a pipe",
      pure("grep -n x < f | head -3")[0] is True, pure("grep -n x < f | head -3"))
check("R3 a quoted `<` is an argument, not a redirect",
      pure("grep -n '<div>' f")[0] is True, pure("grep -n '<div>' f"))
check("R4 a quoted `>` is an argument too",
      pure("grep -n '->' f.py")[0] is True, pure("grep -n '->' f.py"))
for cmd, why in [
    ("cat <<EOF", "heredoc"),
    ("cat <<'PY'", "heredoc"),
    ("cat <> f", "read-write"),
    ("cat <&0", "descriptor"),
    ("cat < <(echo x)", "substitution"),
    ("cat < /dev/tcp/host/1", "network"),
    ("cat <", "target"),
]:
    got, reason = pure(cmd)
    check("R5 %r refused (%s)" % (cmd[:40], why),
          got is False and why in reason.lower(), (got, reason))

# ---- H: ripgrep -------------------------------------------------------------
check("H1 rg is a read", pure("rg -n 'def f' src/")[0] is True)
check("H2 rg --pre executes a command and is refused",
      pure("rg --pre ./x pat")[0] is False
      and "pre" in pure("rg --pre ./x pat")[1])
check("H3 rg --pre=<cmd> is refused too",
      pure("rg --pre=./x pat")[0] is False)

# ---- X: the live corpus shape (the spellings this round measured) -----------
LIVE_SHAPES = [
    "cd /repo && timeout 600 python3 -m pytest tests -q 2>&1 | tail -2",  # interpreter
    "cd /repo && PYTHONPATH=src python3 -m pytest tests -q",              # interpreter
    "cd /repo && git -C workspace/mini-agent rev-parse --show-toplevel",
    "cd /repo && git branch -a && git remote -v && git worktree list",
    "cd /repo && git reflog -5 2>/dev/null | head -5",
    "timeout 15 ssh -o BatchMode=yes win 'echo alive'",                   # ssh
]
EXPECT = [False, False, True, True, True, False]
for cmd, want in zip(LIVE_SHAPES, EXPECT):
    got, why = pure(cmd)
    check("X1 live shape %r -> %s" % (cmd[:40], want), got is want, (got, why))

# ---- O: one implementation --------------------------------------------------
CARD = {"tool": "shell", "args": '{"command": "timeout 5 cat src/a.py"}'}
p = CF.plan(CARD, {"command": "timeout 5 cat src/b.py"})
check("O1 the counterfactual accepts a wrapped pure card", "error" not in p, p)
check("O2 and names the purity it relied on",
      "shell command" in (p.get("purity") or ""), p.get("purity"))
d = CF.plan(CARD, {"command": "timeout 5 cat src/a.py > out"})
check("O3 a change that adds an output redirect is refused",
      "not pure" in (d.get("error") or ""), d.get("error"))
d = CF.plan({"tool": "shell", "args": {"command": "git stash list"}},
            {"command": "git stash pop"})
check("O4 a read recorded and a write proposed is refused",
      "not pure" in (d.get("error") or ""), d.get("error"))

print("\n---\nv1086: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
