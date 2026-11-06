#!/usr/bin/env python3
"""Turn-3 contract: new column order, bumped version, parse untouched."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import load  # noqa: E402


class Final(unittest.TestCase):
    def test_version(self):
        self.assertEqual(load().SCHEMA_VERSION, 4)

    def test_row_order(self):
        m = load()
        self.assertEqual(m.to_row({"a": "1", "b": "2", "c": "3"}), "3,1,2")
        self.assertEqual(m.to_row({"a": "1", "c": "3"}), "3,1,")

    def test_parse_untouched(self):
        m = load()
        self.assertEqual(m.parse("a=1;b=2"), {"a": "1", "b": "2"})
        self.assertEqual(m.parse("a=1;a=2"), {"a": "2"})
        with self.assertRaises(ValueError):
            m.parse("a")


if __name__ == "__main__":
    unittest.main(verbosity=2)
