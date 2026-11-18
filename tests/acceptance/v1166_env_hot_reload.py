#!/usr/bin/env python3
"""v1166 — an edited .env must be used WITHOUT restarting the service.

Operator report: the OpenRouter key was replaced in `.env`, but the WebUI kept
failing with "provider rejected its API key" because the value had been loaded
once at boot (`load_env` never overwrites, `read_secret` read os.environ first).
These tests pin the hot reload and its two safety rules.
"""
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from longrun.model import keys, providers  # noqa: E402


class EnvHotReload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="longrun-env-")
        self.path = pathlib.Path(self.tmp) / "hot.env"
        self._repo = providers.REPO
        providers.REPO = self.tmp          # repo/.env resolves inside the test dir
        os.environ["LONGRUN_ENV_FILE"] = str(self.path)
        providers._ENV_STATE.update(sig=None, applied={}, checked=0.0)
        for name in ("HOT_KEY", "HOT_EXTERNAL", "HOT_GONE"):
            os.environ.pop(name, None)

    def tearDown(self):
        providers.REPO = self._repo
        os.environ.pop("LONGRUN_ENV_FILE", None)
        providers._ENV_STATE.update(sig=None, applied={}, checked=0.0)
        for name in ("HOT_KEY", "HOT_EXTERNAL", "HOT_GONE"):
            os.environ.pop(name, None)

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")
        st = os.stat(self.path)
        os.utime(self.path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    def test_edited_key_is_used_without_restart(self):
        self.write("HOT_KEY=one\n")
        providers.load_env(reload=True)
        self.assertEqual(os.environ.get("HOT_KEY"), "one")
        self.write("HOT_KEY=two\n")
        providers.load_env(reload=True)          # what a later request does
        self.assertEqual(os.environ.get("HOT_KEY"), "two")
        self.assertEqual(keys.read_secret("HOT_KEY"), "two")

    def test_read_secret_sees_the_edit_after_the_throttle(self):
        self.write("HOT_KEY=old\n")
        providers.load_env(reload=True)
        self.write("HOT_KEY=new\n")
        providers._ENV_STATE["checked"] = 0.0     # the 1 s throttle elapsed
        self.assertEqual(keys.read_secret("HOT_KEY"), "new")

    def test_value_injected_by_the_environment_is_never_overwritten(self):
        os.environ["HOT_EXTERNAL"] = "from-systemd"
        self.write("HOT_EXTERNAL=from-file\n")
        providers.load_env(reload=True)
        self.assertEqual(os.environ["HOT_EXTERNAL"], "from-systemd")

    def test_key_removed_from_the_file_is_dropped(self):
        self.write("HOT_GONE=1\n")
        providers.load_env(reload=True)
        self.assertEqual(os.environ.get("HOT_GONE"), "1")
        self.write("HOT_KEY=1\n")
        providers.load_env(reload=True)
        self.assertNotIn("HOT_GONE", os.environ)

    def test_a_quoted_export_line_is_understood(self):
        self.write("export HOT_KEY='three'\n")
        providers.load_env(reload=True)
        self.assertEqual(os.environ.get("HOT_KEY"), "three")


if __name__ == "__main__":
    unittest.main()
