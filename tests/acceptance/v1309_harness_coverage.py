#!/usr/bin/env python3
"""v1309 — ETCSLV harness coverage: the survey's matrix as a rule, and Longrun's own rating.

Source (read in full, 2026-11-26): the survey *Agent Harness for Large Language Model
Agents* (`Awesome-Agent-Harness`, v4, CC-BY-4.0, DOI 10.20944/preprints202604.0428.v3).
It models a harness as H=(E,T,C,S,L,V) and rates 34 systems on one evidence-coded
matrix (`docs/systems.json`). Longrun used it once, by hand, as a reading grid
(`.agent/docs/plans/reference/longrun-vs-harness-codebases.md` §3); this pins the
two things that make that relationship live instead of drifting:

  A  the pure checker `harness/checks/harness_coverage.py`: the six components, the
     evidence-rule verdict, and the vocabulary — the survey's RULES as a deterministic
     audit (a Full with no source is a finding, not prose);
  B  the live self-census `harness/harness_coverage.py`: a declarative owner map
     probed read-only, fail-open to Unverified, plus the join to the 34-system matrix;
  C  the bundled matrix (`harness/harness_matrix.json`): 34 systems, one order, and
     it satisfies the checker's own rules (audit is clean);
  D  the wires: the `harnesscov` forge group, `GET /api/harness/coverage`, the panel
     line, and the `benchmarks/protocol.py:COMPONENTS` tag;
  E  the two new modules import no app layer, and the checker imports no app layer
     (the v1275 contract, asserted here for the pair).

Deterministic: a fake probe, in-test fixtures. No model, no network, no server.
Run:  python3 tests/acceptance/v1309_harness_coverage.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
for _p in (SRC, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from longrun.harness import harness_coverage as hc              # noqa: E402
from longrun.harness.checks import harness_coverage as chk      # noqa: E402

FAILED = []
CHECKS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" — %s" % (detail,)) if detail else ""))
    CHECKS.append(name)
    if not ok:
        FAILED.append(name)


def _cell(cid, rating, source="https://example.invalid/x", etype="first-party source/docs",
          conf="high"):
    return {"id": cid, "rating": rating, "source": source, "version": "v1",
            "evidenceType": etype, "confidence": conf}


def _good_system(name="Sys"):
    return {"name": name, "category": "anchor", "accessDate": "2026-10-13",
            "components": [_cell(c, "Full") for c in chk.COMPONENT_ORDER]}


# ── A · the pure checker: components, rate, matrix ─────────────────────────
check("A1 components() is the six, in order",
      [c["id"] for c in chk.components()] == ["E", "T", "C", "S", "L", "V"])
check("A2 every component carries a name and a what",
      all(c["name"] and c["what"] for c in chk.components()))
check("A3 FORMAT is the survey's coverage format",
      chk.FORMAT == "longrun-harness-coverage/1" and hc.FORMAT == chk.FORMAT)
check("A4 the vocabulary is closed and ordered",
      chk.VOCAB == ("Full", "Partial", "Absent", "Unverified"))

_r = chk.rate(_good_system())
check("A5 rate() of a full system is complete, no missing",
      _r["verdict"] == "complete" and _r["missing"] == [] and _r["coverage"]["Full"] == 6)
_partial = _good_system()
_partial["components"] = _partial["components"][:2]           # only E, T present
_rp = chk.rate(_partial)
check("A6 a system missing components names them and rates them Unverified by absence",
      _rp["missing"] == ["C", "S", "L", "V"] and _rp["coverage"]["Unverified"] == 4)
check("A7 rate() ignores a cell whose id is not one of the six",
      chk.rate({"name": "x", "components": [_cell("Z", "Full")]})["missing"] == list("ETCSLV"))

_m = chk.matrix({"cutoff": "2026-10-12", "componentOrder": list(chk.COMPONENT_ORDER),
                 "systems": [_good_system("A"), _partial]})
check("A8 matrix() summarises ratings per component",
      _m["summary"]["E"]["Full"] == 2 and _m["summary"]["V"]["Unverified"] == 1)
check("A9 matrix() lists a gap per non-Full cell",
      _m["verdict"] == "gaps" and len(_m["gaps"]) == 4
      and all(g["component"] in ("C", "S", "L", "V") for g in _m["gaps"]))

# ── A · the evidence rules as findings ──────────────────────────────────────
_bad = {"cutoff": "2020-01-01", "systems": [
    {"name": "Dup", "components": [_cell("E", "Full"), {"id": "T", "rating": "Full"}]},
    {"name": "Dup", "components": [{"id": "Z", "rating": "Full", "evidenceType": "x"},
                                   _cell("C", "Great"),
                                   {"id": "S", "rating": "Absent", "evidenceType": "x"},
                                   _cell("V", "Unverified", conf="high")]},
]}
_aud = chk.audit(_bad)
kinds = _aud["counts"]
check("A10 a Full with no source is a finding", kinds.get("full-without-source") == 1, kinds)
check("A11 an unknown component id is a finding", kinds.get("unknown-component") == 1)
check("A12 a rating outside the vocabulary is a finding",
      kinds.get("rating-not-in-vocabulary") == 1)
check("A13 an Absent with no source is a finding", kinds.get("absent-without-proof") == 1)
check("A14 Unverified with high confidence is a finding",
      kinds.get("unverified-with-high-confidence") == 1)
check("A15 a repeated system name is a finding", kinds.get("duplicate-system") == 1)
check("A16 verdict is defects and every finding is located",
      _aud["verdict"] == "defects" and _aud["format"] == chk.FORMAT
      and all(f.get("kind") and f.get("system") is not None for f in _aud["findings"]))
check("A17 a clean matrix audits clean",
      chk.audit({"systems": [_good_system()]})["verdict"] == "clean")
check("A18 stale-cutoff fires only with as_of, and honours the limit",
      chk.audit({"cutoff": "2026-10-12", "systems": []}, as_of="2026-11-26")["verdict"] == "clean"
      and chk.audit({"cutoff": "2020-01-01", "systems": []}, as_of="2026-11-26")
      ["counts"].get("stale-cutoff") == 1)
check("A19 an unparseable cutoff is not a stale-cutoff finding",
      chk.audit({"cutoff": "n/a", "systems": []}, as_of="2026-11-26")["verdict"] == "clean")

# ── B · the live census (a fake probe: deterministic) ───────────────────────
_all_yes = hc.build(probe=lambda m: True)
check("B1 all owners present → Full, verdict full",
      _all_yes["verdict"] == "full" and _all_yes["summary"]["Full"] == 6)
check("B2 every component names its evidence modules",
      all(c["evidence"] and all(e["module"] and "what" in e for e in c["evidence"])
          for c in _all_yes["components"]))
_mixed = hc.build(probe=lambda m: m.endswith("agent.agent"))
check("B3 a partly-present component is Partial, a fully-absent one is Absent",
      _mixed["components"][0]["rating"] == "Partial"
      and any(c["rating"] == "Absent" for c in _mixed["components"]))
check("B4 a probe that returns None is Unverified, never a crash",
      hc.build(probe=lambda m: None)["summary"]["Unverified"] == 6)
_live = hc.census()
check("B5 census() reads the live tree: 6 components, each rated",
      len(_live["components"]) == 6
      and all(c["rating"] in chk.VOCAB for c in _live["components"]))
check("B6 card() is non-empty and bounded",
      0 < len(hc.card(_live)) <= hc.MAX_TEXT and "ETCSLV" in hc.card(_live))

# ── C · the bundled matrix ──────────────────────────────────────────────────
_mat = hc.load_matrix()
check("C1 the bundled matrix is present and well-formed",
      _mat.get("schema") == "longrun-harness-matrix/1" and len(_mat.get("systems") or []) == 34)
check("C2 the matrix order equals the checker's and the census's",
      _mat.get("componentOrder") == list(chk.COMPONENT_ORDER) == list(hc.COMPONENT_ORDER))
check("C3 its licence and citation are recorded (CC-BY-4.0)",
      "CC-BY-4.0" in str(_mat.get("license")) and "preprints202604.0428" in str(_mat.get("doi")))
check("C4 the bundled matrix satisfies its own evidence rules (audit clean)",
      chk.audit(_mat)["verdict"] == "clean", str(chk.audit(_mat)["counts"]))
_cmp = hc.compare(_live, _mat)
check("C5 compare() joins the live rating to the 34 systems per component",
      _cmp["systems"] == 34 and [r["id"] for r in _cmp["rows"]] == list(chk.COMPONENT_ORDER))
check("C6 compare() computes the peer Full share",
      all(isinstance(r["peers_full_share"], float) and 0.0 <= r["peers_full_share"] <= 1.0
          for r in _cmp["rows"]))
_fix = {"componentOrder": ["E", "V"], "systems": [
    {"name": "a", "components": [{"id": "E", "rating": "Full"}, {"id": "V", "rating": "Partial"}]},
    {"name": "b", "components": [{"id": "E", "rating": "Full"}, {"id": "V", "rating": "Full"}]},
]}
_cf = hc.compare(_live, _fix)
rowE = next(r for r in _cf["rows"] if r["id"] == "E")
rowV = next(r for r in _cf["rows"] if r["id"] == "V")
check("C7 compare() counts only the Full cells of the fixture",
      rowE["peers_full"] == 2 and rowV["peers_full"] == 1 and rowV["peers_full_share"] == 0.5)

# ── D · the wires (source-level: the caller exists) ─────────────────────────
def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


forge = read("src", "longrun", "core", "forge.py")
httpapi = read("src", "longrun", "core", "httpapi.py")
webui = read("webui", "index.html")
proto = read("benchmarks", "protocol.py")
check("D1 forge.py registers the harnesscov group", '"harnesscov"' in forge)
check("D2 cmd_harnesscov exists and its docstring starts with a round (listed by `harness`)",
      "def cmd_harnesscov(" in forge
      and "Round 171" in forge[forge.find("def cmd_harnesscov("):][:200])
check("D3 the HTTP server serves /api/harness/coverage",
      '"/api/harness/coverage"' in httpapi and "harness_coverage as _cov" in httpapi)
check("D4 the panel reads /api/harness/coverage (backend state, not a second truth)",
      "/api/harness/coverage" in webui)
check("D5 benchmarks tag suites with the six components",
      "COMPONENTS" in proto and {'"humaneval"', '"lhb"', '"swebench"'} <= set(
          '"%s"' % k for k in __import__("benchmarks.protocol", fromlist=["COMPONENTS"]).COMPONENTS))

import benchmarks.protocol as _proto                                    # noqa: E402
_bad_tags = {k: v for k, v in _proto.COMPONENTS.items()
             if not v or any(c not in _proto.COMPONENT_ORDER for c in v)}
check("D6 every suite tag uses only E,T,C,S,L,V",
      not _bad_tags and _proto.COMPONENT_ORDER == chk.COMPONENT_ORDER, str(_bad_tags))

# ── E · the two new modules import no app layer ─────────────────────────────
for name in (("harness", "harness_coverage.py"), ("harness", "checks", "harness_coverage.py")):
    body = read("src", "longrun", *name)
    check("E · %s imports no app package" % name[-1],
          "from longrun.agent" not in body and "from longrun.core" not in body
          and "from longrun.tools" not in body)

print("\n%d/%d checks passed" % (len(CHECKS) - len(FAILED), len(CHECKS)))
if FAILED:
    print("FAILED: " + ", ".join(FAILED))
    sys.exit(1)
