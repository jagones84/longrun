#!/usr/bin/env python3
"""v686 — H2-6 compose: selection is evidence, not durable adoption.

"Composition is selective … Each decision is tied to a concrete observation rather
than a presumed score gain" (`papers/harness2/harness2_2610.14224.txt:291-297`).
The direct-editing ablation jointly removes reference executions, probes and
library (`:646-649`). Its 10.2-point WB-code loss is not a pure no-probe effect.

Selection is a bounded observation: a candidate is kept only
when the contrast is comparable AND its verdict is `improved`. `mixed` is not
"mostly improved" — it is refused, with the introduced error class named.

  A  an improved contrast supports ephemeral candidate selection
  B  regressed / unchanged / mixed / incomparable adopt NOTHING and say why
  C  compatibility adopt always returns None, with no component/experience writes
  D  reflection retains confounded observations as NO_ENTRY, never a lesson
  E  the decision text cites the observation (the fixed class), not a score

No model, no network, no server.
"""
import os
import shutil
import sys
import tempfile
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v686-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "DATA_HOME", "DATA_DIR", "HARNESS_DIR",
           "RUNS_DIR", "PROJECTS_DIR", "SKILLS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_HOOKS"] = os.path.join(TMP, "hooks.yaml")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import compose as C  # noqa: E402
from longrun.harness import library as L  # noqa: E402
from longrun.util import improve as IMP  # noqa: E402

results = []


def check(name, ok, detail=""):
    """Record one assertion (repo convention)."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def contrast(verdict, fixed=(), introduced=(), comparable=True):
    """A contrast shaped like `harness.contrast.diff` output."""
    return {"comparable": comparable, "verdict": verdict,
            "errors": {"base": 1, "cand": 0, "fixed": list(fixed),
                       "introduced": list(introduced), "classes_base": {}, "classes_cand": {}},
            "deliverables": {"base": 1, "cand": 1, "only_base": [], "only_cand": [], "changed": []},
            "steps": {"base": 3, "cand": 3, "saved": 0},
            "steps_saved": 0, "reasons": ["fixed error class(es): " + ", ".join(fixed) if fixed else "none"]}


CAND = {"kind": "skill", "name": "reconcile", "content": "Inventory inputs first.\n"}
STAGE = os.path.join(TMP, "stage")
os.makedirs(STAGE, exist_ok=True)
STAGED = os.path.join(STAGE, "SKILL.md")
with open(STAGED, "w", encoding="utf-8") as f:
    f.write(CAND["content"])

# --------------------------------------------------------------- A: improved --
good = contrast("improved", fixed=["exit # connection refused"])
sel = C.select(good, [CAND])
check("A1 an improved contrast keeps the candidate", sel["adopt"] is True
      and [k["name"] for k in sel["kept"]] == ["reconcile"], sel)
check("A2 the decision names the fixed error class",
      "exit # connection refused" in sel["decision"], sel["decision"])
check("A3 nothing is rejected", sel["rejected"] == [])

# -------------------------------------------------------- B: everything else --
for verdict in ("regressed", "unchanged", "mixed"):
    bad = contrast(verdict, introduced=["exit # permission denied"] if verdict != "unchanged" else [])
    got = C.select(bad, [CAND])
    check("B1 %s adopts nothing and says the verdict" % verdict,
          got["adopt"] is False and got["kept"] == [] and verdict in got["decision"],
          got["decision"])
incomp = contrast("incomparable", comparable=False, fixed=["exit # x"])
got = C.select(incomp, [CAND])
check("B2 an incomparable contrast adopts nothing even with a 'fix'",
      got["adopt"] is False and "not evidence" in got["decision"].lower(), got["decision"])
check("B3 every rejection names a reason",
      len(got["rejected"]) == 1 and got["rejected"][0]["name"] == CAND["name"]
      and all(r.get("reason") for r in got["rejected"]), got["rejected"])

# ------------------------------------------------------------- C: adoption ---
before = IMP.list_proposals()
with patch.object(L, "add", side_effect=AssertionError("durable library write")), \
        patch.object(IMP, "propose", side_effect=AssertionError("durable proposal write")):
    for verdict in ("improved", "regressed", "unchanged", "mixed", "incomparable"):
        row = C.adopt("office", "budget reconciliation", "Unverified transferable claim.",
                      contrast(verdict, fixed=["exit # connection refused"],
                               comparable=verdict != "incomparable"),
                      [CAND], {CAND["name"]: STAGED})
        check("C1 %s compatibility adoption is always None" % verdict, row is None)
check("C2 no component was durably copied",
      not os.path.exists(L.domain_dir("office"))
      and open(STAGED, encoding="utf-8").read() == CAND["content"])
check("C3 no EXPERIENCE.md or proposal was written",
      not any("EXPERIENCE.md" in names for _base, _dirs, names in os.walk(TMP))
      and IMP.list_proposals() == before)

# -------------------------------------------------------- D: reflection ------
trials = [{"candidate": CAND, "status": "ran", "record": {"run_id": "trial-1"},
           "contrast": good},
          {"candidate": dict(CAND, name="regressed"), "status": "ran",
           "record": {"run_id": "trial-2"},
           "contrast": contrast("mixed", fixed=["exit # connection refused"],
                                introduced=["exit # permission denied"])}]
successor = {"record": {"run_id": "successor"}, "contrast": good}
reflected = C.reflect(trials, successor)
check("D1 even an improved executed successor reflects NO_ENTRY",
      reflected["status"] == "NO_ENTRY" and reflected["successor_run"] == "successor"
      and "NO_ENTRY" in reflected["reason"])
check("D2 reflection retains every observed fixed and introduced class",
      len(reflected["edits"]) == 2
      and reflected["edits"][0]["run_id"] == "trial-1"
      and reflected["edits"][0]["observed"] == "improved"
      and reflected["edits"][0]["fixed"] == ["exit # connection refused"]
      and reflected["edits"][1]["introduced"] == ["exit # permission denied"])
check("D3 every single-rollout attribution is confounded and insufficient",
      all(e["attribution"] == "confounded" and e["confidence"] == "insufficient"
          and "controls" in e["reason"] for e in reflected["edits"]))
check("D4 insufficient and absent trials never create durable lessons",
      C.reflect([])["status"] == "NO_ENTRY" and C.reflect([])["edits"] == []
      and L.index("office")["entries"] == [] and IMP.list_proposals() == before)

# ----------------------------------------------------------- E: determinism ---
check("E1 select is deterministic", C.select(good, [CAND]) == sel)
check("E2 reflection is deterministic", C.reflect(trials, successor) == reflected)
check("E3 absent and unknown contrasts cannot select candidates",
      C.select(None, [CAND])["adopt"] is False
      and C.select(contrast("unknown"), [CAND])["kept"] == []
      and C.select(good, [])["adopt"] is False)

shutil.rmtree(TMP, ignore_errors=True)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
