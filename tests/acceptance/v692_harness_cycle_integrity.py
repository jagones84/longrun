#!/usr/bin/env python3
"""Independent probes, successor verification and conservative attribution."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v692-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "HARNESS_DIR", "SESSIONS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.harness import cycle, probe, compose, contrast
from longrun.util import improve


class CycleIntegrity(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.mkdtemp(dir=TMP)
        with open(os.path.join(self.workspace, "input.txt"), "w") as f:
            f.write("input")
        self.base = {"run_id": "base", "workspace": self.workspace, "goal": "Read inputs",
                     "model": "m", "harness": {}, "budget": {},
                     "steps": [{"tool": "fs.read", "ok": False, "error": "missing input"}],
                     "deliverables": [], "files_touched": []}
        self.candidates = [{"kind": "guardrail", "name": "a", "content": "Inventory inputs."},
                           {"kind": "skill", "name": "b", "content": "Read inputs first."}]
        self.config = dict(probe.DEFAULTS, enabled=True, max_candidates=2)

    def editor(self, _messages):
        return json.dumps({"candidates": self.candidates}), "", "m"

    def test_production_cycle_refuses_before_spending_on_editors(self):
        with patch.object(cycle.record_mod, "build", return_value=self.base):
            result = cycle.run("session", dry_run=False, c=self.config,
                               call=lambda _: self.fail("editor spend"))
        self.assertEqual(result["status"], "refused")
        self.assertIn("whole-run", result["reason"])

    def test_editor_failure_stops_round_and_replaces_last_report(self):
        calls = []
        def fail(_messages):
            calls.append("editor")
            raise TimeoutError("private-provider-token")
        before = improve.list_proposals()
        with patch.object(cycle.record_mod, "build", return_value=self.base):
            result = cycle.run("session", dry_run=False, c=self.config, call=fail,
                               runner=lambda *_: self.fail("probe after editor failure"))
        self.assertEqual(calls, ["editor"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("invariant", result["reason"])
        self.assertIn("TimeoutError", result["reason"])
        self.assertNotIn("private-provider-token", json.dumps(result))
        self.assertEqual(cycle.last(), result)
        self.assertIsNone(result["probe"])
        self.assertEqual(improve.list_proposals(), before)

    def test_candidates_run_independently_and_successor_must_pass(self):
        calls = []
        def run(plan, _timeout):
            calls.append(sorted(plan["staged"]))
            steps = [{"tool": "fs.read", "ok": True}]
            if len(plan["staged"]) > 1:
                steps.append({"tool": "fs.read", "ok": False, "error": "new permission failure"})
            return {"record": dict(self.base, run_id="trial-%d" % len(calls), steps=steps)}, ""
        before = improve.list_proposals()
        with patch.object(cycle.record_mod, "build", return_value=self.base):
            result = cycle.run("session", dry_run=False, c=self.config,
                               call=self.editor, runner=run)
        self.assertEqual(calls, [["a"], ["b"], ["a", "b"]])
        self.assertIsNone(result["adopted"])
        self.assertEqual(result["kept"], [])
        self.assertEqual(improve.list_proposals(), before)

    def test_single_rollout_does_not_establish_transferable_library_lesson(self):
        calls = []
        def run(plan, _timeout):
            calls.append(sorted(plan["staged"]))
            return {"record": dict(self.base, run_id="trial-%d" % len(calls),
                                   steps=[{"tool": "fs.read", "ok": True}])}, ""
        with patch.object(cycle.record_mod, "build", return_value=self.base):
            result = cycle.run("session", dry_run=False, c=self.config,
                               call=self.editor, runner=run)
        self.assertIsNone(result["adopted"])
        self.assertEqual(result["reflection"]["status"], "NO_ENTRY")
        self.assertTrue(all(row["attribution"] == "confounded"
                            for row in result["reflection"]["edits"]))
        self.assertEqual(len(result["trials"]), 2)

    def test_direct_adoption_cannot_bypass_missing_reflection_evidence(self):
        good = contrast.diff(self.base, dict(self.base, steps=[{"tool": "fs.read", "ok": True}]))
        staged = probe.stage("skill", "b", self.candidates[1]["content"], tempfile.mkdtemp(dir=TMP))
        row = compose.adopt("test", self.base["goal"], "A claim without controls", good,
                            [self.candidates[1]], {"b": staged["path"]})
        self.assertIsNone(row)

    def test_selection_text_does_not_claim_adoption_or_causal_removal(self):
        observed = contrast.diff(self.base, dict(self.base, steps=[{"tool": "fs.read", "ok": True}]))
        decision = compose.select(observed, [self.candidates[0]])["decision"]
        self.assertIn("select", decision)
        self.assertIn("observed", decision)
        self.assertNotIn("adopt ", decision)
        self.assertNotIn("removed ", decision)


if __name__ == "__main__":
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(CycleIntegrity)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0 if result.wasSuccessful() else 1)
