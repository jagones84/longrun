#!/usr/bin/env python3
"""v1083 — the improvement ledger is a CHAIN, not a file called "append-only".

Rounds 2–13 closed the trace-store boundary (sessions, threads, runs, events,
held-out, proposals) and round 12 made the promotion gate prove it can fail. The
record those verdicts are written INTO was still only append-only by convention.
Measured live 2026-11-18:

    ~/.longrun/data/improvement/ledger.jsonl   500 lines, size 248492
    rows at LEDGER_MAX                         500  -> _trim_ledger REWRITES it
                                                        on every append
    rows carrying prev/hash/chain              0
    shell append / truncate / python / fs.*    auto on all five

So the agent the ledger records could rewrite its own record, and nothing in the
file could tell. Round 14 makes each row carry `seq` / `prev` / `hash`, moves the
chain anchor into `ledger.head.json`, and denies the folder at the same boundary
as the other stores. Design: the tamper-evident verdict log of arXiv 2606.24322
(M4, O(1) append over the previous head). Limit, from arXiv 2609.30266: a chain
proves the rows that ARE there were not altered, never that every action was
written down.

Contract:
  C chain      every row links; verify ok; the cap trims AND records the eviction
  T tamper     edit / delete / swap / truncate / empty / garbage are all named
  M migration  pre-chain rows are re-sealed once, payloads untouched, and said so
  B boundary   no write route reaches the ledger; reading stays allowed
  S surface    the improve tool reports the chain's own verdict

Deterministic: temp data home, no server, no model.
Run: python3 tests/acceptance/v1083_ledger_hash_chain.py
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1083-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import matrix_guard as MG  # noqa: E402
from longrun.tools import registry  # noqa: E402
from longrun.tools import tools as TOOLS  # noqa: E402
from longrun.util import improve, paths  # noqa: E402

RESULTS = []
# the module's OWN defaults, captured before `fresh()` patches them
LEDGER0, HEAD0 = improve.LEDGER_PATH, improve.LEDGER_HEAD_PATH


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def digest(row):
    """The documented formula, recomputed independently of improve._ledger_hash."""
    body = {k: v for k, v in row.items() if k != "hash"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rows():
    with open(improve.LEDGER_PATH, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def rewrite(rs):
    with open(improve.LEDGER_PATH, "w", encoding="utf-8") as f:
        for r in rs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def code():
    return improve.verify_ledger().get("code")


def fresh(n=4, cap=500):
    """A clean ledger of n chained rows, isolated from the live one."""
    d = tempfile.mkdtemp(prefix="sf-v1083-led-", dir=TMP)
    improve.LEDGER_PATH = os.path.join(d, "ledger.jsonl")
    improve.LEDGER_HEAD_PATH = os.path.join(d, "ledger.head.json")
    improve.LEDGER_MAX = cap
    improve.harness_stamp = lambda *a, **k: {}     # keep 500-row loops cheap
    for i in range(n):
        improve.ledger_add("probe", origin="harness", i=i)
    return d


# ---- C: the chain ------------------------------------------------------------
fresh(4)
rs = rows()
check("C1a every row carries seq/prev/hash",
      all(all(k in r for k in ("seq", "prev", "hash")) for r in rs), rs[0].keys())
check("C1b the first row links to the genesis root",
      rs[0]["prev"] == improve.LEDGER_GENESIS, rs[0]["prev"][:12])
check("C1c seq starts at 1 and is consecutive",
      [r["seq"] for r in rs] == list(range(1, len(rs) + 1)), [r["seq"] for r in rs])
check("C2b a clean ledger verifies", code() == "ok", improve.verify_ledger())

walk_ok = True
for i, r in enumerate(rs):
    want = digest(r)
    if want != r["hash"]:
        walk_ok = False
    if i and r["prev"] != rs[i - 1]["hash"]:
        walk_ok = False
check("C3 an independent walk recomputes every link", walk_ok)

tail = improve.ledger_tail(50)
check("C4a ledger_tail is still newest-first",
      tail[0]["seq"] > tail[-1]["seq"], (tail[0]["seq"], tail[-1]["seq"]))
check("C4b ledger_tail still returns the payload fields",
      tail[0].get("kind") == "probe" and tail[0].get("i") == 3, tail[0].get("i"))

# the cap: 5 rows at LEDGER_MAX=4 -> one eviction, recorded in the anchor
fresh(4, cap=4)
improve.ledger_add("cap", origin="harness")
st = improve.verify_ledger()
check("C5a the window stays bounded", st.get("rows") == 4, st.get("rows"))
check("C5b the eviction is recorded in the anchor",
      st.get("evicted") == 1 and (st.get("head") or {}).get("seq") == 1,
      (st.get("evicted"), (st.get("head") or {}).get("seq")))
check("C5c the trimmed chain still verifies", st.get("ok") is True, st.get("code"))
check("C6 the window's first row links to the EVICTED row",
      rows()[0]["prev"] == (st.get("head") or {}).get("hash"))
check("C7 ledger_tail of a capped ledger is exactly the window",
      len(improve.ledger_tail(50)) == 4 and improve.ledger_tail(1)[0]["seq"] == 5)

# ---- T: tamper is named ------------------------------------------------------
fresh(4)
rs = rows()
rs[1]["kind"] = "rewritten"
rewrite(rs)
st = improve.verify_ledger()
check("T1 a payload edit is a hash-mismatch",
      st.get("code") == "hash-mismatch"
      and (st.get("first_bad") or {}).get("id") == rs[1]["id"], st)

fresh(4)
rs = rows()
rewrite(rs[:1] + rs[2:])
check("T2 a middle-row deletion breaks a link", code() == "broken-link", code())

fresh(4)
rs = rows()
rs[1], rs[2] = rs[2], rs[1]
rewrite(rs)
check("T3 two rows swapped break a link", code() == "broken-link", code())

fresh(4)
rewrite(rows()[:2])
check("T4 a tail truncation is `truncated`", code() == "truncated", code())

fresh(4)
open(improve.LEDGER_PATH, "w", encoding="utf-8").close()
check("T5 emptying the file is `truncated` (the anchor proves rows existed)",
      code() == "truncated", code())

fresh(4)
with open(improve.LEDGER_PATH, "a", encoding="utf-8") as f:
    f.write("not json\n")
check("T6 a non-JSON line is `corrupt-line`", code() == "corrupt-line", code())

fresh(4)
rewrite(rows()[1:])
check("T7 dropping the head row without an anchor update is `head-mismatch`",
      code() == "head-mismatch", code())

fresh(4)
rs = rows()
rs[1]["kind"] = "rewritten"
rewrite(rs)
before = open(improve.LEDGER_PATH, encoding="utf-8").read()
st = improve.repair_ledger()
check("T8a repair refuses a hash-mismatch",
      st.get("ok") is False and st.get("repaired") is False
      and st.get("code") == "hash-mismatch", st.get("code"))
check("T8b the refusal leaves the file byte-identical (evidence is not rewritten)",
      open(improve.LEDGER_PATH, encoding="utf-8").read() == before)

fresh(4)
first = rows()[0]
anchor = {"seq": first["seq"], "hash": first["hash"], "evicted": 1,
          "last_seq": rows()[-1]["seq"], "last_hash": rows()[-1]["hash"]}
with open(improve.LEDGER_HEAD_PATH, "w", encoding="utf-8") as f:
    json.dump(anchor, f)
check("T9a a trim that recorded the eviction but did not shrink is `interrupted-trim`",
      code() == "interrupted-trim", code())
st = improve.repair_ledger()
check("T9b repair completes an interrupted trim",
      st.get("ok") is True and st.get("repaired") is True
      and st.get("dropped") == 1, st)
check("T9c the repaired ledger verifies", code() == "ok", code())

# ---- M: the one-time re-seal -------------------------------------------------
d = fresh(3)
legacy = rows()
for r in legacy:
    for k in ("seq", "prev", "hash"):
        r.pop(k, None)
rewrite(legacy)
check("M1 rows written before the chain read as `unchained`", code() == "unchained", code())
improve.ledger_add("after", origin="harness", note="survives")
rs = rows()
marker = [r for r in rs if r.get("kind") == "ledger.chain_init"]
check("M2 the re-seal is recorded as its own entry",
      len(marker) == 1 and marker[0].get("sealed") == 3, marker)
check("M3 the payloads survive the re-seal",
      [r.get("i") for r in rs if r.get("kind") == "probe"] == [0, 1, 2]
      and any(r.get("kind") == "after" and r.get("note") == "survives" for r in rs))
check("M4 the migrated ledger verifies", code() == "ok", code())
check("M5 the chain is continuous across the re-seal",
      [r["seq"] for r in rs] == list(range(1, len(rs) + 1)), [r["seq"] for r in rs])

# ---- B: the boundary ---------------------------------------------------------
STORE = paths.IMPROVEMENT_DIR
LEDGER = os.path.join(STORE, "ledger.jsonl")
ok, err = MG.check_python_write("open(%r, 'w').write('')" % LEDGER)
check("B1a python.run cannot write the ledger", ok is False, (ok, err))
ok, _ = MG.check_python_write("import shutil; shutil.copy('x', %r)" % LEDGER)
check("B1b a copy over it is denied too", ok is False)

d, why = registry.classify("shell.exec", {"command": "echo forged >> data/improvement/ledger.jsonl"})
check("B2a a shell append is denied", d == "denied", (d, why))
d, why = registry.classify("shell.exec", {"command": "truncate -s 0 data/improvement/ledger.jsonl"})
check("B2b truncating it is denied", d == "denied", (d, why))
d, why = registry.classify(
    "shell.exec",
    {"command": 'python3 -c "open(\'data/improvement/ledger.jsonl\',\'w\').write(\'\')"'})
check("B3 a shell-invoked interpreter is denied", d == "denied", (d, why))

for tool in ("fs.write", "fs.edit"):
    d, why = registry.classify(tool, {"path": os.path.join(REPO, "data", "improvement", "ledger.jsonl")})
    check("B4 %s denies data/improvement" % tool, d == "denied", (d, why))

ok, _ = MG.check_shell_command("ls -la %s" % STORE)
check("B5a ls of the store is allowed", ok is True)
ok, _ = MG.check_python_write("print(open(%r).read())" % LEDGER)
check("B5b a read via python is not a write", ok is True)

check("B6a improve.LEDGER_PATH lives under paths.IMPROVEMENT_DIR",
      LEDGER0 == os.path.join(paths.IMPROVEMENT_DIR, "ledger.jsonl"), LEDGER0)
check("B6b the anchor lives beside it",
      os.path.dirname(HEAD0) == os.path.dirname(LEDGER0), HEAD0)

ALT = os.path.join(TMP, "alt-improvement")
out = subprocess.run([sys.executable, "-c",
                      "import sys; sys.path.insert(0, %r); "
                      "from longrun.util import paths, improve; "
                      "print(paths.IMPROVEMENT_DIR); print(improve.LEDGER_PATH)" % os.path.join(REPO, "src")],
                     capture_output=True, text=True,
                     env=dict(os.environ, LONGRUN_IMPROVEMENT_DIR=ALT))
lines = [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]
check("B7 LONGRUN_IMPROVEMENT_DIR moves the store for both owners",
      lines == [ALT, os.path.join(ALT, "ledger.jsonl")], (lines, out.stderr[-200:]))

ok, _ = MG.check_python_write("open(%r, 'w').write('x')" % os.path.join(REPO, "notes.txt"))
check("B8 an ordinary path is not denied", ok is True)

# ---- S: the surface ----------------------------------------------------------
fresh(4)
res = TOOLS._improve({"action": "ledger"}, "run-v1083")
check("S1 improve action=ledger reports a clean chain",
      res.get("ok") is True and (res.get("ledger") or {}).get("code") == "ok", res.get("stdout"))
rs = rows()
rs[0]["kind"] = "rewritten"
rewrite(rs)
res = TOOLS._improve({"action": "ledger"}, "run-v1083")
check("S2 the tool reports a broken chain", res.get("ok") is False
      and (res.get("ledger") or {}).get("code") == "hash-mismatch", res.get("stdout"))
check("S3 the tool names the bad row in its stdout",
      "altered after it was written" in (res.get("stdout") or ""), res.get("stdout"))

# the canonical schema must not demand an argument the action never reads: without
# the `_SUBTOOL_REQUIRED` row the API answered "missing scope" for improve.ledger.
_spec = (registry.tool_spec("improve.ledger") or {}).get("schema") or {}
check("S4 improve.ledger requires no argument it does not read",
      _spec.get("required") == [], _spec.get("required"))
check("S5 improve.ledger advertises repair",
      "repair" in (_spec.get("properties") or {}), list(_spec.get("properties") or {}))

# ---- X: the record is not written by an unisolated test ----------------------
# The chain exposed a real leak: `v183_chat_core` and `v1073` drove the real turn
# loop with the LIVE data home, so their `turn` rows landed in the operator's
# ledger (measured 2026-11-18: sessions v183a..v183i and v1073-* inside the live
# file, the v183 ones unchained and reported as `head-mismatch`). Running through
# `tests/battery.sh` isolates them, but a direct `python3 tests/...` did not.
for _t in ("v183_chat_core.py", "v1073_failure_transparency_contract.py"):
    try:
        _src = open(os.path.join(REPO, "tests", "acceptance", _t), encoding="utf-8").read()
    except OSError:
        _src = ""
    check("X %s isolates the data home" % _t, "LONGRUN_DATA_DIR" in _src)
check("X this test itself does not point at the live data home",
      os.path.realpath(paths.DATA_DIR)
      != os.path.realpath(os.path.join(os.path.expanduser("~"), ".longrun", "data")),
      paths.DATA_DIR)

print("\n---\nv1083: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
