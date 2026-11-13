#!/usr/bin/env python3
"""AA — a harness version is published only if it still matches the reviewed one.

`verify` certifies a set of bytes with a sandbox run; `promote` installs. Nothing
bound the two, so a draft EDITED after verify was published with evidence that
belonged to an earlier version: every gate in `promote` reads the stored numbers,
never the current files. AReaL-RSI (version-consistent publication) makes the
published bytes equal to the reviewed bytes. Here `verify` stamps a content
digest of the artifact and `promote` recomputes it, refusing a mismatch; the
metadata file (`proposal.json`) is excluded because both verbs rewrite it, so a
later annotation is not mistaken for a new version.

Deterministic: temp dirs, no model, no network, no server.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="longrun-v971-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_REQUIRE_HELDOUT"] = "0"   # the sealed suite is not AA's subject
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


CHECK_BODY = "# generated\ndef main():\n    return 0\n"
GREEN = lambda d, c: (True, "ok")  # noqa: E731
CFG = {"min_green_streak": 1, "category": "created", "verify_timeout": 5,
       "promotion_alpha": 0.05}


def draft(tag, md="A skill.\n"):
    """A draft with the two files a promotion ships plus its metadata."""
    d = os.path.join(_tmp, "proposals", tag)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump({"name": tag, "status": "draft", "origin": "user",
                   "pattern": ["fs.read"]}, f)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(d, "check.py"), "w", encoding="utf-8") as f:
        f.write(CHECK_BODY)
    return d


def rewrite(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def verified(tag, md="A skill.\n"):
    d = draft(tag, md=md)
    selfevolve.verify(d, runner=GREEN, c=CFG, cases=["default"], repeats=1)
    return d


def promoted(skills, tag):
    return os.path.isdir(os.path.join(_tmp, skills, "created", tag))


# ---- A: verify stamps the digest of the bytes it ran ----------------------
d = verified("a")
rep = json.load(open(os.path.join(d, "proposal.json"), encoding="utf-8")).get("verify") or {}
check("A1 verify stamps a sha256 of the artifact into the evidence",
      isinstance(rep.get("artifact_sha256"), str) and len(rep["artifact_sha256"]) == 64,
      rep.get("artifact_sha256"))

# ---- B: an untouched verified draft promotes ------------------------------
out = selfevolve.promote(d, skills_dir=os.path.join(_tmp, "s-b"), c=CFG)
check("B1 an untouched verified draft promotes", out.get("ok") is True, out)

# ---- C: an edit AFTER verify refuses the promotion ------------------------
d = verified("c")
rewrite(os.path.join(d, "SKILL.md"), "A skill, edited after the check.\n")
out = selfevolve.promote(d, skills_dir=os.path.join(_tmp, "s-c"), c=CFG)
check("C1 an edit to the skill after verify refuses the promotion",
      out.get("ok") is False and "consistency gate" in str(out.get("error")), out)
check("C2 the refusal names both digests",
      len(str(out.get("verified_sha256") or "")) == 64
      and len(str(out.get("current_sha256") or "")) == 64
      and out.get("verified_sha256") != out.get("current_sha256"), out)
check("C3 nothing was installed", not promoted("s-c", "c"))

# ---- D: editing a code artifact (not just the prose) also refuses ---------
d = verified("d")
rewrite(os.path.join(d, "check.py"), "# generated\ndef main():\n    return 1\n")
out = selfevolve.promote(d, skills_dir=os.path.join(_tmp, "s-d"), c=CFG)
check("D1 editing the check script after verify also refuses",
      out.get("ok") is False and "consistency gate" in str(out.get("error")), out)

# ---- E: proposal.json is metadata, not artifact ---------------------------
d = verified("e")
_p = os.path.join(d, "proposal.json")
_obj = json.load(open(_p, encoding="utf-8"))
_obj["note"] = "a later annotation"
json.dump(_obj, open(_p, "w", encoding="utf-8"))
out = selfevolve.promote(d, skills_dir=os.path.join(_tmp, "s-e"), c=CFG)
check("E1 rewriting proposal.json does not trip the gate (it is metadata)",
      out.get("ok") is True, out)

# ---- F: re-verifying the edited draft clears the gate ---------------------
d = verified("f")
rewrite(os.path.join(d, "SKILL.md"), "A skill, edited then re-verified.\n")
selfevolve.verify(d, runner=GREEN, c=CFG, cases=["default"], repeats=1)
out = selfevolve.promote(d, skills_dir=os.path.join(_tmp, "s-f"), c=CFG)
check("F1 re-verifying after the edit lets it promote", out.get("ok") is True, out)

# ---- G: a legacy proposal with no stamp still promotes --------------------
legacy = os.path.join(_tmp, "proposals", "legacy")
os.makedirs(legacy, exist_ok=True)
with open(os.path.join(legacy, "proposal.json"), "w", encoding="utf-8") as f:
    json.dump({"name": "legacy", "status": "verified", "origin": "user",
               "green_streak": 1, "pattern": ["fs.read"],
               "verify": {"cases": {"default": True}, "baseline": {}}}, f)
out = selfevolve.promote(legacy, skills_dir=os.path.join(_tmp, "s-g"), c=CFG)
check("G1 a proposal with no digest (legacy) still promotes", out.get("ok") is True, out)

# ---- H: the digest is content-addressed, not path- or name-based ----------
a = draft("h1")
b = draft("h2")   # same SKILL.md/check.py bytes, different name
check("H1 two identical trees hash the same",
      selfevolve._artifact_digest(a) == selfevolve._artifact_digest(b),
      (selfevolve._artifact_digest(a), selfevolve._artifact_digest(b)))
with open(os.path.join(b, "runner.py"), "w", encoding="utf-8") as f:
    f.write("pass\n")
check("H2 an extra shipped file changes the digest",
      selfevolve._artifact_digest(a) != selfevolve._artifact_digest(b))

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
