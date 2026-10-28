#!/usr/bin/env python3
"""Verified-experiment admission: only bound matched runs may be approved."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v700-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "SESSIONS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.harness import cycle
from longrun.memory import rules
from longrun.util import improve

DIGEST = "a" * 64
VARIANT = "c" * 64


def experiment(**overrides):
    data = {"verified": True, "snapshot_digest": DIGEST, "variant_digest": VARIANT,
            "runs": [{"run_id": "reference-1", "role": "reference",
                      "digest": DIGEST, "cleanup_verified": True},
                     {"run_id": "candidate-2", "role": "successor",
                      "digest": VARIANT, "cleanup_verified": True}]}
    data.update(overrides)
    return data


def verified_group(digest=DIGEST):
    return {"digest": digest,
            "reference": {"evidence": {"scope": "matched_container_run",
                                       "snapshot_digest": digest}},
            "reference_run": {"run_id": "reference-1", "digest": digest,
                              "cleanup_verified": True}}


def verified_report(digest=VARIANT):
    """Real shape: the successor runs a hardlinked variant, so its package digest
    differs from the reference package it was derived from."""
    return {"successor": {"digest": digest,
                          "record": {"evidence": {"scope": "matched_container_run",
                                                  "snapshot_digest": digest}},
                          "run": {"run_id": "candidate-2", "digest": digest,
                                  "cleanup_verified": True}},
            "decision": "select 1 candidate(s): observed absence of x",
            "contrast": {"verdict": "improved"}, "workspace": os.path.join(TMP, "ws")}


class Admission(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(dir=TMP)

    def test_unverified_cycle_never_writes_an_inbox_entry(self):
        before = {p["id"] for p in improve.list_proposals()}
        with patch.object(improve, "propose", side_effect=AssertionError("wrote inbox")):
            got = cycle._admit({}, {"successor": {}}, [])
        self.assertFalse(got["ok"])
        self.assertEqual({p["id"] for p in improve.list_proposals()}, before)

    def test_unverified_successor_never_writes_an_inbox_entry(self):
        group = verified_group()
        report = verified_report()
        report["successor"]["run"]["cleanup_verified"] = False
        with patch.object(improve, "propose", side_effect=AssertionError("wrote inbox")):
            got = cycle._admit(group, report, [{"kind": "guardrail", "content": "rule"}])
        self.assertFalse(got["ok"])

    def test_snapshot_mismatch_never_writes_an_inbox_entry(self):
        group = verified_group()
        report = verified_report()
        report["successor"]["run"]["digest"] = "b" * 64
        with patch.object(improve, "propose", side_effect=AssertionError("wrote inbox")):
            got = cycle._admit(group, report, [{"kind": "guardrail", "content": "rule"}])
        self.assertFalse(got["ok"])

    def test_reference_from_another_package_never_writes_an_inbox_entry(self):
        group = verified_group()
        group["reference_run"]["digest"] = "b" * 64
        with patch.object(improve, "propose", side_effect=AssertionError("wrote inbox")):
            got = cycle._admit(group, verified_report(),
                               [{"kind": "guardrail", "content": "rule"}])
        self.assertFalse(got["ok"])

    def test_unchanged_package_is_not_an_experiment(self):
        """A delta that leaves the package digest identical changed nothing."""
        with patch.object(improve, "propose", side_effect=AssertionError("wrote inbox")):
            got = cycle._admit(verified_group(), verified_report(digest=DIGEST),
                               [{"kind": "guardrail", "content": "rule"}])
        self.assertFalse(got["ok"])

    def test_skill_only_experiment_has_nothing_approvable(self):
        with patch.object(improve, "propose", side_effect=AssertionError("wrote inbox")):
            got = cycle._admit(verified_group(), verified_report(),
                               [{"kind": "skill", "content": "skill text"}])
        self.assertFalse(got["ok"])

    def test_verified_experiment_admits_one_pending_proposal_with_evidence(self):
        captured = {}

        def capture(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return {"id": "1-project", "status": "pending"}

        with patch.object(improve, "propose", side_effect=capture):
            got = cycle._admit(verified_group(), verified_report(),
                               [{"kind": "guardrail", "content": "Read first."}])
        self.assertTrue(got["ok"], got)
        self.assertEqual(captured["args"][0], "project")
        exp = captured["kwargs"]["experiment"]
        self.assertTrue(exp["verified"])
        self.assertEqual(exp["snapshot_digest"], DIGEST)
        self.assertEqual(exp["variant_digest"], VARIANT)
        self.assertEqual([r["run_id"] for r in exp["runs"]],
                         ["reference-1", "candidate-2"])
        self.assertEqual([r["digest"] for r in exp["runs"]], [DIGEST, VARIANT])

    def test_approval_refuses_harness_without_bound_evidence(self):
        rec = improve.propose("project", "unprobed", ws=self.ws, origin="harness")
        decision = improve.decide(rec["id"], "approve")
        self.assertFalse(decision["ok"])
        self.assertEqual(improve.get_proposal(rec["id"])["status"], "pending")
        self.assertNotIn("unprobed", rules.collect(ws=self.ws)["project"]["text"])

    def test_approval_refuses_incomplete_run_evidence(self):
        bad = experiment(runs=[{"run_id": "same", "cleanup_verified": True},
                               {"run_id": "same", "cleanup_verified": True}])
        rec = improve.propose("project", "same-run", ws=self.ws, origin="harness",
                              experiment=bad)
        self.assertFalse(improve.decide(rec["id"], "approve")["ok"])

    def test_approval_refuses_runs_of_one_unchanged_package(self):
        same = experiment(runs=[{"run_id": "a", "digest": DIGEST, "cleanup_verified": True},
                                {"run_id": "b", "digest": DIGEST, "cleanup_verified": True}])
        rec = improve.propose("project", "same-package", ws=self.ws, origin="harness",
                              experiment=same)
        self.assertFalse(improve.decide(rec["id"], "approve")["ok"])

    def test_approval_refuses_an_unbound_snapshot_digest(self):
        loose = experiment(snapshot_digest="d" * 64)
        rec = improve.propose("project", "loose", ws=self.ws, origin="harness",
                              experiment=loose)
        self.assertFalse(improve.decide(rec["id"], "approve")["ok"])

    def test_approval_applies_a_fully_verified_experiment(self):
        rec = improve.propose("project", "inventory inputs first", ws=self.ws,
                              origin="harness", experiment=experiment())
        decision = improve.decide(rec["id"], "approve")
        self.assertTrue(decision["ok"], decision)
        self.assertEqual(decision["status"], "approved")
        self.assertIn("inventory inputs first", rules.collect(ws=self.ws)["project"]["text"])

    def test_denial_still_works_without_evidence(self):
        rec = improve.propose("project", "unprobed", ws=self.ws, origin="harness")
        self.assertTrue(improve.decide(rec["id"], "deny")["ok"])


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
