#!/usr/bin/env python3
"""v1277 — the command reference documents every CORE CLI command.

`docs/CLI.md` is a ~900-line curated reference, and `AGENTS.md`'s read order points at it,
so an external agent is *sent* here. It deliberately delegates the per-paper groups to
`forge harness` (one family, one generated index) — that part is right and this pin must
not undo it. But nothing checked the **core** commands, and on 2026-11-22 exactly one was
missing: `setup`, a round-106 tool that runs locally rather than against the server.

This pin asserts the doc mentions every core subcommand the parser defines. Rounds are
excluded on purpose: they are one documented family, not 147 rows.

Anti-vacuity: a fabricated name is proven to be reported as missing, and floors guard both
sides (the parser's core set, and the doc's mentions).

Deterministic: no server, no model, no network.
Run: python3 tests/acceptance/v1277_cli_doc_coverage.py
"""
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1277-")
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


def missing_from(text, names):
    """The helper, separately callable so a stub can prove it still bites."""
    return sorted(n for n in names
                  if not re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(n), text))


doc = open(os.path.join(REPO, "docs", "CLI.md"), encoding="utf-8").read()
ap = forge._build_parser()
sub = next(a for a in ap._actions if hasattr(a, "choices") and a.choices)
names = set(sub.choices)
rounds = {n for n in names
          if n == "skills"
          or (getattr(sub.choices[n].get_default("fn"), "__doc__", "") or "").strip().startswith("Round ")}
core = sorted(names - rounds)

# ---- 0. anti-vacuity --------------------------------------------------------
check("self-test: a command absent from the doc is reported",
      missing_from("no relevant words here", ("zeta",)) == ["zeta"])
check("self-test: a documented command is not reported",
      missing_from("run zeta now", ("zeta",)) == [])

# ---- 1. floors --------------------------------------------------------------
check("the parser exposes a core command surface (>=40)", len(core) >= 40, "core=%d" % len(core))
check("the doc mentions a substantial surface (>=40)", len(names) - len(missing_from(doc, names)) >= 40)

# ---- 2. the requirement -----------------------------------------------------
missing = missing_from(doc, core)
check("every CORE command is documented in docs/CLI.md (%d)" % len(core),
      not missing, "missing=%s" % missing)

# ---- 3. the delegation this pin must NOT undo -------------------------------
check("the doc still delegates the round groups to `forge harness`",
      "forge.py harness" in doc, )
check("the round groups are NOT required to be listed individually",
      len(missing_from(doc, rounds)) > 100, "unlisted rounds=%d" % len(missing_from(doc, rounds)))

# ---- 4. the doc is genuinely in the read path -------------------------------
_agents = open(os.path.join(REPO, "AGENTS.md"), encoding="utf-8").read()
check("AGENTS.md still points at docs/CLI.md", "docs/CLI.md" in _agents)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
