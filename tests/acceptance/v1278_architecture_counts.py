#!/usr/bin/env python3
"""v1278 — docs/ARCHITECTURE.md's countable claims match reality.

The architecture doc is the primary "how the system is wired" text in `AGENTS.md`'s read
order, so a stale number there misleads every agent that follows the read path. `v1271`
checks the doc SET (which files exist, and that the README links them); nothing checked the
claims *inside* each doc. On 2026-11-22 one of the three countable claims was stale —
"the 137 report-only per-paper checkers" while the package holds 135 — and, worth saying
because it is the point of measuring first, the other two were **accurate**:

  "the 135 report-only per-paper checkers"  <- `harness/checks/*.py`
  "the 9 gated executors"                   <- `harness/execution/*.py`
  "the 29 modules the running app imports"  <- `harness/` root files reached from the app

Deriving each from the tree makes the doc self-verifying: add a checker, a gated executor
or an app-imported seam without updating the doc, and this pin fails naming it.

The doc also carries a `## Contents` block (finding A5: ~1,050 lines, 26 headings, no map).
It is generated from the real H2 headings, titles only — an agent reads the file as text and
greps by heading. Nothing else pins it, so a new section would silently fall out of the map;
the same pin derives the heading list from the file and requires the two to agree in order.

Anti-vacuity: the comparison helper is exercised on a synthetic mismatch, and a floor
asserts the doc actually states all three claims (a deleted sentence must not pass).

Deterministic: no server, no model, no network.
Run: python3 tests/acceptance/v1278_architecture_counts.py
"""
import ast
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_PKGS = ["agent", "core", "tools", "memory", "model", "plan", "orchestrate",
            "evolve", "orbit", "research", "interop", "util"]

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def modules_in(rel):
    d = os.path.join(REPO, "src", "longrun", *rel)
    return sorted(f[:-3] for f in os.listdir(d) if f.endswith(".py") and f != "__init__.py")


def app_imported_root_modules():
    """`harness/` root modules the running app reaches (the doc's third claim)."""
    root = set(modules_in(("harness",)))
    got = set()
    for pkg in APP_PKGS:
        for dirpath, _, files in os.walk(os.path.join(REPO, "src", "longrun", pkg)):
            for f in files:
                if not f.endswith(".py"):
                    continue
                try:
                    tree = ast.parse(open(os.path.join(dirpath, f), encoding="utf-8").read())
                except (OSError, SyntaxError):
                    continue
                for n in ast.walk(tree):
                    if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("longrun.harness."):
                        parts = n.module.split(".")
                        if len(parts) > 2 and parts[2] in root:
                            got.add(parts[2])
                    elif isinstance(n, ast.ImportFrom) and n.module == "longrun.harness":
                        got |= {a.name for a in n.names if a.name in root}
                    elif isinstance(n, ast.Import):
                        for a in n.names:
                            if a.name.startswith("longrun.harness."):
                                parts = a.name.split(".")
                                if len(parts) > 2 and parts[2] in root:
                                    got.add(parts[2])
    return got


def h2_headings(text):
    """Every real `## …` heading, in order. Fenced code blocks are excluded: the doc's shell
    examples contain `# ` comment lines that are not sections."""
    out, fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if not fence and line.startswith("## ") and not line.startswith("### "):
            title = line[3:].strip()
            if title != "Contents":
                out.append(title)
    return out


def toc_entries(text):
    """The `- …` bullets of the `## Contents` block — or None when the block is absent."""
    lines = text.splitlines()
    if "## Contents" not in lines:
        return None
    out = []
    for line in lines[lines.index("## Contents") + 1:]:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            out.append(line[2:].strip())
    return out


def contents_problems(toc, h2):
    """Human-readable list of why the Contents block does not match the headings."""
    if toc is None:
        return ["no '## Contents' block"]
    if toc == h2:
        return []
    problems = []
    missing = [t for t in h2 if t not in toc]
    stale = [t for t in toc if t not in h2]
    if missing:
        problems.append("missing: " + "; ".join(missing))
    if stale:
        problems.append("stale: " + "; ".join(stale))
    if not missing and not stale:
        problems.append("wrong order")
    return problems


doc = open(os.path.join(REPO, "docs", "ARCHITECTURE.md"), encoding="utf-8").read()


def stated(text, pattern):
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None


def wrong(claim, real):
    return claim is not None and claim != real


# ---- 0. anti-vacuity --------------------------------------------------------
check("self-test: a stale number is detected", wrong(137, 135) is True)
check("self-test: an accurate number passes", wrong(135, 135) is False)

_syn_drift = "## Contents\n\n- A\n- B\n\n## A\n\n## C\n"
check("self-test: a Contents/heading mismatch is detected",
      contents_problems(toc_entries(_syn_drift), h2_headings(_syn_drift)) != [])
_syn_ok = "## Contents\n\n- A\n- B\n\n## A\n\n## B\n"
check("self-test: a matching Contents block passes",
      contents_problems(toc_entries(_syn_ok), h2_headings(_syn_ok)) == [])

# ---- 1. reality -------------------------------------------------------------
checks_n = len(modules_in(("harness", "checks")))
exec_n = len(modules_in(("harness", "execution")))
app_n = len(app_imported_root_modules())
root_n = len(modules_in(("harness",)))
check("harness/checks/ holds a module per paper (>=100)", checks_n >= 100, "n=%d" % checks_n)
check("the app imports some (but not all) of the root", 0 < app_n <= root_n,
      "app=%d root=%d" % (app_n, root_n))

# ---- 2. the doc's claims ----------------------------------------------------
c_checks = stated(doc, r"the (\d+) report-only per-paper checkers")
c_exec = stated(doc, r"the (\d+) gated executors")
c_app = stated(doc, r"the (\d+) modules the running app imports")
check("the doc states all three countable claims",
      None not in (c_checks, c_exec, c_app), "checks=%s exec=%s app=%s" % (c_checks, c_exec, c_app))

check("ARCHITECTURE.md's checker count matches the package", not wrong(c_checks, checks_n),
      "doc=%s real=%d" % (c_checks, checks_n))
check("ARCHITECTURE.md's executor count matches the package", not wrong(c_exec, exec_n),
      "doc=%s real=%d" % (c_exec, exec_n))
check("ARCHITECTURE.md's app-imported root count matches the tree", not wrong(c_app, app_n),
      "doc=%s real=%d" % (c_app, app_n))

# ---- 3. the Contents block lists every H2, in order -------------------------
h2 = h2_headings(doc)
toc = toc_entries(doc)
probs = contents_problems(toc, h2)
check("ARCHITECTURE.md has a non-trivial Contents block", toc is not None and len(toc) >= 10,
      "entries=%s" % (len(toc) if toc is not None else "none"))
check("ARCHITECTURE.md's Contents block matches its H2 headings in order", not probs,
      "; ".join(probs) if probs else "sections=%d" % len(h2))

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
