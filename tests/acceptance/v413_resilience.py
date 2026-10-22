"""v413 — resilience regressions (JAG-413).

Root bugs fixed here (all found by the session-lifecycle / sandbox audits):

  1. A corrupted `events.db` (bad header after `kill -9` / power loss) crashed the
     whole server on the very first event — `sqlite3.connect()` was happy, the
     first `CREATE TABLE`/`PRAGMA` raised `DatabaseError` with no recovery.
  2. `sandbox._run`/`_run_tracked` used `communicate()` on PIPEs, reading ALL
     stdout/stderr into memory — a command that spews gigabytes exhausted the host.
  3. `docio._run` had the same unbounded capture on `pdftotext`/`soffice`/`tesseract`.
  4. `docio._ocr_pdf` sorted the page images lexicographically (`page-1, page-10,
     page-2`), scrambling any 10+ page scan.
  5. A `-x.pdf` path was handed to the converters as a command-line option.
  6. Deleting a session left its checkpoints orphaned (keyed by checkpoint id, but
     carrying `session_id` in the manifest) — a later rollback half-applied.
  7. An UNKNOWN `sandbox.backend` value (a typo, "dockerr") fell into the `auto`
     branch, and `sandbox.run(backend=<unknown>)` fell through to host execution:
     an "isolated" run silently became an unchecked host run (JAG-2.7).

Stdlib-only, deterministic, no network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="v413-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if (detail and not ok) else ""))


# ------------------------------------------------ 1) corrupt events.db recovers
from longrun.core import events  # noqa: E402

with open(events.DB_PATH, "wb") as fh:
    fh.write(b"NOT A SQLITE DATABASE" * 200)
events._db = None
conn = events.db()
tables = {r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
check("1a a corrupt events.db recovers (schema rebuilt)",
      {"events", "runs"} <= tables, tables)
check("1b the corrupt file is quarantined",
      any(".corrupt-" in f for f in os.listdir(os.path.dirname(events.DB_PATH))))
conn.execute("INSERT INTO events(ts, kind, data) VALUES(?,?,?)", (1.0, "t", "{}"))
conn.commit()
check("1c the recovered DB is writable",
      conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1)

# ------------------------------------------------ 2) sandbox caps huge output
from longrun.tools import sandbox  # noqa: E402

r = sandbox._run_tracked([sys.executable, "-c",
                          "import sys; sys.stdout.write('X'*5000000)"], timeout=30)
check("2a sandbox output is capped (no memory blow-up)",
      0 < len(r["stdout"]) <= sandbox.MAX_OUTPUT_BYTES + 200, len(r["stdout"]))
check("2b truncation marker present", "truncated" in r["stdout"])
r2 = sandbox._run([sys.executable, "-c", "print('ok')"], timeout=10)
check("2c normal command output preserved",
      r2["exit_code"] == 0 and r2["stdout"].strip() == "ok", r2)

# ------------------------------- 2d-2h) an unknown backend never means "host"
# JAG-2.7 (live, 2026-10-22): `probe()` treated ANY unrecognized value as `auto`
# (it was the trailing `else`), and `run(backend=...)` fell through to host
# execution for a name it did not know. So `sandbox.backend: docking` (a typo) or
# `run(backend="bogus")` ran the command UNCHECKED on the host while reporting
# `sandboxed: false` — the exact degradation JAG-431r4b set out to remove.
_reg = sandbox.registry
_orig_cfg = _reg.load_config
_orig_probes = (sandbox._probe_docker, sandbox._probe_bwrap, sandbox._probe_nsjail)


def _cfg(backend):
    def _f(force=False):
        return {"sandbox": {"backend": backend, "image": "alpine:latest",
                            "timeout_secs": 10, "workspace": os.path.join(tmp, "ws")}}
    return _f


sandbox._probe_docker = lambda image: (False, "no docker in the test")
sandbox._probe_bwrap = lambda: (False, "no bwrap in the test")
sandbox._probe_nsjail = lambda: (False, "no nsjail in the test")

_reg.load_config = _cfg("dockerr")
sandbox.invalidate_probe()
try:
    _p = sandbox.probe()
    check("2d a misspelled sandbox.backend is refused, not silently auto-picked",
          False, _p)
except RuntimeError as _e:
    check("2d a misspelled sandbox.backend is refused, not silently auto-picked",
          "unknown backend" in str(_e), _e)

_marker = os.path.join(tmp, "sandbox-host-proof")
_reg.load_config = _cfg("auto")
sandbox.invalidate_probe()
_r = sandbox.run("touch %s" % _marker, backend="bogus", run_id="v413-typo")
check("2e run(backend=<unknown>) refuses instead of running on the host",
      _r.get("exit_code") == 126 and _r.get("sandboxed") is False
      and not os.path.exists(_marker) and "unknown backend" in str(_r.get("error")), _r)

_p = sandbox.probe()
check("2f auto with nothing available still reports none (unchanged behaviour)",
      _p["backend"] == "none" and _p["isolated"] is False, _p)

_reg.load_config = _cfg("docker")
sandbox.invalidate_probe()
try:
    _p = sandbox.probe()
    check("2g an explicit unavailable backend still refuses the host fallback",
          False, _p)
except RuntimeError as _e:
    check("2g an explicit unavailable backend still refuses the host fallback",
          "not available" in str(_e), _e)

_reg.load_config = _cfg("auto")
sandbox.invalidate_probe()
_p1 = sandbox.probe()
sandbox._probe_docker = lambda image: (True, "docker appeared")
sandbox.invalidate_probe()
_p2 = sandbox.probe()
check("2h invalidate_probe() re-probes and picks a backend that appeared later",
      _p1["backend"] == "none" and _p2["backend"] == "docker", (_p1, _p2))

_reg.load_config = _orig_cfg
(sandbox._probe_docker, sandbox._probe_bwrap, sandbox._probe_nsjail) = _orig_probes
sandbox.invalidate_probe()

# ------------------------------------------------ 3) docio caps + page order
from longrun.memory import docio  # noqa: E402

docio._MAX_OUTPUT = 1000
_rc, out, _err = docio._run([sys.executable, "-c",
                             "import sys; sys.stdout.write('Y'*5000)"])
check("3a docio subprocess output is capped", len(out) <= 1000, len(out))
names = ["page-10.png", "page-2.png", "page-1.png"]
check("3b OCR pages sort naturally",
      sorted(names, key=docio._page_index) == ["page-1.png", "page-2.png", "page-10.png"],
      sorted(names, key=docio._page_index))
_empty = os.path.join(tmp, "empty.pdf")
with open(_empty, "wb"):
    pass
_res_empty = docio.extract(_empty)
check("3c empty document rejected early",
      _res_empty.get("text") is None and _res_empty.get("engine") == "empty file",
      _res_empty)

# ------------------------------------------------ 4) checkpoints purged on delete
from longrun.memory import checkpoints  # noqa: E402

ck = tempfile.mkdtemp(prefix="v413-ck-")
checkpoints.CKPT_DIR = ck


def _mk(cid, sid):
    with open(checkpoints._snapshot_path(cid), "w") as fh:
        fh.write("{}")
    return {"id": cid, "session_id": sid}


checkpoints._save_index([_mk("cp_a1", "sA"), _mk("cp_b1", "sB"), _mk("cp_a2", "sA")])
_n = checkpoints.purge_session("sA")
check("4a only the deleted session's checkpoints are removed",
      _n == 2 and [m["id"] for m in checkpoints._load_index()] == ["cp_b1"], _n)
check("4b their snapshot files are unlinked, others kept",
      not os.path.exists(checkpoints._snapshot_path("cp_a1"))
      and os.path.exists(checkpoints._snapshot_path("cp_b1")))

print("---")
ok = sum(results)
print("%d/%d checks passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
