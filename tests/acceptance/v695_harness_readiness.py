#!/usr/bin/env python3
"""Readiness and panel text fail closed even when the enable flag is on."""
import json
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v695-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "HARNESS_DIR", "SESSIONS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.harness import cycle, probe, whole


class Readiness(unittest.TestCase):
    def test_enable_flag_is_not_production_readiness(self):
        # The isolation probe is patched so the assertion never depends on the
        # host having Docker: the point is that `enabled` alone is not readiness.
        with patch.object(probe, "cfg", return_value=dict(probe._defaults(), enabled=True)), \
                patch.object(probe, "isolation_status",
                             return_value={"available": False, "reason": "test"}):
            status = cycle.status()
        self.assertTrue(status["enabled"])
        self.assertFalse(status.get("ready", True))
        self.assertFalse(status["isolation"]["available"])
        self.assertEqual(status["config"]["repeats"], whole.DEFAULTS["repeats"])

    def run_js(self, script):
        node = shutil.which("node")
        if node is None:
            installed = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/node")))
            node = installed[-1] if installed else "node"
        result = subprocess.run([node], input=script, text=True, capture_output=True,
                                timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def render(self, payload):
        with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
            ui = f.read()
        function = "async function loadHarnessCycle()" + ui.split(
            "async function loadHarnessCycle()", 1)[1].split(
            "async function runHarnessDryRun()", 1)[0]
        script = """
const nodes = Object.fromEntries(["hcState", "hcSummary", "hcLib", "hcLast"].map(k => [k, {}]));
const $ = id => nodes[id];
const esc = s => String(s).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const api = async () => (PAYLOAD);
FUNCTION
loadHarnessCycle().then(() => console.log(JSON.stringify(nodes)));
""".replace("PAYLOAD", json.dumps(payload)).replace("FUNCTION", function)
        return self.run_js(script)

    def evidence_text(self, payload):
        with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
            ui = f.read()
        function = "function harnessEvidenceText(x) {" + ui.split(
            "function harnessEvidenceText(x) {", 1)[1].split("\n}\n", 1)[0] + "\n}"
        return self.run_js(function + "\nconsole.log(JSON.stringify(harnessEvidenceText(" +
                           json.dumps(payload) + ")));")

    def test_panel_names_isolation_refusal_and_keeps_dry_run_available(self):
        nodes = self.render({"enabled": True, "ready": False,
                             "isolation": {"available": False, "reason": "<whole-run unavailable>"},
                             "config": {"max_candidates": 2, "copy_max_mb": 8},
                             "library": {"entries": 0, "domains": {}}, "last": None})
        self.assertIn("unavailable", nodes["hcState"]["textContent"])
        self.assertIn("&lt;whole-run unavailable&gt;", nodes["hcSummary"]["innerHTML"])
        self.assertIn("dry run", nodes["hcSummary"]["innerHTML"].lower())
        self.assertNotIn("to allow one", nodes["hcSummary"]["innerHTML"])

    def test_missing_isolation_metadata_is_never_called_verified(self):
        nodes = self.render({"enabled": True, "library": {}, "last": None})
        self.assertIn("unavailable", nodes["hcState"]["textContent"])
        self.assertIn("isolation unverified", nodes["hcSummary"]["innerHTML"])
        self.assertNotIn("isolation verified", nodes["hcSummary"]["innerHTML"])

    def test_repeats_is_rendered_from_the_backend_value(self):
        nodes = self.render({"enabled": True, "ready": True,
                             "isolation": {"available": True, "reason": ""},
                             "config": {"max_candidates": 2, "copy_max_mb": 8, "repeats": 2},
                             "library": {"entries": 0, "domains": {}}, "last": None})
        self.assertIn("repeats 2", nodes["hcSummary"]["innerHTML"])

    def test_absent_repeats_is_not_rendered_as_undefined(self):
        nodes = self.render({"enabled": True, "ready": True,
                             "isolation": {"available": True, "reason": ""},
                             "config": {"max_candidates": 2, "copy_max_mb": 8},
                             "library": {"entries": 0, "domains": {}}, "last": None})
        self.assertNotIn("undefined", nodes["hcSummary"]["innerHTML"])
        self.assertNotIn("repeats", nodes["hcSummary"]["innerHTML"])

    def test_harness_evidence_line_names_both_runs_and_digests(self):
        line = self.evidence_text({"verified": True, "repeats": 2,
                                   "snapshot_digest": "a" * 64,
                                   "variant_digest": "c" * 64,
                                   "contrast": "improved",
                                   "runs": [{"role": "reference", "run_id": "reference-1",
                                             "cleanup_verified": True},
                                            {"role": "successor", "run_id": "successor-1",
                                             "cleanup_verified": True}]})
        self.assertIn("verified", line)
        self.assertIn("repeats 2", line)
        self.assertIn("package " + "a" * 12, line)
        self.assertIn("variant " + "c" * 12, line)
        self.assertIn("improved", line)
        self.assertIn("reference-1", line)
        self.assertIn("successor-1", line)
        self.assertNotIn("unverified", line)
        self.assertNotIn("undefined", line)

    def test_harness_evidence_line_marks_an_unverified_cleanup(self):
        line = self.evidence_text({"verified": True,
                                   "runs": [{"role": "reference", "run_id": "r1"},
                                            {"role": "successor", "run_id": "s1",
                                             "cleanup_verified": False}]})
        self.assertIn("successor s1 (unverified cleanup)", line)

    def test_harness_evidence_line_is_empty_without_an_experiment(self):
        self.assertEqual(self.evidence_text(None), "")


if __name__ == "__main__":
    try:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(Readiness))
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0 if result.wasSuccessful() else 1)
