#!/usr/bin/env python3
"""v1082 — the agent may not rewrite its own IMPROVEMENT record.

The trace-store boundary has closed sessions, threads, runs, the event log and
the sealed judge (rounds 2–6). Proved live 2026-11-18: the PROPOSAL record was
still writable by both guards —

    python: (True, '')
    shell : (True, '')
    store targets: [... sessions, threads, runs, heldout, events.db]

— so an agent could rewrite `proposal.json` (status, case table, artifact digest)
and then ask for a promotion whose evidence it had authored. Round 13 adds the
proposal store to the same boundary: `paths.PROPOSALS_DIR` is the ONE owner,
`matrix_guard` denies it in code, `config/tools.yaml` denies it in the fs and
shell spellings, and reading it stays allowed.

Contract:
  L1 python.run cannot write into the proposal store
  L2 shell redirect / delete cannot either
  L3 a shell-invoked interpreter cannot either
  L4 fs.write / fs.edit deny the repo-relative spelling
  L5 reading the store stays allowed (the guard is a write boundary)
  L6 the location has one owner (improve.PROPOSAL_DIR is paths.PROPOSALS_DIR)
  L7 LONGRUN_PROPOSALS_DIR moves the store, like every other store
  L8 an ordinary path is not denied (no blanket)

Deterministic: temp data home, no server, no model.
Run: python3 tests/acceptance/v1082_proposal_store_deny.py
"""
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1082-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
for d in ("data",):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import matrix_guard as MG  # noqa: E402
from longrun.tools import registry  # noqa: E402
from longrun.util import improve, paths  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


STORE = paths.PROPOSALS_DIR
TARGET = os.path.join(STORE, "abc123", "proposal.json")

# ---- L1: python.run ----------------------------------------------------------
ok, err = MG.check_python_write("open(%r, 'w').write('{}')" % TARGET)
check("L1a python.run cannot write proposal.json", ok is False and "heldout" not in err, (ok, err))
ok2, _ = MG.check_python_write("import shutil; shutil.copy('x', %r)" % os.path.join(STORE, "a", "b"))
check("L1b a copy into the store is denied too", ok2 is False)

# ---- L2: shell redirect / delete --------------------------------------------
# Classified through the real gate (the config deny is repo-relative, the same
# spelling an agent emits), exactly as v1071 pins the other stores.
d, why = registry.classify("shell.exec", {"command": "echo '{}' > data/proposals/abc/proposal.json"})
check("L2a a shell redirect is denied", d == "denied", (d, why))
d, why = registry.classify("shell.exec", {"command": "rm -rf data/proposals/abc"})
check("L2b deleting a proposal folder is denied", d == "denied", (d, why))

# ---- L3: shell-invoked interpreter ------------------------------------------
d, why = registry.classify(
    "shell.exec",
    {"command": 'python3 -c "open(\'data/proposals/abc/proposal.json\',\'w\').write(\'{}\')"'})
check("L3 a shell-invoked interpreter is denied", d == "denied", (d, why))

# ---- L4: fs.write / fs.edit, repo-relative spelling -------------------------
for tool in ("fs.write", "fs.edit"):
    d, why = registry.classify(tool, {"path": os.path.join(REPO, "data", "proposals", "abc", "proposal.json")})
    check("L4 %s denies data/proposals" % tool, d == "denied", (d, why))

# ---- L5: reading stays allowed ----------------------------------------------
ok, _ = MG.check_shell_command("ls -la %s" % STORE)
check("L5a ls of the store is allowed", ok is True)
ok, _ = MG.check_python_write("print(open(%r).read())" % TARGET)
check("L5b a read via python is not a write", ok is True)

# ---- L6: one owner -----------------------------------------------------------
check("L6 improve.PROPOSAL_DIR IS paths.PROPOSALS_DIR",
      improve.PROPOSAL_DIR == paths.PROPOSALS_DIR, improve.PROPOSAL_DIR)
check("L6b the store sits under the data home",
      os.path.realpath(STORE).startswith(os.path.realpath(paths.DATA_DIR) + os.sep), STORE)

# ---- L7: the env override ----------------------------------------------------
ALT = os.path.join(TMP, "alt-proposals")
out = subprocess.run([sys.executable, "-c",
                      "import sys; sys.path.insert(0, %r); "
                      "from longrun.util import paths, improve; "
                      "print(paths.PROPOSALS_DIR); print(improve.PROPOSAL_DIR)"
                      % os.path.join(REPO, "src")],
                     capture_output=True, text=True,
                     env=dict(os.environ, LONGRUN_PROPOSALS_DIR=ALT))
lines = [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]
check("L7 LONGRUN_PROPOSALS_DIR moves the store for both owners",
      lines == [ALT, ALT], (lines, out.stderr[-200:]))

# ---- L8: no blanket ----------------------------------------------------------
ok, _ = MG.check_python_write("open(%r, 'w').write('x')"
                              % os.path.join(REPO, "notes.txt"))
check("L8 an ordinary path is not denied", ok is True)

print("\n---\nv1082: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
