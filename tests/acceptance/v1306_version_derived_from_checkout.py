#!/usr/bin/env python3
"""v1306 — the version the service and the agents report is the CHECKOUT's own.

Operator (2026-11-25): *"Poi non e la versione 1.0 di longrun ..perche mente l'agente?"*.
`longrun.__version__` was a hand-typed literal stuck at `1.0.0` (the 2026-10-07 release)
while the tree went through `v1.1.0`, `v1.2.0` and 139+ commits — so `/api/status`,
`/api/self`, the `Server:` header and every agent's self-knowledge (`self_summary`)
stated a version the code no longer was. The agent was not lying: it was repeating a
constant nobody had moved.

Contract:
  A  the package root DERIVES the version (`git describe --tags --always --dirty`), and
     the literal survives only as the fallback for a copy without `.git` — a fallback
     that must equal the newest tag of THIS checkout;
  B  the transformation is pure and total: a tag, a tag+N commits, a bare sha, a dirty
     tree, a non-semver tag and an unreadable string all yield a usable version;
  C  the live value agrees with the checkout (`v1.2.0-139-gsha` -> `1.2.0+139.gsha`) and
     is one PEP 440 local version, never the empty string and never a stale release.

Deterministic: no server, no model, no network (git on the local checkout only, and the
git-dependent checks are skipped — not failed — when it is not available).
Run: python3 tests/acceptance/v1306_version_derived_from_checkout.py
"""
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


def git(*args):
    """The command's stdout, or None when git/the repo is unavailable."""
    try:
        out = subprocess.run(["git", "-C", REPO] + list(args), capture_output=True,
                             text=True, timeout=5)
    except Exception:  # noqa: BLE001 — no git here: the caller skips its check
        return None
    return (out.stdout or "").strip() if out.returncode == 0 else None


PKG = read("src", "longrun", "__init__.py")
import longrun  # noqa: E402
from longrun import _version_from_describe as V  # noqa: E402

# ---- A: derived at the package root, literal only as the fallback ----------
check("A1 the package root derives the version from the checkout",
      "git\", \"-C\", root, \"describe\", \"--tags\", \"--always\", \"--dirty\"" in PKG
      and "__version__ = _derive_version(_BASE)" in PKG)
check("A2 the fallback base is a release literal, not a live value",
      re.search(r'^_BASE = "(\d+\.\d+\.\d+)"$', PKG, re.M) is not None,
      re.search(r'^_BASE = ".*"$', PKG, re.M).group(0) if "_BASE = " in PKG else "missing")
_newest = git("describe", "--tags", "--abbrev=0")
if _newest:
    _base = re.search(r'^_BASE = "(.*)"$', PKG, re.M).group(1)
    check("A3 the fallback equals the newest tag (so a copy without .git is not stale)",
          _newest.lstrip("v") == _base, "%r vs %r" % (_newest, _base))
else:
    print("SKIP A3 (git unavailable in this checkout)")
    results.append(True)
# No SECOND release literal anywhere in the package: one owner.
_literals = []
for root, dirs, names in os.walk(os.path.join(REPO, "src", "longrun")):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for n in names:
        if not n.endswith(".py"):
            continue
        p = os.path.join(root, n)
        rel = os.path.relpath(p, os.path.join(REPO, "src", "longrun"))
        if rel == "__init__.py":
            continue
        src = open(p, encoding="utf-8").read()
        for m in re.finditer(r'__version__\s*=\s*["\'](\d+\.\d+\.\d+)["\']', src):
            _literals.append("%s: %s" % (rel, m.group(1)))
check("A4 no module outside the package root types a release version",
      not _literals, _literals[:3])

# ---- B: the transformation is pure and total -------------------------------
check("B1 exactly on a tag -> the bare release",
      V("v1.2.0") == "1.2.0", V("v1.2.0"))
check("B2 N commits past a tag -> PEP 440 local version with the count and the sha",
      V("v1.2.0-139-ge963a3be") == "1.2.0+139.ge963a3be", V("v1.2.0-139-ge963a3be"))
check("B3 a dirty tree says so",
      V("v1.2.0-139-ge963a3be-dirty") == "1.2.0+139.ge963a3be.dirty",
      V("v1.2.0-139-ge963a3be-dirty"))
check("B4 a bare sha (no tag in reach) still yields a usable version",
      V("e963a3be", "9.9.9") == "9.9.9+ge963a3be", V("e963a3be", "9.9.9"))
check("B5 a non-semver tag cannot produce an empty or punctuated-only version",
      bool(re.fullmatch(r"9\.9\.9\+[0-9A-Za-z.]+", V("checkpoint-longrun-20261010-5-gabc1234",
                                                    "9.9.9"))),
      V("checkpoint-longrun-20261010-5-gabc1234", "9.9.9"))
check("B6 an unreadable string yields the fallback, never '' ",
      V("", "9.9.9") == "9.9.9" and V(None, "9.9.9") == "9.9.9"
      and bool(V("")), "%r / %r" % (V("", "9.9.9"), V(None, "9.9.9")))

# ---- C: the live value agrees with the checkout ----------------------------
check("C1 __version__ is never empty and never the old stale release claim",
      bool(str(longrun.__version__).strip()) and longrun.__version__ != "1.0.0",
      longrun.__version__)
if _newest:
    _desc = git("describe", "--tags", "--always", "--dirty")
    _tag = _newest.lstrip("v")
    check("C2 the live value starts with the newest release tag",
          str(longrun.__version__).startswith(_tag), "%r vs tag %r"
          % (longrun.__version__, _tag))
    if "-g" in (_desc or ""):
        _head, _sha = _desc.rsplit("-g", 1)
        _sha = _sha.replace("-dirty", "")
        check("C3 a tree ahead of the tag carries the commit it really is",
              _sha in longrun.__version__, "%r vs %r" % (longrun.__version__, _sha))
    else:
        print("SKIP C3 (the checkout is exactly on the tag)")
        results.append(True)
else:
    print("SKIP C2/C3 (git unavailable in this checkout)")
    results.extend([True, True])
check("C4 the reported version is ONE PEP 440 version (local part allowed)",
      re.fullmatch(r"\d+(\.\d+)+(\+[0-9A-Za-z.]+)?", str(longrun.__version__)) is not None,
      longrun.__version__)

print("\nv1306: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
