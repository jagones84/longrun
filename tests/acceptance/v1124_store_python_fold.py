#!/usr/bin/env python3
"""v1124 — a CONSTANT path that reaches the record is judged, however it is spelled.

Round 58. `check_python_write` resolved only bare literals, so one rewrite walked
past it — measured live 2026-11-18 against the running service:

    open("/home/jagones/.longrun/data/events.db","a")                  -> refused
    open(os.path.expanduser("~/.longrun/data/events.db"),"a")          -> ALLOWED
    open(os.path.join("~/.longrun/data","events.db"),"a")              -> ALLOWED

The value is a CONSTANT in both spellings, so it is now folded and judged like a
literal. The contract `v1072` pins is unchanged: the guard is a WRITE gate (a
read is not a write), and a target behind a NAME still fails open.

  A  a literal write to the store refused (unchanged)
  B  the expanduser spelling refused
  C  the os.path.join spelling refused
  D  `"a" + "b"` concatenation refused
  E  a python READ of the store stays allowed (v1072 P6)
  F  a target behind a NAME stays fail-open (v1072 P7)
  G  an ordinary workspace write is allowed
  H  a literal Nucleous write keeps its own NUCLEOUS_PROTECTED message
  I  the operator window still lifts the guard
  J  `pathlib.Path(os.path.expanduser(...)).write_text` refused

Deterministic: the guard is a pure function of the snippet; no process, no model.
Run: python3 tests/acceptance/v1124_store_python_fold.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import matrix_guard as G  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def verdict(code, ws=REPO):
    return G.check_python_write(code, workspace=ws, repo_root=REPO)


# The STORE is whatever THIS process's guard protects — the battery isolates the
# data home into sibling dirs (`LONGRUN_DATA_DIR=$d/data`, `LONGRUN_DB=$d/events.db`),
# so a path derived from `paths.DATA_DIR` alone tested the wrong store (measured:
# green standalone, red under the gate).
ROOTS = G._store_targets()
assert ROOTS, "no store roots resolved"
STORE = os.path.join(ROOTS[0], "probe.db")
DATA = os.path.dirname(STORE)
HOME = os.path.expanduser("~")
TILDE = ("~" + STORE[len(HOME):]) if STORE.startswith(HOME + os.sep) else None

# A — the literal rule is unchanged.
ok, why = verdict("open(%r,'a').write('')" % STORE)
check("A1 a literal write to the event log is refused", ok is False and
      "STORE_PROTECTED" in why, why)

# B — a constant folded through os.path (normpath always; expanduser when the
# store lives under the home directory).
ok, why = verdict(
    "import os;open(os.path.normpath(%r),'a').write('')" % (DATA + "/./events.db"))
check("B1 the normpath spelling is refused", ok is False and
      "STORE_PROTECTED" in why, why)
if TILDE:
    ok, why = verdict("import os;open(os.path.expanduser(%r),'a').write('')" % TILDE)
    check("B2 the expanduser spelling is refused", ok is False and
          "STORE_PROTECTED" in why, why)

# C — join of constants.
ok, why = verdict(
    "import os;open(os.path.join(%r,'events.db'),'a').write('')" % DATA)
check("C1 the os.path.join spelling is refused", ok is False and
      "STORE_PROTECTED" in why, why)

# D — concatenation of constants.
ok, why = verdict("open(%r + 'events.db','a').write('')" % (DATA + "/"))
check("D1 a concatenated constant target is refused", ok is False and
      "STORE_PROTECTED" in why, why)

# E — reading is not writing (v1072 P6).
ok, why = verdict("print(open(%r,'rb').read(8))" % STORE)
check("E1 a python read of the store is still allowed", ok is True and not why, why)

# F — a target behind a NAME stays the documented fail-open limit (v1072 P7).
ok, why = verdict("p = %r\nopen(p,'a').write('')" % STORE)
check("F1 a target behind a variable stays fail-open", ok is True and not why, why)

# G — ordinary work still runs.
ok, why = verdict("open('out.json','w').write('{}')")
check("G1 a workspace write is allowed", ok is True and not why, why)

# H — the Nucleous message is not replaced.
ok, why = verdict("open('src/longrun/tools/matrix_guard.py','a').write('')")
check("H1 a Nucleous write keeps its own message",
      ok is False and "NUCLEOUS_PROTECTED" in why, why)

# I — the operator window still lifts it.
_real_unlocked = G.nucleous_write_unlocked
G.nucleous_write_unlocked = lambda: True
try:
    ok, why = verdict("open(%r,'a').write('')" % STORE)
    check("I1 the unlocked window still lifts the guard", ok is True and not why, why)
finally:
    G.nucleous_write_unlocked = _real_unlocked

# J — pathlib over a folded constant.
ok, why = verdict(
    "import os\nfrom pathlib import Path\n"
    "Path(os.path.normpath(%r)).write_text('')" % (DATA + "/./events.db"))
check("J1 pathlib over a folded constant is refused", ok is False and
      "STORE_PROTECTED" in why, why)

print("\n---\nv1124: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
