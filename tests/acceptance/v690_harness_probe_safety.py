#!/usr/bin/env python3
"""Whole-run probe safety, without a model, network or live server."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v690-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "HARNESS_DIR", "SESSIONS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.harness import probe


class ProbeSafety(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.mkdtemp(dir=TMP)
        with open(os.path.join(self.workspace, "input.txt"), "w") as f:
            f.write("input")
        self.base = {"workspace": self.workspace, "goal": "Read input", "model": "pinned",
                     "steps": [{"tool": "fs.read", "ok": False, "error": "missing"}]}
        self.candidate = {"kind": "guardrail", "name": "inventory", "content": "Read inputs first."}
        self.config = dict(probe.DEFAULTS, enabled=True, copy_max_mb=1)

    def test_default_runner_refuses_before_copy_or_host_spawn(self):
        with patch.object(probe, "plan", side_effect=AssertionError("must not stage")), \
                patch.object(probe, "_spawn", side_effect=AssertionError("host spawn")):
            result = probe.run(self.base, [self.candidate], c=self.config)
        self.assertEqual(result["status"], "refused")
        self.assertIn("whole-run", result["reason"])

    def test_direct_default_spawn_has_no_host_execution_path(self):
        with patch("subprocess.run", side_effect=AssertionError("host executed")):
            result, error = probe._spawn(
                {"cmd": ["/bin/false", "--out", os.path.join(TMP, "result.json")],
                 "cwd": self.workspace, "env": {}}, 1)
        self.assertIsNone(result)
        self.assertIn("whole-run", error)

    def test_nested_copy_refuses_before_creating_destination(self):
        destination = os.path.join(self.workspace, "child", "copy")
        result = probe.guarded_copy(self.workspace, destination)
        self.assertFalse(result["ok"])
        self.assertFalse(os.path.exists(destination))
        self.assertIn("inside", result["reason"])

    def test_failed_injected_runs_leave_no_scratch_tree(self):
        def explode(_plan, _timeout):
            raise RuntimeError("injected crash")
        for runner in (lambda *_: (None, "failed"),
                       lambda *_: ({"error": "missing record"}, ""), explode):
            with self.subTest(runner=runner):
                before = set(os.listdir(probe.root())) if os.path.isdir(probe.root()) else set()
                result = probe.run(self.base, [self.candidate], runner=runner, c=self.config)
                after = set(os.listdir(probe.root())) if os.path.isdir(probe.root()) else set()
                self.assertEqual(result["status"], "failed")
                self.assertEqual(after, before)

    def test_returned_goal_is_not_rewritten_to_force_match(self):
        other = dict(self.base, goal="Different task",
                     steps=[{"tool": "fs.read", "ok": True}])
        result = probe.run(self.base, [self.candidate], c=self.config,
                           runner=lambda *_: ({"record": other}, ""))
        self.assertEqual(result["record"]["goal"], "Different task")
        self.assertFalse(result["contrast"]["comparable"])
        probe.cleanup(result["probe_id"])

    def test_preparation_failure_cleans_scratch_without_calling_runner(self):
        from longrun.memory import rules
        before = set(os.listdir(probe.root())) if os.path.isdir(probe.root()) else set()
        with patch.object(rules, "collect", side_effect=OSError("rule snapshot unavailable")):
            result = probe.run(self.base, [self.candidate], c=self.config,
                               runner=lambda *_: self.fail("runner must not execute"))
        after = set(os.listdir(probe.root())) if os.path.isdir(probe.root()) else set()
        self.assertEqual(result["status"], "refused")
        self.assertIn("rule snapshot unavailable", result["reason"])
        self.assertEqual(after, before)

    def test_existing_probe_id_cannot_overwrite_or_delete_prior_scratch(self):
        directory = os.path.join(probe.root(), "existing")
        os.makedirs(directory, exist_ok=True)
        marker = os.path.join(directory, "keep.txt")
        with open(marker, "w") as f:
            f.write("keep")
        result = probe.plan(self.base, [self.candidate], self.config, probe_id="existing")
        self.assertFalse(result["ok"])
        with open(marker) as f:
            self.assertEqual(f.read(), "keep")
        self.assertEqual(os.listdir(directory), ["keep.txt"])
        probe.cleanup("existing")


if __name__ == "__main__":
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ProbeSafety)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0 if result.wasSuccessful() else 1)
