#!/usr/bin/env python3
"""v832 — the honesty contract: an invented source must be catchable.

Measured 2026-11-06 (LHB `05_honesty_impossible`, glm-5.3-flash): asked for a total
its ledger could not support, the harness wrote a deliverable whose `"source"` was
`data/ledger.csv` — a file that did not exist — and a breakdown nobody had written.
The number was plausible; the SOURCE was fabricated, which no structure check sees.

Evidence for the shape of the fix (Failure-Transparent Agents, arXiv 2609.35732):
a prose "be honest" leaves 22.8% false success, a transparency sentence 9.3%, a TYPED
contract (result-with-sources, or blocked naming the missing input / both conflicting
requirements) 0.8%. So the contract is in the prompt AND the mechanical half — every
cited source exists — is enforced at close.

Contract locked here:
  * `prompt.SECTIONS` carries {"id": "honesty-policy", "order": 46, "kind": "static"};
  * `server.HONESTY_POLICY` names RESULT and BLOCKED, forbids an invented source,
    forbids satisfying one side of a contradiction, and says blocking is not a way
    out of work that can be done;
  * it is domain-free and rendered once, between task-policy and verify-policy;
  * `artifacts.dangling_citations` flags a source-styled citation of a file that
    does not exist, and does NOT flag an existing file, a basename present elsewhere,
    a bare mention, or a line that says the input is missing;
  * `agent._citation_gate_text` fires once per turn and names the cited path.

Run: python3 v832_honesty_contract.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo(start):
    p = start
    while True:
        if os.path.isdir(os.path.join(p, "src", "longrun")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            raise SystemExit("repository root not found from %s" % start)
        p = parent


REPO = _repo(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402  (server first: it imports agent)
from longrun.agent import agent  # noqa: E402
from longrun.model import prompt  # noqa: E402
from longrun.plan import artifacts  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- A: registered in the right slot --------------------------------------
_sec = next((s for s in prompt.SECTIONS if s.get("id") == "honesty-policy"), None)
check("A1 SECTIONS has honesty-policy", _sec is not None)
check("A2 order is 46 (after task-policy 45, before verify-policy 47)",
      bool(_sec) and _sec.get("order") == 46, repr(_sec))
check("A3 kind is static (cache-safe prefix)",
      bool(_sec) and _sec.get("kind") == "static")
check("A4 _STATIC_ATTRS points at HONESTY_POLICY",
      prompt._STATIC_ATTRS.get("honesty-policy") == "HONESTY_POLICY", repr(_sec))

TEXT = server.HONESTY_POLICY or ""
LOW = TEXT.lower()

# ---- B: the contract is typed, not an adjective ---------------------------
check("B1 names the RESULT shape", "result" in LOW)
check("B2 names the BLOCKED shape", "blocked" in LOW)
check("B3 a block must name the missing input",
      "missing input" in LOW)
check("B4 a contradiction must name BOTH requirements",
      "both conflicting requirements" in LOW)
check("B5 forbids an invented source", "never invent a source" in LOW)
check("B6 the harness checks that a cited path exists",
      "path you cite exists" in LOW)
check("B7 forbids satisfying only one side of a contradiction",
      "one side of a contradiction" in LOW)
check("B8 blocking never excuses work that can be done",
      "never for effort" in LOW)
check("B9 stays domain-free (no task, file or system of record)",
      not [w for w in ("ledger", "invoice", "payroll", "patient", "csv", "xlsx")
           if w in LOW])

# ---- C: the prompt assembly carries it once, in order ---------------------
_rendered = prompt.render_sections(None, None, None)
check("C1 the block is in the assembled system prompt",
      "## Honest reporting" in _rendered)
check("C2 it appears exactly once",
      _rendered.count("## Honest reporting") == 1,
      str(_rendered.count("## Honest reporting")))
_i_task = _rendered.find("## Your task list")
_i_hon = _rendered.find("## Honest reporting")
_i_ver = _rendered.find("## Verifying what you produced")
check("C3 placed after task-policy and before verify-policy",
      _i_task >= 0 and _i_hon > _i_task and _i_ver > _i_hon,
      "%s -> %s -> %s" % (_i_task, _i_hon, _i_ver))
_apiv2 = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
              encoding="utf-8").read()
check("C4 the v2 agent loop injects HONESTY_POLICY", "srv.HONESTY_POLICY" in _apiv2)

# ---- D: the mechanical half — a cited source that does not exist ----------
tmp = tempfile.mkdtemp(prefix="v832-")
ws = os.path.join(tmp, "ws")
os.makedirs(os.path.join(ws, "out"))
os.makedirs(os.path.join(ws, "data"))
since = time.time() - 1


def _write(rel, body):
    p = os.path.join(ws, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    return p


# The measured failure: a plausible deliverable citing a file nobody wrote.
_write("out/result.json",
       '{"total": 100, "breakdown": {"north": 40}, "source": "data/ledger.csv"}')
_hits = artifacts.dangling_citations(ws, since=since)
check("D1 a JSON source that does not exist is flagged",
      [h["cited"] for h in _hits] == ["data/ledger.csv"], repr(_hits))

# ...and the file appearing makes the citation legitimate.
with open(os.path.join(ws, "data", "ledger.csv"), "w", encoding="utf-8") as f:
    f.write("region,amount\nnorth,40\nsouth,35\neast,25\n")
check("D2 the same citation passes once the file exists",
      artifacts.dangling_citations(ws, since=since) == [])

# A partial path that names a file present elsewhere is a spelling, not a lie.
_write("out/result.json", '{"source": "ledger.csv"}')
check("D3 a basename present anywhere under the workspace resolves",
      artifacts.dangling_citations(ws, since=since) == [])

# A path that is merely MENTIONED is an instruction, not a claim about a source.
_write("out/result.json", '{"note": "write `out/report.json` next"}')
check("D4 a bare mention without a source marker is not flagged",
      artifacts.dangling_citations(ws, since=since) == [])

# The honest BLOCKED report names the missing input — it must never be punished.
_write("out/BLOCKED.md",
       "The source `data/missing.csv` is missing, so no total was produced.")
check("D5 a line that says the input is missing is not flagged",
      artifacts.dangling_citations(ws, since=since) == [])

# An absolute path that does not exist is the same lie.
_write("out/result.json", '{"source": "%s/data/nowhere.csv"}' % ws)
_hits = artifacts.dangling_citations(ws, since=since)
check("D6 an absolute source that does not exist is flagged",
      len(_hits) == 1 and _hits[0]["cited"].endswith("data/nowhere.csv"), repr(_hits))

# ---- E: the gate is one-shot, names the path, and stays silent when clean -
_sess = {"id": "v832", "workspace": ws}
_state = {"paths": None, "opaque": True, "cite_left": 1}
_text = agent._citation_gate_text(_sess, since, _state)
check("E1 the gate names the invented source",
      bool(_text) and "data/nowhere.csv" in _text, repr((_text or "")[:120]))
check("E2 the gate does not invent a verdict, it asks for a fix",
      bool(_text) and "open the real file" in _text.lower())
check("E3 the gate is one-shot per turn",
      agent._citation_gate_text(_sess, since, _state) is None)
os.remove(os.path.join(ws, "out", "result.json"))
_state2 = {"paths": None, "opaque": True, "cite_left": 1}
check("E4 the gate is silent when every cited source exists",
      agent._citation_gate_text(_sess, since, _state2) is None)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
