#!/usr/bin/env python3
"""v990 — the worker's LAST status line is the one that counts.

A worker is asked to END its reply with `STATUS: DONE` (or `STATUS: BLOCKED: why`).
`parse_status` used `re.search`, i.e. the FIRST line-start declaration, so a reply
that quoted/rehearsed the format before reporting the real outcome was recorded
with the rehearsal:

    The required format is:
    STATUS: DONE
    but the migration failed, so:
    STATUS: BLOCKED: migration error 1064      ->  was ('DONE', 'but the migration failed, so:')

A subjob recorded DONE is handed to the coordinator's synthesis as delivered work,
so this is a false success, not a formatting nit (measured 2026-11-14).

Contract:
  A) one declaration: unchanged;
  B) several: the LAST one wins, with ITS reason;
  C) no declaration: (None, "");
  D) an inline mention (not at line start) is still not a declaration;
  E) the reason is bounded.

Deterministic: pure function.
Run: python3 tests/acceptance/v990_parse_status_last_declaration.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.orchestrate import jobs as J  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: one declaration ---------------------------------------------------
check("A1 DONE alone", J.parse_status("All good.\nSTATUS: DONE") == ("DONE", ""),
      J.parse_status("All good.\nSTATUS: DONE"))
check("A2 BLOCKED keeps its reason",
      J.parse_status("cannot reach it\nSTATUS: BLOCKED: network down") == ("BLOCKED", "network down"),
      J.parse_status("cannot reach it\nSTATUS: BLOCKED: network down"))
check("A3 FAILED", J.parse_status("STATUS: FAILED: tests red") == ("FAILED", "tests red"),
      J.parse_status("STATUS: FAILED: tests red"))
check("A4 OK and COMPLETE both read as DONE",
      J.parse_status("STATUS: OK")[0] == "DONE" and J.parse_status("STATUS: COMPLETE")[0] == "DONE")

# ---- B: the last declaration wins ----------------------------------------
_quoted = ("The required format is:\nSTATUS: DONE\nbut the migration failed, so:\n"
           "STATUS: BLOCKED: migration error 1064")
check("B1 a quoted DONE before the real BLOCKED does not win",
      J.parse_status(_quoted) == ("BLOCKED", "migration error 1064"), J.parse_status(_quoted))
_recovered = "first I thought it was blocked:\nSTATUS: BLOCKED: no network\nthen it worked.\nSTATUS: DONE"
check("B2 a later DONE wins over an earlier BLOCKED",
      J.parse_status(_recovered) == ("DONE", ""), J.parse_status(_recovered))
_three = "STATUS: BLOCKED: a\nSTATUS: DONE\nSTATUS: FAILED: b"
check("B3 three declarations: the last one", J.parse_status(_three) == ("FAILED", "b"),
      J.parse_status(_three))

# ---- C: none -------------------------------------------------------------
check("C1 a reply with no status is (None, '')", J.parse_status("just prose") == (None, ""),
      J.parse_status("just prose"))
check("C2 empty reply is (None, '')", J.parse_status("") == (None, ""), J.parse_status(""))

# ---- D: an inline mention is not a declaration ---------------------------
check("D1 inline mention is ignored",
      J.parse_status("I will end with `STATUS: DONE` when finished") == (None, ""),
      J.parse_status("I will end with `STATUS: DONE` when finished"))
check("D2 a bulleted example is ignored",
      J.parse_status("- Example: STATUS: DONE") == (None, ""),
      J.parse_status("- Example: STATUS: DONE"))

# ---- E: the reason is bounded -------------------------------------------
_long = "STATUS: BLOCKED: " + ("x" * 900)
check("E1 reason is capped at 300 chars", len(J.parse_status(_long)[1]) == 300,
      len(J.parse_status(_long)[1]))

ok = sum(RESULTS)
print("\nv990: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
