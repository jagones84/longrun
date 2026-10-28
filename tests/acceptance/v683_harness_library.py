#!/usr/bin/env python3
"""v683 — H2-3 improvement library: executable components + the lesson of when.

Harness² keeps the ADOPTED harness of a task together with an `EXPERIENCE.md`
(why it was chosen, which recurring weakness it addressed) and an index, and the
next task starts from the base harness but may REUSE components from the library
(`papers/harness2/harness2_2610.14224.txt:1291-1294`, `:370-404`). The library
ablation is the second-largest measured loss (−3.1 WB / −1.8 JB, Table 3).

Longrun has lessons as TEXT (`memory/memory.py:723`) and an inbox of proposals
(`util/improve.py:18`), but nowhere to keep an executable component with the
evidence for its use. This test pins that store:

  A  add copies the component files and writes EXPERIENCE.md
  B  the id is unique (a duplicate is refused, never merged silently)
  C  a corrupt index self-heals from the entry directories
  D  relevant() returns bounded, matching entries only
  E  domains are isolated
  F  a component that does not exist is refused (no dangling reference)
  G  leave_one_out reports "insufficient" until there is enough data

No model, no network, no server.
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v683-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "DATA_DIR", "HARNESS_DIR", "RUNS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_HOOKS"] = os.path.join(TMP, "hooks.yaml")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import library as L  # noqa: E402

results = []


def check(name, ok, detail=""):
    """Record one assertion (repo convention)."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


SKILL = os.path.join(TMP, "src", "SKILL.md")
GUARD = os.path.join(TMP, "src", "guardrails.md")
os.makedirs(os.path.dirname(SKILL), exist_ok=True)
with open(SKILL, "w", encoding="utf-8") as f:
    f.write("---\nname: reconcile\n---\nReconcile schedule, roster and budget files.\n")
with open(GUARD, "w", encoding="utf-8") as f:
    f.write("Before analysing, inventory ALL supplied files.\n")

ENTRY = {
    "id": "reconcile-schedule-budget",
    "task_kind": "budget reconciliation across spreadsheets",
    "lesson": "Reconciling the schedule against the budget removed 12 missed cells.",
    "evidence": {"verdict": "improved", "fixed": ["exit # formula blank"]},
    "files": {"SKILL.md": SKILL, "guardrails.md": GUARD},
}

# ------------------------------------------------------------------ A: add ---
got = L.add("office", ENTRY)
check("A1 add returns the stored entry", bool(got) and got.get("id") == ENTRY["id"], got)
components = sorted(os.listdir(os.path.join(L.entry_dir("office", ENTRY["id"]), "components")))
check("A2 both components are copied as files", components == ["SKILL.md", "guardrails.md"],
      components)
experience = L.experience_text("office", ENTRY["id"])
check("A3 EXPERIENCE.md carries the situation, the lesson and the evidence",
      "budget reconciliation" in experience and "12 missed cells" in experience
      and "improved" in experience, experience[:120])

# ------------------------------------------------------------ B: duplicate ----
check("B1 a duplicate id is refused (no silent merge)", L.add("office", ENTRY) is None)

# ------------------------------------------------------------- C: index ------
idx = L.index("office")
check("C1 the index lists the entry with its component names",
      len(idx["entries"]) == 1
      and idx["entries"][0]["components"] == ["SKILL.md", "guardrails.md"], idx)
index_path = L.index_path("office")
with open(index_path, "w", encoding="utf-8") as f:
    f.write("{broken")
healed = L.index("office")
check("C2 a corrupt index self-heals from the entry directories",
      len(healed["entries"]) == 1 and healed["entries"][0]["id"] == ENTRY["id"], healed)
check("C3 rewriting the index is idempotent", L.index("office") == L.index("office"))

# ---------------------------------------------------------- D: relevance -----
hit = L.relevant("office", "reconcile the budget spreadsheet against the schedule")
check("D1 a matching task finds the entry", [e["id"] for e in hit] == [ENTRY["id"]], hit)
check("D2 a lesson in the index is bounded", all(len(e["lesson"]) <= L.LESSON_MAX for e in hit))
miss = L.relevant("office", "write a haiku about the sea")
check("D3 an unrelated task returns nothing", miss == [], miss)
many = L.relevant("office", "budget schedule spreadsheet reconcile", limit=1)
check("D4 the limit is respected", len(many) <= 1, many)

# ------------------------------------------------------------ E: domains -----
check("E1 another domain does not see it", L.index("legal")["entries"] == []
      and L.relevant("legal", "reconcile the budget") == [])

# -------------------------------------------------------- F: bad component ---
bad = dict(ENTRY, id="dangling", files={"SKILL.md": os.path.join(TMP, "nope.md")})
check("F1 a missing component file is refused", L.add("office", bad) is None)
check("F2 the refused entry left nothing behind", not os.path.isdir(L.entry_dir("office", "dangling")))

# ------------------------------------------------------- G: leave-one-out ----
loo = L.leave_one_out("office")
check("G1 under three entries the report says insufficient",
      loo["status"] == "insufficient" and loo["entries"] == 1, loo)

# ------------------------------------------------------- H: index fields ----
row = L.index("office")["entries"][0]
check("H1 an index row is small and complete",
      sorted(row.keys()) == ["components", "id", "lesson", "task_kind", "ts"], sorted(row.keys()))
check("H2 the index file is valid JSON", isinstance(json.load(open(index_path)), dict))

shutil.rmtree(TMP, ignore_errors=True)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
