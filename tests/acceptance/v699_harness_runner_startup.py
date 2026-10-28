#!/usr/bin/env python3
"""Headless runner startup contract: workspace seeding, relay refusal, evidence."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v699-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "SESSIONS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.harness import runner


def result_line(output):
    for line in output.splitlines():
        if line.startswith("H2_RESULT "):
            return json.loads(line[len("H2_RESULT "):])
    raise AssertionError("no H2_RESULT line: %r" % output)


class RunnerStartup(unittest.TestCase):
    def setUp(self):
        self.source = tempfile.mkdtemp(dir=TMP)
        with open(os.path.join(self.source, "input.txt"), "w") as f:
            f.write("payload")
        self.work = tempfile.mkdtemp(dir=TMP)

    def run_main(self, argv):
        previous = os.getcwd()
        os.chdir(self.work)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = runner.main(argv)
        finally:
            os.chdir(previous)
        return code, out.getvalue()

    def test_workspace_copy_seeds_the_work_dir(self):
        previous = os.getcwd()
        os.chdir(self.work)
        try:
            runner._copy_workspace(self.source)
        finally:
            os.chdir(previous)
        with open(os.path.join(self.work, "input.txt")) as f:
            self.assertEqual(f.read(), "payload")

    def test_missing_workspace_is_a_reported_error(self):
        with self.assertRaises(RuntimeError):
            runner._copy_workspace(os.path.join(TMP, "absent"))

    def test_unavailable_gateway_stops_before_any_model_import(self):
        code, output = self.run_main([
            "--goal", "g", "--model", "m",
            "--gateway-socket", os.path.join(TMP, "missing.sock"),
            "--workspace-from", self.source])
        payload = result_line(output)
        self.assertEqual(code, 1)
        self.assertIn("gateway relay unavailable", payload["error"])
        self.assertIsNone(payload["record"])
        self.assertTrue(os.path.isfile(os.path.join(self.work, "input.txt")))

    def test_evidence_line_is_bounded_and_flags_truncation(self):
        small = {"goal": "g", "record": {"steps": []}}
        encoded, truncated = runner.evidence_line(small)
        self.assertFalse(truncated)
        self.assertEqual(json.loads(encoded)["goal"], "g")
        big = {"goal": "g", "record": {"steps": [{"blob": "x" * 5000}]},
               "probe_id": "p", "snapshot": "d"}
        encoded, truncated = runner.evidence_line(big, max_chars=1000)
        reduced = json.loads(encoded)
        self.assertTrue(truncated)
        self.assertIsNone(reduced["record"])
        self.assertTrue(reduced["record_truncated"])
        self.assertEqual(reduced["probe_id"], "p")

    def test_evidence_line_reports_unavailable_output(self):
        encoded, truncated = runner.evidence_line({"error": "boom"}, max_chars=10)
        self.assertTrue(truncated)
        self.assertIn("boom", json.loads(encoded)["error"])


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
