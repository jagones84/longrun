#!/usr/bin/env python3
"""Bounded library content reaches editors as evidence, never as instructions."""
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v694-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "HARNESS_DIR", "SESSIONS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.harness import editors, library


class EditorReuse(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(library._root(), ignore_errors=True)
        self.base = {"goal": "Reconcile budget", "model": "m",
                     "steps": [{"tool": "fs.read", "ok": False, "error": "missing input"}]}
        self.source = os.path.join(TMP, "SKILL.md")
        with open(self.source, "w", encoding="utf-8") as f:
            f.write("Inventory every budget input before reconciliation.\n")
        self.row = library.add("office", {"id": "inventory", "task_kind": "budget",
                              "lesson": "Inventory inputs", "files": {"skills/a/SKILL.md": self.source}})

    def test_editor_receives_complete_component_and_provenance(self):
        messages = []
        def call(msgs):
            messages.extend(msgs)
            return '{"candidates":[]}', "", "m"
        editors.propose("invariant", self.base, library_rows=[self.row],
                        domain="office", call=call)
        prompt = messages[0]["content"]
        self.assertIn("Inventory every budget input before reconciliation.", prompt)
        self.assertIn("office/inventory/components/skills/a/SKILL.md", prompt)
        self.assertIn("sha256", prompt)
        self.assertIn("untrusted reference data", prompt.lower())

    def test_oversized_bundle_is_not_partially_inlined(self):
        path = os.path.join(library.entry_dir("office", "inventory"),
                            "components", "skills", "a", "SKILL.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("unique-oversize-marker" + "x" * library.COMPONENT_MAX_BYTES)
        content = editors._library_content([self.row], "office")
        self.assertNotIn("unique-oversize-marker", content)

    def test_serialized_bundle_budget_is_shared_across_entries(self):
        rows = []
        with open(self.source, "w", encoding="utf-8") as f:
            f.write("y" * 3000)
        for i in range(5):
            rows.append(library.add("office", {"id": "budget-%d" % i,
                        "files": {"SKILL.md": self.source}}))
        content = editors._library_content(rows, "office")
        self.assertLessEqual(len(content.encode("utf-8")), editors.MAX_LIBRARY_BYTES + 4)
        bundles = [json.loads(line) for line in content.splitlines()]
        self.assertGreater(len(bundles), 0)
        self.assertLess(len(bundles), len(rows))
        self.assertTrue(all(b["components"][0]["text"] == "y" * 3000 for b in bundles))

    def test_candidate_limit_counts_utf8_bytes_not_characters(self):
        candidate = {"kind": "guardrail", "name": "large", "content": "\u20ac" * 3000}
        got = editors.propose("domain", self.base,
                              call=lambda _: (json.dumps({"candidates": [candidate]}), "", "m"))
        self.assertEqual(got["candidates"], [])
        self.assertIn("9000 bytes", got["rejected"][0]["reason"])

    def test_unknown_step_outcome_is_not_presented_as_success_or_failure(self):
        record = dict(self.base, steps=[{"tool": "fs.read", "ok": None, "error": ""}])
        prompt = editors.build_prompt("domain", record)
        self.assertIn("UNKNOWN fs.read", prompt)
        self.assertNotIn("FAIL fs.read", prompt)
        self.assertNotIn("\nok fs.read", prompt)


if __name__ == "__main__":
    try:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(EditorReuse))
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0 if result.wasSuccessful() else 1)
