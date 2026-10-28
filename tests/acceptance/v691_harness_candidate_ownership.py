#!/usr/bin/env python3
"""Candidates must be ephemeral until evidence selection and human approval."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v691-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "HARNESS_DIR", "SESSIONS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.harness import editors, probe, runner
from longrun.util import improve


class CandidateOwnership(unittest.TestCase):
    def setUp(self):
        self.base = {"workspace": TMP, "goal": "Inventory inputs", "model": "m",
                     "steps": [{"tool": "fs.read", "ok": False, "error": "missing"}]}
        self.skill = {"kind": "skill", "name": "inventory",
                      "content": "Inventory inputs.", "why": "Missing input"}

    def test_editor_candidate_generation_does_not_write_approval_inbox(self):
        before = improve.list_proposals()
        answer = json.dumps({"candidates": [self.skill]})
        got = editors.propose("invariant", self.base, call=lambda _: (answer, "", "m"))
        self.assertEqual(len(got["candidates"]), 1)
        self.assertEqual(got["proposals"], [])
        self.assertNotIn("proposal", got["candidates"][0])
        self.assertEqual(improve.list_proposals(), before)

    def test_valid_empty_candidate_array_is_a_clean_no_edit_decision(self):
        got = editors.propose("domain", self.base, call=lambda _: ('{"candidates":[]}', "", "m"))
        self.assertEqual(got["candidates"], [])
        self.assertEqual(got["rejected"], [])

    def test_standalone_script_has_no_consumer_and_is_refused(self):
        candidate = dict(self.skill, kind="script", content="print('unreachable')")
        got = editors.propose("invariant", self.base,
                              call=lambda _: (json.dumps({"candidates": [candidate]}), "", "m"))
        self.assertEqual(got["candidates"], [])
        self.assertIn("consumer", got["rejected"][0]["reason"])
        staged = probe.stage("script", "unreachable", candidate["content"], TMP)
        self.assertFalse(staged["ok"])

    def test_guardrail_is_loaded_through_existing_rules_owner(self):
        from longrun.memory import rules
        workspace = tempfile.mkdtemp(dir=TMP)
        stage = probe.stage("guardrail", "inventory", "Inventory ALL inputs.", TMP)
        runner.prepare_rules(workspace, {"global": "", "project": ""}, stage["path"])
        collected = rules.collect(ws=workspace)
        self.assertIn("Inventory ALL inputs.", collected["project"]["text"])
        self.assertEqual(collected["project"]["path"], rules.project_rules_path(workspace))
        self.assertFalse(os.path.exists(os.path.join(workspace, "Project_rules.md")))

    def test_probe_plan_pins_model_and_boxes_all_rule_state(self):
        workspace = tempfile.mkdtemp(dir=TMP)
        with open(os.path.join(workspace, "input.txt"), "w") as f:
            f.write("input")
        base = dict(self.base, workspace=workspace)
        candidate = dict(self.skill, kind="guardrail")
        plan = probe.plan(base, [candidate], dict(probe.DEFAULTS, enabled=True))
        try:
            self.assertIn("--model", plan["cmd"])
            self.assertEqual(plan["cmd"][plan["cmd"].index("--model") + 1], "m")
            self.assertIn("--guardrail", plan["cmd"])
            self.assertIn("--rules", plan["cmd"])
            for key in ("DATA_HOME", "CONFIG_DIR", "PROJECTS_DIR", "HARNESS_DIR"):
                self.assertTrue(plan["env"]["LONGRUN_" + key].startswith(probe.root()))
            self.assertFalse(os.path.exists(os.path.join(plan["workspace"], "Project_rules.md")))
        finally:
            probe.cleanup(plan["probe_id"])

    def test_legacy_harness_proposal_cannot_bypass_missing_experiment_gate(self):
        proposal = improve.propose("project", "Unprobed legacy text", ws=TMP, origin="harness")
        result = improve.decide(proposal["id"], "approve")
        self.assertFalse(result["ok"])
        self.assertIn("experiment", result["error"])
        self.assertEqual(improve.get_proposal(proposal["id"])["status"], "pending")
        self.assertTrue(improve.decide(proposal["id"], "deny")["ok"])


if __name__ == "__main__":
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(CandidateOwnership)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0 if result.wasSuccessful() else 1)
