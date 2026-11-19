#!/usr/bin/env python3
"""v1179 — safe reuse, principal contexts, residency band (round 110).

Sources:
  * arXiv:2611.09254 "TwinHash" — an input-side key alone is unsafe: a hit needs
    an allowlist of deterministic tools, per-resource state epochs in the key,
    and an output fingerprint that still matches. Reuse is capped per key.
  * arXiv:2611.08768 "Conflux" — an action may proceed only if EVERY principal
    that influenced it allows it; unknown provenance poisons the context, and
    provenance must be no-laundering (derived objects inherit their sources'
    authors).
  * arXiv:2611.13412 "Bursts That Outlast Themselves" — bound the resident
    demand of admitted sessions; park the session at the turn boundary above the
    high mark, re-admit parked before new below the low mark; fixed thresholds.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1179_safe_reuse_principals_residency.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1179-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import reuse as RU  # noqa: E402
from longrun.harness.checks import principals as PR  # noqa: E402
from longrun.util import residency as RS           # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# ---- 1. safe reuse ----------------------------------------------------------
check("a read tool is reusable", RU.classify("fs.read", {"path": "a.py"})["reusable"])
check("a write tool is never reusable",
      RU.classify("fs.write")["stream"] == "write"
      and not RU.classify("fs.write")["reusable"])
check("a shell tool is never reusable",
      RU.classify("shell.exec")["stream"] == "exec"
      and not RU.classify("shell.exec")["reusable"])
check("an allowlist decides an ambiguous name",
      RU.classify("repo.inspect", allow={"repo.inspect"})["reusable"]
      and not RU.classify("repo.inspect")["reusable"])

k1 = RU.key("fs.read", {"path": "a.py", "timeout": 5})
k2 = RU.key("fs.read", {"timeout": 9, "path": "a.py"})
check("transient arg fields and order do not change the key", k1 == k2, (k1, k2))
check("a different path is a different key",
      RU.key("fs.read", {"path": "a.py"}) != RU.key("fs.read", {"path": "b.py"}))

ep = RU.Epochs()
before = RU.key("fs.read", {"path": "a.py"}, epochs=ep)
ep.advance(os.path.normpath("a.py"))
after = RU.key("fs.read", {"path": "a.py"}, epochs=ep)
check("a write advances the epoch and invalidates the read key", before != after)
check("an unrelated resource does not invalidate this read",
      RU.key("fs.read", {"path": "c.py"}, epochs=ep)
      == RU.key("fs.read", {"path": "c.py"}, epochs=RU.Epochs()))
g1 = RU.key("grep.search", {"pattern": "x"}, epochs=RU.Epochs())
ep2 = RU.Epochs()
RU.key("fs.read", {"path": "a.py"}, epochs=ep2)
ep2.advance("a.py")
g2 = RU.key("grep.search", {"pattern": "x"}, epochs=ep2)
check("a tool with no declared resource depends on the global epoch",
      RU.key("grep.search", {"pattern": "x"}, epochs=RU.Epochs()) == g1 and g1 != g2)

store = RU.Store(cap=2)
fp = store.put("k", "hello")
got = store.get("k")
check("a committed output is served by key", got["hit"] and got["output"] == "hello", got)
check("a fingerprint mismatch is a miss",
      store.get("k", expect="deadbeef")["reason"] == "fingerprint-mismatch")
check("an unknown key is a miss", store.get("nope")["reason"] == "unknown-key")
hit_cap = [store.get("k")["hit"] for _ in range(3)]
check("the per-key serve cap stops replaying diversity",
      hit_cap == [True, False, False], hit_cap)
mutated = RU.Store()
mutated.put("m", "x")
mutated._rows["m"]["output"] = "y"
check("mutated stored bytes are never served",
      mutated.get("m")["reason"] == "content-changed")

cards = [
    {"tool": "fs.read", "args": {"path": "a.py"}, "result": "one"},
    {"tool": "fs.read", "args": {"path": "a.py"}, "result": "one"},
    {"tool": "fs.read", "args": {"path": "a.py"}, "result": "one"},
    {"tool": "shell.exec", "args": {"command": "ls"}, "result": "a.py"},
]
au = RU.audit(cards, allow={"fs.read"})
check("three identical reads are two reusable hits",
      au["reusable_hits"] == 2 and au["saved_calls"] == 2, au)
check("the repeated key is reported once",
      len(au["top"]) == 1 and au["top"][0]["count"] == 3, au["top"])

unsafe = [
    {"tool": "fs.read", "args": {"path": "clock"}, "result": "12:00"},
    {"tool": "fs.read", "args": {"path": "clock"}, "result": "12:01"},
]
au2 = RU.audit(unsafe, allow={"fs.read"})
check("same key with different outputs is unsafe, not a hit",
      au2["unsafe"] and au2["reusable_hits"] == 0 and au2["verdict"] == "unsafe-only", au2)

epoch_cards = [
    {"tool": "fs.read", "args": {"path": "a.py"}, "result": "v1"},
    {"tool": "fs.write", "args": {"path": "a.py"}, "result": "ok"},
    {"tool": "fs.read", "args": {"path": "a.py"}, "result": "v2"},
]
au3 = RU.audit(epoch_cards, allow={"fs.read"})
check("a write between reads makes the second read a new key",
      au3["repeats"] == 0 and au3["reusable_hits"] == 0, au3)

# ---- 2. principal contexts ------------------------------------------------
ctx = PR.decision_context(["alice", "bob"])
check("context merges every influencing principal",
      ctx == {"principals": ["alice", "bob"], "known": True, "empty": False}, ctx)
check("unknown provenance poisons the context",
      PR.decision_context(["alice", None])["known"] is False)
check("an empty context is not permissive",
      PR.decision_context([])["empty"] is True)

perms = {"alice": ["read", "fs.*"], "bob": ["read"]}
ok = PR.authorize("read", ctx, perms)
check("all principals allow => allowed", ok["allow"] and ok["blocked_by"] == [], ok)
bad = PR.authorize("fs.write", ctx, perms)
check("one denying principal blocks the action",
      not bad["allow"] and bad["blocked_by"] == ["bob"], bad)
check("a principal with no record denies (fail-closed)",
      not PR.authorize("read", PR.decision_context(["carol"]), perms)["allow"])
check("unknown provenance never authorizes",
      PR.authorize("read", PR.decision_context(["alice", None]), perms)["reason"]
      == "unknown-provenance")

objects = [
    {"id": "web", "authors": ["attacker"], "sources": []},
    {"id": "brief", "authors": ["ava"], "sources": ["web"]},
    {"id": "clean", "authors": ["ava"], "sources": []},
]
lnd = PR.no_laundering(objects)
check("a derived object that drops a source author is a laundering violation",
      lnd["verdict"] == "laundered" and lnd["violations"][0]["object"] == "brief"
      and lnd["violations"][0]["missing_authors"] == ["attacker"], lnd)
fixed = [
    {"id": "web", "authors": ["attacker"], "sources": []},
    {"id": "brief", "authors": ["ava", "attacker"], "sources": ["web"]},
]
check("inheriting the source authors is clean", PR.no_laundering(fixed)["verdict"] == "clean")
check("an unknown source is a violation, not a pass",
      PR.no_laundering([{"id": "x", "authors": ["a"], "sources": ["ghost"]}])["verdict"]
      == "laundered")

doc = {"action": "fs.write", "influences": ["aria", "audit"],
       "permissions": {"aria": ["fs.*"], "audit": ["read"]}}
out = PR.check(doc)
check("the fixture path reports the blocking principal",
      out["allow"] is False and out["blocked_by"] == ["audit"], out)

# ---- 3. residency band -----------------------------------------------------
sessions = [
    {"id": "a", "ctx_tokens": 340, "admitted": True},
    {"id": "b", "ctx_tokens": 340, "admitted": True},
    {"id": "c", "ctx_tokens": 340, "admitted": True},
    {"id": "d", "ctx_tokens": 100},
]
check("demand counts only admitted sessions",
      RS.demand(sessions) == 1020, RS.demand(sessions))
p = RS.plan(sessions, 1000, current="c")
check("over the high mark, the boundary session is parked",
      p["verdict"] == "parked" and p["decisions"][0] ==
      {"session": "c", "action": "park", "reason": "demand-over-high-water"}, p["decisions"])
check("parking brings the demand back into the band",
      p["demand"] == 1020 and p["demand_after"] == 680, p)
check("the decision is taken at the boundary, never for in-flight work",
      all(d["action"] != "park" or d["session"] == "c" for d in p["decisions"]))

p2 = RS.plan([s for s in sessions if s.get("admitted")], 5000, current="c")
check("under the band nothing is parked and nothing is admitted",
      p2["decisions"] == [] and p2["verdict"] == "within-band", p2)

p3 = RS.plan([{"id": "a", "ctx_tokens": 400, "admitted": True},
              {"id": "p", "ctx_tokens": 100, "parked": True, "parked_seq": 1},
              {"id": "n", "ctx_tokens": 50}], 1000)
check("parked sessions are re-admitted before new ones",
      p3["decisions"] and p3["decisions"][0]["session"] == "p"
      and p3["decisions"][0]["reason"] == "parked-before-new", p3["decisions"])
check("re-admission stops before the low mark",
      p3["demand_after"] <= 750, p3["demand_after"])

p4 = RS.plan(sessions, 0)
check("an unknown capacity plans nothing",
      p4["verdict"] == "no-capacity" and p4["decisions"] == [], p4)

big = [{"id": "x", "ctx_tokens": 960, "admitted": True},
       {"id": "y", "ctx_tokens": 800, "parked": True, "parked_seq": 1},
       {"id": "z", "ctx_tokens": 10, "parked": True, "parked_seq": 2}]
p5 = RS.plan(big, 1000, current="x")
check("a small parked session still fits after a large one does not",
      [d["session"] for d in p5["decisions"]] == ["x", "z"], p5["decisions"])

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
