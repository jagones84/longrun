#!/usr/bin/env python3
"""Whole-process prerequisites: deterministic, no Docker, model or network."""
import os
import shutil
import signal
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v696-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "SESSIONS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.tools import sandbox


class WholeRunTracking(unittest.TestCase):
    def test_fabricated_private_directory_is_not_an_issued_reservation(self):
        base = os.path.join(TMP, "scratch")
        path = os.path.join(base, "h2-" + "f" * 32, "inputs")
        os.makedirs(path, mode=0o700)
        os.chmod(os.path.dirname(path), 0o700)
        with patch.object(sandbox.registry, "workspace_dir", return_value=base), \
                patch.object(sandbox, "_run_tracked", side_effect=AssertionError("launched")):
            result = sandbox.run_whole(path, "sha256:" + "a" * 64, ["-c", "pass"])
        self.assertEqual(result["exit_code"], 126)

    def test_final_capture_read_failure_is_reported(self):
        with patch.object(sandbox, "_read_capped", side_effect=OSError("private-readback-error")):
            result = sandbox._run_tracked(
                [sys.executable, "-c", "print('out')"], timeout=5, output_limit=1024)
        self.assertTrue(result.get("output_error"), result)
        self.assertEqual(result["exit_code"], 125)
        self.assertNotIn("private-readback-error", result["stderr"])

    def test_cancel_retains_already_detected_capture_error(self):
        kill = sandbox._kill
        def concurrent_cancel(entry):
            entry["cancelled"] = True
            return kill(entry)
        with patch.object(sandbox.selectors.DefaultSelector, "select", side_effect=OSError), \
                patch.object(sandbox, "_kill", side_effect=concurrent_cancel):
            result = sandbox._run_tracked(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                timeout=5, output_limit=1024)
        self.assertTrue(result.get("cancelled"), result)
        self.assertTrue(result.get("output_error"), result)

    def test_container_kill_keeps_the_same_daemon_and_environment(self):
        argv = sandbox._whole_run_argv(
            "/input-fixture", "sha256:" + "a" * 64, ["-c", "pass"],
            "h2-" + "b" * 32, 1000, 1000)
        entry = {"proc": object(), "argv": argv, "env": {"PATH": os.defpath}}
        with patch.object(sandbox.subprocess, "run") as run, \
                patch.object(sandbox.osutil, "kill_tree"):
            sandbox._kill(entry)
        self.assertEqual(run.call_args.args[0],
                         argv[:3] + ["kill", "h2-" + "b" * 32])
        self.assertEqual(run.call_args.kwargs["env"], entry["env"])

    def test_launcher_exception_still_checks_cleanup_without_exposing_error_text(self):
        calls = []
        def tracked(argv, **_options):
            calls.append(argv)
            if len(calls) == 2:
                raise RuntimeError("private-launch-error")
            return {"exit_code": 0, "stdout": "null" if "inspect" in argv else "",
                    "stderr": "", "duration_ms": 0}
        with patch.object(sandbox.registry, "workspace_dir", return_value=os.path.join(TMP, "scratch")):
            snapshot = sandbox.reserve_whole_run()
            with patch.object(sandbox, "_run_tracked", side_effect=tracked):
                result = sandbox.run_whole(snapshot, "sha256:" + "a" * 64, ["-c", "pass"])
        self.assertEqual(len(calls), 4)
        self.assertFalse(result["ok"])
        self.assertTrue(result["cleanup_verified"])
        self.assertNotIn("private-launch-error", result["stderr"])

    def test_failed_cleanup_is_not_reported_as_success(self):
        def tracked(argv, **_options):
            return {"exit_code": 0, "stdout": "remaining" if "ls" in argv else "",
                    "stderr": "", "duration_ms": 0}
        with patch.object(sandbox.registry, "workspace_dir", return_value=os.path.join(TMP, "scratch")):
            snapshot = sandbox.reserve_whole_run()
            with patch.object(sandbox, "_run_tracked", side_effect=tracked):
                result = sandbox.run_whole(snapshot, "sha256:" + "a" * 64, ["-c", "pass"])
        self.assertFalse(result["ok"])
        self.assertFalse(result["cleanup_verified"])
        self.assertEqual(result["exit_code"], 125)

    def test_unowned_mounts_mutable_images_and_invalid_arguments_refuse(self):
        with patch.object(sandbox.registry, "workspace_dir", return_value=os.path.join(TMP, "scratch")):
            snapshot = sandbox.reserve_whole_run()
            cases = [(TMP, "sha256:" + "a" * 64, ["-c", "pass"], 5),
                     (snapshot, "python:latest", ["-c", "pass"], 5),
                     (snapshot, "sha256:" + "a" * 64, ["\0"], 5),
                     (snapshot, "sha256:" + "a" * 64, ["-c", "pass"], 0)]
            for path, image, args, timeout in cases:
                with self.subTest(path=path, image=image, timeout=timeout), \
                        patch.object(sandbox, "_run_tracked", side_effect=AssertionError("launched")):
                    result = sandbox.run_whole(path, image, args, timeout)
                self.assertEqual(result["exit_code"], 126)

    def test_launcher_uses_existing_tracker_and_verifies_owned_container_absence(self):
        calls = []
        def tracked(argv, **options):
            calls.append((argv, options))
            return {"exit_code": 0, "stdout": "null" if "inspect" in argv else "",
                    "stderr": "", "duration_ms": 1}
        with patch.object(sandbox.registry, "workspace_dir", return_value=os.path.join(TMP, "scratch")):
            snapshot = sandbox.reserve_whole_run()
            with patch.object(sandbox, "_run_tracked", side_effect=tracked):
                result = sandbox.run_whole(snapshot, "sha256:" + "a" * 64,
                                           ["-c", "print('fixture')"], timeout=5)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["cleanup_verified"], result)
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0][0][3:5], ["image", "inspect"])
        self.assertEqual(calls[1][1]["output_limit"], sandbox.MAX_OUTPUT_BYTES)
        self.assertEqual(calls[1][1]["env"], {"PATH": os.defpath})
        name = calls[1][0][calls[1][0].index("--name") + 1]
        self.assertIn(name, calls[2][0])
        self.assertIn("label=longrun.whole_run=" + name, calls[3][0])
        self.assertEqual(calls[2][0][3:6], ["container", "rm", "--force"])

    def test_image_declared_volumes_refuse_before_launch(self):
        with patch.object(sandbox.registry, "workspace_dir", return_value=os.path.join(TMP, "scratch")):
            snapshot = sandbox.reserve_whole_run()
            for volumes in ({"data": {}}, None):
                with self.subTest(volumes=volumes), \
                        patch.object(sandbox, "_image_volumes", return_value=volumes), \
                        patch.object(sandbox, "_run_tracked",
                                     side_effect=AssertionError("launched")):
                    result = sandbox.run_whole(snapshot, "sha256:" + "a" * 64,
                                               ["-c", "pass"])
                self.assertEqual(result["exit_code"], 126)

    def test_image_volume_metadata_is_parsed_not_assumed(self):
        calls = []
        def tracked(argv, **_options):
            calls.append(argv)
            return {"exit_code": 0, "stdout": "null\n", "stderr": "", "duration_ms": 0}
        with patch.object(sandbox, "_run_tracked", side_effect=tracked):
            self.assertEqual(sandbox._image_volumes("sha256:" + "a" * 64), {})
        self.assertEqual(calls[0][3:6], ["image", "inspect", "--format"])

    def test_gateway_socket_is_the_only_extra_mount_and_must_be_private(self):
        import socket as socket_mod
        with patch.object(sandbox.registry, "workspace_dir", return_value=os.path.join(TMP, "scratch")):
            snapshot = sandbox.reserve_whole_run()
            gateway = os.path.join(TMP, "gateway.sock")
            server = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
            server.bind(gateway)
            os.chmod(gateway, 0o600)
            calls = []
            try:
                with patch.object(sandbox, "_run_tracked",
                                  side_effect=lambda argv, **o: calls.append(argv) or {
                                      "exit_code": 0,
                                      "stdout": "null" if "inspect" in argv else "",
                                      "stderr": "", "duration_ms": 0}):
                    ok = sandbox.run_whole(snapshot, "sha256:" + "a" * 64,
                                           ["-c", "pass"], gateway_socket=gateway,
                                           extra_env={"LONGRUN_H2_SNAPSHOT": "digest"})
                self.assertTrue(ok["ok"], ok)
                argv = calls[1]
                self.assertIn("type=bind,src=%s,dst=/state/gateway.sock,readonly"
                              % gateway, argv)
                self.assertIn("LONGRUN_H2_SNAPSHOT=digest", argv)
                os.chmod(gateway, 0o666)
                with patch.object(sandbox, "_run_tracked",
                                  side_effect=AssertionError("launched")):
                    refused = sandbox.run_whole(snapshot, "sha256:" + "a" * 64,
                                                ["-c", "pass"], gateway_socket=gateway)
                self.assertEqual(refused["exit_code"], 126)
                plain = os.path.join(TMP, "plain.txt")
                open(plain, "w").close()
                with patch.object(sandbox, "_run_tracked",
                                  side_effect=AssertionError("launched")):
                    refused = sandbox.run_whole(snapshot, "sha256:" + "a" * 64,
                                                ["-c", "pass"], gateway_socket=plain)
                self.assertEqual(refused["exit_code"], 126)
                for env in ({"lower": "x"}, {"OK": "a\nb"}):
                    with self.subTest(env=env), \
                            patch.object(sandbox, "_run_tracked",
                                         side_effect=AssertionError("launched")):
                        refused = sandbox.run_whole(snapshot, "sha256:" + "a" * 64,
                                                    ["-c", "pass"], extra_env=env)
                    self.assertEqual(refused["exit_code"], 126)
            finally:
                server.close()

    def test_whole_run_profile_has_only_read_only_host_input(self):
        snapshot = os.path.join(TMP, "inputs")
        argv = sandbox._whole_run_argv(
            snapshot, "sha256:" + "a" * 64, ["-c", "print('isolated')"],
            "h2-" + "b" * 32, 1000, 1000)
        def option(name):
            return argv[argv.index(name) + 1]
        self.assertEqual(option("--network"), "none")
        self.assertEqual(option("--pull"), "never")
        self.assertEqual(option("--user"), "1000:1000")
        self.assertEqual(option("--runtime"), "runc")
        self.assertEqual(option("--cap-drop"), "ALL")
        self.assertEqual(option("--security-opt"), "no-new-privileges")
        self.assertIn("--read-only", argv)
        self.assertIn("--init", argv)
        self.assertNotIn("--privileged", argv)
        self.assertEqual(argv.count("--mount"), 1)
        self.assertEqual(option("--mount"), "type=bind,src=%s,dst=/input,readonly" % snapshot)
        self.assertEqual(argv.count("--tmpfs"), 3)
        self.assertEqual(option("--entrypoint"), "python3")
        self.assertEqual(argv[-3:], ["sha256:" + "a" * 64, "-c", "print('isolated')"])

    def test_output_overflow_fails_without_unbounded_capture(self):
        result = sandbox._run_tracked(
            [sys.executable, "-c", "import os; os.write(1, b'x' * 8000000)"],
            timeout=5, output_limit=1024, job_id="v696-overflow")
        self.assertTrue(result.get("output_limit"), result)
        self.assertNotEqual(result["exit_code"], 0)
        self.assertLessEqual(len(result["stdout"].encode()), 1200)
        self.assertFalse(any(row["job"] == "v696-overflow" for row in sandbox.running()))

    def test_output_files_are_capped_not_only_the_return_value(self):
        read = sandbox._read_capped
        def inspect(fh):
            fh.seek(0, os.SEEK_END)
            self.assertLessEqual(fh.tell(), 1024)
            return read(fh)
        with patch.object(sandbox, "_read_capped", side_effect=inspect):
            result = sandbox._run_tracked(
                [sys.executable, "-c", "import os; os.write(2, b'x' * 8000000)"],
                timeout=5, output_limit=1024)
        self.assertTrue(result.get("output_limit"), result)

    def test_success_preserves_both_streams(self):
        result = sandbox._run_tracked(
            [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
            timeout=5, output_limit=1024)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"], "out\n")
        self.assertEqual(result["stderr"], "err\n")

    def test_timeout_retains_real_job_cancellation(self):
        result = sandbox._run_tracked(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.1, output_limit=1024, job_id="v696-timeout")
        self.assertTrue(result.get("timeout"), result)
        self.assertEqual(result["exit_code"], 124)
        self.assertFalse(sandbox.running())

    def test_external_cancel_works_with_bounded_pipes(self):
        entered = threading.Event()
        wait = sandbox._wait_bounded
        result = {}
        def coordinate(*args):
            entered.set()
            return wait(*args)
        def run():
            result.update(sandbox._run_tracked(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                timeout=5, output_limit=1024, job_id="v696-cancel"))
        with patch.object(sandbox, "_wait_bounded", side_effect=coordinate):
            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertTrue(sandbox.cancel("v696-cancel")["cancelled"])
            finally:
                worker.join(7)
        self.assertFalse(worker.is_alive())
        self.assertTrue(result.get("cancelled"), result)
        self.assertEqual(result["exit_code"], 130)

    def test_descendant_held_pipe_is_failed_not_a_false_success(self):
        result = sandbox._run_tracked(
            [sys.executable, "-c",
             "import subprocess, sys; "
             "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
             "print(p.pid, flush=True)"],
            timeout=5, output_limit=1024)
        try:
            self.assertTrue(result.get("output_incomplete"), result)
            self.assertEqual(result["exit_code"], 125)
        finally:
            pid = int(result["stdout"].strip())
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_invalid_limit_refuses_before_any_process(self):
        for limit in (0, -1, True, "1024", sandbox.MAX_OUTPUT_BYTES + 1):
            with self.subTest(limit=limit), \
                    patch.object(sandbox.subprocess, "Popen", side_effect=AssertionError("launched")):
                result = sandbox._run_tracked(["untrusted"], output_limit=limit)
            self.assertEqual(result["exit_code"], 126)

    def test_pipe_reader_failure_is_reported_and_the_job_is_stopped(self):
        with patch.object(sandbox.selectors.DefaultSelector, "select",
                          side_effect=OSError("private-reader-error")):
            result = sandbox._run_tracked(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                timeout=5, output_limit=1024, job_id="v696-reader")
        self.assertTrue(result.get("output_error"), result)
        self.assertEqual(result["exit_code"], 125)
        self.assertNotIn("private-reader-error", result["stderr"])
        self.assertFalse(sandbox.running())


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
