#!/usr/bin/env python3
"""v1212 — admission scheduling, stateful scheduling, capacity pools (round 143).

Sources:
  * arXiv:2604.17111 "HiveMind" — admission, rate tracking, AIMD + circuit
    breaker, token budgets, priority + dependency queue, central retry.
  * arXiv:2512.14142 "Astraea" — Stateful-MLFQ promotion/demotion, HRRN, aging,
    KV policy by waste, JCT against the baselines, stability.
  * arXiv:2603.00356 "Token Management in Multi-Tenant AI Inference" — service
    classes, the priority scalar, debt, burst, KV/concurrency resources, ordered
    admission, reclaim ordering, protected latency, fair share.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1212_admission_state_capacity.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1212-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import admission_schedule as AS  # noqa: E402
from longrun.harness import stateful_scheduling as SS  # noqa: E402
from longrun.harness import capacity_pools as CP       # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. admission scheduling (HiveMind) ---------------------------------
prof = AS.provider({"rpm": 60, "tpm": 100_000, "cmax": 5, "target_ms": 2000,
                    "retryable": [429, 502]})
check("a complete provider profile passes",
      kinds(prof) == ["profile-complete"], prof)
check("a missing rate limit is named",
      "limit-missing" in kinds(AS.provider({"rpm": 60, "retryable": [429]})))
check("an empty retryable set is named",
      "retryable-set-empty" in kinds(AS.provider(
          {"rpm": 60, "tpm": 1, "cmax": 1, "target_ms": 1, "retryable": []})))

check("a free slot admits", AS.slot(3, 5)["admitted"] is True)
check("a full pool waits", AS.slot(5, 5)["admitted"] is False)
check("a full pool names its reason",
      AS.slot(5, 5)["reason"] == "at-capacity")
check("no capacity is its own reason", AS.slot(0, 0)["reason"] == "no-capacity")

check("under the latency target the concurrency grows",
      AS.aimd({"c": 3, "target_ms": 2000, "mean_latency": 1500})["c"] == 3.5)
check("under-target is named",
      AS.aimd({"c": 3, "target_ms": 2000, "mean_latency": 1500})["action"]
      == "increase")
check("over the target the concurrency halves",
      AS.aimd({"c": 4, "target_ms": 2000, "mean_latency": 3000})["c"] == 2.0)
check("an error halves the concurrency regardless of latency",
      AS.aimd({"c": 4, "target_ms": 2000, "error": True})["c"] == 2.0)
check("the floor is respected",
      AS.aimd({"c": 1, "target_ms": 2000, "error": True, "cmin": 1})["c"] == 1.0)
check("no latency sample holds the level",
      AS.aimd({"c": 3, "target_ms": 2000})["action"] == "hold")

check("a sustained error rate opens the circuit",
      AS.circuit({"errors": 12, "total": 20, "state": "closed"})["state"]
      == "open")
check("an open circuit fast-fails with 503",
      AS.circuit({"state": "open"})["status"] == 503)
check("after the cooldown one probe is allowed",
      AS.circuit({"state": "open", "cooled": True})["state"] == "half-open")
check("a successful probe closes the circuit",
      AS.circuit({"state": "half-open", "probe_ok": True})["state"] == "closed")
check("a failed probe re-opens it",
      AS.circuit({"state": "half-open", "probe_ok": False})["state"] == "open")
check("an unknown circuit state is refused",
      AS.circuit({"state": "vibes"})["verdict"] == "unknown-state")

check("exponential backoff doubles per attempt",
      AS.backoff(3, base=1.0, cap=30.0)["delay"] == 8.0)
check("backoff respects its cap", AS.backoff(6, base=1.0, cap=30.0)["delay"] == 30.0)
check("Retry-After overrides the computed delay",
      AS.backoff(3, retry_after=7)["delay"] == 7.0)
check("the Retry-After source is named",
      AS.backoff(3, retry_after=7)["source"] == "retry-after")

check("a budget below the warning line continues",
      AS.budget(100, 50)["verdict"] == "ok")
check("85% warns the agent", AS.budget(100, 85)["verdict"] == "warn")
check("100% checkpoints and stops",
      AS.budget(100, 100)["verdict"] == "checkpoint")
check("the checkpoint action is named",
      AS.budget(100, 120)["action"] == "stop-and-save")

TASKS = [{"id": "A", "priority": "critical", "tokens": 500, "created": 3},
         {"id": "B", "priority": "critical", "tokens": 100, "created": 1},
         {"id": "C", "priority": "normal", "tokens": 10, "created": 1}]
ordered = AS.order(TASKS)
check("the queue orders by priority then shortest job",
      [t["id"] for t in ordered["ready"]] == ["B", "A", "C"], ordered)
blocked = AS.order([{"id": "A", "priority": "critical", "tokens": 1},
                    {"id": "B", "priority": "critical", "tokens": 2,
                     "depends_on": ["A"]}])
check("a dependent task waits for its predecessor",
      [t["id"] for t in blocked["ready"]] == ["A"]
      and [t["id"] for t in blocked["blocked"]] == ["B"], blocked)
check("a completed predecessor releases the dependent",
      [t["id"] for t in AS.order(
          [{"id": "B", "priority": "normal", "tokens": 1, "depends_on": ["A"]}],
          completed=["A"])["ready"]] == ["B"])
check("a dependency cycle is refused",
      AS.order([{"id": "A", "depends_on": ["B"]},
                {"id": "B", "depends_on": ["A"]}])["verdict"]
      == "dependency-cycle")
check("a dangling dependency is refused",
      AS.order([{"id": "A", "depends_on": ["Z"]}])["verdict"]
      == "dangling-dependency")
check("an unknown priority is refused",
      AS.order([{"id": "A", "priority": "urgent"}])["verdict"]
      == "unknown-priority")

ab = AS.ablate([{"config": "Full HiveMind", "failures": 0.0},
                {"config": "No admission", "failures": 0.0},
                {"config": "No rate limit", "failures": 0.0},
                {"config": "No backpressure", "failures": 0.091},
                {"config": "No retry", "failures": 0.636},
                {"config": "Admission only", "failures": 0.818}])
check("removing retry is load-bearing",
      "retry-is-load-bearing" in kinds(ab), ab)
check("admission alone is insufficient",
      "admission-only-insufficient" in kinds(ab), ab)

pr = AS.pressure([{"arm": "direct", "failures": 1.0},
                  {"arm": "direct", "failures": 0.73},
                  {"arm": "managed", "failures": 0.10},
                  {"arm": "managed", "failures": 0.0}])
check("unmanaged contention is a stampede",
      pr["verdict"] == "stampede-without-scheduling", pr)
check("the failure reduction is measured", abs(pr["reduction"] - 0.815) < 1e-9)
check("one arm is not a comparison",
      AS.pressure([{"arm": "direct", "failures": 1.0}])["verdict"]
      == "two-arms-required")
check("advise names every missing practice", len(AS.advise({})["findings"]) == 6)
check("a fully declared profile has no finding", AS.advise(
    {k: True for k in ("gates_concurrency", "tracks_rate_limits",
                       "adjusts_concurrency", "retries_centrally",
                       "budgets_each_agent", "orders_by_priority_and_deps")})
    ["findings"] == [])

# ---- 2. stateful scheduling (Astraea) -----------------------------------
check("the HRRN score is (wait + proc)/proc", SS.hrrn(5, 5) == 2.0)
check("a non-positive service time cannot be scored", SS.hrrn(5, 0) is None)

check("a yielding segment is promoted",
      SS.queue_event({"queue": 1, "m": 3, "token_cost": 50,
                      "threshold": 100, "yielded_to_api": True})["action"]
      == "promote")
check("an I/O-bound request at Q0 stays",
      SS.queue_event({"queue": 0, "m": 3, "token_cost": 50,
                      "threshold": 100, "yielded_to_api": True})["action"]
      == "stay")
demoted = SS.queue_event({"queue": 0, "m": 3, "token_cost": 200,
                          "threshold": 100, "yielded_to_api": False})
check("a compute-heavy segment is demoted", demoted["action"] == "demote")
check("the demotion lands one queue lower", demoted["queue"] == 1)
check("the bottom queue demotes no further",
      SS.queue_event({"queue": 2, "m": 3, "token_cost": 200,
                      "threshold": 100})["action"] == "stay")
check("a segment within quota stays",
      SS.queue_event({"queue": 1, "m": 3, "token_cost": 50,
                      "threshold": 100})["action"] == "stay")

check("an old request is aged out of the bottom queue",
      SS.aging({"wait": 10, "next_proc": 5, "tau": 2.0})["aged"] is True)
check("a young request is not aged",
      SS.aging({"wait": 2, "next_proc": 5, "tau": 2.0})["aged"] is False)
check("aging reports its ratio", SS.aging({"wait": 10, "next_proc": 5})
      ["score"] == 3.0)

packed = SS.batch([{"id": "x", "wait": 10, "proc": 5, "tokens": 10},
                   {"id": "y", "wait": 20, "proc": 5, "tokens": 10},
                   {"id": "z", "wait": 0, "proc": 4, "tokens": 10}], 20)
check("the batch takes the highest HRRN first",
      [s["id"] for s in packed["batch"]] == ["y", "x"], packed)
check("the batch stops at capacity", [s["id"] for s in packed["left"]] == ["z"])
check("the packed tokens are reported", packed["used"] == 20.0)

kv = SS.kv_policy({"t_api": 10, "c_self": 100, "t_recompute": 50,
                   "c_batch": 10, "t_swap": 1, "m_bytes": 1})
check("swap wins when the API wait dwarfs the copy", kv["policy"] == "swap", kv)
check("the wastes are all reported",
      set(kv["waste"]) == {"preserve", "discard", "swap"})
kv2 = SS.kv_policy({"t_api": 1, "c_self": 10, "t_recompute": 100,
                    "c_batch": 10, "t_swap": 100, "m_bytes": 1})
check("preserve wins when the wait is short", kv2["policy"] == "preserve")

pred = SS.predict({"prefill_ms": 100, "n_gen": 50, "decode_ms_per_token": 2,
                   "api_mean_ms": 3000})
check("the compute estimate adds prefill and decode",
      pred["compute_ms"] == 200.0, pred)
check("the API term is carried separately", pred["api_ms"] == 3000.0)
check("the segment estimate adds both", pred["segment_ms"] == 3200.0)
check("the API term is a category mean", pred["api_source"] == "category-mean")
check("an incomplete prediction is refused",
      SS.predict({"n_gen": 1})["verdict"] == "state-incomplete")

total = SS.jct([{"wait": 5, "compute": 10, "api": 100},
                {"wait": 1, "compute": 2, "api": 50}])
check("the JCT sums waits, computes and API calls",
      total["jct"] == 168.0, total)
check("no segments is its own verdict", SS.jct([])["verdict"] == "no-segments")

cmp_out = SS.compare([{"policy": "vLLM-FCFS", "jct": 164.9},
                      {"policy": "Infercept", "jct": 151.9},
                      {"policy": "Astraea", "jct": 122.88}])
check("the lifecycle scheduler wins", cmp_out["best"]["policy"] == "Astraea")
check("the improvement against FCFS is measured",
      abs(cmp_out["improvement"] - 0.2548) < 1e-3, cmp_out)
check("a lifecycle gain above 10% is named", cmp_out["verdict"] == "lifecycle-pays")

stab = SS.stability([{"policy": "Astraea", "low": 100, "high": 116.2},
                     {"policy": "vLLM-SJF", "low": 100, "high": 151.9}])
check("the robust policy degrades least",
      stab["best"]["policy"] == "Astraea", stab)
check("the degradation ratio is measured", abs(stab["ratio"] - 3.2) < 0.05)
check("a 2x gap is named", stab["verdict"] == "degrades-less")
check("advise names every missing practice", len(SS.advise({})["findings"]) == 6)
check("a fully declared profile has no finding", SS.advise(
    {k: True for k in ("optimizes_end_to_end", "classifies_compute_and_io",
                       "ages_the_lowest_queue", "predicts_the_api_duration",
                       "manages_kv_on_wait", "reports_jct_not_ttft")})
    ["findings"] == [])

# ---- 3. capacity pools (token management) -------------------------------
table = CP.classes()
check("five service classes exist", len(table) == 5)
check("guaranteed is never shrunk", table["guaranteed"]["shrink"] == "never")
check("spot has no baseline", table["spot"]["baseline"] == "none")
check("class weights span four orders",
      table["dedicated"]["weight"] / table["preemptible"]["weight"] == 10000.0)
check("an unknown class is named",
      CP.classify("vip")["verdict"] == "unknown-class")
check("a known class returns its policy",
      CP.classify("elastic")["shrink"] == "yes")

copilot = CP.priority({"class": "elastic", "base_weight": 100,
                       "slo_ms": 500, "avg_slo_ms": 15250})
check("a tight SLO raises the weight", abs(copilot["weight"] - 93.4) < 1.0, copilot)
synth = CP.priority({"class": "elastic", "base_weight": 100,
                     "slo_ms": 30000, "avg_slo_ms": 15250, "burst": 13.5})
check("a sustained burst suppresses a loose SLO",
      abs(synth["weight"] - 20.2) < 1.0, synth)
debted = CP.priority({"class": "elastic", "base_weight": 100,
                      "slo_ms": 30000, "avg_slo_ms": 15250, "burst": 13.5,
                      "debt": 0.775})
check("debt restores a suppressed weight",
      abs(debted["weight"] - 82.8) < 2.0, debted)
check("the urgency term is a magnitude, never negative",
      CP.priority({"class": "elastic", "base_weight": 100, "slo_ms": 1,
                   "avg_slo_ms": 1000})["urgency"] >= 0.0)
check("a missing SLO is refused",
      CP.priority({"class": "elastic"})["verdict"] == "slo-missing")
check("an unknown class is refused",
      CP.priority({"class": "vip", "slo_ms": 1, "avg_slo_ms": 1})["verdict"]
      == "unknown-class")

d = CP.debt({"entitled": 10, "served": 5, "prev_debt": 0, "gamma": 0.7})
check("underservice accrues debt", abs(d["debt"] - 0.15) < 1e-9, d)
check("the service gap is reported", abs(d["gap"] - 0.5) < 1e-9)
d2 = CP.debt({"entitled": 10, "served": 10, "prev_debt": 1.0, "gamma": 0.7})
check("recovery decays the debt", abs(d2["debt"] - 0.7) < 1e-9)
check("decay is not accrual", d2["accruing"] is False)
b = CP.burst({"throughput": 1.2, "throughput_entitled": 1.0,
              "kv": 1.5, "kv_entitled": 1.0,
              "concurrency": 1.0, "concurrency_entitled": 1.0,
              "prev_burst": 0.0, "gamma": 0.7})
check("burst sums the over-baseline dimensions",
      abs(b["instant"] - 0.7) < 1e-9, b)
check("the burst is smoothed", abs(b["burst"] - 0.21) < 1e-9)

res = CP.resources({"layers": 32, "kv_heads": 8, "head_dim": 128,
                    "element_bytes": 2, "context": 1000,
                    "gpu_kv_bytes": 1_000_000_000, "concurrency": 4})
check("KV bytes per token use 2*L*H*d*b",
      res["per_token_bytes"] == 131072.0, res)
check("the sequence cache multiplies by context",
      res["sequence_bytes"] == 131_072_000.0)
check("the concurrency ceiling is floor(GPU/sequence)",
      res["max_concurrency"] == 7)
check("a fitting concurrency is named",
      res["verdict"] == "concurrency-fits")
check("a KV-bound request is named",
      CP.resources({"layers": 32, "kv_heads": 8, "head_dim": 128,
                    "element_bytes": 2, "context": 1000,
                    "gpu_kv_bytes": 1_000_000_000, "concurrency": 10})
      ["verdict"] == "kv-bound")

check("a valid request is admitted",
      CP.admission({"inflight": 2, "concurrency": 4, "request_tokens": 100,
                    "remaining_tokens": 500})["admitted"] is True)
conc = CP.admission({"inflight": 4, "concurrency": 4})
check("the concurrency limit denies with 429",
      conc["status"] == 429 and conc["reason"] == "concurrency-limit")
check("a denial carries a retry hint", conc["retry_after"] >= 1)
check("an over-budget request is denied",
      CP.admission({"inflight": 0, "concurrency": 4, "request_tokens": 600,
                    "remaining_tokens": 500})["reason"] == "token-budget")
check("a low-priority request during contention is denied",
      CP.admission({"inflight": 1, "concurrency": 4, "contended": True,
                    "priority": 10, "threshold": 50})["reason"]
      == "below-contention-threshold")
check("a high-priority request during contention is admitted",
      CP.admission({"inflight": 1, "concurrency": 4, "contended": True,
                    "priority": 90, "threshold": 50})["admitted"] is True)
check("a non-bound entitlement is refused",
      CP.admission({"state": "degraded"})["reason"] == "state-degraded")
check("the executed checks are reported",
      "contention" in CP.admission({"inflight": 1, "concurrency": 4,
                                    "contended": True, "priority": 90,
                                    "threshold": 50})["checks"])

rec = CP.reclaim([{"id": "g", "class": "guaranteed"},
                  {"id": "s", "class": "spot"},
                  {"id": "p", "class": "preemptible"},
                  {"id": "e", "class": "elastic"}])
check("preemptible yields first", rec["rows"][0]["id"] == "p")
check("guaranteed is never touched", rec["rows"][-1]["action"] == "never")
check("spot is throttled, not evicted", rec["rows"][1]["action"] == "throttle")
check("elastic is throttled", rec["rows"][2]["action"] == "throttle")

prot = CP.protect([{"arm": "managed pool", "p99_s": 1.1},
                   {"arm": "baseline", "p99_s": 19.0}])
check("protected latency stays bounded", prot["verdict"]
      == "bounded-protected-latency", prot)
check("the latency ratio is measured", abs(prot["ratio"] - 17.27) < 0.02)
check("a slow managed arm is named", CP.protect(
    [{"arm": "managed", "p99_s": 3.0}, {"arm": "baseline", "p99_s": 5.0}])
    ["verdict"] == "latency-unbounded")

fs = CP.fairshare({"gap_before": 4.6, "gap_after": 3.9})
check("debt narrows the priority gap", fs["verdict"] == "debt-narrows-gap")
check("the narrowing is explicit", fs["narrowed"] is True)
check("a gap that does not move is named",
      CP.fairshare({"gap_before": 3.0, "gap_after": 3.0})["verdict"]
      == "debt-does-not-bind")
check("advise names every missing practice", len(CP.advise({})["findings"]) == 6)
check("a fully declared profile has no finding", CP.advise(
    {k: True for k in ("prices_in_inference_units", "declares_service_classes",
                       "accumulates_debt", "tracks_burst_dimensions",
                       "admits_at_the_gateway", "denies_with_retry_after")})
    ["findings"] == [])

# ---- result --------------------------------------------------------------
ok = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
