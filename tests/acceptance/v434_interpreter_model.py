"""v434 — interpreter & dependency model: the app runs NON-venv (JAG-431e).

The app runs on the system interpreter (stdlib core + PyYAML); a venv's packages are
invisible to it. `requirements.txt` = runtime extras (installed for THAT interpreter);
`requirements-dev.txt` = the dev tooling that populates the repo's `.venv` (used by
`tests/mega_test.sh`), which is NOT the app runtime. Also guards the dev venv rebuild
recipe so it stops drifting.

Deterministic, offline.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


REQS = _read("requirements.txt")
DEV = _read("requirements-dev.txt")
RUN_SH = _read("run.sh")
MEGA = _read("tests", "mega_test.sh")
README = _read("README.md")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- the app runs on the system interpreter (non-venv) ----------------------
check("1a run.sh launches the app with the system `python3`",
      "exec python3 server.py" in RUN_SH, "")
check("1b requirements.txt is the RUNTIME (extras) file, not the dev tools",
      "docling" in REQS and "pytest" not in REQS, "")

# --- the dev venv is reproducible -------------------------------------------
check("2a requirements-dev.txt exists with the dev tooling",
      all(t in DEV for t in ("pytest", "mypy", "ruff", "mutmut")), "")
check("2b it is documented as dev-only (not the app runtime)",
      "DEVELOPMENT" in DEV.upper() and "does NOT need" in DEV, "")
check("2c mega_test.sh uses a THROWAWAY venv under TMPDIR (repo stays clean)",
      'VENV="${TMPDIR' in MEGA and "requirements-dev.txt" in MEGA, "")

# --- the README explains the model (NO bundled venv) ------------------------
check("3a README installs extras with `pip install --user`",
      "pip install --user -r requirements.txt" in README, "")
check("3b README says requirements are installed for the running interpreter",
      "system" in README.lower() and "interpreter" in README.lower(), "")
check("3c README does NOT tell users to create a repo venv",
      "python3 -m venv .venv" not in README and ".venv/bin/python" not in README, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
