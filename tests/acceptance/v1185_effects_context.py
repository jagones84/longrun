#!/usr/bin/env python3
"""v1185 — effect recovery, effect-typed tools, context cost (round 116).

Sources:
  * arXiv:2610.41453 "Evidence-Guided Recovery for AI Agents with Ambiguous Tool
    Outcomes and Partial Execution" — states compatible with public evidence, an
    admissibility check on the proposed next action, and a terminal certificate
    that separates goal satisfaction from safe completion.
  * arXiv:2610.35981 "Small agents should know what their tools do" — every tool
    declares its effect, idempotency and the resources it reads/writes, so a
    replay verifier can judge effect safety without labels.
  * arXiv:2611.22238 "Context Has a Price" — price a run under a prefix-cache
    discount and refuse a token-only comparison.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1185_effects_context.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1185-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import effect_recovery as ER    # noqa: E402
from longrun.harness import effect_types as ET        # noqa: E402
from longrun.harness import context_cost as CC        # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# ---- 1. ambiguous outcome recovery -----------------------------------------
CAPS = {"charge": {"idempotent": False, "read_after_write": True},
        "annotate": {"idempotent": True},
        "mail": {"idempotent": False}}
check("a read-back pins the committed state",
      ER.compatible({"action": "charge"}, [{"kind": "readback-committed"}], CAPS) == ["committed"])
check("a read-back absence pins not-started when the provider can read after write",
      ER.compatible({"action": "charge"}, [{"kind": "readback-absent"}], CAPS) == ["not-started"])
check("a timeout leaves all three states open",
      ER.compatible({"action": "charge"}, [{"kind": "timeout"}], CAPS)
      == ["committed", "in-flight", "not-started"])

ok_rec = {"capabilities": CAPS, "now": 5,
          "obligations": [{"id": "o1", "action": "charge"}],
          "evidence": [{"obligation": "o1", "kind": "readback-committed"}]}
res = ER.adjudicate(ok_rec)
check("evidence of commit certifies the goal", res["certificate"] == "goal-satisfied", res)

stop_rec = {"capabilities": CAPS, "now": 5,
            "obligations": [{"id": "o1", "action": "charge"}],
            "evidence": [{"obligation": "o1", "kind": "readback-absent"}]}
check("nothing started is a safe stop, not a failure",
      ER.adjudicate(stop_rec)["certificate"] == "safe-stop", ER.adjudicate(stop_rec))

dup_rec = {"capabilities": CAPS, "now": 5,
           "obligations": [{"id": "o1", "action": "charge"}],
           "evidence": [{"obligation": "o1", "kind": "timeout"}],
           "proposed": [{"obligation": "o1", "action": "retry"}]}
dup = ER.adjudicate(dup_rec)
check("re-issuing a non-idempotent call with open evidence is unsafe",
      dup["certificate"] == "unsafe"
      and any(f["kind"] == "retry-would-duplicate" for f in dup["findings"]), dup)
check("the unsafe row asks to verify instead of retrying",
      dup["obligations"][0]["next"] == "verify", dup["obligations"])

idem_rec = {"capabilities": CAPS, "now": 5,
            "obligations": [{"id": "o1", "action": "annotate"}],
            "evidence": [{"obligation": "o1", "kind": "timeout"}],
            "proposed": [{"obligation": "o1", "action": "retry"}]}
check("an idempotent call may be retried under the same evidence",
      ER.adjudicate(idem_rec)["certificate"] != "unsafe", ER.adjudicate(idem_rec))

dep_rec = {"capabilities": CAPS, "now": 5,
           "obligations": [{"id": "o1", "action": "charge"},
                           {"id": "o2", "action": "mail", "requires": ["o1"]}],
           "evidence": [{"obligation": "o1", "kind": "timeout"}]}
dep = ER.adjudicate(dep_rec)
check("a dependency on an unproven obligation is flagged",
      any(f["kind"] == "blocked-by-unproven-dependency" for f in dep["findings"]), dep)
dangling = ER.adjudicate({"capabilities": CAPS,
                          "obligations": [{"id": "o2", "action": "mail", "requires": ["o9"]}]})
check("a dependency on an unknown obligation is a finding",
      any(f["kind"] == "dangling-dependency" for f in dangling["findings"]), dangling)

exp_rec = {"capabilities": CAPS, "now": 99,
           "obligations": [{"id": "o1", "action": "charge", "deadline": 10}],
           "evidence": [{"obligation": "o1", "kind": "timeout"}],
           "proposed": [{"obligation": "o1", "action": "retry"}]}
exp = ER.adjudicate(exp_rec)
check("an expired authorization is flagged and cannot be retried",
      any(f["kind"] == "expired-authorization" for f in exp["findings"]), exp)

resid = ER.adjudicate({"capabilities": CAPS,
                       "obligations": [{"id": "o1", "action": "charge"}],
                       "evidence": [{"obligation": "o1", "kind": "readback-committed"}],
                       "residual": [{"action": "refund"}]})
check("an effect nobody owns is unsafe", resid["certificate"] == "unsafe"
      and any(f["kind"] == "unowned-residue" for f in resid["findings"]), resid)

check("evidence about an unknown obligation is reported",
      any(f["kind"] == "evidence-for-unknown-obligation"
          for f in ER.adjudicate({"obligations": [{"id": "o1", "action": "charge"}],
                                  "evidence": [{"obligation": "zz", "kind": "ack"}]})["findings"]))
check("two committed effects for one non-idempotent action are a duplicate",
      ER.trace_safety([{"kind": "committed", "action": "charge"},
                       {"kind": "committed", "action": "charge"}], CAPS)["verdict"] == "duplicate")
check("an idempotent action may commit twice",
      ER.trace_safety([{"kind": "committed", "action": "annotate"},
                       {"kind": "committed", "action": "annotate"}], CAPS)["verdict"] == "clean")

# ---- 2. effect-typed tools -------------------------------------------------
CATALOG = {
    "fs.read": {"effect": "read", "reads": ["file:a"]},
    "fs.write": {"effect": "write", "idempotent": False, "writes": ["file:a"]},
    "fs.delete": {"effect": "delete", "idempotent": False, "writes": ["file:a"]},
    "job.retry": {"effect": "external", "idempotent": True, "writes": ["job:1"]},
}
cov = ET.coverage(CATALOG)
check("a fully declared catalog is typed", cov["verdict"] == "typed" and cov["untyped"] == 0, cov)
cov_bad = ET.coverage({"x": {"effect": "sideways"}, "y": {}})
check("an invalid effect is its own state, not double-counted as untyped",
      cov_bad["verdict"] == "invalid" and len(cov_bad["invalid"]) == 1
      and cov_bad["untyped"] == 1, cov_bad)

safe = ET.verify_trace([{"tool": "fs.read"}, {"tool": "fs.write"}], CATALOG)
check("read then write is effect-safe", safe["verdict"] == "safe", safe)
blind = ET.verify_trace([{"tool": "fs.delete"}], CATALOG)
check("a delete nobody read first is unsafe",
      blind["verdict"] == "unsafe"
      and any(f["kind"] == "delete-without-read" for f in blind["findings"]), blind)
rep = ET.verify_trace([{"tool": "fs.write"}, {"tool": "fs.write"}], CATALOG)
check("a repeated non-idempotent write is unsafe",
      any(f["kind"] == "repeat-write" for f in rep["findings"]), rep)
idem = ET.verify_trace([{"tool": "job.retry"}, {"tool": "job.retry"}], CATALOG)
check("an idempotent external call may repeat", idem["verdict"] == "safe", idem)
red = ET.verify_trace([{"tool": "fs.read"}, {"tool": "fs.read"}], CATALOG)
check("a re-read of unchanged state is reported",
      any(f["kind"] == "redundant-read" for f in red["findings"]), red)
prog = ET.verify_trace([{"tool": "fs.write"}, {"tool": "fs.read"}], CATALOG)
check("a call consuming the previous write could have been one turn",
      any(f["kind"] == "program-opportunity" for f in prog["findings"]), prog)
undecl = ET.verify_trace([{"tool": "ghost"}], CATALOG)
check("an undeclared tool leaves the trace undecidable, not unsafe",
      undecl["verdict"] == "undecidable"
      and any(f["kind"] == "undeclared-tool" for f in undecl["findings"]), undecl)
mixed = ET.verify_trace([{"tool": "ghost"}, {"tool": "fs.write"},
                         {"tool": "fs.write"}], CATALOG)
check("a proven violation outranks an undecidable call",
      mixed["verdict"] == "unsafe", mixed)

# ---- 3. context cost -------------------------------------------------------
PRICES = {"uncached": 1.0, "cached": 0.1, "output": 4.0}
base_run = {"solved": True, "steps": [
    {"prompt_tokens": 100_000, "cached_prefix_tokens": 90_000, "output_tokens": 1_000},
    {"prompt_tokens": 120_000, "cached_prefix_tokens": 100_000, "output_tokens": 1_000},
]}
cost = CC.run_cost(base_run, PRICES)
check("a priced run separates cached and uncached input",
      abs(cost["cost"] - 0.057) < 1e-9
      and cost["per_step"][0]["cached"] == 90_000, cost)
check("a missing price book falls back to the declared defaults",
      CC.run_cost({"steps": []}, None)["cost"] == 0.0)

# The paper's headline shape: fewer tokens, more money (caching pays for the baseline).
heavy_cache = {"solved": True, "steps": [
    {"prompt_tokens": 1_000_000, "cached_prefix_tokens": 990_000, "output_tokens": 1_000},
]}
lean = {"solved": True, "steps": [
    {"prompt_tokens": 400_000, "cached_prefix_tokens": 0, "output_tokens": 1_000},
]}
cmp = CC.compare(heavy_cache, lean, PRICES)
check("a token win that costs more money is flagged",
      cmp["tokens"]["treatment"] < cmp["tokens"]["baseline"]
      and any(f["kind"] == "cache-blind-comparison" for f in cmp["findings"]), cmp)
check("the comparison reports the money verdict", cmp["verdict"] == "more-expensive", cmp)

sampled = {"solved": True, "steps": [
    {"prompt_tokens": 100_000, "cached_prefix_tokens": 90_000, "output_tokens": 1_000},
]}
cheap = CC.compare(base_run, sampled, PRICES)
check("removing a cached-heavy step can genuinely reduce cost",
      cheap["verdict"] == "cheaper" and cheap["delta_pct"] is not None, cheap)

slow = {"solved": True, "steps": base_run["steps"] + [
    {"prompt_tokens": 40_000, "cached_prefix_tokens": 30_000, "output_tokens": 500}]}
steps_cmp = CC.compare(base_run, slow, PRICES)
check("more steps at a higher bill is not a cheaper run",
      steps_cmp["verdict"] == "more-expensive"
      and any(f["kind"] == "shorter-prompts-more-steps" for f in steps_cmp["findings"]), steps_cmp)

sc = CC.screen({"baseline": base_run, "lean": lean, "sampled": sampled}, PRICES)
check("the screen names only a clean winner",
      sc["clean_winners"] == ["sampled"] and sc["verdict"] == "clean-winner", sc)
check("a screen without a baseline is refused",
      CC.screen({"lean": lean}, PRICES)["verdict"] == "no-baseline")

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
