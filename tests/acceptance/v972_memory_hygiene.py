#!/usr/bin/env python3
"""v972 — the machine-written memory store bounds itself (admission has a retirement).

Measured on 2026-11-14: `agent_notes.md` held 684 records / 213 KB, and NOTHING in
the tree ever retired one — the loop admits and never retires ("hundreds of
useless memories"). The primitives already existed (`invalidate`, `supersede`,
`effective_score`, the 0.85 near-duplicate test) with no caller and no budget.

This pins the new contract:

  A) under the budget, every store appends and nothing is superseded (unchanged);
  B) over the budget the LOWEST-value records are superseded, not the oldest —
     a high-scoring old record survives a low-scoring new one;
  C) the file stays APPEND-ONLY: every record is still on disk, only hidden;
  D) recall stops surfacing a superseded record, and its id is a tombstone target;
  E) a near-duplicate write supersedes the copy already stored (no second truth);
  F) a USER-authored kind is never auto-retired, however far over budget;
  G) `hygiene(dry_run=True)` reports and changes nothing;
  H) the budget is read from the config owner (env override -> LIMITS block);
  I) `store()` still returns its record with `mid`/`ts` (contract unchanged).

Deterministic: temp data dir, no model, no network, no server.
Run: python3 tests/acceptance/v972_memory_hygiene.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v972-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "config")
os.environ["LONGRUN_MEMORY_MAX_RECORDS"] = "5"
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import memory  # noqa: E402

memory._REBUILD_INTERVAL = 10 ** 9          # no vector rebuild, no embedder
DERIVED = "agent.note"
USER_KIND = "memory.store"

CHECK = []


def ok(name, cond, detail=""):
    CHECK.append((name, bool(cond), detail))
    print("%s %s%s" % ("ok  " if cond else "FAIL", name,
                       "" if cond else "  <- %s" % (detail,)))


def note(text, score=1.0, kind=DERIVED):
    return memory.store(kind, text, origin="reflect", score=score)


def live(kind=DERIVED):
    return [r for r in memory._parse_md_file(memory._path(kind))
            if memory.is_valid(r)]


def raw_count(kind=DERIVED):
    return len(memory._parse_md_file(memory._path(kind)))


def reset(kind=DERIVED):
    p = memory._path(kind)
    if os.path.exists(p):
        os.remove(p)


# --- A) under budget: append only, nothing superseded -------------------------
reset()
a = note("alpha one")
ok("A1 store returns its record (mid + ts)",
   isinstance(a, dict) and a.get("mid") and a.get("ts"), a)
for i in range(4):
    note("filler record %d" % i)
ok("A2 under the budget nothing is superseded",
   len(live()) == 5 and memory.superseded_count(DERIVED) == 0,
   (len(live()), memory.superseded_count(DERIVED)))

# --- B) over budget: the LOWEST value goes, not the oldest --------------------
reset()
note("high value old", score=5.0)
note("low one", score=1.0)
note("low two", score=1.0)
note("low three", score=1.0)
note("low four", score=1.0)
note("low five", score=1.0)      # 6th -> budget 5 -> one retirement
kept = [r["content"] for r in live()]
ok("B1 the count lands exactly on the budget", len(kept) == 5, len(kept))
ok("B2 the high-scoring OLD record survives", "high value old" in kept, kept)
ok("B3 the lowest-value (oldest of the rest) is the one retired",
   "low one" not in kept and "low five" in kept, kept)

# --- C) append-only: the file still holds every record ------------------------
ok("C1 nothing was deleted from the file", raw_count() == 6, raw_count())

# --- D) recall hides it; the id is a tombstone target ------------------------
bad = memory.invalid_targets()
hidden = [r for r in memory._parse_md_file(memory._path(DERIVED))
          if str(r.get("mid") or "") in bad]
ok("D1 exactly one record is tombstoned, and the file still holds all six",
   len(hidden) == 1 and raw_count() == 6, (hidden, raw_count()))
hits = memory.governed_query(kind=DERIVED, limit=20)
ok("D2 recall no longer surfaces it",
   all(r.get("mid") != hidden[0].get("mid") for r in hits),
   [r.get("content") for r in hits])

# --- E) a near-duplicate supersedes the stored copy --------------------------
reset()
first = note("the workspace build must run before the battery suite")
note("the workspace build must run before the battery suite")
dups = [r for r in live() if "workspace build" in r["content"]]
ok("E1 a near-duplicate is superseded, not duplicated", len(dups) == 1, len(dups))
ok("E2 the survivor is the NEWER copy", dups and dups[0]["mid"] != first["mid"],
   dups)
ok("E3 the file kept both (append-only)", raw_count() == 2, raw_count())

# --- F) a user-authored kind is never auto-retired ---------------------------
reset(USER_KIND)
for i in range(12):
    memory.store(USER_KIND, "user preference %d" % i)
ok("F1 the user's own memories are untouched by hygiene",
   len(live(USER_KIND)) == 12 and memory.superseded_count(USER_KIND) == 0,
   (len(live(USER_KIND)), memory.superseded_count(USER_KIND)))

# --- G) dry run ---------------------------------------------------------------
# The bound is AUTOMATIC, so `store()` alone cannot leave the file over budget:
# the dry run is exercised with an explicit lower budget.
reset()
for i in range(5):
    note("dry run record %d" % i)
rep = memory.hygiene(DERIVED, budget=2, dry_run=True)
ok("G1 a dry run reports the excess and changes nothing",
   rep.get("dry_run") is True and rep.get("excess") == 3
   and len(live()) == 5, rep)

# --- H) the budget comes from the config owner -------------------------------
ok("H1 the budget honours the env override",
   memory.hygiene_budget(DERIVED) == 5, memory.hygiene_budget(DERIVED))

# --- I) a non-derived kind has no budget -------------------------------------
ok("I1 no budget declared for a user kind",
   memory.hygiene_budget(USER_KIND) is None, memory.hygiene_budget(USER_KIND))

# --- J) a kind never written yet is normal, not an error ----------------------
fresh = os.path.join(TMP, "data", "memory", "plan_updates.md")
if os.path.exists(fresh):
    os.remove(fresh)
rep = memory.hygiene("plan.update", dry_run=True)
ok("J1 an absent store reports zero records, not an error",
   rep.get("ok") is True and rep.get("records") == 0 and not rep.get("error"), rep)

good = [n for n, c, _ in CHECK if c]
print("\n%d/%d checks passed" % (len(good), len(CHECK)))
sys.exit(0 if len(good) == len(CHECK) else 1)
