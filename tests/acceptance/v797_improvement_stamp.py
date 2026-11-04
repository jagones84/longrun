#!/usr/bin/env python3
"""v797 — every improvement record says WHICH harness produced it.

Evidence for the need (2026-11-04): a decision row was built from `id/ts/kind/origin`
(`util/improve.py:97-99`), so a lesson, a proposal and a review could not be tied to
the code revision and config that produced them. Acting on a stale lesson was
indistinguishable from acting on a current one — the operator had to re-read the
ledger by hand to guess.

The digests already existed for traced runs (`util/tracing.build_manifest` →
`revision`, per-file `config`, `overlay`); this row makes them cheap enough to stamp
on EVERY record and applies them in the one writer.

Contract locked here:
  * `harness_stamp()` = {revision, config, overlay}, deterministic, digest-only;
  * `config` is a short hash that CHANGES when a config file's content changes, so
    "same harness?" is one comparison;
  * `ledger_add` stamps every row, and a caller-supplied `harness=` still wins;
  * a broken tracing import/stamp NEVER loses the audit row (fail-open, no key);
  * a review report carries the same stamp (the review is an improvement record too).

Deterministic, no live model, no network, no server.

Run: python3 tests/acceptance/v797_improvement_stamp.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v797-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import improve, tracing     # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _hex(s):
    return isinstance(s, str) and len(s) == 16 and all(c in "0123456789abcdef" for c in s)


# ---------------------------------------------------------------- A. the stamp --
st = improve.harness_stamp()
check("A1 harness_stamp returns a dict", isinstance(st, dict), type(st).__name__)
check("A2 it names the git revision", st.get("revision") == tracing.git_revision(),
      "%r vs %r" % (st.get("revision"), tracing.git_revision()))
check("A3 the config digest is a short hex hash", _hex(st.get("config")), st.get("config"))
check("A4 it carries the policy-overlay digest (str or None)",
      st.get("overlay") is None or isinstance(st.get("overlay"), str), st.get("overlay"))
check("A5 it carries only digests, never config content",
      all(k in ("revision", "config", "overlay") for k in st), sorted(st))

# ------------------------------------------------------------ B. determinism --
check("B1 two calls agree", improve.harness_stamp() == st)

# ---------------------------------------------- C. it tracks a config change --
cfg_a = os.path.join(TMP, "cfg_a")
cfg_b = os.path.join(TMP, "cfg_b")
os.makedirs(cfg_a)
os.makedirs(cfg_b)
with open(os.path.join(cfg_a, "tools.yaml"), "w", encoding="utf-8") as f:
    f.write("a: 1\n")
with open(os.path.join(cfg_b, "tools.yaml"), "w", encoding="utf-8") as f:
    f.write("a: 2\n")
_sa = improve.harness_stamp(config_dir=cfg_a)
_sb = improve.harness_stamp(config_dir=cfg_b)
check("C1 same content -> same config digest",
      _sa.get("config") == improve.harness_stamp(config_dir=cfg_a).get("config"))
check("C2 changed content -> different config digest",
      _sa.get("config") != _sb.get("config"),
      "%r vs %r" % (_sa.get("config"), _sb.get("config")))

# ------------------------------------------------------- D. the ledger writer --
improve.ledger_add("probe", origin="harness", note="one")
rows = [json.loads(x) for x in
        open(improve.LEDGER_PATH, encoding="utf-8").read().splitlines() if x.strip()]
row = rows[-1]
check("D1 ledger_add stamps the row", isinstance(row.get("harness"), dict), row.get("harness"))
check("D2 the stamp carries the revision",
      (row.get("harness") or {}).get("revision") == tracing.git_revision(),
      (row.get("harness") or {}).get("revision"))
check("D3 the row keeps its own fields", row.get("note") == "one", row.get("note"))

improve.ledger_add("probe2", origin="user", harness={"revision": "caller-wins"})
rows = [json.loads(x) for x in
        open(improve.LEDGER_PATH, encoding="utf-8").read().splitlines() if x.strip()]
check("D4 a caller-supplied harness= wins", rows[-1].get("harness") == {"revision": "caller-wins"},
      rows[-1].get("harness"))

# --------------------------------------------------------- E. never loses a row --
_orig = tracing.build_manifest


def _boom(*_a, **_k):
    raise RuntimeError("tracing broke")


tracing.build_manifest = _boom
try:
    check("E1 a broken stamp returns {} instead of raising", improve.harness_stamp() == {})
    improve.ledger_add("probe3", origin="harness", note="survived")
    rows = [json.loads(x) for x in
            open(improve.LEDGER_PATH, encoding="utf-8").read().splitlines() if x.strip()]
    check("E2 the audit row is still written", rows[-1].get("note") == "survived", rows[-1])
    check("E3 no empty harness key is written", "harness" not in rows[-1], rows[-1])
finally:
    tracing.build_manifest = _orig

# ----------------------------------------------------- F. review reports carry it --
rep = improve.review(limit=0)
check("F1 a review report carries the stamp", isinstance(rep.get("harness"), dict),
      rep.get("harness"))
check("F2 the review stamp names the revision",
      (rep.get("harness") or {}).get("revision") == tracing.git_revision(),
      (rep.get("harness") or {}).get("revision"))
_saved_rep = improve.latest_review() or {}
check("F3 the SAVED review file carries it too (not only the return value)",
      isinstance(_saved_rep.get("harness"), dict), _saved_rep.get("harness"))

# -------------------------------------------------------------- G. source pins --
_src = open(os.path.join(REPO, "src", "longrun", "util", "improve.py"), encoding="utf-8").read()
check("G1 ledger_add stamps only a NON-EMPTY stamp",
      'if _stamp:' in _src and 'entry.setdefault("harness", _stamp)' in _src)
check("G2 the stamp is defined once", _src.count("def harness_stamp(") == 1)

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
