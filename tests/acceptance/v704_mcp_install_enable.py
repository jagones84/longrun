#!/usr/bin/env python3
"""v704: installing an MCP client also ENABLES its tools (one install, usable).

Before: `mcp.upsert` wrote the client, reloaded, and reported ok — but external
tools are opt-in (JAG-80), so the model never saw `<client>__<tool>` and the install
was unusable. The enable step must go through the existing policy owner, touch only
that client's names, and keep per-call approval.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v704-")
for key in ("CONFIG_DIR", "DATA_HOME", "DATA_DIR", "SESSIONS_DIR"):
    os.environ["LONGRUN_" + key] = os.path.join(TMP, key)
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.interop import mcp_client
from longrun.tools import registry


class InstallEnables(unittest.TestCase):
    def setUp(self):
        self.cfg = {"tools": {"fs.read": {"enabled": True, "approval": "auto"},
                              "echo__ping": {"enabled": False, "approval": "auto"}}}
        self.ext = {"echo__ping": {"name": "echo__ping", "description": "p"},
                    "echo__ping2": {"name": "echo__ping2", "description": "p"},
                    "other__x": {"name": "other__x", "description": "x"}}
        self.saved = {}
        self.patches = [
            patch.object(registry, "load_config", side_effect=lambda: self.cfg),
            patch.object(registry, "save_config",
                         side_effect=lambda c: self.saved.update(cfg=c) or c),
            patch.object(registry, "_external_tools", side_effect=lambda: self.ext),
            patch.object(mcp_client, "reload", side_effect=lambda: {"ok": True}),
            patch.object(mcp_client, "_load_local_doc", side_effect=lambda: {"clients": {}}),
            patch.object(mcp_client, "_save_local_doc", side_effect=lambda doc: "/tmp/local"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def install(self):
        return mcp_client.upsert_client("echo", {"command": "true"})

    def test_install_enables_exactly_the_new_clients_tools(self):
        got = self.install()
        self.assertTrue(got.get("ok"), got)
        self.assertEqual(got["enabled_tools"], ["echo__ping", "echo__ping2"])
        tools = self.saved["cfg"]["tools"]
        self.assertTrue(tools["echo__ping"]["enabled"])
        self.assertTrue(tools["echo__ping2"]["enabled"])
        self.assertNotIn("other__x", tools)

    def test_enable_keeps_per_call_approval_and_an_explicit_choice(self):
        self.install()
        tools = self.saved["cfg"]["tools"]
        # the entry that already existed had approval "auto": the operator's choice
        # is preserved, a NEW entry defaults to required (never silent auto-approval)
        self.assertEqual(tools["echo__ping"]["approval"], "auto")
        self.assertEqual(tools["echo__ping2"]["approval"], "required")

    def test_unrelated_policy_is_untouched(self):
        self.install()
        self.assertEqual(self.saved["cfg"]["tools"]["fs.read"],
                         {"enabled": True, "approval": "auto"})

    def test_client_without_tools_writes_no_policy(self):
        self.ext = {}
        got = self.install()
        self.assertEqual(got["enabled_tools"], [])
        self.assertEqual(self.saved, {})

    def test_policy_failure_never_fails_the_install(self):
        with patch.object(registry, "save_config", side_effect=OSError("read-only")):
            got = self.install()
        self.assertTrue(got.get("ok"), got)
        self.assertEqual(got["enabled_tools"], [])


if __name__ == "__main__":
    try:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(InstallEnables))
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0 if result.wasSuccessful() else 1)
