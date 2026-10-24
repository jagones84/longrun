#!/usr/bin/env python3
"""v591 (RED) — P2 skill trust: content digests bound to (name, path).

OpenClaw's skillBinTrust adapted to prompt-only skills: Longrun never executes
skill binaries, but a swapped SKILL.md (overwrite install, matrix promote,
upstream pull) silently changes what the model reads. The trust anchor is
(name, resolved path, content digest):

- `skills.skill_digest(path)` -> sha256 hex of the SKILL.md bytes (None when
  missing/unreadable); stable for identical content, different after any edit.
- `list_skills()` entries carry `digest`.
- `skills.verify_skill_digests(baseline)` compares {name: digest} against the
  live tree -> {ok, changed, new, gone} (pure, no I/O besides the scan).
- `install_zip()` stamps the new skill's digest into the baseline on success
  (trust-on-first-install); `audit_skills()` reports `changed` skills.

Deterministic: temp dirs for writes, real repo tree read-only otherwise.
Run: python3 tests/acceptance/v591_skill_trust.py
"""
import hashlib
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo(start):
    p = start
    while True:
        if os.path.isdir(os.path.join(p, "src", "longrun")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            raise SystemExit("repository root not found from %s" % start)
        p = parent


REPO = _repo(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import skills  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def _mkskill(body="---\nname: t\n---\n# T\nDo things.\n"):
    d = tempfile.mkdtemp(prefix="lr-skill-")
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(body)
    return d


# ---- A: the digest primitive -------------------------------------------------
check("A1 skills.skill_digest exists", callable(getattr(skills, "skill_digest", None)))
dg = getattr(skills, "skill_digest", None)
if callable(dg):
    d = _mkskill()
    sp = os.path.join(d, "SKILL.md")
    want = hashlib.sha256(open(sp, "rb").read()).hexdigest()
    check("A2 digest equals sha256 of the bytes", dg(sp) == want, (dg(sp) or "")[:16])
    check("A3 stable across calls", dg(sp) == dg(sp))
    check("A4 missing file -> None", dg(os.path.join(d, "NOPE.md")) is None)
    d2 = _mkskill("# different body\n")
    check("A5 different content -> different digest",
          dg(os.path.join(d2, "SKILL.md")) != dg(sp))
    d3 = tempfile.mkdtemp(prefix="lr-skilldir-")
    check("A6 directory without SKILL.md -> None", dg(d3) is None)
    d4 = _mkskill()
    check("A7 directory with SKILL.md digests it",
          dg(d4) == hashlib.sha256(
              open(os.path.join(d4, "SKILL.md"), "rb").read()).hexdigest())
else:
    for n in ("A2", "A3", "A4", "A5", "A6", "A7"):
        check(n, False, "skill_digest missing")

# ---- B: pure baseline comparison ---------------------------------------------
vh = getattr(skills, "verify_skill_digests", None)
check("B0 skills.verify_skill_digests exists", callable(vh))
if callable(vh):
    live = {"a": "d1", "b": "d2", "c": "d3"}
    got = vh({"a": "d1", "b": "DX", "z": "d9"}, live)
    check("B1 unchanged names are ok", got.get("ok") == ["a"], repr(got))
    check("B2 edited digest is changed", got.get("changed") == ["b"], repr(got))
    check("B3 unknown name is new", got.get("new") == ["c"], repr(got))
    check("B4 vanished baseline entry is gone", got.get("gone") == ["z"], repr(got))
    check("B5 empty baseline -> all new",
          vh({}, live).get("new") == ["a", "b", "c"])
else:
    for n in ("B1", "B2", "B3", "B4", "B5"):
        check(n, False, "verify_skill_digests missing")

# ---- C: the scan carries digests ----------------------------------------------
try:
    sk = skills.list_skills(reload=True)
    with_digest = [s for s in sk if s.get("digest")]
    check("C1 list_skills entries carry digest",
          len(sk) > 0 and len(with_digest) == len(sk),
          "%d/%d" % (len(with_digest), len(sk)))
    bad = [s["name"] for s in sk
           if not isinstance(s.get("digest"), str) or len(s["digest"]) != 64]
    check("C2 every digest is 64 hex chars", not bad, repr(bad[:3]))
except Exception as e:  # noqa: BLE001
    check("C1 list_skills entries carry digest", False, str(e)[:150])
    check("C2 every digest is 64 hex chars", False, "skipped")

# ---- D: install stamps, audit reports ------------------------------------------
try:
    with open(os.path.join(REPO, "src", "longrun", "memory", "skills.py"),
              encoding="utf-8") as f:
        _src = f.read()
except OSError as e:
    _src = ""
    print("WARN cannot read skills.py: %s" % e)

_inst = _src.split("def install_zip(", 1)
_inst = _inst[1] if len(_inst) > 1 else ""
_nxt = _inst.find("\ndef ")
_inst = _inst[:_nxt] if _nxt >= 0 else _inst
check("D1 install_zip stamps the digest baseline",
      "digest" in _inst and ("save_digests" in _inst or "record" in _inst),
      "trust-on-first-install")
_aud = _src.split("def audit_skills(", 1)
_aud = _aud[1] if len(_aud) > 1 else ""
_nxt = _aud.find("\ndef ")
_aud = _aud[:_nxt] if _nxt >= 0 else _aud
check("D2 audit_skills reports changed skills",
      "changed" in _aud, "report-only, never deletes")

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
