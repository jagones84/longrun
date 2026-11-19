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

# ---- JAG-CLIa: usage stays in sync with the parser --------------------------
# The ~140 per-paper groups are no longer hand-listed in the docstring (that
# block drifted: it showed one action per group and a `--json` flag nobody
# defines). `forge harness` derives them from the parser instead, so the test
# checks THAT listing rather than a hand-maintained string.
import contextlib
import io

sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.core import forge as _forge                  # noqa: E402

_ap = _forge._build_parser()
_sub = next(a for a in _ap._actions
            if hasattr(a, "choices") and a.choices)
_round = sorted(
    name for name, parser in _sub.choices.items()
    if re.match(r"Round \d+",
                (getattr(parser.get_default("fn"), "__doc__", "") or "").strip())
    or name == "skills")
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    _forge.cmd_harness(type("Args", (), {"group": None})())
_listed = _buf.getvalue()
check("JAG-CLIa harness lists every per-paper group",
      not [g for g in _round if g not in _listed],
      "missing=%s" % [g for g in _round if g not in _listed])
check("JAG-CLIa harness reports actions, not one example",
      "tiers" in _listed and "adjudicate" in _listed)
check("JAG-CLIa usage points at the generated index", "harness [GROUP]" in usage)
_core_missing = [c for c in cmds if c not in usage and c != "paperclip-bot"
                 and c not in _round and c != "harness"]
check("JAG-CLIa usage lists every core subcommand", not _core_missing,
      "missing=%s" % _core_missing)
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
