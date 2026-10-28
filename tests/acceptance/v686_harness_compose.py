#!/usr/bin/env python3
"""v686 — H2-6 compose: adopt only what a contrast supports.

"Composition is selective … Each decision is tied to a concrete observation rather
than a presumed score gain" (`papers/harness2/harness2_2610.14224.txt:291-297`).
The failure this prevents is measured: editing the harness WITHOUT probing costs
10.2 points on WB-code (`:646-649`).

So the rule here is one line and it is the whole feature: a candidate is kept only
when the contrast is comparable AND its verdict is `improved`. `mixed` is not
"mostly improved" — it is refused, with the introduced error class named.

  A  an improved contrast keeps the candidates and allows an adoption
  B  regressed / unchanged / mixed / incomparable adopt NOTHING and say why
  C  the adopted entry lands in the library with its components + EXPERIENCE.md
  D  an unchanged contrast writes no library entry at all
  E  the decision text cites the observation (the fixed class), not a score

No model, no network, no server.
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v686-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "DATA_DIR", "HARNESS_DIR", "RUNS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_HOOKS"] = os.path.join(TMP, "hooks.yaml")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import compose as C  # noqa: E402
from longrun.harness import library as L  # noqa: E402

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
      all(r.get("reason") for r in got["rejected"]), got["rejected"])

# ------------------------------------------------------------- C: adoption ---
row = C.adopt("office", "budget reconciliation", "Inventory inputs before writing.",
              good, [CAND], {CAND["name"]: STAGED})
check("C1 the adoption lands in the library", bool(row) and row["id"], row)
check("C2 the component is stored as a file",
      "SKILL.md" in os.listdir(os.path.join(L.entry_dir("office", row["id"]), "components")),
      os.listdir(os.path.join(L.entry_dir("office", row["id"]), "components")))
exp = L.experience_text("office", row["id"])
check("C3 EXPERIENCE.md records the verdict and the class it removed",
      "improved" in exp and "connection refused" in exp, exp[:160])

# ------------------------------------------------------- D: no entry if flat --
empty_row = C.adopt("office", "another task", "nothing to learn", contrast("unchanged"), [CAND],
                    {CAND["name"]: STAGED})
check("D1 an unchanged contrast writes no library entry", empty_row is None)
check("D2 the library still holds exactly the first entry", len(L.index("office")["entries"]) == 1)

# ----------------------------------------------------------- E: determinism ---
check("E1 select is deterministic", C.select(good, [CAND]) == sel)

shutil.rmtree(TMP, ignore_errors=True)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
