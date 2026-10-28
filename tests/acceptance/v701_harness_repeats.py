#!/usr/bin/env python3
"""Repeated matched controls: agreement raises confidence, disagreement never does."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v701-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "SESSIONS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.harness import compose, whole


def record(run_id, steps):
    return {"run_id": run_id, "goal": "g", "model": "m", "workspace": TMP,
            "steps": steps, "deliverables": []}


FAIL = {"tool": "shell", "ok": False, "error": "exit 7 connection refused"}
OK = {"tool": "fs.read", "ok": True, "error": ""}


class Aggregation(unittest.TestCase):
    def test_agreement_keeps_the_verdict(self):
        self.assertEqual(compose.aggregate([{"verdict": "improved"},
                                            {"verdict": "improved"}]), "improved")

    def test_disagreement_is_mixed_never_a_win(self):
        self.assertEqual(compose.aggregate([{"verdict": "improved"},
                                            {"verdict": "regressed"}]), "mixed")

    def test_no_contrast_is_unknown(self):
        self.assertEqual(compose.aggregate([]), "unknown")

    def test_repeated_agreement_raises_confidence_but_not_a_lesson(self):
        trial = {"candidate": {"name": "c", "kind": "guardrail"},
                 "record": record("run-1", [OK]), "status": "ran", "repeats": 2,
                 "contrast": {"verdict": "improved",
                              "errors": {"fixed": ["exit # connection refused"]}},
                 "contrasts": [{"verdict": "improved"}, {"verdict": "improved"}]}
        got = compose.reflect([trial], {"record": record("run-2", [OK]),
                                        "repeats": 2})
        edit = got["edits"][0]
        self.assertEqual(edit["attribution"], "repeated_matched_runs")
        self.assertEqual(edit["confidence"], "supported")
        self.assertEqual(got["status"], "NO_ENTRY")
        self.assertTrue(got["evidence"]["consistent_repeats"])
        self.assertEqual(got["evidence"]["successor_repeats"], 2)

    def test_repeated_disagreement_stays_confounded(self):
        trial = {"candidate": {"name": "c", "kind": "guardrail"},
                 "record": record("run-1", [OK]), "status": "ran", "repeats": 2,
                 "contrast": {"verdict": "mixed"},
                 "contrasts": [{"verdict": "improved"}, {"verdict": "regressed"}]}
        got = compose.reflect([trial], None)
        self.assertEqual(got["edits"][0]["attribution"], "confounded")
        self.assertEqual(got["edits"][0]["confidence"], "insufficient")
        self.assertFalse(got["evidence"]["consistent_repeats"])

    def test_single_rollout_is_still_confounded(self):
        trial = {"candidate": {"name": "c"}, "record": record("run-1", [OK]),
                 "status": "ran", "contrast": {"verdict": "improved"}}
        got = compose.reflect([trial], None)
        self.assertEqual(got["edits"][0]["confidence"], "insufficient")


class RepeatedExecution(unittest.TestCase):
    """The orchestrator pairs run i of the reference with run i of the candidate."""

    def test_repeats_pair_reference_and_candidate_and_aggregate(self):
        calls = []

        def fake_execute(path, digest, c, tag, candidates, guardrail=False):
            calls.append(tag)
            if tag.startswith("reference"):
                return {"ok": True, "record": record(tag, [FAIL]), "digest": digest,
                        "run_id": tag, "cleanup_verified": True}
            return {"ok": True, "record": record(tag, [OK]), "digest": digest,
                    "run_id": tag, "cleanup_verified": True}

        base = {"workspace": TMP, "goal": "g", "model": "m"}
        candidate = {"kind": "guardrail", "name": "good", "content": "rule"}
        with patch.object(whole, "readiness",
                          return_value={"available": True, "backend": "docker-whole",
                                        "reason": ""}), \
                patch.object(whole.snapshot_mod, "build",
                             return_value={"ok": True, "path": "/fake/inputs",
                                           "digest": "d" * 64}), \
                patch.object(whole.snapshot_mod, "verify", return_value={"ok": True}), \
                patch.object(whole.snapshot_mod, "variant",
                             return_value={"ok": True, "path": "/fake/variant",
                                           "digest": "e" * 64}), \
                patch.object(whole.snapshot_mod, "remove", return_value={"ok": True}), \
                patch.object(whole, "_execute", side_effect=fake_execute):
            got = whole.run_group(base, [candidate], c={"repeats": 2})
        self.assertEqual(got["status"], "ran", got)
        self.assertEqual(len(calls), 4)
        row = got["trials"][0]
        self.assertEqual(row["repeats"], 2)
        self.assertEqual(len(row["runs"]), 2)
        self.assertEqual(len(row["contrasts"]), 2)
        self.assertEqual(row["contrast"]["verdict"], "improved")
        self.assertEqual(len(got["references"]), 2)
        self.assertEqual(got["reference"]["run_id"], "reference-1")

    def test_one_failing_repeat_fails_the_trial(self):
        def fake_execute(path, digest, c, tag, candidates, guardrail=False):
            ok = tag != "c-2"
            return {"ok": ok, "record": record(tag, [OK]) if ok else None,
                    "digest": digest, "run_id": tag, "cleanup_verified": ok,
                    "reason": "" if ok else "run failed"}

        with patch.object(whole, "readiness",
                          return_value={"available": True, "reason": ""}), \
                patch.object(whole.snapshot_mod, "build",
                             return_value={"ok": True, "path": "/fake/inputs",
                                           "digest": "d" * 64}), \
                patch.object(whole.snapshot_mod, "verify", return_value={"ok": True}), \
                patch.object(whole.snapshot_mod, "variant",
                             return_value={"ok": True, "path": "/fake/variant",
                                           "digest": "e" * 64}), \
                patch.object(whole.snapshot_mod, "remove", return_value={"ok": True}), \
                patch.object(whole, "_execute", side_effect=fake_execute):
            got = whole.run_group({"workspace": TMP, "goal": "g", "model": "m"},
                                  [{"kind": "guardrail", "name": "c", "content": "r"}],
                                  c={"repeats": 2})
        self.assertEqual(got["trials"][0]["status"], "failed", got["trials"][0])


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
