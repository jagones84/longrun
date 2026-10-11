#!/usr/bin/env python3
"""v416 — autonomous skill lifecycle: the skills/created/ box (JAG-426 · Domain 4).

Auto-distilled skills must be confined to `skills/created/`, must never touch the
built-in `skills/core/**` library, must respect a quota, and must never overwrite.
A human-authored proposal (no `origin: auto`) keeps the old freedom.

Deterministic, no live server. Run: python3 tests/v416_autoskill_created.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v416-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
# The sealed held-out gate (plan/heldout.py) is ON by default and fail-closed;
# this test targets the NEW box/quota rules, so disable the gate here and pin its
# fail-closed behaviour explicitly in check 8 instead.
os.environ["LONGRUN_REQUIRE_HELDOUT"] = "0"
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve as E   # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


ROOT = os.path.join(TMP, "skills")
OUT = os.path.join(TMP, "proposals")


_KEEP = object()


def _verified(pattern, origin=_KEEP):
    """A prepared, sandbox-verified proposal.

    `origin=_KEEP` (default) keeps the mined `auto` stamp; `origin=None` CLEARS it
    (simulating a human-authored proposal).
    """
    E.draft(pattern, 3, OUT)
    E.synth(pattern, OUT)
    d = os.path.join(OUT, E.slug(pattern))
    E.verify(d, runner=lambda pd, cmd: (True, "green"))
    if origin is not _KEEP:
        p = os.path.join(d, "proposal.json")
        with open(p, encoding="utf-8") as f:
            obj = json.load(f)
        obj["origin"] = origin
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f)
    return d


# ---- 1. the new default + provenance ----------------------------------------
check("1a the default category is 'created'", E.cfg().get("category") == "created")
d0 = os.path.join(OUT, E.slug(["fs.read", "diff"]))
E.draft(["fs.read", "diff"], 3, OUT)
with open(os.path.join(d0, "proposal.json"), encoding="utf-8") as f:
    check("1b a mined proposal is stamped origin=auto", json.load(f).get("origin") == "auto")

# ---- 2. it lands under skills/created/ --------------------------------------
d = _verified(["fs.read", "diff"])
arch = E.promote(d, skills_dir=ROOT)
check("2 promote writes under skills/created/",
      arch.get("ok") is True and "/created/" in (arch.get("path") or "").replace(os.sep, "/"),
      arch.get("path"))

# ---- 3. the built-in library is immutable -----------------------------------
d2 = _verified(["shell", "git"])
r = E.promote(d2, skills_dir=ROOT, c=E.cfg({"category": "core"}))
check("3 promoting into skills/core is refused",
      r.get("ok") is False and "core" in (r.get("error") or ""))

# ---- 4. an auto skill cannot escape skills/created/ -------------------------
d3 = _verified(["web", "memory"])
r2 = E.promote(d3, skills_dir=ROOT, c=E.cfg({"category": "my-cat"}))
check("4 an auto skill cannot be promoted to another category",
      r2.get("ok") is False and "created" in (r2.get("error") or ""))

# ---- 5. a HUMAN proposal keeps the freedom ----------------------------------
d4 = _verified(["skills", "index"], origin=None)
r3 = E.promote(d4, skills_dir=ROOT, c=E.cfg({"category": "my-cat"}))
check("5 a non-auto proposal may go to a custom category",
      r3.get("ok") is True and os.sep + "my-cat" + os.sep in (r3.get("path") or ""),
      r3)

# ---- 6. never overwrite ------------------------------------------------------
r4 = E.promote(d, skills_dir=ROOT)
check("6 promoting the same skill twice never overwrites", r4.get("ok") is False)

# ---- 7. the quota holds ------------------------------------------------------
box = os.path.join(ROOT, "created")
for i in range(E.AUTO_SKILL_CAP):
    os.makedirs(os.path.join(box, "filler_%02d" % i), exist_ok=True)
d5 = _verified(["git", "diff"])
r5 = E.promote(d5, skills_dir=ROOT)
check("7 the skills/created quota is enforced",
      r5.get("ok") is False and "quota" in (r5.get("error") or ""), r5.get("error"))

# ---- 8. autonomy is GATED: the held-out gate is fail-closed when ON ----------
os.environ["LONGRUN_REQUIRE_HELDOUT"] = "1"
d6 = _verified(["index", "knowledge"])
r6 = E.promote(d6, skills_dir=os.path.join(TMP, "skills2"))
check("8 with the held-out gate ON, promotion is refused (fail-closed)",
      r6.get("ok") is False and "held-out" in (r6.get("error") or ""), r6.get("error"))

print("---")
okc = sum(results)
print("\nv416: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
