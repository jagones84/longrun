#!/usr/bin/env python3
"""v1271 — the docs' INVENTORY claims match the tree (drift detector).

The docs make inventory claims: how many subpackages the core has, which packages they
are, which docs exist, which seams expose a fail-open hook point. Those claims rot
silently — the 2026-11-22 retro found README/CONTRIBUTING still saying "14 subpackages"
while the tree had 15 (`evolve/` omitted), and the README Documentation table missing
four tracked docs. This pin makes each claim mechanical, so the gate catches the drift
instead of a reader.

Deterministic: no server, no model, no network.
Run: python3 tests/acceptance/v1271_docs_inventory.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# ---- the truth: the core's subpackages --------------------------------------
PKG_ROOT = os.path.join(REPO, "src", "longrun")
pkgs = sorted(
    d for d in os.listdir(PKG_ROOT)
    if os.path.isfile(os.path.join(PKG_ROOT, d, "__init__.py"))
)
readme = read("README.md")
contrib = read("CONTRIBUTING.md")

check("the core exposes its subpackages", len(pkgs) >= 10, "n=%d" % len(pkgs))

# ---- claim 1: the numeric count, stated in both docs ------------------------
for doc, text in (("README.md", readme), ("CONTRIBUTING.md", contrib)):
    m = re.search(r"(\d+)\s+subpackages", text)
    check("%s states the real subpackage count (%d)" % (doc, len(pkgs)),
          bool(m) and int(m.group(1)) == len(pkgs),
          "claim=%s" % (m.group(1) if m else "absent"))

# ---- claim 2: every package is NAMED in CONTRIBUTING's layout row -----------
row = next((ln for ln in contrib.splitlines()
            if ln.startswith("| `src/longrun/` |")), "")
check("CONTRIBUTING has the src/longrun layout row", bool(row))
missing_pkgs = [p for p in pkgs if ("`%s/`" % p) not in row]
check("CONTRIBUTING names every subpackage in that row",
      not missing_pkgs, "missing=%s" % missing_pkgs)

# ---- claim 3: every tracked doc is LINKED from the README ------------------
# A bare filename appearing anywhere is too weak (it also matches prose); the link
# form is the one a reader can actually follow. `docs/*.md` are linked with their
# directory prefix, the root documents without one.
docs_dir = sorted(f for f in os.listdir(os.path.join(REPO, "docs")) if f.endswith(".md"))
root_docs = ["GLOSSARY.md", "CODING_STANDARDS.md", "AGENTS.md", "CONTRIBUTING.md", "CHANGELOG.md"]
unlinked = ["docs/" + f for f in docs_dir if ("](docs/%s)" % f) not in readme]
unlinked += [f for f in root_docs if ("](%s)" % f) not in readme]
check("README links every tracked doc (%d)" % (len(docs_dir) + len(root_docs)),
      not unlinked, "unlinked=%s" % unlinked)
# The two DIRECTORIES holding the domain layer are named, not enumerated: the glossary
# and the decisions have to be findable from the README even as they grow.
for d in ("docs/adr/", "docs/agents/"):
    check("README names the %s directory" % d, d in readme)

# ---- claim 4: the fail-open seam list mirrors the code ---------------------
# `core/matrix.py` owns the list; the README repeats it in prose.
src = read("src", "longrun", "core", "matrix.py")
m = re.search(r"HOOK_SUBPACKAGES\s*=\s*\(([^)]*)\)", src, re.S)
hooks = re.findall(r'"([^"]+)"', m.group(1)) if m else []
check("HOOK_SUBPACKAGES is readable from core/matrix.py", bool(hooks), "hooks=%s" % hooks)
if hooks:
    seam_missing = [h for h in hooks if ("`%s`" % h) not in readme]
    check("README's seam list mirrors HOOK_SUBPACKAGES (%d)" % len(hooks),
          not seam_missing, "missing=%s" % seam_missing)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
