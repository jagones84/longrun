#!/usr/bin/env python3
"""v722 — the self-evolve surface answers an ERROR, never a traceback (EV-14).

Operator: "debug all self-evolve features till 100% working, no possible error
left". This battery drives every `improve` action the miner owns with the inputs a
model (or a user) actually gets wrong, and requires the same contract each time:
`ok` false, `error` a non-empty string, no exception, no write outside the store.

  A  missing / escaping paths are refused with the real reason
  B  a draft that is not a draft (no proposal.json) is refused, not crashed on
  C  forge refuses short, unreplayable and disabled-Matrix cases
  D  a hostile `name` cannot escape the Matrix tools dir
  E  mine / evolve on an empty history answer honestly with zero work
  F  propose keeps its scope/content contract
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v722-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k.lower())
os.environ["LONGRUN_MATRIX_SRC"] = os.path.join(TMP, "src", "Matrix")
os.environ["LONGRUN_MATRIX_DOT"] = os.path.join(TMP, ".Matrix")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402
from longrun.util import improve  # noqa: E402
from longrun.tools import registry  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


def refused(label, args, want=""):
    """Call the tool; require a clean refusal AND the reason in the answer."""
    try:
        r = T._improve(dict(args), run_id="v722")
    except Exception as e:  # noqa: BLE001 — the point of the test
        check(label, False, "raised %s: %s" % (type(e).__name__, e))
        return None
    err = str((r or {}).get("error") or "")
    ok = (r or {}).get("ok") is False and bool(err) and (not want or want in err)
    check(label, ok, r)
    return r


DRAFTS = improve.DRAFT_DIR
os.makedirs(DRAFTS, exist_ok=True)

# ------------------------------------- A: paths -----------------------------
refused("A1 verify without a path", {"action": "verify"}, "path required")
refused("A2 verify outside the store", {"action": "verify", "path": "/etc/passwd"},
        "must be under")
refused("A3 promote without a path", {"action": "promote"}, "path required")
refused("A4 forge without a path", {"action": "forge"}, "path required")
refused("A5 forge outside the store", {"action": "forge", "path": "/tmp"},
        "must be under")

# ------------------------------------- B: not a draft -----------------------
empty = os.path.join(DRAFTS, "not-a-draft")
os.makedirs(empty, exist_ok=True)
refused("B1 a folder without proposal.json", {"action": "forge", "path": empty},
        "no proposal.json")
refused("B2 verify of that folder", {"action": "verify", "path": empty})


def make_draft(name, pattern, support=3):
    d = os.path.join(DRAFTS, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
        json.dump({"name": name, "pattern": pattern, "support": support,
                   "status": "proposed"}, f)
    return d


short = make_draft("one-step", ["fs.read"])
refused("C1 a 1-step draft cannot be forged", {"action": "forge", "path": short},
        "at least 2 steps")
pseudo = make_draft("with-batch", ["fs.read", "batch"])
refused("C2 an unreplayable draft cannot be forged",
        {"action": "forge", "path": pseudo}, "not replayable")

cfg = registry.load_config()
cfg.setdefault("approvals", {})["matrix_enabled"] = False
registry.save_config(cfg)
registry.load_config(reload=True)
real = make_draft("real-two", ["fs.read", "fs.edit"])
refused("C3 a disabled Matrix refuses instead of writing", {"action": "forge", "path": real},
        "Matrix is disabled")
cfg = registry.load_config()
cfg.setdefault("approvals", {})["matrix_enabled"] = True
registry.save_config(cfg)
registry.load_config(reload=True)

# ------------------------------------- D: hostile name ----------------------
hostile = T._improve({"action": "forge", "path": real, "name": "../../etc/evil"},
                     run_id="v722")
p = str((hostile or {}).get("path") or "")
tools_dir = os.path.join(os.environ["LONGRUN_MATRIX_SRC"], "tools")
check("D1 a hostile name cannot escape the Matrix tools dir",
      (hostile or {}).get("ok") is True and os.path.dirname(p) == tools_dir,
      {"path": p, "res": hostile})

# ------------------------------------- E: empty history ---------------------
m = T._improve({"action": "mine"}, run_id="v722")
check("E1 mine on an empty history answers zero", (m or {}).get("ok") is True
      and (m or {}).get("mined") == 0, m)
e = T._improve({"action": "evolve"}, run_id="v722")
check("E2 evolve on an empty history answers zero", (e or {}).get("ok") is True
      and (e or {}).get("evolved") == 0, e)

# ------------------------------------- F: propose contract -----------------
refused("F1 propose with a bad scope", {"action": "propose", "scope": "wat",
                                        "content": "x"}, "invalid scope")
refused("F2 propose with no content", {"action": "propose", "scope": "project",
                                       "content": "   "}, "content")

# ------------------------------------- G: the canonical schema --------------
spec = registry.tool_spec("improve.forge") or {}
sch = spec.get("schema") or {}
check("G1 forge requires ONLY its draft path", list(sch.get("required") or []) == ["path"],
      sch.get("required"))
check("G2 its real arguments are declared",
      {"path", "name", "content"} <= set((sch.get("properties") or {})),
      list(sch.get("properties") or {}))
check("G3 verify/promote keep their own shape",
      (registry.tool_spec("improve.verify") or {}).get("schema", {}).get("required") == ["path"]
      and (registry.tool_spec("improve.promote") or {}).get("schema", {}).get("required") == ["path"],
      "verify/promote schema changed")

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
