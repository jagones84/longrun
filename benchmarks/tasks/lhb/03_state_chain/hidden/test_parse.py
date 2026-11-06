#!/usr/bin/env python3
"""parse() contract: survives every turn."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import load  # noqa: E402


class Parse(unittest.TestCase):
    def test_basic(self):
        m = load()
        self.assertEqual(m.parse("a=1;b=2"), {"a": "1", "b": "2"})
        self.assertEqual(m.parse(" a = 1 ; b = 2 "), {"a": "1", "b": "2"})
        self.assertEqual(m.parse("a=1;a=2"), {"a": "2"})
        self.assertEqual(m.parse(""), {})
        self.assertEqual(m.parse("a=x=y"), {"a": "x=y"})

    def test_invalid(self):
        m = load()
        for bad in ("a", "=1", "a=1;b"):
            with self.assertRaises(ValueError, msg=bad):
                m.parse(bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
