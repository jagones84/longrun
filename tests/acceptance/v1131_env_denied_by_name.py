#!/usr/bin/env python3
"""v1131 — the env file is protected by NAME, not by the reader that names it.

Round 65 (arXiv:2611.15223 guardscope — a control is CHECKED, BYPASSED or
PREVENTED, and a spelling-based rule only ever checks the spellings).

Measured 2026-11-18 on the shipped policy, `approvals.mode=full`, via
`registry.classify`:

  awk 'NR==1' .env                                        -> auto   (EXECUTED)
  sort .env | head -1                                     -> auto   (EXECUTED)
  python3 -c 'print(open(".env").read()[:10])'            -> auto   (EXECUTED)
  node -e '…readFileSync(".env","utf8")…'                 -> auto   (EXECUTED)

Four one-line bypasses of a hard deny that exists to keep the API bearer and every
provider key out of a tool result. The rule named its READERS (`cat|head|tail|…` and
`grep`), so any other program — or a language one-liner — walked straight through it.
This test pins the replacement: ONE rule that matches the env file as a PATH TOKEN
wherever it appears in the command, with `.env.template` the only readable spelling.

  A  the four measured bypasses are now denied
  B  more readers (perl, sed, tar, base64, an interpreter) are denied too
  C  the historical spellings stay denied and the refusal still teaches
  D  the template and look-alike names stay readable
  E  exactly one shell.exec rule fires for the env file, and the two reader-name
     rules are gone (one rule owns the object)
  F  the refusal is still the `permission` family

Deterministic: config + registry only; nothing executes.
Run: python3 tests/acceptance/v1131_env_denied_by_name.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1131-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as R  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def verdict(cmd):
    return R.classify("shell.exec", {"command": cmd})


# --- A: the four spellings measured live --------------------------------------
BYPASSES = [
    ("A1 awk reads it", "awk 'NR==1' .env"),
    ("A2 sort reads it", "sort .env | head -1"),
    ("A3 a python one-liner reads it",
     'python3 -c \'print(open(".env").read()[:10])\''),
    ("A4 a node one-liner reads it",
     'node -e \'console.log(require("fs").readFileSync(".env","utf8").slice(0,10))\''),
]
for name, cmd in BYPASSES:
    d, why = verdict(cmd)
    check(name, d == "denied", d)

# --- B: every other reader is the same object --------------------------------
OTHER = [
    ("B1 perl", "perl -ne 'print' .env"),
    ("B2 sed", "sed -n '1p' .env"),
    ("B3 tar (exfiltration shape)", "tar czf /tmp/x.tgz .env"),
    ("B4 base64", "base64 .env"),
    ("B5 a copy out of the repo", "cp .env /tmp/x"),
]
for name, cmd in OTHER:
    d, why = verdict(cmd)
    check(name, d == "denied", d)

# --- C: the historical spellings and their lesson ----------------------------
for name, cmd in (("C1 cat", "cat .env"),
                  ("C2 grep", "grep -oP 'API_KEY' .env"),
                  ("C3 a piped extraction",
                   "cat .env | grep -oP 'API_KEY:\\K.*' | tr -d '\"'")):
    d, why = verdict(cmd)
    check(name + " stays denied", d == "denied", d)
    check(name + " names what it protects", "env file" in why and "provider key" in why, why)
check("C4 the refusal also names the alternative",
      "self.info" in verdict("cat .env")[1], verdict("cat .env")[1])

# --- D: the template and look-alike names are NOT the credential file --------
for name, cmd in (("D1 the template", "cat .env.template"),
                  ("D2 a listing of the template", "ls -la .env.template"),
                  ("D3 a diff of the template", "git diff -- .env.template"),
                  ("D4 a name that merely starts with .env", "cat .env_template"),
                  ("D5 an unrelated .envrc", "ls -la /home/x/.envrc"),
                  ("D6 a different file called x.env", "cat my.env")):
    d, why = verdict(cmd)
    check(name + " is not denied", d != "denied", (d, why))
check("D7 the fs.read path rule is unchanged",
      R.classify("fs.read", {"path": os.path.join(REPO, ".env")})[0] == "denied",
      R.classify("fs.read", {"path": os.path.join(REPO, ".env")}))

# --- E: one rule owns the object ---------------------------------------------
spec = R.tool_spec("shell.exec")
hits = [p for p in spec["deny"] if __import__("re").search(p, "awk 'NR==1' .env")]
check("E1 exactly one shell.exec rule fires for the env file", len(hits) == 1, hits)
check("E2 and it is the one that carries the why",
      bool(hits) and hits[0] in (spec.get("deny_why") or {}), spec.get("deny_why"))
check("E3 the grep-only rule is gone (its object moved, not duplicated)",
      not any(p.startswith("grep[^") for p in spec["deny"]), spec["deny"])
check("E4 the reader-name rule is gone (only the held-out store still lists readers)",
      not any("cat|head" in p and ".env" in p for p in spec["deny"]), spec["deny"])
check("E5 the token guard is untouched",
      any(p == "LONGRUN_TOKEN" for p in spec["deny"]), spec["deny"])

# --- F: the register keeps classifying it as a policy answer -----------------
why = verdict("awk 'NR==1' .env")[1]
fam = selfevolve.failure_family("shell.exec", selfevolve.error_class(why), why)
check("F1 the refusal is the permission family", fam == "permission", fam)

print("\n---\nv1131: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
