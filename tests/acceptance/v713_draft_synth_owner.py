#!/usr/bin/env python3
"""v713 — a mined draft can actually be verified, and its check speaks the truth.

Found on the live service, in order:

  1  `improve{action:verify}` on a real mined draft answered
     `python3: can't open file '…/shell-matrix-shell/check.py'`. A mined draft is
     only a tool pattern — `check.py` is written by the synth stage, which only
     the APPROVAL path ran inline, so the documented loop
     (mine -> verify -> promote) dead-ended on its first step.
  2  once the check existed it answered `unknown tools: shell, matrix, shell` for
     a sequence that had just run: the check compared the RECORDED names against
     the catalogue's canonical names only (`shell.exec`, `matrix.status`), so no
     mined draft could ever be green.

  A  ensure_check is the owner: it synthesizes exactly when it must, refreshes a
     generated check, never touches a hand-written one, and says why it cannot
  B  both lanes call it — the tool's verify/promote actions and `decide`
  D  "known tool" means what the registry ACCEPTS (plain name or canonical), and
     an invented name still fails
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v713-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import improve  # noqa: E402
from longrun.util import selfevolve as SE  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


DRAFTS = os.path.join(TMP, "data", "proposals", "skills")
improve.DRAFT_DIR = DRAFTS
os.makedirs(DRAFTS, exist_ok=True)
fresh = SE.draft(["fs.read", "fs.edit", "shell"], 4, DRAFTS)
no_pattern = os.path.join(DRAFTS, "empty-draft")
os.makedirs(no_pattern, exist_ok=True)
with open(os.path.join(no_pattern, "proposal.json"), "w", encoding="utf-8") as f:
    json.dump({"kind": "skill", "status": "proposed", "name": "empty-draft"}, f)

# ------------------------------------- A: the owner synthesizes when needed --
check("A0 the fixture draft starts with no check.py",
      bool(fresh) and not os.path.isfile(os.path.join(str(fresh), "check.py")), fresh)
ready = SE.ensure_check(fresh)
check("A1 a fresh draft gets its check", ready.get("ok") is True and ready.get("synth") is True, ready)
have = sorted(x for x in os.listdir(fresh) if x in ("skill.json", "runner.py", "check.py"))
check("A2 synth wrote the three artifacts", have == ["check.py", "runner.py", "skill.json"], have)
hand = SE.draft(["shell", "fs.read", "fs.edit"], 2, DRAFTS)
with open(os.path.join(str(hand), "check.py"), "w", encoding="utf-8") as f:
    f.write("# hand written\nprint('ok')\n")
kept = SE.ensure_check(hand)
check("A3 a hand-written check is left alone",
      kept.get("ok") is True and kept.get("synth") is False
      and "hand written" in open(os.path.join(str(hand), "check.py"), encoding="utf-8").read(), kept)
again = SE.ensure_check(fresh)
check("A3b a check WE generated is refreshed (it embeds the tool names)",
      again.get("ok") is True and again.get("synth") is True, again)
bad = SE.ensure_check(no_pattern)
check("A4 a draft with no usable pattern says why",
      bad.get("ok") is False and "pattern" in str(bad.get("error")), bad)
gone = SE.ensure_check(os.path.join(DRAFTS, "nope"))
check("A5 a missing draft folder is named", gone.get("ok") is False
      and "missing" in str(gone.get("error")), gone)

# ------------------------------------- B: both lanes use that owner ----------
fresh2 = SE.draft(["fs.read", "shell", "web.fetch"], 3, DRAFTS)
_old_verify = SE.verify
SE.verify = lambda d, runner=None, c=None: {"green": True, "output": "ok"}
try:
    r = T._improve({"action": "verify", "scope": "mine", "path": fresh2}, run_id="v713")
finally:
    SE.verify = _old_verify
check("B1 the tool's verify synthesizes instead of failing",
      r.get("ok") is True and r.get("synth") is True
      and (r.get("verify") or {}).get("green") is True, r)
check("B2 the check the tool left behind is real",
      os.path.isfile(os.path.join(fresh2, "check.py")), fresh2)
r = T._improve({"action": "promote", "scope": "mine", "path": no_pattern}, run_id="v713")
check("B3 promote names the real reason a draft cannot be verified",
      bool(r.get("error")) and "pattern" in str(r.get("error")), r)

imp_src = open(os.path.join(REPO, "src", "longrun", "util", "improve.py"), encoding="utf-8").read()
tools_src = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"), encoding="utf-8").read()
check("B4 the synth-if-missing rule lives in ONE place",
      "selfevolve.ensure_check(draft)" in imp_src
      and tools_src.count("selfevolve.ensure_check(") == 2
      and '"check.py"' not in imp_src.split("def decide(")[1].split("def ")[0], "")

# --------------------- D: a recorded name counts as a known tool -------------
# The live check answered "unknown tools: shell, matrix, shell" for a sequence
# that had just run: the catalogue holds only `<ns>.<subtool>` names, while a
# recorded sequence keeps the name the model called.
known = SE._known_tools()
check("D1 a legacy plain name the registry accepts is known",
      "shell" in known and "matrix" in known, [n for n in known if not "." in n][:12])
check("D2 a canonical name is still known", "fs.read" in known and "shell.exec" in known, "")
rec = SE.draft(["shell", "matrix", "shell"], 5, DRAFTS)
SE.ensure_check(rec)
import subprocess  # noqa: E402

ran = subprocess.run([sys.executable, "check.py"], cwd=rec, capture_output=True, text=True, timeout=30)
check("D3 the check goes GREEN for a real recorded sequence",
      ran.returncode == 0 and "ok:" in (ran.stdout or ""), (ran.stdout, ran.stderr))
made = SE.draft(["nope.tool", "fs.read", "shell"], 2, DRAFTS)
SE.ensure_check(made)
ran = subprocess.run([sys.executable, "check.py"], cwd=made, capture_output=True, text=True, timeout=30)
check("D4 an invented tool still fails the check",
      ran.returncode != 0 and "unknown tools" in (ran.stdout or ""), ran.stdout)

print("\n---\nv713: %d/%d PASS" % (sum(results), len(results)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if all(results) else 1)
