#!/usr/bin/env python3
"""v688: H2R-2 evidence contracts. No model, network or server."""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v688-")
for key in ("CONFIG_DIR", "SESSIONS_DIR", "DATA_DIR", "HARNESS_DIR", "RUNS_DIR",
            "SKILLS_DIR", "ROLES_DIR", "GRAPH_DIR", "THREADS_DIR", "COSTS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
    os.makedirs(os.environ["LONGRUN_" + key], exist_ok=True)
os.environ["LONGRUN_HOOKS"] = os.path.join(TMP, "hooks.yaml")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import contrast as C  # noqa: E402
from longrun.harness import record as R  # noqa: E402
from longrun.util import fswrite  # noqa: E402


def step(ok, error="", tool="shell", exit_code=None):
    return {"tool": tool, "ok": ok, "error": error, "exit_code": exit_code}


def rec(steps, **fields):
    out = {"goal": "repair report", "model": "m", "workspace": "",
           "steps": steps, "deliverables": [], "files_touched": [],
           "budget": {}, "harness": {}}
    out.update(fields)
    return out


class Evidence(unittest.TestCase):
    def test_candidate_needs_successful_execution(self):
        base = rec([step(False, "connection refused")])
        for steps in ([], [None], [{}], [step(False, "   ")]):
            with self.subTest(steps=steps):
                diff = C.diff(base, rec(steps))
                self.assertNotEqual(diff["verdict"], "improved")
                self.assertIn("successful", C.evidence_text(diff))
        self.assertEqual(
            C.diff(base, rec([step(True)]))["verdict"], "improved")

    def test_record_does_not_invent_success_for_missing_outcome(self):
        base = rec([step(False, "connection refused")])
        for outcome in ({}, {"ok": None}, {"ok": "false"}):
            with self.subTest(outcome=outcome):
                card = dict(outcome, tool="fs.write", args={"path": "unknown.md"})
                built = R.build("unknown-outcome", session={
                    "model": "m", "workspace": TMP,
                    "messages": [{"role": "user", "content": base["goal"]}],
                    "tool_cards": [card]})
                self.assertIsNone(built["steps"][0]["ok"])
                self.assertEqual(built["files_touched"], [])
                self.assertNotEqual(C.diff(base, built)["verdict"], "improved")

    def test_blank_diagnostics_keep_tool_exit_failure_classes(self):
        failures = [step(False, "", exit_code=7),
                    step(False, " \n ", exit_code=7),
                    step(False, "", exit_code=126),
                    step(False, "", tool="fs.write")]
        diff = C.diff(rec(failures), rec([step(True)]))
        self.assertEqual(diff["errors"]["base"], 4)
        classes = diff["errors"]["classes_base"]
        self.assertEqual(len(classes), 3)
        self.assertTrue(any("shell" in key and "7" in key and n == 2
                            for key, n in classes.items()))
        self.assertTrue(any("shell" in key and "126" in key for key in classes))
        self.assertTrue(any("fs.write" in key for key in classes))
        self.assertEqual(diff["verdict"], "improved")

    def test_full_goal_is_identity_not_editor_excerpt(self):
        prefix = "same opening " * 50
        session = {"model": "m", "messages": [
            {"role": "user", "internal": True, "content": "ignore"},
            {"role": "user", "content": "[harness] ignore"},
            {"role": "user", "content": prefix + "task A"}],
            "tool_cards": [step(False, "connection refused")]}
        base = R.build("identity-base", session=session)
        other = copy.deepcopy(session)
        other["messages"][-1]["content"] = prefix + "task B"
        other["tool_cards"] = [step(True)]
        cand = R.build("identity-cand", session=other)
        self.assertEqual(base["goal"], prefix + "task A")
        self.assertEqual(base.get("goal_display"), base["goal"][:R.GOAL_MAX])
        self.assertEqual(C.diff(base, cand)["verdict"], "incomparable")

    def test_explicit_model_mismatch_is_incomparable(self):
        base = rec([step(False, "connection refused")])
        cand = rec([step(True)], model="other-model")
        original = copy.deepcopy(cand)
        diff = C.diff(base, cand)
        self.assertFalse(diff["comparable"])
        self.assertEqual(diff["verdict"], "incomparable")
        self.assertIn("model", C.evidence_text(diff))
        self.assertEqual(cand, original)
        unknown = C.diff(base, rec([step(True)], model=""))
        self.assertIsNone(unknown.get("identity", {}).get("model_match"))

    def test_workspace_relative_deliverables_survive_scratch_roots(self):
        records = []
        for name in ("base-ws", "scratch-ws"):
            ws = os.path.join(TMP, name)
            os.makedirs(os.path.join(ws, "reports"), exist_ok=True)
            path = os.path.join(ws, "reports", "result.md")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("same report")
            session = {"model": "m", "workspace": ws,
                       "messages": [{"role": "user", "content": "repair report"}],
                       "tool_cards": [dict(step(True, tool="fs.write"),
                                           args={"path": path})]}
            records.append(R.build(name, session=session))
        for built in records:
            self.assertEqual(built["deliverables"][0]["path"], "reports/result.md")
        diff = C.diff(*records)
        self.assertEqual(diff["verdict"], "unchanged")
        self.assertEqual(diff["files"]["common"], 1)
        self.assertEqual(diff["deliverables"]["only_base"], [])
        # Persisted schema-1 absolute paths must compare against the new shape.
        legacy = copy.deepcopy(records[0])
        legacy["deliverables"][0]["path"] = legacy["files_touched"][0]
        self.assertEqual(C.diff(legacy, records[1])["verdict"], "unchanged")
        rewritten = copy.deepcopy(records[1])
        rewritten["deliverables"][0]["sha256"] = "changed"
        self.assertEqual(C.diff(legacy, rewritten)["deliverables"]["changed"],
                         ["reports/result.md"])
        lost = copy.deepcopy(records[1])
        lost["deliverables"] = []
        self.assertEqual(C.diff(legacy, lost)["verdict"], "regressed")

    def test_session_and_live_digest_provenance_is_not_a_run_snapshot(self):
        session = {"model": "session-model", "workspace": TMP,
                   "messages": [{"role": "user", "content": "repair report"}],
                   "tool_cards": [step(False, "old failure"), step(True)]}
        manifest = {"run_id": "manifest-run", "model": "historical-model",
                    "revision": "historical-revision", "config": {},
                    "overlay": None, "prompt": {"sha256": "historical-prompt"}}
        path = os.path.join(os.environ["LONGRUN_RUNS_DIR"],
                            "manifest-run", "manifest.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream)
        built = R.build("aggregate", run_id="manifest-run", session=session)
        provenance = built.get("evidence") or {}
        self.assertEqual(provenance.get("scope"), "session_aggregate")
        self.assertEqual(provenance.get("run_binding"), "unverified")
        self.assertEqual(provenance.get("deliverables_source"), "live_workspace")
        self.assertEqual(provenance.get("model_source"), "session_current")
        self.assertEqual(len(built["steps"]), 2)
        self.assertEqual(built["model"], "session-model")
        harness = built["harness"]
        self.assertEqual(harness["source"], "mixed")
        self.assertEqual(harness.get("sources", {}).get("skills"), "live")
        self.assertEqual(harness.get("sources", {}).get("hooks"), "live")
        self.assertEqual(harness.get("sources", {}).get("prompt"), "manifest")
        self.assertEqual(harness["config"], {})
        self.assertIsNone(harness["overlay"])
        live = R.build("aggregate", session=session)
        self.assertEqual(live["harness"].get("sources", {}).get("prompt"), "unknown")
        text = C.evidence_text(C.diff(built, live))
        self.assertIn("session aggregate", text)
        self.assertIn("live", text)

    def test_atomic_saves_allow_concurrent_writers(self):
        first = rec([step(True)], run_id="concurrent", payload="first")
        second = rec([step(True)], run_id="concurrent", payload="second")
        barrier = Barrier(2)
        replace = os.replace

        def synchronized_replace(source, target):
            barrier.wait(timeout=5)
            replace(source, target)

        with patch("os.replace", side_effect=synchronized_replace):
            with ThreadPoolExecutor(max_workers=2) as pool:
                saved = list(pool.map(R.save, (first, second)))
        self.assertEqual(saved, [R.path_for("concurrent")] * 2)
        self.assertIn(R.load("concurrent"), (first, second))
        self.assertFalse(any(name.endswith(".tmp") for name in
                             os.listdir(os.path.dirname(saved[0]))))

    def test_save_uses_shared_writer_and_preserves_old_file_on_failure(self):
        value = rec([step(True)], run_id="atomic-round-trip")
        with patch.object(fswrite, "write_json", wraps=fswrite.write_json) as writer:
            self.assertEqual(R.save(value), R.path_for(value["run_id"]))
            self.assertEqual(writer.call_count, 1)
        self.assertEqual(R.load(value["run_id"]), value)
        invalid = dict(value, unserializable=object())
        self.assertIsNone(R.save(invalid))
        self.assertEqual(R.load(value["run_id"]), value)
        self.assertFalse(any(name.endswith(".tmp") for name in
                             os.listdir(os.path.dirname(R.path_for(value["run_id"])))))


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
