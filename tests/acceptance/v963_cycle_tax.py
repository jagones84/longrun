#!/usr/bin/env python3
"""RSI-U — the cycle records what the improvement process itself spent.

The bill has two stages that are measured in different places and one that is
honestly declared missing: the editors' provider usage (propose), each probe
run's own `budget.tokens` (probe), and nothing at all when the record carries no
number. A zero is never substituted for "not measured".
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v963-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "HARNESS_DIR", "SESSIONS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.harness import cycle, probe
from longrun.util import improve


class CycleTax(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.mkdtemp(dir=TMP)
        self.base = {"run_id": "base", "workspace": self.workspace, "goal": "Read inputs",
                     "model": "m", "harness": {}, "budget": {},
                     "steps": [{"tool": "fs.read", "ok": False, "error": "missing input"}],
                     "deliverables": [], "files_touched": []}
        self.candidates = [{"kind": "guardrail", "name": "a", "content": "Inventory inputs."}]
        self.config = dict(probe.DEFAULTS, enabled=True, max_candidates=1)

    def editor(self, _messages):
        payload = json.dumps({"candidates": self.candidates})
        return payload, "", "m", {"prompt_tokens": 100, "completion_tokens": 20}

    def runner(self, _plan, _timeout, tokens=900):
        budget = {} if tokens is None else {"tokens": tokens}
        return {"record": dict(self.base, run_id="probe", budget=budget,
                               steps=[{"tool": "fs.read", "ok": True}])}, ""

    def test_dry_run_carries_an_empty_bill_not_a_missing_field(self):
        with patch.object(cycle.record_mod, "build", return_value=self.base):
            result = cycle.run("session", dry_run=True, c=self.config)
        self.assertEqual(result["tax"]["total_tokens"], 0)
        self.assertEqual(result["tax"]["propose"]["calls"], 0)
        self.assertFalse(result["tax"]["probe"]["measured"])

    def test_editor_usage_is_summed_once_per_call(self):
        with patch.object(cycle.record_mod, "build", return_value=self.base):
            result = cycle.run("session", dry_run=False, c=self.config,
                               call=self.editor, runner=self.runner)
        propose = result["tax"]["propose"]
        self.assertEqual(propose["calls"], 2)          # one per scope, both paid
        self.assertEqual(propose["prompt_tokens"], 200)
        self.assertEqual(propose["completion_tokens"], 40)

    def test_probe_spend_is_read_from_the_run_record(self):
        with patch.object(cycle.record_mod, "build", return_value=self.base):
            result = cycle.run("session", dry_run=False, c=self.config,
                               call=self.editor, runner=self.runner)
        probe_tax = result["tax"]["probe"]
        self.assertTrue(probe_tax["measured"])
        self.assertGreaterEqual(probe_tax["tokens"], 900)
        self.assertEqual(result["tax"]["total_tokens"],
                         result["tax"]["propose"]["prompt_tokens"]
                         + result["tax"]["propose"]["completion_tokens"]
                         + probe_tax["tokens"])

    def test_a_record_without_tokens_is_not_counted_as_free(self):
        with patch.object(cycle.record_mod, "build", return_value=self.base):
            result = cycle.run("session", dry_run=False, c=self.config,
                               call=self.editor,
                               runner=lambda plan, t: self.runner(plan, t, tokens=None))
        self.assertFalse(result["tax"]["probe"]["measured"])
        self.assertEqual(result["tax"]["probe"]["tokens"], 0)
        self.assertEqual(result["tax"]["total_tokens"], 240)   # propose only

    def test_the_durable_ledger_row_carries_the_bill(self):
        with patch.object(cycle.record_mod, "build", return_value=self.base):
            result = cycle.run("session", dry_run=False, c=self.config,
                               call=self.editor, runner=self.runner)
        rows = [r for r in improve.ledger_tail(50) if r.get("kind") == "harness_cycle"]
        self.assertTrue(rows, "the cycle must leave an audit row")
        last = rows[0]
        self.assertEqual(last.get("tax_total"), result["tax"]["total_tokens"])
        self.assertEqual(last.get("tax_probe_measured"), True)
        self.assertEqual(last.get("tax_propose"), 200)

    def test_an_editor_that_reports_no_usage_is_not_invented(self):
        def bare(_messages):
            return json.dumps({"candidates": self.candidates}), "", "m"
        with patch.object(cycle.record_mod, "build", return_value=self.base):
            result = cycle.run("session", dry_run=False, c=self.config,
                               call=bare, runner=self.runner)
        self.assertEqual(result["tax"]["propose"]["calls"], 0)
        self.assertEqual(result["tax"]["propose"]["prompt_tokens"], 0)


if __name__ == "__main__":
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(CycleTax)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0 if result.wasSuccessful() else 1)
