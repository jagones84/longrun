"""v663 — the operator's retest: the two defects that were REAL.

The retest reported four residues; two of them reproduce, and their causes are
different from "the layer below is wrong" — they live UNDER the layer v659 fixed:

  * `routine.create disabled:true` came back ENABLED, and `routine.update` with
    ONLY `disabled:true` answered "nothing to update". `routines._enabled_arg` has
    read both spellings since v659, but the TOOL mapping above it hardcoded
    `bool(args.get("enabled", True))` and its update key list did not carry
    `disabled` — so the two spellings met a layer that spoke only one.
  * `skills.search` answered [] for a name fragment containing a DIGIT while
    `list_skills` showed the same skill: the token class was `[a-z]{3,}`, so
    `search("9x2")` tokenised to nothing at all. A name is alphanumeric.

The other two residues did NOT reproduce on the live DGX (evidence in HANDOFF):
a rule scaffold really is created and removed (it lives in the Matrix RUNTIME dir,
not in `src/Matrix/rules/`), and two consecutive `fs.write` onto the rules path
both landed with correct content.

Deterministic, no model, no network, no server.
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v663-")
for _var, _tail in (
    ("LONGRUN_DATA_DIR", "data"),
    ("LONGRUN_CONFIG_DIR", "cfg"),
    ("LONGRUN_DB", "events.db"),
    ("LONGRUN_SESSIONS_DIR", "sessions"),
    ("LONGRUN_GRAPH_DIR", "graphs"),
    ("LONGRUN_ROUTINES_FILE", "routines.json"),
):
    os.environ[_var] = os.path.join(TMP, _tail)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import longrun_agent as L  # noqa: E402
from longrun.orchestrate import routines as routines_mod  # noqa: E402
from longrun.memory import skills  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A. one switch, spelled either way, from the tool layer down -------------
_PROPS = {n: L.TOOL_SCHEMAS[n]["properties"] for n in ("routine.create", "routine.update")}
check("A1 the tool schema declares BOTH spellings of the switch",
      all("disabled" in p and "enabled" in p for p in _PROPS.values()),
      {k: sorted(v) for k, v in _PROPS.items()})

# The roster/session lookup is not what this test is about; the routine store IS
# (LONGRUN_ROUTINES_FILE), so only the identity hop is stubbed.
_old_resolve = L._resolve_agent_session
_old_canon = routines_mod._canonical_agent
L._resolve_agent_session = lambda a: ("session-v663", {"id": "A1"})
routines_mod._canonical_agent = lambda a: (True, "A1")


def _create(**extra):
    args = {"agent": "A1", "goal": "v663 probe", "every_seconds": 60}
    args.update(extra)
    return L._routine_create(args)


try:
    off = _create(disabled=True)
    on = _create()
    explicit = _create(enabled=False)
    check("A2 create disabled:true really starts DISABLED",
          (off.get("routine") or {}).get("enabled") is False, off)
    check("A3 create with no switch still starts ENABLED",
          (on.get("routine") or {}).get("enabled") is True, on)
    check("A4 create enabled:false starts disabled (the documented spelling)",
          (explicit.get("routine") or {}).get("enabled") is False, explicit)

    rid = (off.get("routine") or {}).get("id")
    _create()  # one more, to prove a patch touches only the target
    upd = L._routine_update({"routine": rid, "disabled": True})
    got = (L._routine_get({"routine": rid}) or {}).get("routine") or {}
    check("A5 update with ONLY disabled:true flips the switch (was 'nothing to update')",
          upd.get("ok") and got.get("enabled") is False, (upd, got.get("enabled")))
    empty = L._routine_update({"routine": rid})
    check("A6 an empty patch is still refused by name",
          empty.get("ok") is False and "nothing to update" in str(empty.get("error")),
          empty)
finally:
    L._resolve_agent_session = _old_resolve
    routines_mod._canonical_agent = _old_canon

# ---- B. a name fragment with a digit is a word -------------------------------
_SKILLS = os.path.join(TMP, "skills")
SD = os.path.join(_SKILLS, "probe", "probe-9x2")
os.makedirs(SD, exist_ok=True)
with open(os.path.join(SD, "SKILL.md"), "w", encoding="utf-8") as f:
    f.write("# probe-9x2\n\nA probe skill for the digit tokenizer.\n")
_old_dir, _old_matrix = skills.SKILLS_DIR, skills._matrix_skills_dir
# `list_skills` reports `os.path.relpath(sp, REPO)`; point REPO at the temp root so
# the row is computable even when the temp dir is on another mount (Windows).
_old_repo = skills.REPO
skills.SKILLS_DIR = _SKILLS
skills.REPO = TMP
skills._matrix_skills_dir = lambda: ""
try:
    listed = [s["name"] for s in skills.list_skills(reload=True)]
    hit = [h["name"] for h in skills.search_skills("9x2", limit=5)]
    miss = [h["name"] for h in skills.search_skills("zz99", limit=5)]
    plain = [h["name"] for h in skills.search_skills("probe", limit=5)]
finally:
    skills.SKILLS_DIR, skills._matrix_skills_dir = _old_dir, _old_matrix
    skills.REPO = _old_repo
    shutil.rmtree(_SKILLS, ignore_errors=True)
check("B1 the library lists the skill (the control)",
      listed == ["probe-9x2"], listed)
check("B2 a digit-bearing fragment finds it (was [] — the token was dropped)",
      hit == ["probe-9x2"], hit)
check("B3 a term nobody has still finds nothing (no over-matching)",
      miss == [], miss)
check("B4 a plain word keeps working",
      plain == ["probe-9x2"], plain)

print("\n---\nv663: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
