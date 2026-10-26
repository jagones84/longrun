#!/usr/bin/env python3
"""v679 — the longrunAgent automation ledger: the record a stateless run leaves.

I-9. `reset_stateless_session()` wipes the VEO session, its tool cards, its
injects and its task graph before AND after every automation turn (by design).
Nothing recorded WHAT the run wrote to the substrate: verified 2026-10-26 an
operator clicked `⚡ automate (Teamorg)`, six `ROLE.md` files were written at
22:56, and no surface in the product could show it — the archived run graph
(`data/graphs/longrunAgent_run_<id>.json`) is read by nothing, and the agent
itself could only answer "my transcript resets".

This test pins the ledger that closes the hole: the derivation from the run's OWN
trace, the single NDJSON store, the two read routes, and the two UI readings
(the AGENTS report block and the `AI` provenance badge).
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v679-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_AUTOMATION_LEDGER"] = os.path.join(TMP, "data", "automation",
                                                      "ledger.ndjson")
sys.path.insert(0, os.path.join(ROOT, "src"))

from longrun.agent import automation_log as AL  # noqa: E402
from longrun.agent import longrun_agent as LRA  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def read_src(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


UI = read_src("webui", "index.html")
ORBIT = read_src("src", "longrun", "orbit", "web", "orbit.html")
API = read_src("src", "longrun", "core", "api_v02.py")
LRA_SRC = read_src("src", "longrun", "agent", "longrun_agent.py")

# ---------------------------------------------------------------- A: derivation
AL.clear()
PROMPT = "x" * 40
single = [{"i": 1, "action": "tool", "tool": "agent.prompt_set",
           "args": {"agent": "A48", "prompt": PROMPT},
           "tool_result": {"tool": "agent.prompt_set", "ok": True}}]
rows = AL.writes_from_trace(single)
check("A1 a single write step -> one row with target and prompt size",
      len(rows) == 1 and rows[0] == {"tool": "agent.prompt_set", "target": "A48",
                                     "ok": True, "chars": 40}, rows)

read_only = [{"i": 1, "action": "tool", "tool": "agent.get",
              "args": {"agent": "A48"}, "tool_result": {"tool": "agent.get", "ok": True}},
             {"i": 2, "action": "tool", "tool": "team.list", "args": {},
              "tool_result": {"tool": "team.list", "ok": True}}]
check("A2 read-only subtools are NOT writes (a scan is not a change)",
      AL.writes_from_trace(read_only) == [])

# A batch carries its args in `calls` and its outcomes in `results`, and the two
# lists are NOT index-aligned (tool items run concurrently, other items after).
batch = [{"i": 1, "action": "batch", "calls": [
              {"action": "tool", "tool": "agent.get", "args": {"agent": "A49"}},
              {"action": "tool", "tool": "agent.prompt_set",
               "args": {"agent": "A49", "prompt": "abc"}}],
          "results": [{"tool": "agent.get", "ok": True},
                      {"tool": "agent.prompt_set", "ok": True}]}]
brows = AL.writes_from_trace(batch)
check("A3 a batch write is attributed by tool name, not by list position",
      len(brows) == 1 and brows[0]["target"] == "A49" and brows[0]["ok"] is True
      and brows[0]["chars"] == 3, brows)

check("A4 a blocked call is recorded as a FAILED write",
      AL.writes_from_trace([{"action": "tool", "tool": "agent.update",
                             "args": {"agent": "A1", "reports_to": "A2"},
                             "tool_result": {"tool": "agent.update",
                                             "blocked": "policy denied"}}])[0]["ok"] is False)
check("A5 an unattributable outcome is None, never a claimed success",
      AL.writes_from_trace([{"action": "tool", "tool": "team.member_add",
                             "args": {"team": "T8", "agent": "A48"}}])[0]["ok"] is None)
check("A6 the target comes from the tool's own subject key (`team` here)",
      AL.writes_from_trace([{"action": "tool", "tool": "team.member_add",
                             "args": {"team": "T8", "agent": "A48"},
                             "tool_result": {"ok": True}}])[0]["target"] == "T8")
order = AL.writes_from_trace([
    {"action": "tool", "tool": "agent.prompt_set", "args": {"agent": "A1", "prompt": "a"},
     "tool_result": {"ok": True}},
    {"action": "tool", "tool": "agent.prompt_set", "args": {"agent": "A2", "prompt": "b"},
     "tool_result": {"ok": True}}])
check("A7 writes keep the run's own order",
      [r["target"] for r in order] == ["A1", "A2"])
check("A8 a non-exclusive tool in the trace is ignored",
      AL.writes_from_trace([{"action": "tool", "tool": "fs.write",
                             "args": {"path": "a.py", "content": "x"},
                             "tool_result": {"ok": True}}]) == [])

# ---------------------------------------------------------------- B: the store
AL.clear()
first = AL.record(section="teamorg", run_id="run_1", model="glm-5.3-flash", ok=True,
                  summary="wrote 2 prompts", trace=single)
second = AL.record(section="rules", run_id="run_2", model="deepseek-flash", ok=True,
                   summary="tightened the rules",
                   trace=[{"action": "tool", "tool": "agent.prompt_set",
                           "args": {"agent": "A54", "prompt": "y" * 12},
                           "tool_result": {"ok": True}}])
check("B1 record() appends a run row plus its write rows",
      len(first) == 2 and first[0]["kind"] == "run" and first[0]["writes"] == 1
      and first[1]["kind"] == "write" and os.path.exists(AL.LEDGER_FILE))
runs = AL.read_runs(10)
check("B2 read_runs is newest first and groups each write under its own run",
      [r["run_id"] for r in runs] == ["run_2", "run_1"]
      and [w["target"] for w in runs[1]["detail"]] == ["A48"], runs)
check("B3 the run's `writes` count equals its own detail rows (no second truth)",
      runs[0]["writes"] == len(runs[0]["detail"]) == 1)
check("B4 read_runs honours its limit",
      [r["run_id"] for r in AL.read_runs(1)] == ["run_2"])
badge = AL.last_write_by_target()
check("B5 the badge map names the newest write per target, with its run",
      badge.get("A48", {}).get("run_id") == "run_1"
      and badge["A48"]["section"] == "teamorg"
      and badge["A48"]["tool"] == "agent.prompt_set"
      and badge["A48"]["chars"] == 40
      and badge.get("A54", {}).get("run_id") == "run_2", badge)
check("B6 the raw rows are one JSON object per line (append-only NDJSON)",
      all(json.loads(ln)["kind"] in ("run", "write")
          for ln in open(AL.LEDGER_FILE, encoding="utf-8") if ln.strip()))
with open(AL.LEDGER_FILE, "a", encoding="utf-8") as f:
    f.write(json.dumps({"kind": "write", "run_id": "run_gone", "target": "A9"}) + "\n")
check("B7 a write whose run row was pruned is attached to nothing",
      all(r["run_id"] != "run_gone" for r in AL.read_runs(20)))
AL.clear()
check("B8 an absent ledger reads as empty, not as an error",
      AL.read_runs(10) == [] and AL.last_write_by_target() == {})

# ------------------------------------------------------------ C: single truth
mut = AL.mutating_tools()
check("C1 mutating_tools marks writes and spares reads",
      "agent.prompt_set" in mut and "team.member_add" in mut
      and "agent.get" not in mut and "agent.list" not in mut and "agent.prompt_get" not in mut,
      sorted(mut))
excl = {k for k, v in LRA.TOOL_SCHEMAS.items()
        if isinstance(v, dict) and v.get("_origin") == "exclusive"}
check("C2 mutating_tools is DERIVED from TOOL_SCHEMAS (no second hand-kept list)",
      mut <= excl and len(mut) > 5)

# ----------------------------------------------------------- D: automate wiring
body = LRA_SRC[LRA_SRC.index("def automate("):]
_end = body.find("\ndef ", 1)
body = body[:_end] if _end > 0 else body
check("D1 automate() records the run in the ledger",
      "automation_log.record(" in body
      and 'section=section' in body and "trace=run_res.get(\"trace\")" in body)
check("D2 the record is written BEFORE the stateless wipe that erases the run",
      body.index("automation_log.record(") < body.rindex("reset_stateless_session()"))
check("D3 the response reports the run's summary (the old code read a key that"
      " never existed: `result` instead of `summary`)",
      '"result": run_res.get("summary") or "",' in body
      and 'run_res.get("result")' not in body and 'run_res.get("steps")' not in body)
check("D4 the response also carries the writes the run made",
      '"writes": writes,' in body)

# ------------------------------------------------------------------ E: routes
check("E1 GET /api/longrun-agent/reports reads the ledger (bounded by ?limit)",
      'if path == "/api/longrun-agent/reports":' in API
      and '_al.read_runs(_int(qs.get("limit"), 20))' in API and '"runs":' in API)
check("E2 GET /api/longrun-agent/writes returns the per-target badge map",
      'if path == "/api/longrun-agent/writes":' in API
      and "_al.last_write_by_target()" in API and '"targets":' in API)

# ---------------------------------------------------------------------- F: UI
check("F1 the deck has a report toggle that survives a reload",
      'id="lraRepBtn"' in ORBIT and 'id="lraRep"' in ORBIT
      and 'if ($("lraRepBtn")) $("lraRepBtn").onclick' in ORBIT)
check("F2 the report reads the SAME route the backend serves",
      '"/api/longrun-agent/reports?limit=' in ORBIT)
check("F3 the badge map is fetched from the backend route",
      'this.api.get("/api/longrun-agent/writes")' in ORBIT
      and "this.agents.written = (wrote && wrote.targets) || {};" in ORBIT)
check("F4 the badge renders real provenance and escaped model text",
      ".aibadge{" in ORBIT and "const aiBadge = w" in ORBIT
      and 'esc(w.section || "?")' in ORBIT and "esc(String(w.run_id" in ORBIT)
check("F5 the report escapes every model-provided field",
      "esc(String(run.summary).slice(0, 240))" in ORBIT and "esc(w.tool || \"\")" in ORBIT
      and "esc(w.target)" in ORBIT)
check("F6 the truncated `slice(0, 120)` report is gone (it showed 120 chars of an"
      " EMPTY string, because the backend sent no `result`)",
      '(r.result || "done").slice(0, 120)' not in ORBIT
      and "this.loadReport(true);" in ORBIT)
check("F7 the Settings ▸ Rules automate reports writes too (parity, one shape)",
      "const nw = (r.writes || []).length;" in UI and 'nw + " write(s)"' in UI)

# ------------------------------------------------------------- G: bounded file
AL.clear()


def _write_rows(rows):
    os.makedirs(os.path.dirname(AL.LEDGER_FILE), exist_ok=True)
    with open(AL.LEDGER_FILE, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


W = lambda i: {"kind": "write", "run_id": "r", "tool": "agent.prompt_set", "target": "A%d" % i}  # noqa: E731
mixed = [W(i) for i in range(200)] + [{"kind": "run", "run_id": "r", "writes": 300}] \
    + [W(i) for i in range(200, 500)]
_write_rows(mixed)
AL._MAX_BYTES = 0
AL._compact(mixed)
kept = [json.loads(ln) for ln in open(AL.LEDGER_FILE, encoding="utf-8") if ln.strip()]
check("G1 past the cap the ledger keeps its tail, starting at a `run` row",
      len(kept) == 301 and kept[0]["kind"] == "run", len(kept))
check("G2 the trim drops the writes of the pruned head, never the run's own",
      kept[0]["run_id"] == "r" and all(r["kind"] == "write" for r in kept[1:])
      and len(kept[1:]) == 300)
_write_rows([W(i) for i in range(500)])
AL._compact([W(i) for i in range(500)])
only = [json.loads(ln) for ln in open(AL.LEDGER_FILE, encoding="utf-8") if ln.strip()]
check("G3 a tail with no run row at all is preserved, not emptied",
      len(only) == 400 and only[-1]["target"] == "A499", len(only))
AL._MAX_BYTES = 512 * 1024
AL.clear()

shutil.rmtree(TMP, ignore_errors=True)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
