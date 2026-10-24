#!/usr/bin/env python3
"""v587 — CLI parity: usage docstring, query encoding, doc claims (JAG-CLI).

JAG-CLIa  forge.py Usage block omitted 9 subcommands (roles, agents,
          routines, jobs, index, knowledge, research, embedding, hooks),
          so `--help`-adjacent docs drift from the parser.
JAG-CLIb  `forge events --session/--kind` spliced raw values into the query
          string (JAG-246 class): spaces broke the URL and req() swallowed it
          into an error dict with exit 0 and no output.
JAG-CLIc  docs/CLI.md advertised `runs summary [--limit N]` and
          `context show [--model ALIAS]` — neither flag exists in the parser.

Deterministic, no live server. Run:  python3 tests/acceptance/v587_cli_parity.py
"""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-587-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


fv = read("src", "longrun", "core/forge.py")
usage = fv.split('"""', 2)[1]
cmds = sorted(set(re.findall(r'add_parser\("([a-z-]+)"\)', fv)))

# ---- JAG-CLIa: every subcommand appears in the Usage block ------------------
missing = [c for c in cmds if c not in usage and c != "paperclip-bot"]
check("JAG-CLIa usage lists every subcommand", not missing, "missing=%s" % missing)
for c in ("roles", "agents", "routines", "jobs", "index", "knowledge",
          "research", "embedding", "hooks"):
    check("JAG-CLIa usage mentions %s" % c, c in usage)

# ---- JAG-CLIb: events encodes session/kind ----------------------------------
check("JAG-CLIb events encodes --session", '"&session=" + _q(args.session)' in fv)
check("JAG-CLIb events encodes --kind", '"&kind=" + _q(' in fv)
check("JAG-CLIb no raw session splice",
      '"&session=" + args.session' not in fv)
check("JAG-CLIb no raw kind splice", '"&kind=" + args.kind' not in fv)

# ---- JAG-CLIc: docs claim only flags the parser has --------------------------
cli = read("docs", "CLI.md")
check("JAG-CLIc docs drop runs summary --limit", "runs summary [--limit" not in cli)
check("JAG-CLIc docs drop context show --model",
      "context show [--session ID] [--model" not in cli)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
