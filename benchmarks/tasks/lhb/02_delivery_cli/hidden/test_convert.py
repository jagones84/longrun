#!/usr/bin/env python3
"""Hidden grader: imports the delivered module and tests the omitted cases."""
import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path

WS = Path(os.environ["LHB_WS"])
MOD = WS / "out" / "convert.py"


def _load():
    spec = importlib.util.spec_from_file_location("lhb_convert", str(MOD))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Convert(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load()

    def test_parse_units(self):
        self.assertEqual(self.m.parse_duration("45s"), 45)
        self.assertEqual(self.m.parse_duration("2h"), 7200)
        self.assertEqual(self.m.parse_duration("1h30m"), 5400)
        self.assertEqual(self.m.parse_duration("1h30m15s"), 5415)
        self.assertEqual(self.m.parse_duration("0s"), 0)

    def test_parse_invalid(self):
        for bad in ("", "1h30", "10x", "30m1h", "1h1h", "1h30m "):
            with self.assertRaises(ValueError, msg=bad):
                self.m.parse_duration(bad)

    def test_format(self):
        self.assertEqual(self.m.format_duration(0), "0s")
        self.assertEqual(self.m.format_duration(45), "45s")
        self.assertEqual(self.m.format_duration(7200), "2h")
        self.assertEqual(self.m.format_duration(5400), "1h30m")
        self.assertEqual(self.m.format_duration(5415), "1h30m15s")
        with self.assertRaises(ValueError):
            self.m.format_duration(-1)

    def test_cli(self):
        ok = subprocess.run([sys.executable, str(MOD), "1h30m15s"],
                            capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0)
        self.assertEqual(ok.stdout.strip(), "5415")
        bad = subprocess.run([sys.executable, str(MOD), "nope"],
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertTrue((bad.stderr or "").strip(), "no usage message on stderr")


if __name__ == "__main__":
    unittest.main(verbosity=2)
