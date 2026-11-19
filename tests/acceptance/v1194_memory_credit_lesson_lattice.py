#!/usr/bin/env python3
"""v1194 — decision-utility memory, falsification-gated lessons, security lattice (round 125).

Sources:
  * arXiv:2611.15600 "MemCredit" — relevance is recall, utility arbitrates;
    utility is sparse (86.9% zero), state-dependent, and poorly correlated with
    relevance; the budget is a ceiling.
  * arXiv:2611.14326 "FGSE" — a lesson is a hypothesis (precondition, change,
    expected effect, verifier), tested on transfer / falsification / regression
    probes before it may be committed.
  * arXiv:2611.13960 "ActiveSecHarness" — a product taint lattice
    Ltrust x Lsens, monotone capability attenuation, and a workspace provenance
    ledger that makes the Lethal Trifecta a deterministic check.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1194_memory_credit_lesson_lattice.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1194-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import memory_credit as MC  # noqa: E402
from longrun.harness.checks import lesson_gate as LG  # noqa: E402
from longrun.harness.checks import security_lattice as SL  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. decision utility: novelty, not relevance ----------------------------
FREE = {"id": "m1", "content": "alpha beta", "utility": 0.5, "relevance": 0.99}
check("with an empty selection the whole utility counts",
      MC.credit(FREE, [])["credit"] == 0.5)
half = MC.credit(FREE, [{"content": "alpha"}])
check("a memory whose facts are half covered is worth half its utility",
      half["novelty"] == 0.5 and half["credit"] == 0.25, half)
check("a memory fully covered by the selection is worth zero",
      MC.credit(FREE, [{"content": "alpha beta"}])["credit"] == 0.0)
check("relevance is carried but never used as the credit",
      MC.credit(FREE, [])["relevance"] == 0.99
      and MC.credit(FREE, [{"content": "alpha beta"}])["credit"] == 0.0)
check("a candidate with no content is not silently zeroed by an empty selection",
      MC.credit({"id": "x", "utility": 0.2}, [])["credit"] == 0.2)

CAND = [{"id": "big", "content": "x y", "utility": 1.0, "tokens": 100},
        {"id": "small", "content": "x", "utility": 0.3, "tokens": 10}]
picked = MC.arbitrate(CAND, budget=110)
check("credit per added token picks the small item first",
      [s["id"] for s in picked["selected"]] == ["small", "big"], picked["selected"])
check("the big item's credit is re-scored after its fact is covered",
      picked["selected"][1]["credit"] == 0.5, picked["selected"][1])
check("the budget is spent exactly as the ceiling allows", picked["spent"] == 110)
tight = MC.arbitrate(CAND, budget=100)
check("an item that does not fit under the ceiling is not admitted",
      [s["id"] for s in tight["selected"]] == ["small"] and tight["spent"] == 10)
check("an unfilled budget is reported, never padded",
      "budget-not-filled" in kinds(tight) and
      [f for f in tight["findings"] if f["kind"] == "budget-not-filled"][0]["unused"] == 90)
check("a zero-utility candidate is refused by the credit floor",
      MC.arbitrate([{"id": "z", "content": "q", "utility": 0.0, "tokens": 1}],
                   budget=10)["selected"] == [])
check("a duplicate id is reported instead of silently re-inserted",
      "duplicate-id" in kinds(MC.arbitrate(
          [{"id": "d", "content": "a", "utility": 1.0, "tokens": 1},
           {"id": "d", "content": "b", "utility": 1.0, "tokens": 1}], budget=10)))
check("a bad budget is refused, not guessed",
      "bad-budget" in kinds(MC.arbitrate(CAND, budget="lots")))
check("no candidates is a finding",
      "no-candidates" in kinds(MC.arbitrate([], budget=10)))

SPARSE = ([{"credit": 0.0}] * 9) + [{"credit": 1.0, "state": "failure_context"}]
sp = MC.sparsity(SPARSE)
check("the zero share is the headline of a sparse memory set",
      sp["zero_share"] == 0.9 and "utility-sparse" in kinds(sp), sp)
check("the failure-context effect is reported separately",
      sp["failure_mean"] == 1.0 and sp["other_mean"] == 0.0
      and "failure-concentrated" in kinds(sp), sp)
check("sparsity without interventions says so",
      "no-interventions" in kinds(MC.sparsity([])))

# ---- 2. lessons are hypotheses until a probe survives ----------------------
GOOD = {"id": "L1", "precondition": "when tests fail twice",
        "change": "read the failing test before editing",
        "expected": "one fewer failed attempt", "verifier": "test exit code"}
check("a complete hypothesis is admissible",
      LG.hypothesis(GOOD)["valid"] is True)
partial = LG.hypothesis({"id": "L2", "change": "try harder"})
check("a lesson without a precondition or verifier is rejected",
      partial["valid"] is False and len(kinds(partial)) == 3, kinds(partial))
check("a trial applies the lesson to a temporary state",
      LG.trial(GOOD, "sandbox")["temporary"] is True)
held = LG.trial(GOOD, "live", persist=True)
check("persisting before probing is refused",
      held["applied"] is False and "premature-persist" in kinds(held), held)
check("a probed lesson may be applied persistently",
      LG.trial({**GOOD, "probes": ["t"]}, "live", persist=True)["applied"] is True)

RESULTS_OK = {
    "target_transfer": [{"task": "a", "before": 0.5, "after": 0.8},
                        {"task": "b", "before": 0.4, "after": 0.6}],
    "falsification": [{"case": "c1", "held": True}],
    "regression": [{"task": "r", "before": 0.9, "after": 0.9}],
}
committed = LG.probe(GOOD, RESULTS_OK)
check("positive transfer, nothing falsified, no regression ⇒ commit",
      committed["decision"] == "commit" and committed["gain"] == 0.25, committed)
falsified = LG.probe(GOOD, {**RESULTS_OK,
                            "falsification": [{"case": "c9", "held": False}]})
check("one falsified probe rejects the lesson even with a gain",
      falsified["decision"] == "reject" and "falsified" in kinds(falsified), falsified)
damaged = LG.probe(GOOD, {**RESULTS_OK,
                          "regression": [{"task": "r", "before": 1.0, "after": 0.8}]})
check("an archived regression rejects the lesson",
      damaged["decision"] == "reject" and "regression-damage" in kinds(damaged), damaged)
flat = LG.probe(GOOD, {**RESULTS_OK,
                       "target_transfer": [{"task": "a", "before": 0.5, "after": 0.5}]})
check("no transfer refines instead of committing",
      flat["decision"] == "refine" and "no-transfer" in kinds(flat), flat)
unmeasured = LG.probe(GOOD, {**RESULTS_OK, "target_transfer": []})
check("a transfer class with no measurement refines",
      unmeasured["decision"] == "refine"
      and "no-transfer-measurement" in kinds(unmeasured), unmeasured)
unprobed = LG.probe(GOOD, {**RESULTS_OK, "falsification": []})
check("a missing probe class is not a pass",
      unprobed["decision"] == "refine" and "missing-probe" in kinds(unprobed), unprobed)
check("an unstructured lesson is rejected before any probe",
      LG.probe({"id": "L9"}, RESULTS_OK)["decision"] == "reject")

# ---- 3. the product lattice ------------------------------------------------
check("join takes the higher trust and the higher sensitivity",
      SL.join(SL.label("trusted", "public"),
              SL.label("derived", "sensitive")) == SL.label("derived", "sensitive"))
check("the trust order is trusted ⊑ sanitized ⊑ derived ⊑ untrusted",
      SL.join(SL.label("trusted"), SL.label("sanitized"))["trust"] == "sanitized"
      and SL.join(SL.label("derived"), SL.label("untrusted"))["trust"] == "untrusted")
san = SL.sanitize(SL.label("derived", "sensitive"))
check("sanitization lowers trust and NEVER clears sensitivity",
      san["label"] == SL.label("sanitized", "sensitive"), san)
check("a trusted input is not re-labelled by sanitization",
      SL.sanitize(SL.label("trusted", "public"))["label"]["trust"] == "trusted")
check("declassification without authority is refused",
      SL.declassify(SL.label("derived", "sensitive"))["allowed"] is False)
check("an authorized redaction is the only path to public",
      SL.declassify(SL.label("derived", "sensitive"), authorized=True)["label"]
      == SL.label("derived", "public"))
check("an untrusted input permits local inspection only",
      SL.admit(SL.label("untrusted"), "read_workspace")["allowed"] is True
      and SL.admit(SL.label("untrusted"), "write_workspace")["allowed"] is False
      and "untrusted-input" in kinds(SL.admit(SL.label("untrusted"), "write_workspace")))
check("derived provenance permits workspace edits, extraction and isolated tests",
      all(SL.admit(SL.label("derived"), a)["allowed"]
          for a in ("write_workspace", "extract", "test_isolated")))
check("derived provenance still closes arbitrary shells and egress",
      SL.admit(SL.label("derived"), "shell_arbitrary")["allowed"] is False
      and SL.admit(SL.label("derived"), "net_egress")["allowed"] is False)
check("a trusted label permits arbitrary execution",
      SL.admit(SL.label("trusted"), "shell_arbitrary")["allowed"] is True)
check("sensitivity closes shell and egress at ANY trust level",
      SL.admit(SL.label("trusted", "sensitive"), "shell_arbitrary")["allowed"] is False
      and "sensitive-flow" in kinds(SL.admit(SL.label("trusted", "sensitive"), "net_egress")))
check("sensitivity does not block isolated tests",
      SL.admit(SL.label("derived", "sensitive"), "test_isolated")["allowed"] is True)

PARENT = {"tools": ["fs.read", "fs.write"], "paths": ["/work"], "cidrs": ["10.0.0.0/16"],
          "ttl_s": 600, "quota": 50}
check("a narrower child capability is valid",
      SL.attenuate(PARENT, {"tools": ["fs.read"], "paths": ["/work"], "cidrs": [],
                            "ttl_s": 60, "quota": 10})["valid"] is True)
check("a wider tool set is refused",
      "widened-tools" in kinds(SL.attenuate(PARENT, {"tools": ["fs.read", "net.fetch"],
                                                    "ttl_s": 1, "quota": 1})))
check("a longer TTL is refused",
      "ttl-extended" in kinds(SL.attenuate(PARENT, {"ttl_s": 3600, "quota": 1})))
check("a larger quota is refused",
      "quota-raised" in kinds(SL.attenuate(PARENT, {"ttl_s": 1, "quota": 99})))

A = {"id": "A", "label": SL.label("trusted", "public")}
B = {"id": "B", "label": SL.label("trusted", "public")}
secret = {"id": "src", "label": SL.label("trusted", "sensitive"), "effects": ["read_sensitive"]}
led = SL.ledger_write({}, "/work/notes.txt", A)["ledger"]
led = SL.ledger_write(led, "/work/notes.txt", secret)["ledger"]
check("a file joins every writer's label",
      led["/work/notes.txt"]["label"] == SL.label("trusted", "sensitive"),
      led["/work/notes.txt"])
read = SL.ledger_read(led, "/work/notes.txt", B)
check("a reader inherits the file's sensitivity and its effects",
      read["actor"]["label"]["sens"] == "sensitive"
      and "read_sensitive" in read["actor"]["effects"], read["actor"])
egress = SL.admit_effect(read["actor"], "net_egress")
check("the cross-agent Lethal Trifecta is refused deterministically",
      egress["allowed"] is False and "lethal-trifecta" in kinds(egress), egress)
check("the same egress is allowed for an agent that never read the secret",
      SL.admit_effect(B, "net_egress")["allowed"] is True)
check("an unlabelled path is reported instead of trusted",
      "unlabelled-path" in kinds(SL.ledger_read({}, "/work/x", B)))

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
