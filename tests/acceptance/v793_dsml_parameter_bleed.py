#!/usr/bin/env python3
"""v793 — a parameter VALUE can never swallow the next parameter.

(Renumbered from the untracked `v787_dsml_parameter_bleed.py`, which collided with
the tracked `v787_verifier_wired_and_bounded.py`. The test was green and the fix it
guards is in the parser; only the file was never committed. 2026-11-04.)

Live 2026-11-04 (session `b7329cccf94c`): the model closed `path` and opened
`content` in ONE merged tag —

    <|DSML| parameter name="path">trash/x.py</|DSML| parameter="content">import re…

— so the `path` close was never seen and the lazy value matched ran to the next
BARE `</|DSML|>` hundreds of chars later. The harness then CALLED the tool with

    fs.write(args={"path": <495 chars, containing "|DSML|" and NEWLINES>})

and no `content` at all: a tool invocation carrying the harness' own wire markup
as a filesystem path (the operator saw `exit 64` and read it as "tools run
erroneously"). Measured with the real parser before the fix:
`path len=495 marker_in_value=True newline=True`.

Locked here:
  * a value ends at the NEXT parameter tag — open, close, or the model's merged
    `</… parameter="name">` (which is BOTH: it ends `path` AND opens `content`);
  * a value still ends at a bare `</…>` marker close (the v369 G1 dialect);
  * NO parsed argument ever contains the wire marker;
  * well-formed multi-parameter invokes are untouched (v369/v782 stay green).

Deterministic, no model, no network.
Run: python3 tests/acceptance/v793_dsml_parameter_bleed.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v793-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _s  # noqa: E402,F401  (server bootstraps agent)
from longrun.agent import agent as a  # noqa: E402

D = "\uff5c\uff5cDSML\uff5c\uff5c"
OPEN = "<" + D
CLOSE = "</" + D

BODY = ("# A54 - parallelismo\n\n"
        "## DIFETTO 1 (ALTA)\n"
        "3 dispatch in un batch -> 1 arrivato.\n")

# The verbatim shape of the failure: the close of `path` and the open of
# `content` are the SAME tag (`</|DSML| parameter="content">`).
BLEED = (OPEN + ' calls">\n'
         + OPEN + ' invoke name="fs.write">\n'
         + OPEN + ' parameter name="path">trash/A54-parallel-report.md</' + D
         + ' parameter="content">' + BODY
         + CLOSE + '>\n'
         + CLOSE + '>')

# The same pathology on a second tool: `start_line` opens where `path` closes.
MERGED_READ = (OPEN + ' calls>\n'
               + OPEN + ' invoke name="fs.read">\n'
               + OPEN + ' parameter name="path">/tmp/a.py</' + D
               + ' parameter="start_line">10</' + D + ' parameter>\n'
               + CLOSE + ' invoke>\n' + CLOSE + ' calls>')

# A well-formed three-parameter invoke must keep working (guard against the fix
# over-cutting).
WELL_FORMED = (OPEN + ' calls>\n'
               + OPEN + ' invoke name="fs.write">\n'
               + OPEN + ' parameter name="path">/tmp/b.txt</' + D + ' parameter>\n'
               + OPEN + ' parameter name="content">hello\nworld</' + D + ' parameter>\n'
               + OPEN + ' parameter name="lines" string="false">42</' + D + ' parameter>\n'
               + CLOSE + ' invoke>\n' + CLOSE + ' calls>')

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- the live failure -------------------------------------------------------
act = a._extract_action(BLEED)
args = (act or {}).get("args") or {}
check("A1 the merged tag still yields an fs.write action",
      (act or {}).get("tool") == "fs.write" and (act or {}).get("action") == "tool",
      str(act)[:160])
check("A2 `path` is the real path — no markup, no newline",
      args.get("path") == "trash/A54-parallel-report.md",
      "%d chars :: %r" % (len(str(args.get("path") or "")), str(args.get("path"))[:80]))
check("A3 `content` is recovered from the merged tag",
      args.get("content") == BODY, repr(str(args.get("content"))[:80]))
check("B1 NO parsed argument carries the wire marker",
      all(D not in str(v) for v in args.values()), sorted(args))

# ---- the same pathology on another tool ------------------------------------
act2 = a._extract_action(MERGED_READ)
args2 = (act2 or {}).get("args") or {}
check("C1 a merged tag splits into TWO parameters, in order",
      act2.get("tool") == "fs.read" and args2.get("path") == "/tmp/a.py"
      and args2.get("start_line") == "10", str(args2))
act3 = a._extract_action(WELL_FORMED)
args3 = (act3 or {}).get("args") or {}
check("D1 well-formed parameters are untouched (3/3, JSON decoded)",
      args3.get("path") == "/tmp/b.txt" and args3.get("content") == "hello\nworld"
      and args3.get("lines") == 42, str(args3))

# ---- the invariant, stated positively --------------------------------------
check("E1 no argument of ANY of the three calls contains the marker",
      all(D not in str(v) for it in (act, act2, act3)
          for v in ((it or {}).get("args") or {}).values()))

print("---")
okc = sum(results)
print("v793: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
