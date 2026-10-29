"""v662 — one address, one store, one evolve flow, one artifact policy.

Operator's SSOT audit: "general single source of truth AUDIT for the whole
codebase". Four residues, each one a question with more than one answer:

  A) the ROUTER ADDRESS — `rllm.ROUTER_BASE` is the one reader of
     `LONGRUN_ROUTER`, but the memory embedder had `http://127.0.0.1:8080`
     hardcoded (so a custom router was ignored: the memory index embedded against
     the wrong host) and two diagnostics re-typed the env var AND the default;
  B) the PROPOSAL STORE — `improve.PROPOSAL_DIR` is its home, and the tool spelled
     the same directory a second time from a different root;
  C) the EVOLVE FLOW — the mine -> pipeline -> collect-archived loop lived in
     `improve.mine_once` AND in the `improve` tool, so "what does evolve do?" had
     two answers;
  D) the ARTIFACT SCOPE — "which memory records are improvement artifacts" (skip
     user-written, skip empty, label a missing origin `unattributed`) was copied
     into the LLM backlog review and the Improvement panel.

Deterministic, no model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v662-")
for _var, _tail in (
    ("LONGRUN_DATA_DIR", "data"),
    ("LONGRUN_CONFIG_DIR", "cfg"),
    ("LONGRUN_DB", "events.db"),
    ("LONGRUN_SESSIONS_DIR", "sessions"),
    ("LONGRUN_GRAPH_DIR", "graphs"),
):
    os.environ[_var] = os.path.join(TMP, _tail)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import improve  # noqa: E402
from longrun.util import selfevolve  # noqa: E402
from longrun.memory import memory as memory_mod  # noqa: E402

SRC = os.path.join(REPO, "src", "longrun")


def _read(rel):
    return open(os.path.join(SRC, rel), encoding="utf-8").read()


MEM = _read(os.path.join("memory", "memory.py"))
TOOLS = _read(os.path.join("tools", "tools.py"))
DIAG = _read(os.path.join("tools", "diag.py"))
HTTP = _read(os.path.join("core", "httpapi.py"))
IMPR = _read(os.path.join("util", "improve.py"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def files_with(needle):
    """Every backend module holding `needle` (a comment does not count as a reader)."""
    out = []
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(root, f)
            if needle in open(p, encoding="utf-8").read():
                out.append(os.path.relpath(p, REPO).replace("\\", "/"))
    return out


# ---- A. one router address ---------------------------------------------------
_URL = files_with("http://127.0.0.1:8080")
check("A1 the router URL literal lives in ONE module", _URL == ["src/longrun/model/rllm.py"], _URL)
_ENV = files_with('"LONGRUN_ROUTER"')
check("A2 LONGRUN_ROUTER is read in ONE module", _ENV == ["src/longrun/model/rllm.py"], _ENV)
check("A3 the memory embedder builds its URL from ROUTER_BASE",
      "from longrun.model import rllm as _rllm" in MEM
      and '_base + "/v1/embeddings"' in MEM)
check("A4 the two diagnostics report ROUTER_BASE, not their own reading",
      "from longrun.model.rllm import ROUTER_BASE" in TOOLS
      and "from longrun.model.rllm import ROUTER_BASE" in DIAG
      and 'os.environ.get("LONGRUN_ROUTER"' not in TOOLS
      and 'os.environ.get("LONGRUN_ROUTER"' not in DIAG)

# ---- B. one proposal store ---------------------------------------------------
# v711: the pin used to accept the expression `os.path.join(improve.PROPOSAL_DIR,
# "skills")` because that was the only spelling available. The drafts folder now
# has its own owner (`improve.DRAFT_DIR`, patched by tests), so the tool must read
# THAT — keeping the old expression would be the second spelling this test names.
check("B1 the tool derives the drafts dir from the store, not from a second spelling",
      "improve.DRAFT_DIR" in TOOLS
      and 'os.path.join(improve.PROPOSAL_DIR, "skills")' not in TOOLS
      and 'os.path.join(_paths.DATA_DIR, "proposals"' not in TOOLS)

# ---- C. one evolve flow ------------------------------------------------------
check("C1 evolve_once IS the stage-2 flow",
      "def evolve_once(" in IMPR
      and 'return [r["rel"] for r in evolve_once(note) if r["rel"]]' in IMPR)
check("C2 the tool runs that flow instead of its own copy",
      "improve.evolve_once(" in TOOLS and "selfevolve.pipeline" not in TOOLS
      and "selfevolve.mine(" not in TOOLS)

_MINED = [{"pattern": ["fs.read", "fs.write"], "support": 3}]
_old_mine, _old_pipe = selfevolve.mine, selfevolve.pipeline
selfevolve.mine = lambda hist, c: [dict(m) for m in _MINED]
selfevolve.pipeline = lambda pattern, out, support, **kw: {
    "ok": True, "verify": {"green": True}, "archived": {"rel": "skills/created/probe"}}
try:
    _reports = improve.evolve_once()
    _installed = improve.mine_once(evolve=True)
finally:
    selfevolve.mine, selfevolve.pipeline = _old_mine, _old_pipe
check("C3 the end-of-turn pass and the tool see the SAME reports",
      [r["rel"] for r in _reports if r["rel"]] == _installed == ["skills/created/probe"],
      (_reports, _installed))
check("C4 a report states the pattern and whether it was green",
      _reports and _reports[0]["pattern"] == ["fs.read", "fs.write"] and _reports[0]["green"] is True)

# ---- D. one artifact scope ---------------------------------------------------
check("D1 the scope decision has ONE implementation",
      "def _memory_artifacts(" in IMPR and "for r in _memory_artifacts(200):" in IMPR)
check("D2 the panel asks that implementation (no copied rules)",
      "improve_mod._memory_artifacts(120)" in HTTP and 'origin == "user"' not in HTTP)

_ROWS = [
    {"mid": "m1", "ts": 1.0, "kind": "agent.note", "source": "user",
     "session": "s", "content": "my own note"},
    {"mid": "m2", "ts": 2.0, "kind": "agent.note", "source": "",
     "session": "s", "content": "distilled lesson"},
    {"mid": "m3", "ts": 3.0, "kind": "chat.summary", "session": "s", "content": "   "},
    {"mid": "m4", "ts": 4.0, "kind": "chat.summary", "origin": "reflect",
     "session": "s", "content": "a reflection"},
]
_old_query = memory_mod.query
memory_mod.query = lambda kind, sess, limit=0: [dict(r) for r in _ROWS[:limit or None]]
try:
    _arts = improve._memory_artifacts(10)
finally:
    memory_mod.query = _old_query
check("D3 user-written memory is out of scope, empty text is skipped",
      [a["mid"] for a in _arts] == ["m2", "m4"], [a["mid"] for a in _arts])
check("D4 a record with no origin is labelled, and the store file is stated",
      _arts[0]["origin"] == "unattributed"
      and _arts[0]["path"] == "data/memory/agent_notes.md", _arts[0])

print("\n---\nv662: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
