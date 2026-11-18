#!/usr/bin/env python3
"""v1121 — the Nucleous write guard reads redirections OUTSIDE quotes only.

Round 55. The register's `shell.exec · permission` row carries six
`NUCLEOUS_PROTECTED: … unresolvable target` refusals whose commands never write:
a `>` INSIDE a quoted string was tokenized as a redirect, and the token after it
(`$`, `` ` ``, `$(cat`) failed the fail-closed variable rule.

    for f in $(find data -name published.txt); do echo "$f -> $(cat $f)"; done
    for p in 8080 …; do code=$(curl …); echo "port $p -> $code"; done
    printf '%s -> %s\\n' a b

Reading is not writing: a `>` inside single/double quotes is literal. The guard
still refuses every real write, and it still descends into command substitution
(and backticks) — `echo "$(echo x > src/…)"` is a write through expansion.

  A  a quoted `>` (arrow / literal) is not a redirect
  B  an unquoted redirect into the Nucleous / to a variable is still refused
  C  a redirect inside `$(...)` or backticks is still seen, even inside quotes
  D  a real write outside the repository stays allowed
  E  the write verbs keep their behaviour
  F  a quoted `>` beside a real redirect keeps the real one

Deterministic: temp repo, no process, no model, no server.
Run: python3 tests/acceptance/v1121_guard_quoted_redirect.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import matrix_guard  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


tmp = tempfile.mkdtemp(prefix="sf-1121-")
os.makedirs(os.path.join(tmp, "src", "longrun", "core"), exist_ok=True)
with open(os.path.join(tmp, "src", "longrun", "core", "server.py"), "w",
          encoding="utf-8") as fh:
    fh.write("# nucleous\n")
os.makedirs(os.path.join(tmp, "data"), exist_ok=True)


def allowed(cmd):
    ok, err = matrix_guard.check_shell_command(cmd, cwd=tmp, repo_root=tmp)
    return ok, err


# A — a quoted `>` is literal.
for name, cmd in (
        ("A1 an arrow inside a loop is not a redirect",
         'for f in $(find data -name x); do echo "$f -> $(cat $f)"; done'),
        ("A2 a quoted `>` is not a redirect", 'echo "a > b"'),
        ("A3 a single-quoted `>` is not a redirect", "echo 'x > y'"),
        ("A4 a printf format with an arrow", "printf '%s -> %s\\n' a b"),
        ("A5 a quoted arrow beside text", 'echo "port $p -> $code"')):
    ok, err = allowed(cmd)
    check(name, ok, err)

# B — real redirects are still refused.
ok, err = allowed("echo x > src/longrun/core/server.py")
check("B1 an unquoted redirect into the Nucleous is refused",
      not ok and "NUCLEOUS_PROTECTED" in err, err)
ok, err = allowed('echo x > "$OUT"')
check("B2 a redirect to a variable is refused (fail closed)",
      not ok and "unresolvable" in err, err)

# C — expansion is still descended into, even inside double quotes.
ok, err = allowed('echo "$(echo x > src/longrun/core/server.py)"')
check("C1 a redirect inside $() is seen through double quotes",
      not ok and "NUCLEOUS_PROTECTED" in err, err)
ok, err = allowed('echo "`echo x > src/longrun/core/server.py`"')
check("C2 a redirect inside backticks is seen through double quotes",
      not ok and "NUCLEOUS_PROTECTED" in err, err)

# D — a write outside the repository stays allowed.
ok, err = allowed("echo x > /tmp/sf-1121-out.txt")
check("D1 a redirect outside the repository is allowed", ok, err)

# E — the write verbs.
ok, err = allowed("cp a src/longrun/core/server.py")
check("E1 cp into the Nucleous is refused", not ok and "NUCLEOUS_PROTECTED" in err, err)
ok, err = allowed("rm src/longrun/core/server.py")
check("E2 rm of a Nucleous file is refused", not ok and "NUCLEOUS_PROTECTED" in err, err)
ok, err = allowed("ls -ld skills .agent && cat README.md")
check("E3 a read-only command is allowed", ok, err)

# F — a quoted `>` beside a real redirect keeps the real one.
ok, err = allowed('echo "a > b" > src/longrun/core/server.py')
check("F1 the real redirect is still found beside a quoted one",
      not ok and "NUCLEOUS_PROTECTED" in err, err)

print("\n---\nv1121: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
