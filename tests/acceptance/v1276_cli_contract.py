#!/usr/bin/env python3
"""v1276 — the CLI contract, read from the LIVE parser (not the source text).

`v312` and `v587` used to pin the command surface by regexing `core/forge.py`'s
**source**: `add_parser("...")` blocks, the usage docstring spliced out of the file, the
handler function names. That protected the CLI, but it was exactly the syntax a
table-driven refactor deletes — so it could not survive the collapse, and it pinned
*shape* where the requirement is *contract*. Both were retired once this pin proved it
carries their whole intent (the last three assertions were ported here in the same
change); the source-shape form is gone.

This pin states the same requirements against the **live parser**, which is what the
CLI actually is and which keeps answering after any internal reorganisation:

  A. **help completeness** — every core subcommand the parser defines is documented in
     the usage block (`forge.__doc__`), and the per-paper `harness` listing names every group;
  B. **the required core surface** — the subcommands/actions/flags the operator relies on
     are present, and the policy-WRITE presets are absent (a CLI has no verb for an
     operator act).

It deliberately does NOT cover route parity (every declared route served, under the right
method): the CLI's `(method, path)` pairs are only readable from the literals in the
source today, so that half needs the command **declaration table** the collapse
introduces. `v588` keeps covering it until then.

Anti-vacuity: a synthetic helper proves a subcommand missing from the usage block is
detected, and a floor guards the discovery.

Deterministic: no server, no model, no network (the parser is built in-process).
Run: python3 tests/acceptance/v1276_cli_contract.py
"""
import contextlib
import io
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1276-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import forge  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def missing_from_usage(names, usage):
    """The helper, separately callable so a stub can prove it still bites."""
    return sorted(n for n in names if n not in (usage or ""))


# The required surface: what the operator relies on (the intent the retired v312 held).
REQUIRED_ACTIONS = {
    "sessions": {"clear", "model"},
    "context": {"items"},
    "routines": {"ls", "new", "rm", "enable", "disable"},
    "jobs": {"get"},
    "mcp": {"ls", "add", "remove", "reload", "local-file"},
    "providers": {"ls", "add", "rm", "default", "rm-model"},
    "tools": {"ls", "call", "running", "cancel"},
    "market": {"ls", "sources", "status", "sync", "remote", "import", "install", "installed", "rm"},
}
REQUIRED_FLAGS = {"jobs": {"--blocked-by", "--agents", "--coordinator"},
                  "market": {"--source", "--category", "--offset", "--wait"}}
# A policy WRITE is an operator act: the CLI must have no verb for it (v1052).
FORBIDDEN_TOOL_ACTIONS = {"runtime", "verifier", "bestofn", "difficulty",
                          "selfevolve", "reasoning", "approvals", "policy"}

parser = forge._build_parser()
_sub = next(a for a in parser._actions if hasattr(a, "choices") and a.choices)
choices = _sub.choices
names = sorted(choices)
usage = forge.__doc__ or ""


def actions_of(name):
    """The `action` choice list of a subcommand, read from its live parser."""
    p = choices[name]
    for a in p._actions:
        if a.choices and not a.option_strings:
            return set(a.choices)
    return set()


def flags_of(name):
    return {o for a in choices[name]._actions for o in a.option_strings}


# ---- 0. anti-vacuity --------------------------------------------------------
check("self-test: a subcommand missing from the usage block is detected",
      missing_from_usage(("zeta",), "") == ["zeta"])
check("self-test: a documented subcommand is not reported",
      missing_from_usage(("zeta",), "usage: forge zeta ...") == [])

# ---- 1. discovery -----------------------------------------------------------
check("the parser really exposes the command surface (>=150 subcommands)",
      len(names) >= 150, "n=%d" % len(names))
check("the usage block is readable", len(usage) > 500, "chars=%d" % len(usage))

# ---- 2. help completeness (v587's intent, live) ----------------------------
_round = sorted(n for n in names
                if n == "skills"
                or (getattr(choices[n].get_default("fn"), "__doc__", "") or "").strip().startswith("Round "))
_core = [n for n in names if n not in _round and n not in ("harness", "paperclip-bot")]
missing = missing_from_usage(_core, usage)
check("every core subcommand is documented in the usage block (%d)" % len(_core),
      not missing, "missing=%s" % missing)
# The per-paper groups are NOT hand-listed; the usage block must point at the generated index.
check("the usage block points at the generated harness index", "harness [GROUP]" in usage)

# ---- 3. the harness listing names every per-paper group --------------------
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    forge.cmd_harness(type("Args", (), {"group": None})())
_listed = _buf.getvalue()
unlisted = [g for g in _round if g not in _listed]
check("`forge harness` lists every per-paper group (%d)" % len(_round),
      not unlisted, "missing=%s" % unlisted[:6])
check("`forge harness` reports actions, not one example",
      "tiers" in _listed and "adjudicate" in _listed)

# ---- 4. the required core surface ------------------------------------------
for name, want in REQUIRED_ACTIONS.items():
    got = actions_of(name)
    check("`%s` accepts %s" % (name, "/".join(sorted(want))),
          want <= got, "missing=%s" % sorted(want - got))
for name, want in REQUIRED_FLAGS.items():
    got = flags_of(name)
    check("`%s` accepts %s" % (name, " ".join(sorted(want))),
          want <= got, "missing=%s" % sorted(want - got))
check("the CLI has no verb that WRITES the tool policy",
      not (actions_of("tools") & FORBIDDEN_TOOL_ACTIONS),
      "found=%s" % sorted(actions_of("tools") & FORBIDDEN_TOOL_ACTIONS))

# ---- 5. what this pin deliberately does NOT cover --------------------------
check("route parity stays with v588 until the declaration table exists",
      os.path.isfile(os.path.join(REPO, "tests", "acceptance", "v588_cli_route_parity.py")))

# ---- 6. test infra: pytest must be able to import the package ---------------
# (Ported from the retired v312: a pytest run needs `src/` on `sys.path`.)
_conf = os.path.join(REPO, "tests", "conftest.py")
check("tests/conftest.py exists (JAG-313)", os.path.isfile(_conf))
if os.path.isfile(_conf):
    _ctext = open(_conf, encoding="utf-8").read()
    check("conftest puts src/ on sys.path", '"src"' in _ctext and "sys.path.insert" in _ctext)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
