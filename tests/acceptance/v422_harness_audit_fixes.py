#!/usr/bin/env python3
"""v422 — harness-audit bug fixes (JAG-426 follow-up).

Five defects found by auditing the JAG-426 code are pinned here so they can never
regress:

  A. `glob` escaped its allow-list through an ABSOLUTE or `../` pattern
     (`os.path.join(root, "/etc/*")` discards `root`).
  B. `events.feed_seq()` was a PROCESS-LOCAL counter that reset to 0 on restart,
     so a turn anchor stamped right after a boot could carry a cut BELOW the
     session history and a rewind would then drop far too many events.
  C. `checkpoints.create_turn` re-stamped `events_upto` on an idempotent
     duplicate mark, moving the cut ABOVE the turn's own events (rewind then
     failed to truncate them).
  D. `decision.pre_tool` built the decision model twice and re-read/re-parsed
     `config/decisions.yaml` on every tool call.
  E. the streaming chat path anchored the turn OUTSIDE the turn lock with a stale
     message index; the anchor now lives inside the worker, like the sync path.

Deterministic, no live server. Run: python3 tests/acceptance/v422_harness_audit_fixes.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v422-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_REQUIRE_HELDOUT"] = "0"
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import events                      # noqa: E402
from longrun.core import server as s                 # noqa: E402
from longrun.memory import checkpoints               # noqa: E402
from longrun.model import decision                   # noqa: E402
from longrun.tools import tools as T                 # noqa: E402

checkpoints.CKPT_DIR = os.path.join(TMP, "ckpt")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A. glob cannot escape its roots ----------------------------------------
ra = T.execute("glob", {"pattern": "/etc/*.conf", "root": ".", "workspace": REPO}, run_id="v422")
check("A1 an ABSOLUTE pattern is rejected, not resolved",
      ra.get("ok") is False and "relative" in (ra.get("error") or "").lower(),
      ra.get("error"))

# a real tree under an ALLOWED root (trash/ is gitignored): root/ has ok.py; a
# sibling escaped-v422.py OUTSIDE the root must never appear in a `../` match.
import shutil                                        # noqa: E402

tree = os.path.join(REPO, "trash", "v422-tree")
escaped = os.path.join(REPO, "trash", "escaped-v422.py")
try:
    os.makedirs(os.path.join(tree, "sub"), exist_ok=True)
    open(os.path.join(tree, "sub", "ok.py"), "w").close()
    open(escaped, "w").close()

    rb = T.execute("glob", {"pattern": "**/*.py", "root": tree, "workspace": REPO}, run_id="v422")
    check("A2 a normal pattern still finds files under the root",
          rb.get("ok") is True and any(f.endswith("ok.py") for f in rb.get("files", [])),
          rb.get("files"))

    rc = T.execute("glob", {"pattern": "../*.py", "root": tree, "workspace": REPO}, run_id="v422")
    check("A3 a `../` pattern cannot return files outside the root",
          all("escaped-v422" not in f for f in rc.get("files", [])), rc.get("files"))
finally:
    shutil.rmtree(tree, ignore_errors=True)
    try:
        os.remove(escaped)
    except OSError:
        pass

# ---- B. feed_seq is the DURABLE high-water ----------------------------------
events.publish("v422.evt", session="v422")
durable = events.db().execute("SELECT MAX(id) FROM events").fetchone()[0]
events._feed_seq = 0                                  # simulate a fresh process
check("B1 feed_seq() reads the durable MAX(id), not the process counter",
      events.feed_seq() == durable and durable >= 1, (events.feed_seq(), durable))

# ---- C. a duplicate mark keeps the anchor's original cut --------------------
s.get_or_create_session("v422s", title="v422")
cp1 = checkpoints.create_turn("v422s", 1)
e1 = cp1.get("events_upto")
check("C1 the first mark stamps an events_upto cut", isinstance(e1, int) and e1 >= 1, e1)
events.publish("v422.turn", session="v422s")          # the turn produced events
cp2 = checkpoints.create_turn("v422s", 1)             # a retried/duplicate mark
check("C2 a duplicate mark does NOT move events_upto",
      cp2.get("events_upto") == e1, (e1, cp2.get("events_upto")))
check("C3 it is still the SAME checkpoint (idempotent)",
      cp2.get("id") == cp1.get("id") and cp2.get("kind") == "turn")

# ---- D. the decision layer is built once per call and cached ----------------
_cfg = os.path.join(TMP, "decisions.yaml")
open(_cfg, "w", encoding="utf-8").write('enabled: false\nmode: "null"\n')
decision.CONFIG_PATH = _cfg
decision._cfg_cache["key"] = None                     # cold
calls = {"n": 0}
_orig = decision.load_config


def _counting():
    calls["n"] += 1
    return _orig()


decision.load_config = _counting
decision.pre_tool("shell", {"command": "ls"})
decision.load_config = _orig
check("D1 pre_tool builds the decision model (and config) once, not twice",
      calls["n"] == 1, calls["n"])
check("D2 the parsed config is memoised on (path, mtime, size)",
      decision._cfg_cache.get("cfg") is not None)
_deep = decision.load_config()
check("D3 a second read returns the same values from the cache",
      _deep.get("enabled") is False and _deep.get("mode") == "null")

# ---- E. the streaming anchor lives INSIDE the worker / turn lock -------------
with open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8") as f:
    http = f.read()
start = http.index("def chat_stream_gen(")
worker = http.index("def worker()", start)
before_worker = http[start:worker]
check("E1 the request thread no longer anchors the turn",
      "_rewind.mark(" not in before_worker)
check("E2 the worker anchors it AFTER the authoritative `since`",
      http.index("_rewind.mark(") > worker
      and worker < http.index("since = session_mark(sess)") < http.index("_rewind.mark("))
check("E3 the sync path keeps its own anchor",
      http.count("_rewind.mark(") >= 2)

print("---")
okc = sum(results)
print("\nv422: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
