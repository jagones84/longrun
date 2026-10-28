#!/usr/bin/env python3
"""v689: canonical, bounded harness library reuse. No model/network/server."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v689-")
for key in ("CONFIG_DIR", "SESSIONS_DIR", "DATA_DIR", "HARNESS_DIR", "RUNS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.harness import library as L  # noqa: E402


class Integrity(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(L._root(), ignore_errors=True)
        self.source = os.path.join(TMP, "source.md")
        with open(self.source, "w", encoding="utf-8") as f:
            f.write("Never execute this fixture.\n")

    def add(self, ident="one", files=None):
        return L.add("office", {"id": ident, "task_kind": "budget reconciliation",
                               "lesson": "Check budget cells",
                               "files": files or {"SKILL.md": self.source}})

    def test_canonical_index_ignores_valid_stale_cache(self):
        self.assertIsNotNone(self.add())
        with open(L.index_path("office"), "w", encoding="utf-8") as f:
            json.dump({"entries": [{"id": "phantom"}]}, f)
        self.assertEqual([r["id"] for r in L.index("office")["entries"]], ["one"])

    def test_relevance_zero_and_cap(self):
        for i in range(12):
            self.assertIsNotNone(self.add("entry-%02d" % i))
        self.assertEqual(L.relevant("office", "budget", limit=0), [])
        self.assertEqual(L.relevant("office", "budget", limit=-1), [])
        self.assertEqual(len(L.relevant("office", "budget", limit=10000)), L.RELEVANT_MAX)

    def test_nested_components_preserve_same_basename(self):
        other = os.path.join(TMP, "other.md")
        with open(other, "w", encoding="utf-8") as f:
            f.write("Second component\n")
        row = self.add(files={"skills/a/SKILL.md": self.source,
                              "skills/b/SKILL.md": other})
        self.assertEqual(row["components"], ["skills/a/SKILL.md", "skills/b/SKILL.md"])
        for name, text in (("skills/a/SKILL.md", "Never execute"),
                           ("skills/b/SKILL.md", "Second component")):
            with open(os.path.join(L.entry_dir("office", "one"), "components", name)) as f:
                self.assertIn(text, f.read())

    def test_unsafe_component_paths_and_sources_refused(self):
        for i, name in enumerate(("../x", "/x", "C:/x", "\\\\server\\x",
                                  "a\\b", "a/../b", "./x", "a//b", ".", "..")):
            with self.subTest(name=name):
                self.assertIsNone(self.add("bad-%d" % i, {name: self.source}))
        link = os.path.join(TMP, "source-link")
        if os.path.lexists(link):
            os.unlink(link)
        os.symlink(self.source, link)
        self.assertIsNone(self.add("symlink", {"SKILL.md": link}))
        self.assertEqual(L.index("office")["entries"], [])

    def test_concurrent_same_id_has_unique_staging_and_one_winner(self):
        barrier = threading.Barrier(2)
        destinations = []
        copy = shutil.copyfileobj

        def copying(src, dst):
            destinations.append(dst.name)
            barrier.wait(timeout=5)
            return copy(src, dst)

        with patch.object(L.shutil, "copyfileobj", copying):
            with ThreadPoolExecutor(max_workers=2) as pool:
                rows = list(pool.map(lambda _: self.add("race"), range(2)))
        self.assertEqual(len(set(destinations)), 2)
        self.assertEqual(sum(row is not None for row in rows), 1)
        self.assertEqual([r["id"] for r in L.index("office")["entries"]], ["race"])
        self.assertEqual(sorted(os.listdir(L.domain_dir("office"))), ["index.json", "race"])

    def test_retrieval_full_text_and_provenance_for_flat_and_nested(self):
        self.assertIsNotNone(self.add(files={"SKILL.md": self.source,
                                            "skills/check/SKILL.md": self.source}))
        got = L.retrieve("office", "one")
        self.assertEqual(got["id"], "one")
        self.assertEqual(len(got["components"]), 2)
        for item in got["components"]:
            self.assertEqual(item["text"], "Never execute this fixture.\n")
            provenance = item["provenance"]
            self.assertEqual(provenance["entry_id"], "one")
            self.assertEqual(provenance["domain"], "office")
            self.assertEqual(provenance["path"], "office/one/components/" + item["name"])
            self.assertEqual(provenance["bytes"], len(item["text"].encode("utf-8")))
            self.assertEqual(len(provenance["sha256"]), 64)
        self.assertIn("Check budget cells", got["experience"]["text"])
        self.assertEqual(L.experience_text("office", "one"), got["experience"]["text"])
        self.assertEqual(L.read_component("office", "one", "SKILL.md"), got["components"][0])
        self.assertEqual(L.read_experience("office", "one"), got["experience"])

    def test_retrieval_refuses_oversize_binary_and_small_total_budget(self):
        self.assertIsNotNone(self.add())
        path = os.path.join(L.entry_dir("office", "one"), "components", "SKILL.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("x" * (L.COMPONENT_MAX_BYTES + 1))
        self.assertIsNone(L.read_component("office", "one", "SKILL.md", max_bytes=10**9))
        self.assertIsNone(L.retrieve("office", "one"))
        with open(path, "wb") as f:
            f.write(b"\xff")
        self.assertIsNone(L.retrieve("office", "one"))
        with open(path, "w", encoding="utf-8") as f:
            f.write("x" * L.COMPONENT_MAX_BYTES)
        self.assertEqual(len(L.read_component("office", "one", "SKILL.md")["text"]),
                         L.COMPONENT_MAX_BYTES)
        self.assertIsNone(L.retrieve("office", "one", max_bytes=1))
        exp = os.path.join(L.entry_dir("office", "one"), "EXPERIENCE.md")
        with open(exp, "w", encoding="utf-8") as f:
            f.write("x" * (L.EXPERIENCE_MAX_BYTES + 1))
        self.assertIsNone(L.retrieve("office", "one"))
        self.assertEqual(L.experience_text("office", "one"), "")

    def test_retrieval_rejects_traversal_unlisted_and_symlinks(self):
        self.assertIsNotNone(self.add(files={"nested/SKILL.md": self.source}))
        for name in ("../EXPERIENCE.md", "/tmp/x", "C:\\x", "not-listed.md"):
            self.assertIsNone(L.read_component("office", "one", name))
        for ident in ("..", "../one", "/one"):
            self.assertIsNone(L.retrieve("office", ident))
        base = L.entry_dir("office", "one")
        nested = os.path.join(base, "components", "nested")
        shutil.rmtree(nested)
        os.symlink(TMP, nested)
        self.assertIsNone(L.retrieve("office", "one"))
        exp = os.path.join(base, "EXPERIENCE.md")
        os.unlink(exp)
        os.symlink(self.source, exp)
        self.assertIsNone(L.read_experience("office", "one"))
        metadata = os.path.join(base, "entry.json")
        os.unlink(metadata)
        os.symlink(self.source, metadata)
        self.assertEqual(L.index("office")["entries"], [])
        self.assertIsNone(L.retrieve("office", "one"))

    def test_index_ignores_staging_symlink_and_invalid_metadata(self):
        self.assertIsNotNone(self.add())
        base = L.domain_dir("office")
        os.symlink(L.entry_dir("office", "one"), os.path.join(base, "alias"))
        os.makedirs(os.path.join(base, ".stage-unfinished"))
        with open(os.path.join(base, ".stage-unfinished", "entry.json"), "w") as f:
            json.dump({"id": ".stage-unfinished", "components": ["SKILL.md"]}, f)
        os.makedirs(os.path.join(base, "bad"))
        with open(os.path.join(base, "bad", "entry.json"), "w") as f:
            json.dump({"id": "bad", "ts": "not-a-number", "components": ["../x"]}, f)
        self.assertEqual([r["id"] for r in L.index("office")["entries"]], ["one"])

    def test_loo_reports_availability_not_measurement(self):
        for i in range(3):
            self.assertIsNotNone(self.add("entry-%d" % i))
        got = L.leave_one_out("office")
        self.assertEqual(got["status"], "not-run")
        self.assertEqual(got["availability"], "sufficient")
        self.assertEqual(L.leave_one_out("empty")["availability"], "insufficient")
        self.assertEqual(L.leave_one_out("empty")["status"], "not-run")

    def test_maximum_nested_depth_is_retrievable(self):
        name = "/".join(["nested"] * 7 + ["SKILL.md"])
        self.assertIsNotNone(self.add(files={name: self.source}))
        self.assertIsNotNone(L.read_component("office", "one", name))

    def test_source_symlink_swap_after_validation_is_refused(self):
        staging = tempfile.mkdtemp

        def swapped(*args, **kwargs):
            result = staging(*args, **kwargs)
            os.unlink(self.source)
            os.symlink(os.path.join(TMP, "outside.md"), self.source)
            return result

        with open(os.path.join(TMP, "outside.md"), "w") as f:
            f.write("Outside component")
        with patch.object(L.tempfile, "mkdtemp", swapped):
            self.assertIsNone(self.add())
        os.unlink(self.source)

    def test_concurrent_distinct_entries_are_all_indexed(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(lambda i: self.add("many-%d" % i), range(8)))
        self.assertTrue(all(row is not None for row in rows))
        self.assertEqual(len(L.index("office")["entries"]), 8)

    def test_deep_json_metadata_refused_without_exception(self):
        self.assertIsNotNone(self.add())
        path = os.path.join(L.entry_dir("office", "one"), "entry.json")
        with open(path, "w") as f:
            f.write("[" * 1100 + "0" + "]" * 1100)
        previous = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(1000)
            self.assertIsNone(L.retrieve("office", "one"))
            self.assertEqual(L.index("office")["entries"], [])
        finally:
            sys.setrecursionlimit(previous)

    def test_aggregate_hard_cap_refuses_complete_bundle(self):
        with open(self.source, "w") as f:
            f.write("x" * L.COMPONENT_MAX_BYTES)
        self.assertIsNotNone(self.add(files={"part-%d.md" % i: self.source for i in range(5)}))
        self.assertIsNotNone(L.read_component("office", "one", "part-0.md"))
        self.assertIsNone(L.retrieve("office", "one", max_bytes=10**9))
        path = os.path.join(L.entry_dir("office", "one"), "entry.json")
        with open(path, "w") as f:
            f.write(" " * (L.METADATA_MAX_BYTES + 1))
        self.assertIsNone(L.retrieve("office", "one"))

    def test_nonregular_component_and_symlink_domain_refused(self):
        self.assertIsNotNone(self.add())
        path = os.path.join(L.entry_dir("office", "one"), "components", "SKILL.md")
        os.unlink(path)
        os.mkfifo(path)
        self.assertIsNone(L.read_component("office", "one", "SKILL.md"))
        base = L.domain_dir("office")
        shutil.rmtree(base)
        os.symlink(TMP, base)
        self.assertIsNone(self.add())
        self.assertIsNone(L.retrieve("office", "one"))
        self.assertEqual(L.index("office")["entries"], [])
        os.unlink(base)


if __name__ == "__main__":
    try:
        suite = unittest.main(exit=False)
        sys.exit(0 if suite.result.wasSuccessful() else 1)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
