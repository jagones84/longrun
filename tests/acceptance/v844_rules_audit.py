#!/usr/bin/env python3
"""v844 — a rules corpus can be AUDITED (HA-1, lot H).

The harness assembles global + project rules into every turn's system prompt and
only caps their total size (`memory/rules.py` `MAX_BYTES`). It cannot see that two
rules contradict each other, that a rule points at a file that no longer exists,
that the same rule was pasted into both scopes, or WHICH scope is over its budget.
The talk behind lot H (`/doctor`) is exactly that audit.

  A) a contradiction is found (same content, one side negated);
  B) a stale absolute path is found;
  C) a line duplicated across scopes is found;
  D) an over-budget scope is found, with its size;
  E) a clean corpus produces ZERO findings (no noisy doctor);
  F) `GET /api/rules` carries the audit (one surface, no second endpoint).

Deterministic, no live model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v844-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "config")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(TMP, "workspaces")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import rules as R  # noqa: E402

WS = os.path.join(TMP, "workspace")
os.makedirs(WS, exist_ok=True)
os.makedirs(R.prompt_paths(WS)["project_extra_dir"], exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def codes(res):
    return sorted({f["code"] for f in res.get("findings") or []})


# ---------------------------------------------------------------- clean corpus ---
R.save("global", "# House rules\n- Answer in English.\n- Keep commits small.\n")
R.save("project", "# Project\n- Tests run with `bash tests/battery_tmp.sh`.\n", ws=WS)
clean = R.audit(ws=WS)
check("E1 a clean corpus has no findings", clean["findings"] == [], codes(clean))
check("E2 the audit reports its scope counts",
      clean["counts"]["contradiction"] == 0 and clean["total"] == 0)

# -------------------------------------------------------------- contradiction ---
R.save("global", "Always use the staging database for migrations.\n")
R.save("project", "Never use the staging database for migrations.\n", ws=WS)
res = R.audit(ws=WS)
hit = [f for f in res["findings"] if f["code"] == "rules.contradiction"]
check("A1 the contradiction is found", len(hit) == 1, codes(res))
check("A2 it names both files and lines", hit and hit[0]["file"] and hit[0]["line"] > 0,
      hit and (hit[0]["file"], hit[0]["line"]))
check("A3 it carries both offending lines as the evidence",
      hit and "staging database" in hit[0]["evidence"].lower())

# ---------------------------------------------------------------- stale path ---
missing = os.path.join(TMP, "gone", "old-policy.md")
R.save("global", "Read the archive notes at %s before changing the schema.\n" % missing)
R.save("project", "\n", ws=WS)
res = R.audit(ws=WS)
hit = [f for f in res["findings"] if f["code"] == "rules.stale_path"]
check("B1 a rule pointing at a missing file is found", len(hit) == 1, codes(res))
check("B2 the finding names the missing path", hit and missing in hit[0]["evidence"])

# ----------------------------------------------------------------- duplicate ---
same = "- Never edit the contracts folder without an explicit approval."
R.save("global", same + "\n")
R.save("project", same + "\n", ws=WS)
res = R.audit(ws=WS)
hit = [f for f in res["findings"] if f["code"] == "rules.duplicate"]
check("C1 a rule duplicated across scopes is found", len(hit) == 1, codes(res))
check("C2 the duplicate names both scopes",
      hit and len(hit[0].get("scopes") or []) == 2, hit and hit[0].get("scopes"))

# ---------------------------------------------------------------- over budget ---
R.save("global", "- " + ("verbose rule " * 40) + "\n")
R.save("project", "\n", ws=WS)
res = R.audit(ws=WS, max_bytes=200)
hit = [f for f in res["findings"] if f["code"] == "rules.over_budget"]
check("D1 an over-budget scope is found", len(hit) == 1, codes(res))
check("D2 it carries size and cap",
      hit and hit[0]["chars"] > hit[0]["max_bytes"], hit and (hit[0].get("chars"), hit[0].get("max_bytes")))

# --------------------------------------------------------------- one surface ---
src = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"), encoding="utf-8").read()
check("F1 GET /api/rules carries the audit", '"audit"] = ' in src)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
