#!/usr/bin/env python3
"""v1246 — one hard-deny answer for every filesystem door.

Bug hunt 2026-11-21 (Chapter 1, API boundary), CONFIRMED high severity:
`POST /api/tools/call fs.read` on the repo `.env` answered
`{"status":"blocked","reason":"matches hard-deny pattern '(^|/)\\.env…'"}` while
the OPERATOR preview doors read the SAME file:
`GET /api/fs/read?path=…/.env` → 200 with the API bearer and every provider key,
`/api/fs/structured` and `/api/fs/sheet` → 200, and `/api/fs/raw` leaked its
existence (415 instead of 404). One rule, two answers.

The fix: `registry.deny_hit(tool, args)` is the ONE judge (no approval
machinery, no rule_firings accounting — an operator preview is not a blocked tool
call) and the four doors ask it via `api_v02._fs_deny` before they open a file.

  A  the judge exists, is side-effect-free, and shares the tool layer's patterns
  B  the judge agrees with the tool layer: .env denied, .env.template allowed
  C  read / structured / sheet all deny the env file (in-process, real calls)
  D  the raw door asks the same judge before serving bytes
  E  traversal still cannot leave the browse roots
  F  the template and a normal file keep working (the fix refuses nothing else)

Deterministic and offline: temp browse root + the shipped default config.
Run: python3 tests/acceptance/v1246_fs_door_deny_single_truth.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1246-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)

ROOT = os.path.join(_tmp, "workspace")
os.makedirs(ROOT, exist_ok=True)
ENV = os.path.join(ROOT, ".env")
ENV_T = os.path.join(ROOT, ".env.template")
NOTE = os.path.join(ROOT, "note.txt")
with open(ENV, "w", encoding="utf-8") as f:
    f.write("LONGRUN_TOKEN=secret\n")
with open(ENV_T, "w", encoding="utf-8") as f:
    f.write("LONGRUN_TOKEN=\n")
with open(NOTE, "w", encoding="utf-8") as f:
    f.write("plain\n")
os.environ["LONGRUN_BROWSE_ROOTS"] = ROOT

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as A  # noqa: E402
from longrun.tools import registry as R  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


API = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
           encoding="utf-8").read()

# --- A: the judge -----------------------------------------------------------
check("A1 `deny_hit` is a public judge on the registry",
      callable(getattr(R, "deny_hit", None)))
_hit = R.deny_hit("fs.read", {"path": ENV})
check("A2 it names the shipped .env hard-deny rule",
      bool(_hit) and ".env" in _hit, _hit)
check("A3 it takes NO approval machinery (one rule, one answer)",
      "classify(" not in __import__("inspect").getsource(R.deny_hit).split('"""')[2]
      and "rule_firings" not in
      __import__("inspect").getsource(R.deny_hit).split('"""')[2])
check("A4 the no-match answer is the empty string the docstring promises",
      R.deny_hit("fs.read", {"path": NOTE}) == "",
      repr(R.deny_hit("fs.read", {"path": NOTE})))

# --- B: the judge agrees with the tool layer -------------------------------
_d, _why = R.classify("fs.read", {"path": ENV})
check("B1 the tool layer still denies the env file", _d == "denied", (_d, _why))
check("B2 the judge denies it too", bool(R.deny_hit("fs.read", {"path": ENV})))
check("B3 the template stays readable for BOTH",
      R.deny_hit("fs.read", {"path": ENV_T}) == ""
      and R.classify("fs.read", {"path": ENV_T})[0] != "denied")

# --- C: the three model-facing preview doors -------------------------------
_r = A.fs_read({"path": ENV})
check("C1 /api/fs/read denies the env file",
      str(_r.get("error", "")).startswith("denied: "), _r)
_s = A.fs_structured({"path": ENV})
check("C2 /api/fs/structured denies it",
      _s.get("ok") is False and str(_s.get("error", "")).startswith("denied: "), _s)
_h = A.fs_sheet({"path": ENV})
check("C3 /api/fs/sheet denies it",
      str(_h.get("error", "")).startswith("denied: "), _h)

# --- D: the raw door --------------------------------------------------------
check("D1 _fs_raw asks _fs_deny before it serves bytes",
      "_deny = _fs_deny(p)" in API.split("def _fs_raw")[1][:3000]
      and "403" in API.split("def _fs_raw")[1][:3000])
check("D2 _fs_deny delegates to the ONE judge (registry.deny_hit)",
      "_reg.deny_hit(" in API and "fail CLOSED" in API)

# --- E: traversal -----------------------------------------------------------
_trav = A.fs_read({"path": os.path.join(ROOT, "..", "..", "etc", "passwd")})
check("E1 a traversal stays outside the allowed roots",
      _trav.get("error") == "path outside allowed roots", _trav)

# --- F: nothing else was refused -------------------------------------------
_ok = A.fs_read({"path": NOTE})
check("F1 a plain file still reads", _ok.get("text") == "plain\n", _ok)
_ok_t = A.fs_read({"path": ENV_T})
check("F2 the env TEMPLATE still reads",
      "LONGRUN_TOKEN" in (_ok_t.get("text") or ""), _ok_t)

print("\n---\nv1246: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
