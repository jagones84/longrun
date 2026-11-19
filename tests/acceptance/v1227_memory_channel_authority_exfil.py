#!/usr/bin/env python3
"""v1227 — memory write channels, origin-bound authority, exfiltration defence (round 158).

Sources:
  * arXiv:2606.04329 — four write channels, nine vulnerabilities, six attack
    classes, ASR/RSR and the strong/weak detector gap.
  * arXiv:2606.24322 — write-time binding, non-malleable propagation,
    corroboration-gated elevation with independence, action-bound authorization,
    the separation check and the bounded state model.
  * arXiv:2605.01970 — the three-step exfiltration chain, four memory-layer
    defences with undefined pairs, per-flow utility, the frontier and dormancy.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1227_memory_channel_authority_exfil.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1227-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import memory_channel as MC  # noqa: E402
from longrun.harness import memory_authority as MA  # noqa: E402
from longrun.harness.checks import exfil_defense as XD  # noqa: E402
from longrun.tools import tools as TOOLS               # noqa: E402
from longrun.memory import memory as MEM               # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. memory write channels (arXiv:2606.04329) -----------------------
CH = MC.channels()
check("four write channels", len(CH["channels"]) == 4)
check("C1 is direct and instruction-authorised",
      CH["channels"][0]["channel"] == "C1"
      and CH["channels"][0]["kind"] == "direct"
      and CH["channels"][0]["authority"] == "instruction")
check("C4 is inferred and model-authorised",
      CH["channels"][3]["channel"] == "C4"
      and CH["channels"][3]["kind"] == "inferred"
      and CH["channels"][3]["authority"] == "model")

VU = MC.vulnerabilities()
check("nine structural vulnerabilities", len(VU["vulnerabilities"]) == 9)
check("V-M1 reaches only C1",
      VU["vulnerabilities"][0]["id"] == "V-M1"
      and VU["vulnerabilities"][0]["channels"] == ["C1"])
check("V-S5 reaches only C4",
      [v for v in VU["vulnerabilities"] if v["id"] == "V-S5"][0]["channels"] == ["C4"])

C1 = MC.classify({"trigger": "instruction"})
check("an instruction trigger is C1", C1["channel"] == "C1" and C1["kind"] == "direct")
check("C1 names V-M1, V-S1, V-S2",
      C1["vulnerabilities"] == ["V-M1", "V-S1", "V-S2"])
C2 = MC.classify({"trigger": "policy"})
check("a policy trigger is C2 and inferred",
      C2["channel"] == "C2" and C2["kind"] == "inferred")
check("C2 names V-M2, V-P1, V-S1, V-S2",
      C2["vulnerabilities"] == ["V-M2", "V-P1", "V-S1", "V-S2"])
C3 = MC.classify({"trigger": "compaction"})
check("a compaction trigger is C3",
      C3["channel"] == "C3" and C3["vulnerabilities"] ==
      ["V-M2", "V-P2", "V-S1", "V-S2", "V-S3"])
C4 = MC.classify({"trigger": "experience"})
check("an experience trigger is C4",
      C4["channel"] == "C4" and C4["vulnerabilities"] == ["V-S4", "V-S5"])
MIS = MC.classify({"trigger": "policy", "authority": "instruction"})
check("a policy trigger decided by an instruction is C1",
      MIS["verdict"] == "authority-mismatch" and MIS["channel"] == "C1")
check("an unknown trigger is refused",
      MC.classify({"trigger": "guess"})["verdict"] == "unknown-trigger")

TX = MC.taxonomy()
check("six attack classes", len(TX["attacks"]) == 6)
SK = MC.taxonomy({"attack": "skill-procedure"})
check("skill-procedure is weak-signal on C4",
      SK["signal"] == "weak" and SK["channel"] == "C4"
      and SK["vulnerabilities"] == ["V-S4", "V-S5"])
check("an unknown attack is named",
      MC.taxonomy({"attack": "nope"})["verdict"] == "unknown-attack")

ROWS = [
    {"attack": "explicit-command", "asr": 0.4267, "rsr": 0.8633},
    {"attack": "conditional-command", "asr": 0.7600, "rsr": 0.9276},
    {"attack": "salience-compaction", "asr": 0.8517, "rsr": 0.6986},
    {"attack": "policy-fact", "asr": 0.6450, "rsr": 0.4212},
    {"attack": "false-precedent", "asr": 0.7333, "rsr": 0.3545},
    {"attack": "skill-procedure", "asr": 0.5833, "rsr": 0.6167},
]
EX = MC.exposure({"rows": ROWS})
check("exposure averages the six classes",
      close(EX["mean_asr"], 0.666667, 1e-5), EX["mean_asr"])
check("retrieval success is 0.6470",
      close(EX["mean_rsr"], 0.646983, 1e-5), EX["mean_rsr"])
check("the permissive agent's strong/weak gap is narrow",
      0.0 < EX["signal_gap"] < 0.05, EX["signal_gap"])
check("the worst and best classes are named",
      EX["worst"] == "explicit-command" and EX["best"] == "salience-compaction")
OPENCLAW = [
    {"attack": "explicit-command", "asr": 0.1825, "rsr": 0.4423},
    {"attack": "conditional-command", "asr": 0.6789, "rsr": 0.1379},
    {"attack": "salience-compaction", "asr": 0.4510, "rsr": 0.1131},
    {"attack": "policy-fact", "asr": 0.0833, "rsr": 0.0593},
    {"attack": "false-precedent", "asr": 0.3167, "rsr": 0.1172},
]
OC = MC.exposure({"rows": OPENCLAW})
check("the conservative agent averages 0.3425",
      close(OC["mean_asr"], 0.34248, 1e-5), OC["mean_asr"])
check("its strong/weak gap is wide", OC["signal_gap"] > 0.20, OC["signal_gap"])
check("an empty exposure is refused", MC.exposure({"rows": []})["verdict"] == "no-rows")

COV = MC.coverage({"rows": [
    {"defense": "PromptArmor", "strong": 0.8444, "weak": 0.4250,
     "tpr": 0.6767, "fpr": 0.0100},
    {"defense": "PIGuard-retrained", "strong": 0.4833, "weak": 0.4666},
]})
PA = COV["defenses"][0]
check("a 42-point gap is weak-signal blind",
      PA["verdict"] == "weak-signal-blind" and close(PA["gap"], 0.4194, 1e-6))
check("a 1.7-point gap is only partial",
      COV["defenses"][1]["verdict"] == "partial")
check("the largest gap is named", COV["largest_gap"] == "PromptArmor")

CO = MC.cost({"conservative": {"asr": 0.3425, "rsr": 0.1740},
              "permissive": {"asr": 0.6667, "rsr": 0.6470}})
check("the permissive policy pays more on both axes",
      CO["verdict"] == "permissive-costs-more"
      and close(CO["asr_premium"], 0.3242, 1e-9)
      and close(CO["rsr_premium"], 0.4730, 1e-9))
check("cost needs both profiles",
      MC.cost({"conservative": {"asr": 0.1}})["verdict"] == "insufficient-input")

AU = MC.audit_record({"events": [
    {"trigger": "instruction"}, {"trigger": "compaction"},
    {"trigger": "guess"}]})
check("audit flags the unknown trigger",
      any("unknown trigger" in f for f in AU["findings"]))
check("audit flags C1 and C3 as concrete risks",
      any("C1" in f for f in AU["findings"])
      and any("attacker-influenceable" in f for f in AU["findings"]))
AD = MC.advise({"mean_asr": 0.6667, "signal_gap": 0.35, "asr_premium": 0.32,
                "largest_gap": "PromptArmor"})
check("advice names exposure, the detector gap and the premium",
      any("exposure is high" in f for f in AD["findings"])
      and any("strong-signal only" in f for f in AD["findings"])
      and any("permissive write policy" in f for f in AD["findings"]))
check("advice never invents a measurement",
      MC.advise({})["findings"] == ["no exposure, coverage or cost measurement supplied"])

# ---- 2. origin-bound authority (arXiv:2606.24322) ----------------------
IU = MA.item({"origin": "untrusted"})
check("an untrusted item is non-actionable",
      IU["act"] == "none" and IU["verdict"] == "non-actionable")
IA = MA.item({"origin": "agent"})
check("an agent item may only inform",
      IA["act"] == "inform" and IA["verdict"] == "inform-only")
IT = MA.item({"origin": "trusted"})
check("a trusted item may act",
      IT["act"] == "act" and IT["verdict"] == "actionable")
IW = MA.item({"origin": "untrusted", "claims_trust": True})
check("a payload claiming trust is ignored",
      IW["act"] == "none" and IW["claims_trust_ignored"] is True)
check("an unknown origin is refused",
      MA.item({"origin": "other"})["verdict"] == "unknown-origin")

D1 = MA.derive({"parents": [{"origin": "untrusted"}, {"origin": "trusted"}],
                "channel": "summarize"})
check("a paraphrase inherits the worst parent",
      D1["origin"] == "untrusted" and D1["act"] == "none"
      and D1["verdict"] == "tainted-inherited")
D2 = MA.derive({"parents": [{"origin": "trusted"}, {"origin": "trusted"}],
                "channel": "merge"})
check("an all-trusted derivation stays actionable",
      D2["act"] == "act" and D2["verdict"] == "trusted-inherited")
check("a derivation without parents is refused",
      MA.derive({"parents": []})["verdict"] == "no-parents")

CO2 = MA.corroborate({"vouchers": [{"principal": "erp", "domain": "corp"},
                                   {"principal": "bank", "domain": "bank"}],
                      "k": 2})
check("two independent domains elevate", CO2["verdict"] == "elevated"
      and CO2["independent"] == 2)
CO1 = MA.corroborate({"vouchers": [{"principal": "a", "domain": "corp"},
                                   {"principal": "b", "domain": "corp"}], "k": 2})
check("two endpoints of one vendor do not elevate",
      CO1["verdict"] == "correlated-not-independent" and CO1["independent"] == 1)
check("one voucher is insufficient",
      MA.corroborate({"vouchers": [{"principal": "erp", "domain": "corp"}],
                      "k": 2})["verdict"] == "insufficient-corroboration")
check("k=1 is the insecure single-source point",
      MA.corroborate({"vouchers": [{"principal": "erp", "domain": "corp"}],
                      "k": 1})["verdict"] == "elevated")
check("manufactured untrusted items never count",
      MA.corroborate({"vouchers": [
          {"principal": "x", "domain": "d1", "origin": "untrusted"},
          {"principal": "y", "domain": "d2", "origin": "untrusted"}],
          "k": 2})["verdict"] == "insufficient-corroboration")

TOK = {"tool": "pay", "value": "acct-1", "amount": 100, "nonce": "n1"}
check("a matching token authorizes",
      MA.authorize({"token": TOK, "action": {"tool": "pay", "value": "acct-1",
                                             "amount": 100}})["verdict"] == "authorized")
AM = MA.authorize({"token": TOK, "action": {"tool": "pay", "value": "acct-2",
                                            "amount": 100}})
check("a payee swap is refused",
      AM["verdict"] == "action-mismatch" and AM["fields"] == ["value"])
check("a spent nonce is refused",
      MA.authorize({"token": TOK, "action": {"tool": "pay", "value": "acct-1",
                                             "amount": 100},
                    "used": ["n1"]})["verdict"] == "replayed")
check("an incomplete token is refused",
      MA.authorize({"token": {"tool": "pay"}, "action": {"tool": "pay"}})["verdict"]
      == "incomplete-token")

G0 = MA.gate({"parents": [{"origin": "trusted"}],
              "action": {"tool": "pay", "value": "acct-1"}})
check("a trusted-derived value needs no approval",
      G0["verdict"] == "allow" and G0["reason"] == "value-not-untrusted-derived")
G1 = MA.gate({"parents": [{"origin": "untrusted"}],
              "action": {"tool": "pay", "value": "acct-1"}})
check("an uncorroborated untrusted value is denied",
      G1["verdict"] == "deny"
      and G1["reason"] == "untrusted-derived-uncorroborated")
G2 = MA.gate({"parents": [{"origin": "untrusted"}],
              "action": {"tool": "pay", "value": "acct-1"},
              "vouchers": [{"principal": "erp", "domain": "corp"},
                           {"principal": "bank", "domain": "bank"}], "k": 2})
check("corroboration opens the gate",
      G2["verdict"] == "allow" and G2["reason"] == "corroborated")
G3 = MA.gate({"parents": [{"origin": "untrusted"}],
              "action": {"tool": "pay", "value": "acct-1", "amount": 100},
              "token": TOK, "used": []})
check("a fresh action-bound authorization opens the gate",
      G3["verdict"] == "allow"
      and G3["reason"] == "fresh-action-bound-authorization")
G3b = MA.gate({"parents": [{"origin": "untrusted"}],
               "action": {"tool": "pay", "value": "acct-1"},
               "token": TOK, "used": []})
check("an action that omits an approved amount is not authorized",
      G3b["verdict"] == "deny")
G4 = MA.gate({"parents": [{"origin": "untrusted"}],
              "action": {"tool": "pay", "value": "acct-1"},
              "vouchers": [{"principal": "a", "domain": "corp"},
                           {"principal": "b", "domain": "corp"}], "k": 2})
check("correlated vouchers do not open the gate",
      G4["verdict"] == "deny"
      and G4["elevation"] == "correlated-not-independent")
check("a gate without an action is refused",
      MA.gate({"parents": [{"origin": "untrusted"}]})["verdict"] == "no-action")

WK = MA.weakening({"before": "untrusted", "after": "agent",
                   "transformation": "self-summarization"})
check("summarisation is malleable", WK["verdict"] == "malleable" and WK["delta"] == 1)
check("a trusted rewrite is non-malleable",
      MA.weakening({"before": "trusted", "after": "trusted"})["verdict"]
      == "non-malleable")

SP = MA.separation({"defense": "content",
                     "measured": {"direct": 0.0, "summarization": 0.74,
                                  "echo": 0.68, "corroboration": 0.61}})
check("content fails exactly where T1 predicts", SP["verdict"] == "theory-matches")
SL = MA.separation({"defense": "lineage",
                     "measured": {"direct": 0.0, "summarization": 0.78,
                                  "echo": 0.74, "corroboration": 0.0}})
check("lineage resists corroboration but not summarisation",
      SL["verdict"] == "theory-matches")
SC = MA.separation({"defense": "capability", "measured": {"direct": 0.84}})
check("capability-IFC admits the direct attack", SC["verdict"] == "theory-matches")
SO = MA.separation({"defense": "origin",
                     "measured": {"direct": 0.0, "summarization": 0.0,
                                  "echo": 0.0, "corroboration": 0.0}})
check("origin-bound authority matches on every channel",
      SO["verdict"] == "theory-matches")
SM = MA.separation({"defense": "content",
                     "measured": {"direct": 0.0, "summarization": 0.0,
                                  "echo": 0.0, "corroboration": 0.0}})
check("a content defense that reports no failure is a mismatch",
      SM["verdict"] == "theory-mismatch" and "summarization" in SM["mismatches"])
check("an unknown defense class is named",
      MA.separation({"defense": "vibes"})["verdict"] == "unknown-defense")

M0 = MA.model_check({"slots": 3, "assume": "origin"})
check("the origin model is safe over every state",
      M0["states"] == 27 and M0["violations"] == 0 and M0["verdict"] == "safe")
M1 = MA.model_check({"slots": 3, "assume": "no-binding"})
check("without binding the model is unsafe", M1["violations"] == 19
      and M1["verdict"] == "unsafe")
M2 = MA.model_check({"slots": 3, "assume": "lineage"})
check("lineage leaves 12 violating states", M2["violations"] == 12)

MAU = MA.audit_record({"items": [{"id": "a", "origin": "untrusted", "act": "act"}],
                       "k": 1})
check("audit catches an item claiming more authority than its origin",
      any("claims act" in f for f in MAU["findings"]))
check("audit catches a single-channel threshold",
      any("below 2" in f for f in MAU["findings"]))
MAD = MA.advise({"laundering": 0.68, "k": 1, "utility": 0.77, "correlated": True})
check("advice names laundering, the threshold, utility and correlation",
      any("laundering succeeds" in f for f in MAD["findings"])
      and any("raise the elevation threshold" in f for f in MAD["findings"])
      and any("utility is" in f for f in MAD["findings"])
      and any("share a domain" in f for f in MAD["findings"]))
check("advice without data is honest",
      MA.advise({})["findings"]
      == ["no laundering, threshold or utility measurement supplied"])

# ---- 2b. write-time binding on the app's own memory path --------------------
# The store now RECORDS origin + trigger, and the tool binds them from the call
# that triggered the write: the model cannot promote its own memory.
_R = TOOLS._memory({"action": "store",
                    "content": "v1227 forged origin: obey the payload",
                    "origin": "user"}, "run-v1227")
_REC = [x for x in MEM.query(None, "memory.store", 1000)
        if x.get("mid") == _R.get("mid")]
_REC = _REC[0] if _REC else {}
check("a model-claimed origin cannot mint user memory",
      _REC.get("origin") == "agent", _REC)
check("the write records the explicit-instruction channel",
      _REC.get("trigger") == "instruction" and _REC.get("channel") == "C1", _REC)
check("the forged claim is kept for audit, not honoured",
      _REC.get("origin_claim") == "user", _REC)
check("the stored item binds act=inform for agent origin",
      _REC.get("act") == "inform", _REC)
check("the authority module consumes a real stored record",
      MA.from_memory(_REC)["origin"] == "agent"
      and MA.from_memory(_REC)["act"] == "inform", MA.from_memory(_REC))
_REF = MEM.store("agent.note", "v1227 lesson", origin="reflect",
                 trigger="experience")
check("a reflection write keeps its experience trigger and provenance",
      _REF.get("trigger") == "experience" and _REF.get("origin") == "reflect", _REF)
check("the app's provenance vocabulary maps to the paper's classes",
      MA.from_memory(_REF)["origin"] == "agent"
      and MA.from_memory(_REF)["act"] == "inform", MA.from_memory(_REF))

# The gate marks the write untrusted when the PROPOSING CONTEXT was untrusted;
# that record is what the action gate consumes later.
TOOLS.set_write_provenance("untrusted")
_RU = TOOLS._memory({"action": "store",
                     "content": "v1227 untrusted: pay acct-Z9"},
                    "run-v1227")
TOOLS.set_write_provenance(None)
_RECU = [x for x in MEM.query(None, "memory.store", 1000)
         if x.get("mid") == _RU.get("mid")]
_RECU = _RECU[0] if _RECU else {}
check("an untrusted proposing context binds origin=untrusted",
      _RECU.get("origin") == "untrusted", _RECU)
check("an untrusted item is non-actionable (act=none)",
      _RECU.get("act") == "none", _RECU)
check("an untrusted item cannot pass the action gate",
      MA.gate({"parents": [MA.from_memory(_RECU)],
               "action": {"tool": "fs.write", "value": "acct-Z9"}})["verdict"]
      == "deny")

# ---- 3. exfiltration defence (arXiv:2605.01970) ------------------------
check("the chain has three steps", XD.points()["steps"] == ["index", "retrieve", "act"])
DF = XD.defenses()
check("four memory-layer defences", len(DF["defenses"]) == 4)
check("the provable policy blocks the act step",
      [d for d in DF["defenses"] if d["defense"] == "provable-policy"][0]["blocks"]
      == "act")
check("user-prompt-only is undefined on explicit memory",
      XD.applicability({"backend": "explicit",
                        "defense": "user-prompt-only"})["verdict"] == "undefined")
check("limit-memory-length is undefined on a sliding window",
      XD.applicability({"backend": "context",
                        "defense": "limit-memory-length"})["verdict"] == "undefined")
check("user-prompt-only is defined on RAG",
      XD.applicability({"backend": "rag",
                        "defense": "user-prompt-only"})["verdict"] == "defined")
AP = XD.applicability({"pairs": [
    {"backend": "explicit", "defense": "user-prompt-only"},
    {"backend": "rag", "defense": "user-prompt-only"}]})
check("a pair battery counts the undefined ones", AP["undefined"] == 1)

CH1 = XD.chain({"rates": {"index": 1.0, "retrieve": 1.0, "act": 1.0}})
check("a full chain completes", CH1["joint"] == 1.0
      and CH1["verdict"] == "chain-complete")
CH2 = XD.chain({"rates": {"index": 1.0, "retrieve": 1.0, "act": 1.0},
                "defense": "provable-policy"})
check("the provable policy breaks the chain at the act step",
      CH2["joint"] == 0.0 and CH2["blocked_at"] == "act"
      and CH2["verdict"] == "blocked")
CH3 = XD.chain({"rates": {"index": 0.9, "retrieve": 0.8, "act": 0.7}})
check("independent stage rates multiply", close(CH3["joint"], 0.504)
      and CH3["verdict"] == "chain-complete")
check("a weak chain is named",
      XD.chain({"rates": {"index": 0.5, "retrieve": 0.5, "act": 0.5}})["verdict"]
      == "chain-weak")
check("an unknown defense is refused",
      XD.chain({"defense": "nope"})["verdict"] == "unknown-defense")

UT = XD.utility({"flows": {"memory_only": 0.9, "long_memory": 0.9,
                           "assistant_responses": 0.85, "untrusted_probe": 0.9,
                           "disable_send": 0.95, "untrusted_send": 0.8,
                           "memory_tools": 0.85}})
check("a preserved profile keeps both means",
      UT["verdict"] == "preserved" and close(UT["am"], 0.878571, 1e-5)
      and close(UT["hm"], 0.876214, 1e-5))
UB = XD.utility({"flows": {"memory_only": 1.0, "untrusted_send": 0.0,
                           "disable_send": 1.0}})
check("one zeroed flow is a capability break",
      UB["verdict"] == "capability-break" and UB["hm"] == 0.0
      and UB["broken"] == ["untrusted_send"] and close(UB["am"], 0.666667, 1e-5))
check("utility needs at least one flow",
      XD.utility({"flows": {}})["verdict"] == "no-flows")

FR = XD.frontier({"rows": [
    {"backend": "context", "defense": "none", "asr": 0.85, "hm": 0.86},
    {"backend": "rag", "defense": "no-untrusted-write", "asr": 0.05, "hm": 0.70},
    {"backend": "rag", "defense": "limit-memory-length", "asr": 0.30, "hm": 0.88},
]})
check("one row is dominated", FR["dominance"] == 1)
check("the frontier is sorted by ASR", [r["asr"] for r in FR["frontier"]]
      == [0.05, 0.30])

PE = XD.persistence({"sweep": [{"n": 0, "asr": 0.85}, {"n": 50, "asr": 0.90},
                               {"n": 100, "asr": 0.85}]})
check("a flat sweep is persistent", PE["verdict"] == "persistent"
      and PE["drop"] == 0.0)
check("high variance is order sensitivity",
      XD.persistence({"sweep": [{"n": 0, "asr": 0.85}, {"n": 100, "asr": 0.85}],
                      "sd": 0.43})["verdict"] == "persistent-order-sensitive")
check("a real decay is named",
      XD.persistence({"sweep": [{"n": 0, "asr": 0.9}, {"n": 100, "asr": 0.6}]})["verdict"]
      == "decays")
check("an empty sweep is refused",
      XD.persistence({"sweep": []})["verdict"] == "no-sweep")

XA = XD.audit_record({"rows": [
    {"backend": "explicit", "defense": "user-prompt-only", "asr": 0.0},
    {"backend": "rag", "defense": "no-untrusted-write", "asr": 0.0}]})
check("audit flags an undefined pair", any("undefined" in f for f in XA["findings"]))
check("audit flags a zero-ASR row without utility",
      any("without a utility figure" in f for f in XA["findings"]))
XAD = XD.advise({"hm": 0.0, "asr": 0.30, "sd": 0.43, "undefined": 2})
check("advice names the broken flow, residual ASR, variance and undefined pairs",
      any("harmonic utility is zero" in f for f in XAD["findings"])
      and any("residual ASR" in f for f in XAD["findings"])
      and any("session ordering" in f for f in XAD["findings"])
      and any("undefined" in f for f in XAD["findings"]))
check("advice without data is honest",
      XD.advise({})["findings"]
      == ["no ASR, utility or variance measurement supplied"])

# ---- verdict ----------------------------------------------------------
passed = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (passed, len(RESULTS)))
sys.exit(0 if passed == len(RESULTS) else 1)
