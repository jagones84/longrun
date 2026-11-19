#!/usr/bin/env python3
"""v1213 — transcript privacy, privacy memory, privacy audit (round 144).

Sources:
  * arXiv:2607.17147 "SlotGuard" — typed suffix-aware slots, format-preserving
    synthetic secrets, the session entity graph, guarded rebinding, leakage and
    compatibility, the hot path.
  * arXiv:2605.09530 "MemPrivacy" — the four-level taxonomy and its handling
    policies, the threshold, typed sanitize/restore, extraction F1, utility loss,
    leakage and the audit guards.
  * arXiv:2610.06454 "AgentPrivArena" — the five-attribute flow, three
    dispositions, three criteria, exposure/extraction/disposition, the spread
    collapse, stated vs enforced, and the auditor swap.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1213_transcript_memory_audit_privacy.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1213-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness.checks import transcript_privacy as TP  # noqa: E402
from longrun.harness.checks import privacy_memory as PM  # noqa: E402
from longrun.harness.checks import privacy_audit as PA  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


def kinds(out):
    return [f["kind"] for f in (out.get("findings") or [])]


# ---- 1. transcript privacy (SlotGuard) ----------------------------------
sp = TP.suffix("/Users/alice/acme/legal/layoff_bob.pdf",
               ["/Users/alice/acme"])
check("the longest root becomes a typed slot", sp["root_slot"] == "[REPO_ROOT_1]")
check("the sensitive middle is suppressed",
      sp["rewritten"] == "[REPO_ROOT_1]/legal/[SENSITIVE_DOC_1].pdf", sp)
check("the extension is preserved", sp["extension"] == "pdf")
check("a sensitive stem is marked", sp["sensitive"] is True)
plain = TP.suffix("/Users/alice/acme/src/main.py", ["/Users/alice/acme"])
check("a benign file keeps a path-shaped slot",
      plain["rewritten"] == "[REPO_ROOT_1]/src/[FILE_1].py", plain)
check("an unknown root is refused",
      TP.suffix("/etc/passwd", ["/Users/alice/acme"])["verdict"] == "root-unknown")
check("a root with no remainder is named",
      TP.suffix("/Users/alice/acme", ["/Users/alice/acme"])["verdict"] == "root-only")
check("an empty path is refused", TP.suffix("")["verdict"] == "empty-path")

check("a typed email slot carries its index",
      TP.slot("a@b.com", "email", 2)["handle"] == "[EMAIL_2]")
check("an unknown slot kind is refused",
      TP.slot("x", "vibes")["verdict"] == "unknown-kind")

b1 = TP.bind("a@b.com", "email", "session-1")
b2 = TP.bind("a@b.com", "email", "session-1")
b3 = TP.bind("a@b.com", "email", "session-2")
check("the same value in one session gets the same handle", b1["handle"] == b2["handle"])
check("a fresh session key changes the handle", b1["handle"] != b3["handle"])
check("an empty value is refused", TP.bind("", "email", "s")["verdict"] == "empty-value")
check("a missing session key is refused",
      TP.bind("a", "email", "")["verdict"] == "no-session-key")

TABLE = {"[EMAIL_1]": {"value": "a@b.com", "kind": "email"},
         "[REPO_ROOT_1]": {"value": "/Users/alice/acme", "kind": "repo_root"},
         "[X]": {"value": "/Users/alice/acme/../etc/passwd", "kind": "repo_root"},
         "[Y]": {"value": "a;rm -rf /", "kind": "host"},
         "[Z]": {"value": "x", "kind": "mail"}}
check("a known handle is rebound",
      TP.rebind("[EMAIL_1]", TABLE)["value"] == "a@b.com")
check("an unknown handle is rejected",
      TP.rebind("[NOPE]", TABLE)["reason"] == "unknown-handle")
check("traversal is rejected",
      TP.rebind("[X]", TABLE)["reason"] == "traversal")
check("shell metacharacters are rejected",
      TP.rebind("[Y]", TABLE)["reason"] == "metacharacters")
check("a wrong type is rejected",
      TP.rebind("[Z]", TABLE)["reason"] == "type-mismatch")
check("a handle outside the scope is rejected",
      TP.rebind("[REPO_ROOT_1]", TABLE,
                scope="/Users/alice/other")["reason"] == "out-of-scope")
check("a scoped handle inside the scope is rebound",
      TP.rebind("[REPO_ROOT_1]", TABLE,
                scope="/Users/alice")["verdict"] == "rebound")

g = TP.graph([{"raw": "a@b.com", "variant": "a@b.com"},
              {"raw": "a@b.com", "variant": "mailto:a@b.com"},
              {"raw": "a@b.com", "variant": "the sender"}])
check("the graph classifies exact and embedded links",
      [r["class"] for r in g["rows"]] == ["exact", "embedded", "reference"], g)
check("a graph with an embedded link covers",
      g["verdict"] == "graph-covers")
check("an exact-only graph is named",
      TP.graph([{"raw": "x", "variant": "x"}])["verdict"] == "graph-exact-only")

check("no leakage is named", TP.leak([])["verdict"] == "leak-free")
check("a category label alone is named",
      TP.leak([{"category_label": True}])["verdict"] == "categorical-only")
check("residual literal leakage is named",
      TP.leak([{"literal_chars": 3}])["verdict"] == "residual-leakage")
check("reconstructible exposure is counted",
      TP.leak([{"reconstructive": True}])["reconstructive"] == 1)

comp = TP.compatibility([{"method": "raw", "success": 100.0, "raw": 100.0},
                         {"method": "generic", "success": 2.5, "raw": 100.0,
                          "invalid_handles": 0.833},
                         {"method": "slots", "success": 89.5, "raw": 100.0,
                          "invalid_handles": 0.0}])
check("the best method preserves structure",
      comp["verdict"] == "structure-preserved", comp)
check("the best method is the typed one", comp["best"]["method"] == "slots")
check("a collapsing method is named",
      TP.compatibility([{"method": "generic", "success": 2.5, "raw": 100.0,
                         "invalid_handles": 0.833}])["verdict"] == "structure-lost")

oh = TP.overhead([{"micros": 14.424}, {"micros": 96.803}, {"micros": 20.0}])
check("a microsecond rewrite is hot-path-ok", oh["verdict"] == "hot-path-ok", oh)
check("the median is reported", oh["median_us"] == 20.0)
check("a slow rewrite is named",
      TP.overhead([{"micros": 5000}])["verdict"] == "hot-path-slow")

check("a correct boundary passes", kinds(TP.audit(
    {"suffix_preserved": True, "seg_for_split": True})) == ["boundary-conditions-met"])
check("generic replacement is named",
      "generic-replacement" in kinds(TP.audit({"generic_replacement": True})))
check("a lost suffix is named",
      "suffix-lost" in kinds(TP.audit({"suffix_preserved": False})))
check("unguarded split exposure is named",
      "split-exposure-unguarded" in kinds(TP.audit({"seg_for_split": False})))
check("a synchronous detector is named",
      "semantic-detector-on-hot-path" in kinds(
          TP.audit({"semantic_detector_sync": True})))
check("an overclaimed fail-closed is named",
      "fail-closed-overclaimed" in kinds(TP.audit({"fail_closed_claimed": True})))
check("advise names every missing practice", len(TP.advise({})["findings"]) == 6)
check("a fully declared profile has no finding", TP.advise(
    {k: True for k in ("interposes_on_tool_output", "keeps_typed_structure",
                       "preserves_suffix", "uses_format_preserving_secrets",
                       "tracks_cross_turn_references",
                       "rebinds_locally_with_scope")})["findings"] == [])

# ---- 2. privacy memory (MemPrivacy) -------------------------------------
check("four privacy levels exist", len(PM.levels()) == 4)
check("PL4 is prohibited in long-term memory",
      PM.classify("PL4")["long_term_memory"] == "prohibited")
check("PL2 is disallowed by default",
      PM.classify("PL2")["long_term_memory"] == "disallowed-by-default")
check("an unknown level is named",
      PM.classify("PL9")["verdict"] == "unknown-level")

SPANS = [{"text": "I like spicy food", "level": "PL1", "type": "Preference"},
         {"text": "a@b.com", "level": "PL2", "type": "Email"},
         {"text": "89757", "level": "PL4", "type": "Code"}]
san = PM.sanitize(SPANS, "PL2")
check("spans at or above the threshold are replaced",
      [r["handle"] for r in san["replaced"]] == ["<Email_1>", "<Code_1>"], san)
check("a span below the threshold is kept",
      [k["text"] for k in san["kept"]] == ["I like spicy food"])
check("the mapping keeps the raw value locally",
      san["mapping"]["<Email_1>"]["value"] == "a@b.com")
check("the sanitize verdict is named", san["verdict"] == "typed-masked")
only4 = PM.sanitize(SPANS, "PL4")
check("a PL4-only policy masks one span",
      [r["handle"] for r in only4["replaced"]] == ["<Code_1>"])
check("a policy that protects nothing is named",
      PM.sanitize([SPANS[0]], "PL2")["verdict"] == "nothing-protected")
check("an unknown threshold is refused",
      PM.sanitize(SPANS, "PL9")["verdict"] == "unknown-threshold")

res = PM.restore("Hello <Email_1>, your code is <Code_1> and <Other_9>.",
                 {"<Email_1>": {"value": "a@b.com"},
                  "<Code_1>": {"value": "89757"}})
check("known handles are restored",
      "a@b.com" in res["text"] and "89757" in res["text"], res)
check("an unknown handle is reported, not guessed",
      res["unresolved"] == ["<Other_9>"], res)
check("the restore verdict names the unresolved handle",
      res["verdict"] == "unresolved-handles")
check("a fully resolved text passes",
      PM.restore("<Email_1>", {"<Email_1>": {"value": "x"}})["verdict"] == "restored")

ex = PM.extraction([{"text_ok": True, "level_ok": True, "type_ok": True}] * 10)
check("a perfect extractor has F1 1.0", ex["f1"] == 1.0)
check("a strong extractor is named", ex["verdict"] == "extraction-strong")
half = PM.extraction([{"text_ok": True, "level_ok": False, "type_ok": False}] * 10)
check("a one-field extractor is weak", half["verdict"] == "extraction-weak")
check("the weak F1 is one third", abs(half["f1"] - 1 / 3.0) < 1e-9)

ut = PM.utility([{"method": "memprivacy", "none": 0.6537, "protected": 0.6407},
                 {"method": "irreversible", "none": 0.6537, "protected": 0.3870}])
check("typed placeholders stay within tolerance",
      ut["verdict"] == "within-tolerance", ut)
check("irreversible masking is a collapse", ut["masking_collapse"] is True)
check("the best method is typed", ut["best"]["method"] == "memprivacy")
check("the drop is measured", abs(ut["best"]["drop"] - 0.013) < 1e-9)

lk = PM.leakage([{"exposed_values": 0, "protected_values": 10}] * 3)
check("no exposure is named", lk["verdict"] == "zero-exposure")
check("a residual exposure is counted",
      PM.leakage([{"exposed_values": 2, "protected_values": 5}])
      ["exposed_sessions"] == 1)

th = PM.threshold([{"threshold": "PL2", "loss": 0.016},
                   {"threshold": "PL3", "loss": 0.0107},
                   {"threshold": "PL4", "loss": 0.0018}], tolerance=0.016)
check("the loosest viable threshold is chosen", th["chosen"] == "PL2", th)
th2 = PM.threshold([{"threshold": "PL2", "loss": 0.03},
                    {"threshold": "PL3", "loss": 0.0107},
                    {"threshold": "PL4", "loss": 0.0018}], tolerance=0.016)
check("an infeasible loosest level is skipped", th2["chosen"] == "PL3")
check("no viable threshold is named",
      PM.threshold([{"threshold": "PL2", "loss": 0.9}])["verdict"]
      == "no-viable-threshold")

check("a correct memory scheme passes", kinds(PM.audit(
    {"local_mapping_db": True})) == ["memory-privacy-conditions-met"])
check("a missing local mapping is named",
      "no-local-mapping" in kinds(PM.audit({})))
check("an untyped placeholder is named",
      "untyped-placeholder" in kinds(PM.audit(
          {"local_mapping_db": True, "untyped_placeholder": True})))
check("irreversible masking is named",
      "irreversible-masking" in kinds(PM.audit(
          {"local_mapping_db": True, "irreversible": True})))
check("a retained PL4 value is named",
      "pl4-retained" in kinds(PM.audit({"local_mapping_db": True,
                                        "pl4_retained": True})))
check("a general extractor is named",
      "general-extractor" in kinds(PM.audit(
          {"local_mapping_db": True, "general_extractor_for_privacy": True})))
check("advise names every missing practice", len(PM.advise({})["findings"]) == 6)
check("a fully declared profile has no finding", PM.advise(
    {k: True for k in ("extracts_before_cloud", "keeps_type_information",
                       "restores_locally", "persists_the_mapping",
                       "offers_a_threshold", "never_stores_credentials")})
    ["findings"] == [])

# ---- 3. privacy audit (AgentPrivArena) ----------------------------------
fl = PA.flow({"sender": "a", "recipient": "b", "subject": "c",
              "type": "health", "principle": "care"})
check("a complete flow passes", fl["verdict"] == "flow-complete")
check("a missing attribute is named",
      PA.flow({"sender": "a"})["missing"] == ["recipient", "subject", "type",
                                              "principle"])

check("a credential is blocked under PII",
      PA.disposition({"criterion": "pii", "type": "api_key"})["decision"]
      == "block")
check("PII about another person is abstracted",
      PA.disposition({"criterion": "pii", "type": "email",
                      "subject_is_principal": False})["decision"] == "abstract")
check("a principal's own name passes PII",
      PA.disposition({"criterion": "pii", "type": "name",
                      "subject_is_principal": True})["decision"] == "pass")
check("an unnecessary detail is blocked under minimization",
      PA.disposition({"criterion": "minimization", "necessary": False})
      ["decision"] == "block")
check("a necessary but inappropriate detail is abstracted",
      PA.disposition({"criterion": "minimization", "necessary": True,
                      "appropriate": False})["decision"] == "abstract")
check("a necessary detail passes minimization",
      PA.disposition({"criterion": "minimization", "necessary": True})
      ["decision"] == "pass")
check("an inappropriate audience is blocked under CI",
      PA.disposition({"criterion": "ci", "appropriate": False})["decision"]
      == "block")
check("a relational fact in a public channel is abstracted",
      PA.disposition({"criterion": "ci", "relationship": True,
                      "channel_public": True,
                      "subject_is_principal": False})["decision"] == "abstract")
check("an appropriate flow passes CI",
      PA.disposition({"criterion": "ci", "appropriate": True})["decision"]
      == "pass")
check("an unknown criterion is refused",
      PA.disposition({"criterion": "vibes"})["verdict"] == "unknown-criterion")

inv = PA.inventory([{"reference_items": 100, "exposed_items": 79,
                     "extracted_flows": 56,
                     "dispositions": {"pass": 20, "abstract": 30, "block": 6}}])
check("the exposure rate is over reference items",
      abs(inv["exposure_rate"] - 0.79) < 1e-9)
check("the extraction recall is over exposed items",
      abs(inv["extraction_recall"] - 56 / 79.0) < 1e-9)
check("a recall below 0.8 bounds the audit",
      inv["verdict"] == "extraction-bounds-the-audit", inv)
check("the disposition mix is reported",
      abs(inv["dispositions"]["abstract"] - 30 / 56.0) < 1e-9)

cmp_out = PA.compare([
    {"condition": "c0", "leak": 0.334}, {"condition": "c0", "leak": 0.588},
    {"condition": "c4", "leak": 0.173}, {"condition": "c4", "leak": 0.198}])
check("enforcement collapses the spread",
      cmp_out["verdict"] == "enforcement-collapses-spread", cmp_out)
check("the reduction against no mitigation is measured",
      abs(cmp_out["reduction"] - (0.461 - 0.1855)) < 1e-9)
check("a spread that persists is named",
      PA.compare([{"condition": "c0", "leak": 0.3}, {"condition": "c0", "leak": 0.6},
                  {"condition": "c4", "leak": 0.2}, {"condition": "c4", "leak": 0.5}])
      ["verdict"] == "spread-persists")

cr = PA.criteria([{"criterion": "pii", "prompt": 0.407, "audit": 0.217}])
check("a rule enforced beats the same rule stated",
      cr["verdict"] == "mechanism-not-wording", cr)
check("the gain is measured", abs(cr["rows"][0]["gain"] - 0.19) < 1e-9)
check("a small gain is named",
      PA.criteria([{"criterion": "pii", "prompt": 0.40, "audit": 0.38}])
      ["verdict"] == "wording-helps")

au = PA.auditor({"auditor_change": -0.062, "auditor_p": 0.001,
                 "executor_change": 0.018, "executor_p": 0.4})
check("the auditor carries the effect", au["verdict"] == "auditor-carries", au)
check("a significant executor swap is named",
      PA.auditor({"auditor_change": 0.01, "auditor_p": 0.5,
                  "executor_change": -0.2, "executor_p": 0.01})["verdict"]
      == "executor-carries")
check("two significant swaps are named",
      PA.auditor({"auditor_change": -0.1, "auditor_p": 0.01,
                  "executor_change": -0.1, "executor_p": 0.01})["verdict"]
      == "both-carry")
check("no significant swap is named",
      PA.auditor({"auditor_change": 0.01, "auditor_p": 0.5,
                  "executor_change": 0.01, "executor_p": 0.5})["verdict"]
      == "neither-carries")

check("a correct evaluation passes", kinds(PA.audit({})) == ["audit-conditions-met"])
check("outcome-only evaluation is named",
      "outcome-only" in kinds(PA.audit({"outcome_only": True})))
check("a static trajectory is named",
      "static-trajectory" in kinds(PA.audit({"static_trajectory": True})))
check("a single judge is named",
      "single-judge" in kinds(PA.audit({"single_judge": True})))
check("fail-open as a control is named",
      "fail-open-treated-as-control" in kinds(
          PA.audit({"fail_open_as_control": True})))
check("a missing flow schema is named",
      "no-flow-schema" in kinds(PA.audit({"no_flow_schema": True})))
check("advise names every missing practice", len(PA.advise({})["findings"]) == 6)
check("a fully declared profile has no finding", PA.advise(
    {k: True for k in ("audits_the_trajectory", "represents_flows",
                       "enforces_at_the_write", "keeps_the_criterion_pluggable",
                       "measures_extraction_recall", "reports_helpfulness")})
    ["findings"] == [])

# ---- result --------------------------------------------------------------
ok = sum(1 for r in RESULTS if r)
print("\n%d/%d checks passed" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
