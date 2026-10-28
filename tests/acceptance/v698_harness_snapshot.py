#!/usr/bin/env python3
"""Matched input snapshots: deterministic, hardlinked variants, bounded."""
import json
import os
import stat
import sys
import tempfile
import shutil
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v698-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "SESSIONS_DIR", "SKILLS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
os.makedirs(os.path.join(TMP, "skills", "fixture"), exist_ok=True)
with open(os.path.join(TMP, "skills", "fixture", "SKILL.md"), "w") as f:
    f.write("# fixture skill\n")
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.harness import snapshot
from longrun.memory import rules, skills
from longrun.tools import sandbox


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class SnapshotBuild(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.mkdtemp(dir=TMP)
        with open(os.path.join(self.workspace, "input.txt"), "w") as f:
            f.write("input payload")
        with open(os.path.join(self.workspace, "AGENTS.md"), "w") as f:
            f.write("workspace agents addendum")
        rules.append("project", "project rule text", ws=self.workspace)
        self.base = {"workspace": self.workspace, "goal": "Read input",
                     "model": "fixture-model"}
        self.root = os.path.realpath(sandbox.registry.workspace_dir())
        self.config = {"max_mb": 64, "port": 18080}
        self._skills_dir = skills.SKILLS_DIR
        skills.SKILLS_DIR = os.path.join(TMP, "skills")

    def tearDown(self):
        skills.SKILLS_DIR = self._skills_dir
        for name in os.listdir(self.root) if os.path.isdir(self.root) else []:
            snapshot.remove(os.path.join(self.root, name, "inputs"))

    def test_package_contains_matched_inputs_and_verifies(self):
        built = snapshot.build(self.base, self.config, context_length=262144)
        self.assertTrue(built["ok"], built)
        for rel in ("src/longrun/harness/runner.py", "config/tools.yaml",
                    "config/providers.yaml", "config/routing.yaml",
                    "skills/fixture/SKILL.md", "rules/snapshot.json",
                    "workspace/input.txt", "workspace/AGENTS.md", "manifest.json"):
            self.assertTrue(os.path.isfile(os.path.join(built["path"], rel)), rel)
        providers = read(os.path.join(built["path"], "config", "providers.yaml"))
        self.assertIn('base_url: http://127.0.0.1:18080/v1', providers)
        self.assertIn("fixture-model", providers)
        self.assertNotIn("api_key_env", providers)
        routing = read(os.path.join(built["path"], "config", "routing.yaml"))
        self.assertEqual(routing.count("h2:fixture-model"), 7)
        self.assertTrue(snapshot.verify(built["path"])["ok"])
        mode = stat.S_IMODE(os.stat(os.path.join(built["path"], "manifest.json")).st_mode)
        self.assertEqual(mode, stat.S_IRUSR)

    def test_same_inputs_produce_the_same_digest(self):
        first = snapshot.build(self.base, self.config)
        second = snapshot.build(self.base, self.config)
        self.assertTrue(first["ok"] and second["ok"])
        self.assertEqual(first["digest"], second["digest"])

    def test_workspace_agents_is_not_duplicated_in_the_rules_snapshot(self):
        built = snapshot.build(self.base, self.config)
        text = read(os.path.join(built["path"], "rules", "snapshot.json"))
        self.assertIn("project rule text", text)
        self.assertNotIn("workspace agents addendum", text)

    def test_variant_changes_only_the_declared_delta(self):
        base = snapshot.build(self.base, self.config)
        variant = snapshot.variant(base["path"], {
            "rules/guardrail.txt": "Read every input before writing."})
        self.assertTrue(variant["ok"], variant)
        self.assertNotEqual(base["digest"], variant["digest"])
        self.assertEqual(variant["delta"], ["rules/guardrail.txt"])
        self.assertEqual(read(os.path.join(variant["path"], "rules", "guardrail.txt")),
                         "Read every input before writing.")
        self.assertFalse(os.path.exists(os.path.join(base["path"], "rules",
                                                     "guardrail.txt")))
        self.assertTrue(snapshot.verify(base["path"])["ok"])
        self.assertTrue(snapshot.verify(variant["path"])["ok"])
        unchanged = read(os.path.join(variant["path"], "workspace", "input.txt"))
        self.assertEqual(unchanged, "input payload")

    def test_delta_paths_outside_the_candidate_surface_are_refused(self):
        base = snapshot.build(self.base, self.config)
        before = set(os.listdir(self.root))
        for rel in ("../escape.txt", "/etc/passwd", "config/tools.yaml",
                    "workspace/input.txt", "rules/../../x"):
            with self.subTest(rel=rel):
                result = snapshot.variant(base["path"], {rel: "x"})
                self.assertFalse(result["ok"], result)
        self.assertEqual(set(os.listdir(self.root)), before)

    def test_oversized_package_is_refused_and_cleaned(self):
        before = set(os.listdir(self.root))
        built = snapshot.build(self.base, {"max_mb": 1})
        self.assertFalse(built["ok"])
        self.assertEqual(set(os.listdir(self.root)), before)

    def test_remove_refuses_paths_it_did_not_reserve(self):
        built = snapshot.build(self.base, self.config)
        self.assertFalse(snapshot.remove(self.workspace)["ok"])
        self.assertTrue(snapshot.remove(built["path"])["ok"])
        self.assertFalse(os.path.exists(built["path"]))


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
