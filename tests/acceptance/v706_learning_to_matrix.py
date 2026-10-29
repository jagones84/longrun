#!/usr/bin/env python3
"""v706 — verified learning reaches the Matrix zone through ONE reviewed path.

The audit gap: learning (`harness/`) could only admit project guardrails, while
Matrix could only be edited by hand. This pins the bridge:

  A  candidate kinds: every Matrix artifact kind is proposable, code stays refused
  B  target paths come from the Matrix resolver (no second mapping, no traversal)
  C  the matched package carries Matrix source + runtime rules/skills, and the
     container is bound to them
  D  admission: an all-Matrix verified experiment creates ONE pending proposal
     with exact artifact hashes; mixed or unverified bundles create nothing
  E  approval: previews the exact diff, refuses tampered content, applies only
     inside the Matrix zone and hot-loads
  F  a broken learned artifact rolls the bundle back and is isolated
  G  `matrix.load_module` is reachable and isolates import failures

Deterministic: no model, no network, no server, no container.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v706-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "SESSIONS_DIR", "SKILLS_DIR",
            "MATRIX_SRC", "MATRIX_DOT"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import matrix  # noqa: E402
from longrun.harness import cycle, editors, probe, snapshot, whole  # noqa: E402
from longrun.tools import matrix_guard, registry  # noqa: E402
from longrun.util import improve  # noqa: E402

matrix_guard.ensure_layout()
_ROOT, MSRC, MDOT = matrix._roots()

DIGEST = "a" * 64
VARIANT = "c" * 64

TOOL = {"kind": "matrix_tool", "name": "learned", "scope": "invariant",
        "content": 'TOOL_SCHEMAS = {"learned.run": {"description": "learned", "type": "object"}}\n'
                   "def execute(args, run_id=None, subtool=None):\n"
                   '    return {"ok": True, "stdout": "learned"}\n'}
SKILL = {"kind": "matrix_skill", "name": "learned-skill", "scope": "domain",
         "content": "# learned-skill\n\nInventory inputs first.\n"}
RULE = {"kind": "matrix_rule", "name": "learned-rule", "scope": "domain",
        "content": "# learned-rule\n\nRead before writing.\n"}
GUARD = {"kind": "guardrail", "name": "guard", "scope": "invariant",
         "content": "Read every input before writing.\n"}


def artifact(candidate):
    """The exact bundle entry the approval must be bound to."""
    body = candidate["content"]
    return {"kind": candidate["kind"], "name": candidate["name"], "content": body,
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}


def experiment():
    return {"verified": True, "snapshot_digest": DIGEST, "variant_digest": VARIANT,
            "runs": [{"run_id": "reference-1", "role": "reference", "digest": DIGEST,
                      "cleanup_verified": True},
                     {"run_id": "candidate-2", "role": "successor", "digest": VARIANT,
                      "cleanup_verified": True}]}


def group():
    return {"digest": DIGEST,
            "reference": {"evidence": {"scope": "matched_container_run",
                                       "snapshot_digest": DIGEST}},
            "reference_run": {"run_id": "reference-1", "digest": DIGEST,
                              "cleanup_verified": True}}


def report():
    return {"successor": {"digest": VARIANT,
                          "record": {"evidence": {"scope": "matched_container_run",
                                                  "snapshot_digest": VARIANT}},
                          "run": {"run_id": "candidate-2", "digest": VARIANT,
                                  "cleanup_verified": True}},
            "decision": "select 1 candidate(s)", "contrast": {"verdict": "improved"},
            "workspace": TMP}


results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


# ------------------------------------------------------- A: candidate kinds --
check("A1 every Matrix artifact kind is proposable",
      all(k in editors.KINDS for k in
          ("matrix_tool", "matrix_hook", "matrix_module", "matrix_skill", "matrix_rule")))
check("A2 each Matrix kind maps to the proposal scope named 'matrix'",
      all(editors.KINDS.get(k) == "matrix" for k in
          ("matrix_tool", "matrix_hook", "matrix_module", "matrix_skill", "matrix_rule")))
check("A3 a Matrix code candidate is validated like any other",
      editors._validate(TOOL)[0] is True, editors._validate(TOOL))
check("A4 an empty Matrix candidate is refused",
      editors._validate(dict(TOOL, content="  "))[0] is False)
check("A5 standalone scripts stay refused (no second code lane)",
      editors._validate(dict(TOOL, kind="script"))[0] is False)

# ------------------------------------------------------- B: target mapping ---
targets = {k: probe._target(k, n)[0] for k, n in
           (("matrix_tool", "learned"), ("matrix_hook", "plan"),
            ("matrix_module", "util/helper"), ("matrix_skill", "s"),
            ("matrix_rule", "r"))}
check("B1 Matrix targets live under the package's frozen trees",
      targets["matrix_tool"] == "src/Matrix/tools/learned.py"
      and targets["matrix_hook"] == "src/Matrix/plan/hooks.py"
      and targets["matrix_module"] == "src/Matrix/util/helper.py"
      and targets["matrix_skill"] == "matrix/skills/s/SKILL.md"
      and targets["matrix_rule"] == "matrix/rules/r.md", targets)
check("B2 a traversal name is refused, not resolved",
      probe._target("matrix_tool", "../../escape")[0] == ""
      and probe._target("matrix_rule", "/etc/passwd")[0] == "")
check("B3 the Matrix resolver itself refuses traversal",
      matrix._resolve_target_path("tool", "../../x")[2] == ""
      and matrix._resolve_target_path("hook", "../agent")[2] == "")
check("B4 the host probe lane refuses Matrix kinds (no live-source staging)",
      probe.stage("matrix_tool", "learned", TOOL["content"], TMP)["ok"] is False)
check("B5 the matched delta covers the Matrix trees",
      set(snapshot.DELTA_PREFIXES) >= {"rules/", "skills/harness/", "src/Matrix/", "matrix/"},
      snapshot.DELTA_PREFIXES)
check("B6 a Matrix candidate becomes a container delta",
      whole._delta_for(TOOL)[0] == "src/Matrix/tools/learned.py"
      and whole._delta_for(SKILL)[0] == "matrix/skills/learned-skill/SKILL.md",
      (whole._delta_for(TOOL), whole._delta_for(SKILL)))
check("B7 an unsupported delta stays out of the package",
      whole._delta_for({"kind": "script", "name": "x"})[0] is None)

# ---------------------------------------------------- C: package contents ----
os.makedirs(os.path.join(MDOT, "skills", "live"), exist_ok=True)
with open(os.path.join(MDOT, "skills", "live", "SKILL.md"), "w", encoding="utf-8") as f:
    f.write("# live\n")
os.makedirs(os.path.join(MDOT, "rules"), exist_ok=True)
with open(os.path.join(MDOT, "rules", "live.md"), "w", encoding="utf-8") as f:
    f.write("# live rule\n")
WS = os.path.join(TMP, "ws")
os.makedirs(WS, exist_ok=True)
with open(os.path.join(WS, "in.csv"), "w", encoding="utf-8") as f:
    f.write("a,b\n1,2\n")

with patch.object(matrix, "is_enabled", return_value=True):
    built = snapshot.build({"workspace": WS, "goal": "g", "model": "m"},
                           {"max_mb": 64, "port": 18080})
check("C1 the package freezes Matrix runtime skills and rules", built.get("ok")
      and os.path.isfile(os.path.join(built["path"], "matrix", "skills", "live", "SKILL.md"))
      and os.path.isfile(os.path.join(built["path"], "matrix", "rules", "live.md")), built)
check("C2 it also freezes Matrix source", os.path.isfile(
    os.path.join(built["path"], "src", "Matrix", "tools", "toolcontract.py")))
variant = snapshot.variant(built["path"], {whole._delta_for(TOOL)[0]: TOOL["content"]})
check("C3 a Matrix delta changes only itself", variant.get("ok")
      and variant["digest"] != built["digest"]
      and snapshot.verify(variant["path"])["ok"], variant)
env_seen = {}
with patch.object(whole.sandbox, "run_whole",
                  side_effect=lambda *a, **k: env_seen.update(k.get("extra_env") or {}) or
                  {"exit_code": 1, "stdout": "", "container": "x", "cleanup_verified": True}):
    whole._execute(variant["path"], variant["digest"],
                   dict(whole.DEFAULTS, goal="g", model="m", image="sha256:" + "1" * 64,
                        run_timeout=1, port=18080), "t", [TOOL])
check("C4 the container is bound to the frozen Matrix trees",
      env_seen.get("LONGRUN_MATRIX_SRC") == "/input/src/Matrix"
      and env_seen.get("LONGRUN_MATRIX_DOT") == "/input/matrix", env_seen)
if built.get("ok"):
    snapshot.remove(built["path"])
if variant.get("ok"):
    snapshot.remove(variant["path"])

# ------------------------------------------------------------- D: admission --
before = improve.list_proposals()
got = cycle._admit(group(), report(), [TOOL, SKILL])
check("D1 an all-Matrix verified bundle creates ONE pending proposal", got.get("ok")
      and improve.get_proposal(got["id"])["scope"] == "matrix", got)
rec = improve.get_proposal(got.get("id") or "x") or {}
arts = rec.get("artifacts") or []
check("D2 the proposal is bound to exact artifact hashes",
      [a["sha256"] for a in arts] == [artifact(TOOL)["sha256"], artifact(SKILL)["sha256"]],
      arts)
check("D3 mixed project/Matrix bundles are refused",
      cycle._admit(group(), report(), [TOOL, GUARD]).get("ok") is False)
check("D4 an unverified Matrix bundle writes nothing",
      cycle._admit({}, {"successor": {}}, [TOOL]).get("ok") is False)
check("D5 rules-only bundles still admit a project rule",
      cycle._admit(group(), report(), [GUARD]).get("ok") is True)
check("D6 a decision to approve is required before any Matrix write",
      not os.path.exists(os.path.join(MSRC, "tools", "learned.py")))

# -------------------------------------------------------------- E: approval --
preview = improve.diff_preview(rec)
check("E1 the preview shows the exact Matrix files and diff", preview.get("applies")
      and any(str(p).endswith("tools/learned.py") for p in preview.get("files") or [])
      and any(str(p).endswith("skills/learned-skill/SKILL.md")
              for p in preview.get("files") or [])
      and "Inventory inputs first" in (preview.get("diff") or ""), preview.get("path"))
tampered = dict(rec, artifacts=[dict(arts[0], content="evil\n")])
check("E2 tampered content is refused before any write",
      matrix.apply_learning(tampered["artifacts"]).get("ok") is False
      and not os.path.exists(os.path.join(MSRC, "tools", "learned.py")))
decision = improve.decide(rec["id"], "approve")
check("E3 approval applies the bundle inside Matrix and hot-loads", decision.get("ok"),
      decision)
check("E4 the learned tool and skill are live", decision.get("ok")
      and os.path.isfile(os.path.join(MSRC, "tools", "learned.py"))
      and os.path.isfile(os.path.join(MDOT, "skills", "learned-skill", "SKILL.md"))
      and not os.path.exists(os.path.join(_ROOT, "src", "longrun", "tools",
                                          "promoted", "learned.py")))
check("E5 nothing was written into Nucleus", decision.get("ok")
      and "learned" in matrix.discover_tools())
check("E6 a second approval cannot re-apply a decided proposal",
      improve.decide(rec["id"], "approve").get("ok") is False)

# ------------------------------------------------------- F: rollback/isolation --
broken = [{"kind": "matrix_tool", "name": "broken",
           "content": "def execute(:\n", "sha256": ""},
          {"kind": "matrix_rule", "name": "kept-rule",
           "content": "# kept\n", "sha256": ""}]
applied = matrix.apply_learning(broken)
check("F1 a bundle with invalid code is rolled back entirely",
      applied.get("ok") is False
      and not os.path.exists(os.path.join(MSRC, "tools", "broken.py"))
      and not os.path.exists(os.path.join(MDOT, "rules", "kept-rule.md")), applied)
check("F2 the failure names the offending artifact",
      applied.get("failed") == "broken", applied)

# ------------------------------------------------------- G: legacy loading --
check("G1 matrix.load_module loads a module on demand",
      matrix.load_module("util/helper").get("ok") is True
      or matrix.load_module("util/helper").get("error"))
os.makedirs(os.path.join(MSRC, "util"), exist_ok=True)
with open(os.path.join(MSRC, "util", "helper.py"), "w", encoding="utf-8") as f:
    f.write("def helper(value):\n    return value\n")
loaded = matrix.load_module("util/helper")
check("G2 a valid module is importable", loaded.get("ok") is True
      and loaded["module"].helper(3) == 3, loaded.get("error"))
with open(os.path.join(MSRC, "util", "quest.py"), "w", encoding="utf-8") as f:
    f.write("import sys\nsys.exit(3)\n")
check("G3 SystemExit in dynamic code is isolated, not fatal",
      matrix.load_module("util/quest").get("ok") is False)
with open(os.path.join(MSRC, "tools", "suicide.py"), "w", encoding="utf-8") as f:
    f.write("raise SystemExit(4)\n")
check("G4 a hot-load scan survives SystemExit",
      matrix.hotload().get("ok") is False
      and any("suicide" in str(e.get("file")) for e in matrix.hotload().get("errors", [])))
check("G5 load_module refuses traversal",
      matrix.load_module("../../etc/passwd").get("ok") is False)
ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("G6 the panel explains what approving a Matrix bundle writes",
      'p.scope === "matrix"' in ui and "nothing enters Nucleus" in ui)
appr = open(os.path.join(REPO, "src", "longrun", "tools", "approvals.py"),
            encoding="utf-8").read()
check("G7 an artifact-less Matrix proposal is blocked in the inbox",
      "carries no artifact bundle" in appr)

print("\n---\nv706: %d/%d PASS" % (sum(results), len(results)))
try:
    shutil.rmtree(TMP, ignore_errors=True)
finally:
    sys.exit(0 if all(results) else 1)
